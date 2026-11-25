"""Tests for persistent storage, version-aware invalidation and on-demand LLM explanations (no network).

    python -m pytest contrimap_ml/test_v6.py -q
"""

from __future__ import annotations

import json
import re
import time
from urllib.parse import unquote

import numpy as np
import pytest
import requests

from contrimap_ml import feedback, service, store


# ---------------------------------------------------------------------------
# A minimal in-process stand-in for Supabase's PostgREST API
# ---------------------------------------------------------------------------
class FakePostgrest:
    def __init__(self) -> None:
        self.tables: dict[str, dict[str, dict]] = {name: {} for name in store.TABLES}
        self.events: list[dict] = []
        self.calls: list[tuple[str, str]] = []
        self.down = False

    def request(self, method, url, params=None, data=None, headers=None, timeout=None):
        if self.down:
            raise requests.ConnectionError("down")
        table = url.rsplit("/", 1)[-1]
        self.calls.append((method, table))
        response = requests.Response()
        response.status_code = 200
        if table == "feedback_events":
            if method == "POST":
                self.events.append(json.loads(data))
                response._content = b""
            else:
                user = params["user_id"].removeprefix("eq.")
                rows = [event for event in self.events if event["user_id"] == user]
                response._content = json.dumps(rows).encode()
            return response
        if method == "POST":
            assert params == {"on_conflict": "key"} and "merge-duplicates" in headers["Prefer"]
            for row in json.loads(data):
                self.tables[table][row["key"]] = row
            response._content = b""
            return response
        if "key" not in params:  # ping
            response._content = b"[]"
            return response
        # PostgREST unescapes \" and \\ inside double-quoted list values.
        quoted = re.findall(r'"((?:[^"\\]|\\.)*)"', params["key"])
        keys = [re.sub(r"\\(.)", r"\1", unquote(value)) for value in quoted]
        now = params["or"].split('"')[1]
        rows = [{"key": key, "data": self.tables[table][key]["data"]} for key in keys if key in self.tables[table]
                and (self.tables[table][key]["expires_at"] is None or self.tables[table][key]["expires_at"] > now)]
        response._content = json.dumps(rows).encode()
        return response


@pytest.fixture()
def supabase():
    fake = FakePostgrest()
    backend = store._Supabase("https://example.supabase.co", "service-key")
    backend.session.request = fake.request
    target = store.Store(backend)
    store.configure(target)
    return fake, target


# ---------------------------------------------------------------------------
# Store behaviour
# ---------------------------------------------------------------------------
def test_supabase_round_trip_with_awkward_keys(supabase):
    fake, target = supabase
    key = 'pallets/click#12:abc"def:sha:mv'
    target.put("issue_predictions", key, {"files": ["a.py"]}, repository="pallets/click", sha="sha", model_version="mv")
    target.flush()  # writes happen on a background thread
    target.memory.clear()
    assert target.get("issue_predictions", key) == {"files": ["a.py"]}
    assert fake.tables["issue_predictions"][key]["repository"] == "pallets/click"


def test_memory_layer_answers_repeat_reads(supabase):
    fake, target = supabase
    target.put("issue_analyses", "k", {"x": 1})
    calls = len(fake.calls)
    for _ in range(5):
        assert target.get("issue_analyses", "k") == {"x": 1}
    assert len(fake.calls) == calls  # served from memory


def test_expired_rows_are_not_served(supabase):
    fake, target = supabase
    target.put("similar_issues", "k", {"x": 1}, ttl=1)
    target.flush()
    fake.tables["similar_issues"]["k"]["expires_at"] = "2000-01-01T00:00:00Z"
    target.memory.clear()
    assert target.get("similar_issues", "k") is None


def test_misses_are_remembered_and_cleared_by_writes(supabase):
    fake, target = supabase
    assert target.get("explanations", "absent") is None
    calls = len(fake.calls)
    for _ in range(3):
        assert target.get("explanations", "absent") is None
    assert len(fake.calls) == calls  # the miss is remembered: no repeated round trips
    target.put("explanations", "absent", {"source": "llm"})
    assert target.get("explanations", "absent") == {"source": "llm"}


def test_writes_do_not_block_the_caller(supabase):
    fake, target = supabase
    original = fake.request

    def slow(method, url, **kwargs):
        if method == "POST":
            time.sleep(0.5)
        return original(method, url, **kwargs)

    target.backend.session.request = slow
    started = time.perf_counter()
    target.put("issue_analyses", "slow", {"x": 1})
    assert time.perf_counter() - started < 0.2 and target.get("issue_analyses", "slow") == {"x": 1}
    target.flush()
    assert "slow" in fake.tables["issue_analyses"]
    assert target.put("issue_analyses", "sync", {"x": 2}, wait=True) is True and "sync" in fake.tables["issue_analyses"]


def test_unreachable_store_degrades_to_memory(supabase):
    fake, target = supabase
    fake.down = True
    target.put("issue_analyses", "k", {"x": 1})  # no exception
    assert target.get("issue_analyses", "k") == {"x": 1}  # memory still answers
    assert target.get("issue_analyses", "other") is None
    assert target.health()["available"] is False and target.stats["errors"] >= 1
    calls = len(fake.calls)
    target.get("issue_analyses", "third")  # cool-down: no new network attempts
    assert len(fake.calls) == calls


def test_sqlite_backend_persists_across_store_instances(tmp_path):
    first = store.Store(store._SQLite(tmp_path / "s.sqlite3"))
    first.put("repository_metrics", "repo@sha:g1", {"pagerank": {"a.py": 0.5}}, repository="repo", sha="sha")
    first.add_event({"user_id": "ada", "repository": "o/r", "number": 1, "action": "saved", "time": time.time()})
    second = store.Store(store._SQLite(tmp_path / "s.sqlite3"))  # e.g. after a backend restart
    assert second.get("repository_metrics", "repo@sha:g1") == {"pagerank": {"a.py": 0.5}}
    assert [event["action"] for event in second.events("ada")] == ["saved"]


# ---------------------------------------------------------------------------
# Feedback through the store, including migration of old JSON-lines files
# ---------------------------------------------------------------------------
def test_feedback_uses_store_and_migrates_old_files(supabase, tmp_path, monkeypatch):
    fake, _ = supabase
    monkeypatch.setattr(feedback, "FEEDBACK_DIR", tmp_path)
    feedback._EVENT_CACHE.clear()
    (tmp_path / "ada.jsonl").write_text(json.dumps({"time": 1.0, "repository": "o/r", "number": 1, "action": "saved", "title": "", "text": ""}) + "\n", encoding="utf-8")
    feedback.record("ada", "o/r", 2, "dismissed", "Two", "two")
    assert [event["number"] for event in fake.events] == [2]
    assert [event["number"] for event in feedback.events("ada")] == [1, 2]
    assert not (tmp_path / "ada.jsonl").exists() and (tmp_path / "ada.jsonl.migrated").exists()
    assert sorted(event["number"] for event in fake.events) == [1, 2]


def test_feedback_falls_back_to_file_when_store_is_down(supabase, tmp_path, monkeypatch):
    fake, _ = supabase
    fake.down = True
    monkeypatch.setattr(feedback, "FEEDBACK_DIR", tmp_path)
    feedback._EVENT_CACHE.clear()
    feedback.record("bob", "o/r", 3, "saved")
    assert (tmp_path / "bob.jsonl").exists()
    assert [event["number"] for event in feedback.events("bob")] == [3]


# ---------------------------------------------------------------------------
# Version-aware keys
# ---------------------------------------------------------------------------
def test_issue_version_ignores_comments_but_tracks_text():
    issue = {"number": 1, "title": "Crash", "body": "trace", "labels": ["bug"], "comments": 3, "updated_at": "a"}
    assert service.issue_version(issue) == service.issue_version({**issue, "comments": 9, "updated_at": "b"})
    assert service.issue_version(issue) != service.issue_version({**issue, "body": "new trace"})
    assert service.issue_version(issue) != service.issue_version({**issue, "labels": ["bug", "easy"]})


def test_prediction_keys_change_with_commit_and_model(monkeypatch):
    issue = {"number": 7, "title": "t", "body": "b", "labels": []}
    first = service._prediction_key("o/r", issue, "sha1")
    assert first != service._prediction_key("o/r", issue, "sha2")
    monkeypatch.setattr(service, "model_version", lambda: "retrained")
    assert first != service._prediction_key("o/r", issue, "sha1")


def _fake_context(sha="sha1"):
    return {"snapshot": {"sha": sha, "files": ["a.py"], "skills": []}, "graph": None, "metrics": {"pagerank": {}}}


def test_only_new_or_edited_issues_are_recomputed(monkeypatch):
    computed = []

    def fake_localize(full, context, issues, embeddings, top_k=5):
        computed.extend(issue["number"] for issue in issues)
        return [([{"path": "a.py", "rank": 1, "relative_confidence": 1.0}], {}) for _ in issues]

    monkeypatch.setattr(service, "embed", lambda texts, cache=False: np.ones((len(texts), 4), dtype="float32"))
    monkeypatch.setattr(service, "_localize_many", fake_localize)
    monkeypatch.setattr(service, "_difficulty_batch", lambda issues, embeddings, signals: [{"difficulty": "Easy"} for _ in issues])
    monkeypatch.setattr(service, "models", lambda: type("M", (), {"actionability": None})())
    issues = [{"number": n, "title": f"issue {n}", "body": "", "labels": []} for n in (1, 2, 3)]
    service._issue_predictions("o/r", _fake_context(), issues)
    assert computed == [1, 2, 3]
    edited = [issues[0], {**issues[1], "body": "now with details"}, issues[2], {"number": 4, "title": "new", "body": "", "labels": []}]
    result, _ = service._issue_predictions("o/r", _fake_context(), edited)
    assert computed == [1, 2, 3, 2, 4]  # only the edited and the new issue
    assert len(result) == 4 and all(item["estimate"]["difficulty"] == "Easy" for item in result)
    service._issue_predictions("o/r", _fake_context("sha2"), issues)  # a new commit invalidates
    assert computed[-3:] == [1, 2, 3]


def test_issue_batch_is_shared_across_page_sizes(monkeypatch):
    loads = []
    issues = [{"number": n, "title": f"t{n}", "body": "", "labels": []} for n in range(1, 41)]
    monkeypatch.setattr(service, "list_issues", lambda owner, repo, limit=40: issues[:limit])
    monkeypatch.setattr(service, "repository_context", lambda owner, repo: _fake_context())

    def predictions(full, context, batch, allow_stale=False, on_refreshed=None):
        loads.append(len(batch))
        return [{"embedding": [0.0], "files": [], "signals": {}, "estimate": {"n": issue["number"]}, "actionability": 0.5} for issue in batch], {"stale": 0, "refreshing": False}

    monkeypatch.setattr(service, "_issue_predictions", predictions)
    service.CACHE._data.clear()
    sizes = {limit: service._issue_batch("o", "r", limit) for limit in (20, 40, 30, 15)}
    assert loads == [40]
    assert [len(sizes[limit]["issues"]) for limit in (20, 40, 30, 15)] == [20, 40, 30, 15]
    assert [item["n"] for item in sizes[15]["estimates"]] == list(range(1, 16))


# ---------------------------------------------------------------------------
# Claude only on request, stored afterwards
# ---------------------------------------------------------------------------
@pytest.fixture()
def analysed(monkeypatch):
    analysis = {"repository": "o/r", "sha": "sha1", "issue": {"number": 5, "title": "t"}, "files": [{"path": "a.py", "signals": []}], "difficulty": "Easy", "skills": [], "contribution_path": {"steps": []}}
    monkeypatch.setattr(service, "repository_context", lambda owner, repo: _fake_context())
    monkeypatch.setattr(service, "_analyze_issue", lambda *args, **kwargs: dict(analysis))
    service.CACHE._data.clear()
    return {"number": 5, "title": "t", "body": "b", "labels": []}


def test_analysis_and_explanation_reads_never_call_the_llm(analysed, monkeypatch):
    calls = []
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr("contrimap_ml.llm.explain", lambda *args: calls.append(args) or {"source": "llm"})
    monkeypatch.setattr("contrimap_ml.llm.explain_with_llm", lambda *args: calls.append(args) or {"source": "llm"})
    result = service.analyze_issue("o", "r", analysed)
    assert result["explanation"]["source"] == "template" and result["llm_available"] is True
    assert service.explanation("o", "r", analysed)["explanation"]["source"] == "template"
    assert calls == []


def test_generated_explanation_is_stored_and_reused(analysed, monkeypatch):
    calls = []
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr("contrimap_ml.llm.explain_with_llm", lambda issue, analysis, profile: calls.append(1) or {"source": "llm", "model": "m", "summary": "s"})
    first = service.explanation("o", "r", analysed, generate=True)
    assert first["explanation"]["source"] == "llm" and first["stored"] and calls == [1]
    service.CACHE._data.clear()
    again = service.explanation("o", "r", analysed, generate=True)  # stored: no second call
    assert again["explanation"]["summary"] == "s" and calls == [1]
    assert service.analyze_issue("o", "r", analysed)["explanation"]["source"] == "llm"  # analysis page shows the stored one


def test_without_a_key_generation_returns_the_template(analysed, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("CONTRIMAP_FORCE_LLM", raising=False)
    result = service.explanation("o", "r", analysed, generate=True)
    assert result["explanation"]["source"] == "template" and result["llm_available"] is False and not result["stored"]


# ---------------------------------------------------------------------------
# Profiles API
# ---------------------------------------------------------------------------
def test_profile_endpoints_round_trip():
    from fastapi.testclient import TestClient

    from contrimap_ml.api import app

    client = TestClient(app)
    assert client.get("/api/profiles/ada").json()["profile"] is None
    saved = client.post("/api/profiles/ada", json={"profile": {"level": "advanced", "tech_stack": ["Rust"]}}).json()
    assert saved["profile"]["tech_stack"] == ["Rust"]
    assert client.get("/api/profiles/ada").json()["profile"]["level"] == "advanced"
    assert client.get("/api/profiles/bad%20id").status_code == 422
    assert client.get("/api/health").json()["store"]["backend"] == "memory"


# ---------------------------------------------------------------------------
# Path embeddings: stored per text, embedded once
# ---------------------------------------------------------------------------
def test_vector_cache_embeds_each_text_once_across_instances(tmp_path, monkeypatch):
    from contrimap_ml import textfeat

    embedded = []

    def fake_embed(texts, cache=False):
        embedded.extend(texts)
        return np.asarray([[float(len(text)), 1.0] for text in texts], dtype="float32")

    monkeypatch.setattr(textfeat, "embed", fake_embed)
    monkeypatch.setattr(textfeat, "_VECTOR_CACHE", textfeat.VectorCache(tmp_path / "v.sqlite3"))
    first = textfeat.embed_persistent(["src a", "src bb", "src a"])
    assert embedded == ["src a", "src bb"] and first.shape == (3, 2) and first[0][0] == first[2][0]
    # A new process (fresh cache object, same file) and a new commit adding one path: only that path is embedded.
    monkeypatch.setattr(textfeat, "_VECTOR_CACHE", textfeat.VectorCache(tmp_path / "v.sqlite3"))
    again = textfeat.embed_persistent(["src bb", "src a", "src ccc"])
    assert embedded == ["src a", "src bb", "src ccc"]
    assert np.allclose(again[1], first[0]) and again[2][0] == len("src ccc")


def test_new_commit_serves_previous_predictions_and_refreshes_in_background(monkeypatch):
    import threading

    computed, done = [], threading.Event()

    def fake_localize(full, context, issues, embeddings, top_k=5):
        computed.append((context["snapshot"]["sha"], [issue["number"] for issue in issues]))
        return [([{"path": f"{context['snapshot']['sha']}.py", "rank": 1, "relative_confidence": 1.0}], {}) for _ in issues]

    monkeypatch.setattr(service, "embed", lambda texts, cache=False: np.ones((len(texts), 4), dtype="float32"))
    monkeypatch.setattr(service, "_localize_many", fake_localize)
    monkeypatch.setattr(service, "_difficulty_batch", lambda issues, embeddings, signals: [{"difficulty": "Easy"} for _ in issues])
    monkeypatch.setattr(service, "models", lambda: type("M", (), {"actionability": None})())
    issues = [{"number": n, "title": f"issue {n}", "body": "", "labels": []} for n in (1, 2)]
    service._issue_predictions("o/r", _fake_context("old"), issues)
    new_issue = {"number": 3, "title": "brand new", "body": "", "labels": []}
    result, status = service._issue_predictions("o/r", _fake_context("new"), issues + [new_issue], allow_stale=True, on_refreshed=done.set)
    # Unchanged issues: served at once from the previous commit; the new issue: computed before returning.
    assert [item["files"][0]["path"] for item in result] == ["old.py", "old.py", "new.py"]
    assert status == {"stale": 2, "refreshing": True}
    assert done.wait(5)
    assert ("new", [1, 2]) in computed  # background refresh for the new commit
    fresh, status = service._issue_predictions("o/r", _fake_context("new"), issues + [new_issue], allow_stale=True)
    assert [item["files"][0]["path"] for item in fresh] == ["new.py"] * 3 and status["stale"] == 0


def test_gemini_provider_is_used_with_a_google_key(analysed, monkeypatch):
    from contrimap_ml import llm

    monkeypatch.setenv("GEMINI_API_KEY", "test-google-key")
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            text = json.dumps({"summary": "Gemini summary", "where_to_start": [{"path": "a.py", "reason": "r"}, {"path": "invented.py", "reason": "x"}], "approach": ["step"]})
            return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": text}]}}]}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append((url, headers))
        return Response()

    monkeypatch.setattr("requests.post", fake_post)
    assert llm.provider() == "gemini" and llm.active_model() == llm.GEMINI_DEFAULT_MODEL
    result = service.explanation("o", "r", analysed, generate=True)
    explanation = result["explanation"]
    assert explanation["source"] == "llm" and explanation["summary"] == "Gemini summary" and result["llm_provider"] == "Gemini"
    assert [item["path"] for item in explanation["where_to_start"]] == ["a.py"]  # invented paths are dropped
    assert calls[0][1] == {"x-goog-api-key": "test-google-key"} and "gemini-2.5-flash:generateContent" in calls[0][0]


def test_ai_guide_keeps_known_steps_and_never_commands_or_files():
    from contrimap_ml import llm

    context = {"contribution_path": [{"id": "setup", "title": "Set up", "commands": ["pip install -e ."]}, {"id": "implement", "title": "Implement", "files": ["a.py"]}]}
    parsed = {"contribution_guide": [
        {"id": "setup", "title": "Install Click in editable mode", "detail": "Use the commands below.", "commands": ["rm -rf /"]},
        {"id": "implement", "title": "", "detail": "Change `Option.get_error_hint` in a.py.", "files": ["invented.py"]},
        {"id": "made-up", "title": "Extra", "detail": "Not a real step."},
        "not an object",
    ]}
    steps = llm._guide_steps(parsed, context)
    assert steps == {"setup": {"title": "Install Click in editable mode", "detail": "Use the commands below."}, "implement": {"detail": "Change `Option.get_error_hint` in a.py."}}
