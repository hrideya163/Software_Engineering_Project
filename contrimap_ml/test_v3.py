"""Tests for code-reading localization, structural difficulty and backend caching (no network).

    python -m pytest contrimap_ml/test_v3.py -q
"""

from __future__ import annotations

import threading
import time

import numpy as np
import pandas as pd
import pytest

from contrimap_ml.code_features import CODE_FEATURES, code_features, definitions, issue_strings, issue_symbols
from contrimap_ml.localization import FEATURES, LOC_SIGNALS, RERANK_FEATURES, LocalizationModel, PathFeatureCache, localization_signals, rerank_inputs
from contrimap_ml.test_v2 import fake_embed


# ---------------------------------------------------------------------------
# Code features
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("source, expected", [
    ("class Parser:\n    def parse_header(self):\n        pass\nMAX_SIZE = 1\n", {"Parser", "parse_header", "MAX_SIZE"}),
    ("export function renderPage() {}\nexport const useStore = () => {}\n", {"renderPage", "useStore"}),
    ("func (s *Server) ServeHTTP(w Writer) {\n}\ntype Handler struct {}\n", {"ServeHTTP", "Handler"}),
    ("pub fn parse_args() {}\npub(crate) struct Config {}\n", {"parse_args", "Config"}),
    ("public class UserService {\n  public User findById(long id) {\n  }\n}\n", {"UserService", "findById"}),
])
def test_definitions_across_languages(source, expected):
    assert expected <= definitions(source)


def test_issue_symbols_and_strings():
    text = 'Calling `parse_header()` in requests.utils raises ValueError: "invalid header value given"'
    assert {"parse_header", "utils", "ValueError"} <= issue_symbols(text)
    assert "invalid header value given" in issue_strings(text)
    assert issue_strings("see 'src/app/main.py'") == []  # paths are not error messages


def test_code_features_reward_definitions_and_quoted_errors():
    text = 'parse_header() fails with "invalid header value given"'
    contents = {
        "pkg/http.py": 'def parse_header(value):\n    raise ValueError("Invalid header value given")\n',
        "pkg/client.py": "from .http import parse_header\nparse_header(x)\n",
        "pkg/other.py": "x = 1\n",
    }
    matrix = code_features(text, list(contents) + ["pkg/missing.py"], contents)
    column = {name: index for index, name in enumerate(CODE_FEATURES)}
    assert matrix.shape == (4, len(CODE_FEATURES))
    assert matrix[0, column["code_def_hits"]] > 0 and matrix[1, column["code_def_hits"]] == 0
    assert matrix[1, column["code_ref_hits"]] > 0
    assert matrix[0, column["code_string_hit"]] == 1 and matrix[1, column["code_string_hit"]] == 0
    assert matrix[3, column["code_missing"]] == 1 and matrix[0, column["code_missing"]] == 0


# ---------------------------------------------------------------------------
# Two-stage localization
# ---------------------------------------------------------------------------
class _PathRanker:
    """Stage 1 stand-in: prefers files whose name matches issue terms (bm25_name)."""

    def predict(self, x):
        return x[:, FEATURES.index("bm25_name")] + 0.01 * x[:, FEATURES.index("emb_sim")]


class _CodeRanker:
    """Stage 2 stand-in: the file that defines the named symbol wins."""

    def predict(self, x):
        return 10 * x[:, RERANK_FEATURES.index("code_def_hits")] + 0.1 * x[:, RERANK_FEATURES.index("stage1_score")]


FILES = ["src/header_utils.py", "src/http/parsing.py", "src/client.py", "tests/test_parsing.py", "README.md"]
ISSUE = ("header utils: parse_cookie_header crashes", "Calling parse_cookie_header() with an empty value raises IndexError")
CONTENTS = {
    "src/header_utils.py": "def format_header(v):\n    return v\n",
    "src/http/parsing.py": "def parse_cookie_header(value):\n    return value.split(';')[0]\n",
    "src/client.py": "from .http.parsing import parse_cookie_header\n",
}


def _model(reranker=None):
    return LocalizationModel(ranker=_PathRanker(), reranker=reranker)


def test_stage_two_reads_code_and_reorders():
    cache = PathFeatureCache(fake_embed)
    query = fake_embed(["\n".join(ISSUE)])[0]
    stage1 = _model().rank(*ISSUE, FILES, query, cache)
    assert stage1[0]["path"] == "src/header_utils.py" and not stage1[0]["code_read"]
    files, signals = _model(_CodeRanker()).rank(*ISSUE, FILES, query, cache, content_fn=lambda paths: {p: CONTENTS[p] for p in paths if p in CONTENTS}, with_signals=True)
    assert files[0]["path"] == "src/http/parsing.py" and files[0]["code_read"]
    assert "defines a symbol named in the issue" in files[0]["signals"]
    assert all(not path["path"].startswith("tests/") for path in files)
    assert set(signals) == set(LOC_SIGNALS) and signals["loc_code_missing"] < 1


def test_stage_two_degrades_to_stage_one_when_code_is_unavailable():
    cache = PathFeatureCache(fake_embed)
    query = fake_embed(["\n".join(ISSUE)])[0]

    def broken(paths):
        raise RuntimeError("network down")

    files = _model(_CodeRanker()).rank(*ISSUE, FILES, query, cache, content_fn=broken)
    assert files[0]["path"] == "src/header_utils.py" and not files[0]["code_read"]
    legacy = _model()
    del legacy.__dict__["reranker"]  # a model pickled before stage 2 existed
    assert legacy.rank(*ISSUE, FILES, query, cache, content_fn=lambda p: CONTENTS)[0]["path"] == "src/header_utils.py"


def test_localization_signals_summarise_the_shortlist():
    code = code_features("\n".join(ISSUE), list(CONTENTS), CONTENTS)
    inputs = rerank_inputs(np.zeros((3, len(FEATURES)), dtype="float32"), np.array([2.0, 1.0, 0.0], dtype="float32"), code)
    signals = localization_signals(inputs, list(CONTENTS), 120)
    assert signals["loc_dirs_top5"] == 2 and signals["loc_def_hit_top5"] > 0
    assert 0 < signals["loc_top1_conf"] < 1 and signals["loc_repo_files"] == pytest.approx(np.log1p(120))
    assert localization_signals(np.zeros((0, len(RERANK_FEATURES))), [], 0)["loc_code_missing"] == 1.0


# ---------------------------------------------------------------------------
# Structural difficulty head
# ---------------------------------------------------------------------------
def test_difficulty_uses_code_signals_only_when_given():
    from contrimap_ml.difficulty import _fit_components, _fit_head, _stack_inputs

    rng = np.random.default_rng(0)
    words = ["crash", "typo", "refactor", "docs", "parser", "timeout", "feature", "cache"]
    rows = [{"title": f"{rng.choice(words)} {rng.choice(words)} in module {i % 7}", "body": " ".join(rng.choice(words, 12)), "labels": [], "repo": f"r{i % 5}"} for i in range(90)]
    frame = pd.DataFrame(rows).assign(text=lambda f: f.title + "\n" + f.body)
    labels = np.arange(len(frame)) % 3
    embeddings = fake_embed(frame.text.tolist())
    from contrimap_ml.difficulty import handcrafted_matrix

    model = _fit_components(frame, handcrafted_matrix(frame), embeddings, labels, labels.astype(float), 0.5, [1.0, 2.0])
    text_only = model.predict_frame(frame, embeddings)
    assert not text_only["uses_code_signals"] and np.allclose(text_only["proba"], text_only["text_proba"])
    signals = np.column_stack([labels, rng.random((len(frame), len(LOC_SIGNALS) - 1))])  # first signal is informative
    model.structural = _fit_head(_stack_inputs(text_only["text_proba"], text_only["size"], signals), labels)
    with_code = model.predict_frame(frame, embeddings, loc_signals=signals)
    assert with_code["uses_code_signals"] and (with_code["label"] == labels).mean() > 0.9
    assert np.allclose(with_code["proba"].sum(axis=1), 1.0)


# ---------------------------------------------------------------------------
# Backend: single-flight cache, preparation jobs, conditional GitHub requests
# ---------------------------------------------------------------------------
def test_ttl_cache_runs_one_factory_for_concurrent_requests():
    from contrimap_ml.service import TTLCache

    cache, calls, results = TTLCache(), [], []

    def factory():
        calls.append(1)
        time.sleep(0.2)
        return "value"

    threads = [threading.Thread(target=lambda: results.append(cache.get_or_set("k", 60, factory))) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(calls) == 1 and results == ["value"] * 6
    with pytest.raises(ZeroDivisionError):
        cache.get_or_set("bad", 60, lambda: 1 / 0)
    assert cache.get_or_set("bad", 60, lambda: "recovered") == "recovered"  # failures are not cached


def test_prepare_repository_reports_progress_until_ready(monkeypatch):
    from contrimap_ml import service

    gate = threading.Event()

    def fake_snapshot(full, sha=None, progress=None):
        progress("contents", "Downloading 3 of 3 files")
        gate.wait(5)
        return {"sha": "abc", "file_count": 3, "files": ["a.py", "b.py", "c.py"], "import_edges": [], "test_edges": [], "skills": [], "packages": []}

    monkeypatch.setattr(service, "build_git_snapshot", fake_snapshot)
    monkeypatch.setattr(service, "build_repository_graph", lambda snapshot: "graph")
    monkeypatch.setattr(service, "graph_metrics", lambda graph: {"summary": {}, "pagerank": {}})
    indexed = []
    monkeypatch.setattr(service, "PATH_CACHE", type("FakePaths", (), {"ensure": lambda self, paths: indexed.extend(paths)})())
    service.CACHE._data.pop("context:acme/widget", None)
    service._JOBS.pop("context:acme/widget", None)
    first = service.prepare_repository("acme", "widget")
    assert first["state"] in ("queued", "running")
    deadline = time.time() + 5
    while service.preparation_status("acme", "widget").get("stage") != "contents" and time.time() < deadline:
        time.sleep(0.02)
    running = service.preparation_status("acme", "widget")
    assert running["stage"] == "contents" and running["message"].startswith("Downloading") and 0 < running["step"] < running["steps"]
    assert service.prepare_repository("acme", "widget")["state"] == "running"  # idempotent: no second build
    gate.set()
    while service.preparation_status("acme", "widget")["state"] != "ready" and time.time() < deadline:
        time.sleep(0.02)
    assert service.preparation_status("acme", "widget")["state"] == "ready"
    assert service.repository_context("acme", "widget")["graph"] == "graph"
    # Path embeddings are built in the background after the repository is ready (pages do not wait for them).
    while len(indexed) < 3 and time.time() < deadline:
        time.sleep(0.02)
    assert indexed == ["a.py", "b.py", "c.py"]


def test_ready_does_not_wait_for_path_indexing(monkeypatch):
    from contrimap_ml import service

    release, started = threading.Event(), threading.Event()

    def slow_ensure(self, paths):
        started.set()
        release.wait(5)

    monkeypatch.setattr(service, "build_git_snapshot", lambda full, sha=None, progress=None: {"sha": "abc", "file_count": 1, "files": ["a.py"], "import_edges": [], "test_edges": [], "skills": [], "packages": []})
    monkeypatch.setattr(service, "build_repository_graph", lambda snapshot: "graph")
    monkeypatch.setattr(service, "graph_metrics", lambda graph: {"summary": {}, "pagerank": {}})
    monkeypatch.setattr(service, "PATH_CACHE", type("SlowPaths", (), {"ensure": slow_ensure})())
    service.CACHE._data.pop("context:acme/slow", None)
    service._JOBS.pop("context:acme/slow", None)
    try:
        assert service.repository_context("acme", "slow")["graph"] == "graph"  # returns while indexing is still running
        assert started.wait(5) and service.preparation_status("acme", "slow")["state"] == "ready"
        assert service._PATH_LOCK.locked()  # ranking would wait here for the paths
    finally:
        release.set()


class _Response:
    def __init__(self, status, payload=None, headers=None):
        self.status_code, self._payload, self.headers, self.text = status, payload, headers or {}, ""

    def json(self):
        return self._payload


def test_github_client_reuses_etag_and_serves_stale_on_rate_limit():
    from contrimap_ml.service import GitHub

    client = GitHub(token="")
    sent = []
    replies = iter([
        _Response(200, {"stars": 1}, {"ETag": 'W/"v1"', "X-RateLimit-Remaining": "59", "X-RateLimit-Limit": "60"}),
        _Response(304, None, {"X-RateLimit-Remaining": "59", "X-RateLimit-Limit": "60"}),
        _Response(403, {"message": "rate limited"}, {"X-RateLimit-Remaining": "0", "X-RateLimit-Limit": "60", "X-RateLimit-Reset": "0"}),
    ])

    def fake_get(url, params=None, headers=None, timeout=None):
        sent.append(dict(headers or {}))
        return next(replies)

    client.session.get = fake_get
    assert client.get("/repos/a/b") == {"stars": 1}
    assert client.get("/repos/a/b") == {"stars": 1} and sent[1]["If-None-Match"] == 'W/"v1"'
    assert client.get("/repos/a/b") == {"stars": 1}  # stale copy instead of a 429 page
    assert client.quota == {"remaining": 0, "limit": 60, "reset": 0}


def test_prepare_and_status_routes(monkeypatch):
    from fastapi.testclient import TestClient

    from contrimap_ml import api, service

    monkeypatch.setattr(service, "prepare_repository", lambda owner, repo: {"state": "running", "stage": "tree", "step": 1, "steps": 6})
    monkeypatch.setattr(service, "preparation_status", lambda owner, repo: {"state": "ready", "stage": "ready", "step": 6, "steps": 6})
    client = TestClient(api.app)
    assert client.post("/api/repos/a/b/prepare").json()["state"] == "running"
    assert client.get("/api/repos/a/b/status").json()["state"] == "ready"
    assert client.post("/api/repos/a/b%2Fc/prepare").status_code in (404, 422)


def test_contributor_profiles_use_changed_files(monkeypatch):
    from contrimap_ml import service

    class FakeClient:
        authenticated, quota = True, None

        def get(self, path, **params):
            if path.endswith("/pulls/7/files"):
                return [{"filename": "src/server/router.go"}, {"filename": "Dockerfile"}]
            raise service.GitHubError("Not found on GitHub.", 404)

    monkeypatch.setattr(service, "github", lambda: FakeClient())
    contributions = [{"title": "Fix routing", "repository": "acme/api", "number": 7, "files": []}, {"title": "Docs", "repository": "acme/api", "number": 8, "files": []}]
    service._attach_changed_files(contributions)
    assert contributions[0]["files"] == ["src/server/router.go", "Dockerfile"] and contributions[1]["files"] == []
    from contrimap_ml.recommendation import ContributorProfile

    skills = ContributorProfile.from_contributions("dev", contributions).skills
    assert "go" in skills or "docker" in skills


def test_git_stdin_is_passed_byte_exact(tmp_path):
    """Object ids reach git through stdin; text-mode pipes on Windows used to append a carriage return."""
    import subprocess

    from contrimap_ml.repo_trees import TreeFetchError, _git_retry

    subprocess.run(["git", "init", "-q", "--bare", str(tmp_path)], check=True)
    # git's object id for the 4 bytes "abc\n": any "\r" would change it.
    assert _git_retry(["hash-object", "--stdin"], tmp_path, stdin="abc\n").strip() == "8baef1b4abc478178b004d62031cf7fe6db6f903"
    with pytest.raises(TreeFetchError):
        _git_retry(["rev-parse", "--verify", "no-such-ref"], tmp_path)  # non-network errors are not retried
