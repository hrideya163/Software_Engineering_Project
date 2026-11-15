"""Tests for repository history, the visualizer's file/module views and recommendation feedback (no network).

    python -m pytest contrimap_ml/test_v4.py -q
"""

from __future__ import annotations

import networkx as nx
import numpy as np
import pytest

from contrimap_ml import feedback
from contrimap_ml.history import HybridRetriever, changed_file_votes, history_text, link_history, linked_issues
from contrimap_ml.insights import extract_symbols, file_details, module_view, symbol_dependents, symbol_usage
from contrimap_ml.test_v2 import fake_embed


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------
def test_linked_issues_closing_keywords():
    assert linked_issues("Fixes #12 and closes #7. Resolved owner/repo#99") == [12, 7, 99]
    assert linked_issues("Related to #5") == []
    assert linked_issues("Related to #5", closing_only=False) == [5]
    assert linked_issues(None) == []


def test_history_text_drops_code_and_links():
    text = history_text("Crash on start", "See https://x.y/z\n```\nTraceback ...\n```\nreal words")
    assert "Traceback" not in text and "https" not in text and "real words" in text


def test_link_history_attaches_resolving_pulls_and_keeps_unlinked_pulls():
    issues = [{"number": 1, "title": "Bug A", "body": ""}, {"number": 2, "title": "Bug B", "body": ""}]
    pulls = [{"number": 10, "title": "Fix A", "body": "Fixes #1", "merged_at": "2026-01-01"}, {"number": 11, "title": "Refactor", "body": "", "merged_at": "2026-01-02"}]
    records = {(r["kind"], r["number"]): r for r in link_history(issues, pulls)}
    assert [p["number"] for p in records[("issue", 1)]["pull_requests"]] == [10]
    assert records[("issue", 2)]["pull_requests"] == []
    assert ("pull_request", 11) in records and ("pull_request", 10) not in records


def test_hybrid_retriever_ranks_the_matching_record_first():
    texts = ["option envvar missing from error message", "colour output on windows terminal", "progress bar flickers"]
    retriever = HybridRetriever(texts, fake_embed(texts), semantic_weight=0.0)  # fake embeddings carry no meaning: test the keyword side
    query = "error message drops the envvar of an option"
    top = retriever.top(query, fake_embed([query])[0], k=2)
    assert top and top[0][0] == 0
    assert all(index != 0 for index, _ in retriever.top(query, fake_embed([query])[0], k=3, exclude=[0]))


def test_changed_file_votes_weight_by_similarity():
    votes = changed_file_votes([{"number": 1, "similarity": 0.9, "changed_files": ["a.py", "b.py"]}, {"number": 2, "similarity": 0.4, "changed_files": ["b.py"]}])
    assert votes[0]["path"] == "b.py" and votes[0]["from"] == [1, 2]


# ---------------------------------------------------------------------------
# Symbols, file details and module view
# ---------------------------------------------------------------------------
PY = "class Parser:\n    def parse(self):\n        pass\n\ndef helper():\n    return 1\n\ndef _private():\n    pass\n"


def test_extract_symbols_python_with_lines():
    symbols = {s["name"]: s for s in extract_symbols("pkg/parser.py", PY)}
    assert symbols["Parser"]["kind"] == "class" and symbols["Parser"]["line"] == 1
    assert symbols["parse"]["kind"] == "method" and symbols["helper"]["line"] == 5
    assert symbols["_private"]["private"]


def test_extract_symbols_javascript_and_unknown_language():
    js = "export default function App() {}\nexport const useStore = () => {}\ninterface Props {}\nclass Store {}\n"
    assert {"App", "useStore", "Props", "Store"} <= {s["name"] for s in extract_symbols("src/app.tsx", js)}
    assert extract_symbols("README.md", "# Title") == []


def test_symbol_usage_and_inversion():
    symbols = extract_symbols("pkg/parser.py", PY)
    usage = symbol_usage(symbols, {"pkg/cli.py": "from pkg.parser import Parser, helper\nParser().parse()\nhelper()", "pkg/other.py": "print(1)"})
    assert usage == [{"path": "pkg/cli.py", "symbols": ["Parser", "helper", "parse"], "references": 5}]
    assert {item["name"] for item in symbol_dependents(usage)} == {"Parser", "helper", "parse"}


def _graph() -> nx.DiGraph:
    graph = nx.DiGraph()
    for path in ["pkg/a.py", "pkg/b.py", "pkg/c.py", "app/main.py", "tests/test_b.py"]:
        graph.add_node(path, kind="file", language="Python", is_test=path.startswith("tests/"))
    graph.add_edge("pkg/a.py", "pkg/b.py", type="imports")
    graph.add_edge("pkg/b.py", "pkg/c.py", type="imports")
    graph.add_edge("app/main.py", "pkg/a.py", type="imports")
    graph.add_edge("tests/test_b.py", "pkg/b.py", type="tests")
    return graph


METRICS = {"pagerank": {"pkg/c.py": 0.4, "pkg/b.py": 0.3, "pkg/a.py": 0.2, "app/main.py": 0.05, "tests/test_b.py": 0.05}, "community": {"pkg/a.py": 0, "pkg/b.py": 0, "pkg/c.py": 0}}


def test_file_details_lists_links():
    details = file_details(_graph(), METRICS, "pkg/b.py")
    assert details["imports"] == ["pkg/c.py"] and details["dependents"] == ["pkg/a.py"] and details["tests"] == ["tests/test_b.py"]
    with pytest.raises(KeyError):
        file_details(_graph(), METRICS, "missing.py")


def test_module_view_layers_left_to_right_and_shows_outside_importers():
    view = module_view(_graph(), METRICS, "pkg", highlight=[{"path": "pkg/b.py", "rank": 1}])
    x = {node["id"]: node["position"]["x"] for node in view["nodes"]}
    assert x["pkg/a.py"] < x["pkg/b.py"] < x["pkg/c.py"]  # importer left of what it imports
    assert view["layers"] == 3 and view["files_total"] == 3
    types = {node["id"]: node["type"] for node in view["nodes"]}
    assert types["pkg/b.py"] == "target" and types["ext:in:app/"] == "external"
    assert "tests/test_b.py" not in types  # outside the module


def test_module_view_wraps_tall_layers():
    graph = nx.DiGraph()
    for index in range(10):
        graph.add_node(f"m/f{index}.py", kind="file", is_test=False)
    view = module_view(graph, {"pagerank": {}}, "m", rows_per_column=4)
    assert max(node["position"]["y"] for node in view["nodes"]) <= 3 * 92.0
    assert len({node["position"]["x"] for node in view["nodes"]}) == 3


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------
@pytest.fixture()
def feedback_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(feedback, "FEEDBACK_DIR", tmp_path)
    return tmp_path


def test_feedback_state_latest_action_wins(feedback_dir):
    feedback.record("alice", "o/r", 1, "saved", "One", "one text")
    feedback.record("alice", "o/r", 1, "unsaved")
    feedback.record("alice", "o/r", 2, "dismissed", "Two", "two text")
    feedback.record("alice", "o/r", 3, "completed", "Three", "three text")
    state = feedback.state("alice", "o/r")
    assert not state["o/r#1"]["saved"] and state["o/r#2"]["dismissed"] and state["o/r#3"]["completed"]
    assert feedback.summary("alice")["counts"] == {"opened": 0, "saved": 0, "dismissed": 1, "completed": 1}


def test_feedback_rejects_bad_input(feedback_dir):
    with pytest.raises(ValueError):
        feedback.record("../evil", "o/r", 1, "saved")
    with pytest.raises(ValueError):
        feedback.record("bob", "o/r", 1, "liked")


def test_preference_vector_points_towards_saved_issues():
    events = [
        {"repository": "o/r", "number": 1, "action": "saved", "text": "option envvar error message"},
        {"repository": "o/r", "number": 2, "action": "dismissed", "text": "windows terminal colours"},
    ]
    vector = feedback.preference_vector(events, fake_embed)
    saved, dismissed = fake_embed(["option envvar error message", "windows terminal colours"])
    assert vector is not None and float(vector @ saved) > float(vector @ dismissed)
    assert feedback.preference_vector(events[1:], fake_embed) is None  # only negative signal: no preference


def test_feedback_api_round_trip(feedback_dir):
    from fastapi.testclient import TestClient

    from contrimap_ml.api import app

    client = TestClient(app)
    response = client.post("/api/feedback", json={"user": "carol", "repository": "o/r", "number": 4, "action": "saved", "title": "T"})
    assert response.status_code == 200 and response.json()["state"]["saved"]
    assert client.get("/api/feedback/carol").json()["counts"]["saved"] == 1
    assert client.post("/api/feedback", json={"user": "carol", "repository": "o/r", "number": 4, "action": "boost"}).status_code == 422
    assert client.get("/api/repos/o/r/file", params={"path": "../etc/passwd"}).status_code == 422
