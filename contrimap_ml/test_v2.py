"""Tests for the v2 pipeline (no network, no trained artifacts, no GPU).

    python -m pytest contrimap_ml/test_v2.py -q
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import networkx as nx
import numpy as np
import pandas as pd
import pytest

from contrimap_ml.codegraph import architecture_view, build_repository_graph, file_tree, graph_metrics, impact_radius, import_edges, issue_view
from contrimap_ml.codegraph import test_edges as derive_test_edges
from contrimap_ml.corpus import CLOSING_REFERENCE, is_test_path, parse_patch
from contrimap_ml.github_ingest import _linked_issue_numbers
from contrimap_ml.guidance import UserProfile, contribution_path, detect_commands, learning_opportunity, resolve_skills
from contrimap_ml.ingest import pull_request_rows
from contrimap_ml.issue_ranking import availability_score, rank_issues
from contrimap_ml.localization import FEATURES, PathFeatureCache, RepoHistory, _bm25, candidate_features, localization_candidates, prefilter, ranking_metrics
from contrimap_ml.recommendation import ContributorProfile, difficulty_fit, score_contributor_for_issue
from contrimap_ml.skills import extract_issue_skills, extract_repository_skills, match_skills, skills_from_manifests, skills_from_text
from contrimap_ml.success import build_examples, history_features
from contrimap_ml.textfeat import extract_mentions, handcrafted_features, path_tokens, split_identifier


def fake_embed(texts):
    """Deterministic unit vectors: identical texts map to identical vectors."""
    rows = []
    for text in texts:
        seed = int(hashlib.md5(text.encode()).hexdigest()[:8], 16)
        vector = np.random.default_rng(seed).normal(size=384).astype("float32")
        rows.append(vector / np.linalg.norm(vector))
    return np.asarray(rows, dtype="float32")


# ---------------------------------------------------------------------------
# Corpus and labels
# ---------------------------------------------------------------------------
PATCH = """diff --git a/src/pkg/core.py b/src/pkg/core.py
--- a/src/pkg/core.py
+++ b/src/pkg/core.py
@@ -1,3 +1,4 @@
-old = 1
+new = 1
+extra = 2
@@ -10,2 +11,2 @@
-x
+y
diff --git a/src/pkg/new_mod.py b/src/pkg/new_mod.py
new file mode 100644
--- /dev/null
+++ b/src/pkg/new_mod.py
@@ -0,0 +1 @@
+print(1)
"""


def test_parse_patch_counts_lines_hunks_and_new_files():
    files = {item["path"]: item for item in parse_patch(PATCH)}
    assert files["src/pkg/core.py"]["added"] == 3 and files["src/pkg/core.py"]["deleted"] == 2
    assert files["src/pkg/core.py"]["hunks"] == 2
    assert files["src/pkg/new_mod.py"]["new"] is True


@pytest.mark.parametrize("path,expected", [
    ("tests/test_app.py", True), ("src/app_test.go", True), ("lib/foo.spec.ts", True), ("src/FooTest.java", True),
    ("spec/models/user_spec.rb", True), ("src/app.py", False), ("src/latest.py", False), ("docs/testing.md", False),
])
def test_is_test_path(path, expected):
    assert is_test_path(path) is expected


def test_closing_reference_requires_keyword():
    assert {int(m.group(3)) for m in CLOSING_REFERENCE.finditer("Fixes #12. Ref #13. closes: #14")} == {12, 14}
    assert _linked_issue_numbers({"title": "", "body": "see #5, resolves #6"}) == {6}


# ---------------------------------------------------------------------------
# Text features
# ---------------------------------------------------------------------------
def test_identifier_splitting_and_path_tokens():
    assert split_identifier("parseHTTPResponse_body") == ["parse", "http", "response", "body"]
    assert path_tokens("src/utils/dateFormat.ts") == ["date", "format"] or "date" in path_tokens("src/utils/dateFormat.ts")


def test_extract_mentions_finds_paths_tracebacks_modules():
    text = 'Error in `django/db/models/query.py`\nFile "/site/sklearn/utils/validation.py", line 3\nuse sklearn.linear_model.LogisticRegression and parse_args()'
    mentions = extract_mentions(text)
    assert "django/db/models/query.py" in mentions["paths"]
    assert any(path.endswith("sklearn/utils/validation.py") for path in mentions["paths"])
    assert "sklearn.linear_model.LogisticRegression" in mentions["dotted"]
    assert "parse_args" in mentions["identifiers"]


def test_handcrafted_features_flags():
    features = handcrafted_features("Fix crash in parser", "Steps to reproduce:\n```py\nx\n```\nTraceback (most recent call last)", ["good first issue"])
    assert features["title_bug"] == 1 and features["has_repro"] == 1 and features["has_traceback"] == 1
    assert features["code_blocks"] == 1 and features["label_good_first_issue"] == 1


# ---------------------------------------------------------------------------
# Localization
# ---------------------------------------------------------------------------
FILES = ["src/pkg/core.py", "src/pkg/parser.py", "src/pkg/__init__.py", "docs/index.md", "tests/test_parser.py", "setup.py", "src/pkg/http/client.py"]


def test_localization_candidates_exclude_tests_and_vendored():
    candidates = localization_candidates(FILES + ["node_modules/x/index.js", "yarn.lock"])
    assert "tests/test_parser.py" not in candidates and "node_modules/x/index.js" not in candidates and "yarn.lock" not in candidates
    assert "src/pkg/parser.py" in candidates


def test_bm25_prefers_matching_documents():
    scores = _bm25({"parser": 1, "error": 1}, [["core"], ["parser"], ["http", "client"]])
    assert scores.argmax() == 1 and scores[0] == 0


def test_candidate_features_detect_mentions_and_history():
    cache = PathFeatureCache(fake_embed)
    candidates = localization_candidates(FILES)
    history = RepoHistory.build([1.0, 2.0], fake_embed(["parser bug", "client timeout"]), [["src/pkg/parser.py"], ["src/pkg/http/client.py"]])
    query = fake_embed(["parser bug"])[0]
    text = "The parser crashes: see src/pkg/parser.py and pkg.http.client"
    matrix = candidate_features(text, query, candidates, cache, history.stats(query, before=10.0), "Python")
    column = {name: index for index, name in enumerate(FEATURES)}
    row = {path: matrix[i] for i, path in enumerate(candidates)}
    assert row["src/pkg/parser.py"][column["mention_path"]] == 1
    assert row["src/pkg/http/client.py"][column["mention_module"]] >= 2
    assert row["src/pkg/parser.py"][column["hist_freq"]] > 0
    assert row["src/pkg/parser.py"][column["knn_max"]] > 0.9  # identical earlier issue
    assert row["src/pkg/core.py"][column["lang_match"]] == 1 and row["docs/index.md"][column["is_doc"]] == 1


def test_history_is_point_in_time():
    history = RepoHistory.build([5.0, 1.0], fake_embed(["a", "b"]), [["late.py"], ["early.py"]])
    stats = history.stats(fake_embed(["a"])[0], before=3.0)
    assert stats["m"] == 1 and "late.py" not in stats["counts"] and stats["counts"]["early.py"] == 1


def test_prefilter_keeps_mentions_and_ranking_metrics():
    matrix = np.zeros((500, len(FEATURES)), dtype="float32")
    matrix[:, FEATURES.index("emb_sim")] = np.linspace(0, 1, 500)
    matrix[3, FEATURES.index("mention_path")] = 1
    kept = prefilter(matrix)
    assert 3 in kept and 499 in kept and len(kept) < 500
    metrics = ranking_metrics([["a", "b"], ["c", "d"]], [{"b"}, {"x"}], [{"a", "b"}, {"c", "d"}])
    assert metrics["acc@1"] == 0 and metrics["acc@5"] == 0.5 and metrics["mrr"] == 0.25 and metrics["oracle_candidate_coverage"] == 0.5


# ---------------------------------------------------------------------------
# Code graph
# ---------------------------------------------------------------------------
CONTENTS = {
    "src/pkg/__init__.py": "from .core import run\n",
    "src/pkg/core.py": "from pkg.parser import parse\nimport pkg.http.client\n",
    "src/pkg/parser.py": "import re\n",
    "src/pkg/http/client.py": "from ..core import run\n",
    "tests/test_parser.py": "from pkg.parser import parse\n",
    "web/app.ts": "import { x } from './lib/util'\nconst y = require('../web/lib/util')\n",
    "web/lib/util.ts": "export const x = 1\n",
    "go.mod": "module github.com/acme/tool\n",
    "cmd/main.go": 'package main\nimport (\n  "fmt"\n  "github.com/acme/tool/internal/db"\n)\n',
    "internal/db/db.go": "package db\n",
    "src/lib.rs": "mod parser;\nuse crate::parser::parse;\n",
    "src/parser.rs": "pub fn parse() {}\n",
    "app/Main.java": "import com.acme.util.Strings;\n",
    "src/main/java/com/acme/util/Strings.java": "class Strings {}\n",
}


def test_import_resolution_across_languages():
    edges = set(import_edges(list(CONTENTS), CONTENTS))
    assert ("src/pkg/core.py", "src/pkg/parser.py") in edges
    assert ("src/pkg/core.py", "src/pkg/http/client.py") in edges
    assert ("src/pkg/http/client.py", "src/pkg/core.py") in edges  # relative import
    assert ("web/app.ts", "web/lib/util.ts") in edges
    assert ("cmd/main.go", "internal/db/db.go") in edges
    assert ("src/lib.rs", "src/parser.rs") in edges
    assert ("app/Main.java", "src/main/java/com/acme/util/Strings.java") in edges


def _snapshot():
    files = list(CONTENTS)
    imports = import_edges(files, CONTENTS)
    return {"full_name": "acme/tool", "files": files, "import_edges": imports, "test_edges": derive_test_edges(files, imports), "packages": ["requests"], "skills": [{"id": "python", "name": "Python", "weight": 0.9}]}


def test_knowledge_graph_metrics_and_views():
    snapshot = _snapshot()
    assert ("tests/test_parser.py", "src/pkg/parser.py") in snapshot["test_edges"]
    graph = build_repository_graph(snapshot)
    assert graph.nodes["src/pkg/core.py"]["kind"] == "file" and graph.nodes["src/pkg"]["kind"] == "directory"
    metrics = graph_metrics(graph)
    assert metrics["summary"]["import_edges"] >= 6 and "tests/test_parser.py" not in metrics["summary"]["core_files"]
    assert "src/pkg/core.py" in impact_radius(graph, ["src/pkg/parser.py"])
    view = issue_view(graph, [{"path": "src/pkg/parser.py", "rank": 1, "relative_confidence": 0.8}], metrics)
    roles = {node["id"]: node["data"]["role"] for node in view["nodes"]}
    assert roles["src/pkg/parser.py"] == "target" and roles["src/pkg/core.py"] == "importer" and roles["tests/test_parser.py"] == "test"
    architecture = architecture_view(graph, metrics, [{"path": "src/pkg/parser.py", "rank": 1, "relative_confidence": 0.8}])
    assert architecture["nodes"] and any(node["data"]["highlight"] > 0 for node in architecture["nodes"])
    tree = file_tree(snapshot["files"], [{"path": "src/pkg/parser.py", "rank": 1}])
    assert tree["children"][0]["highlighted"] >= 1  # highlighted subtree sorted first


# ---------------------------------------------------------------------------
# Skills, recommendation, guidance
# ---------------------------------------------------------------------------
def test_skill_extraction_sources():
    text_skills = skills_from_text("Pandas DataFrame groupby is slow, add a benchmark")
    assert "pandas" in text_skills and "performance" in text_skills
    manifest = skills_from_manifests({"package.json": json.dumps({"dependencies": {"react": "18", "next": "14"}, "devDependencies": {"jest": "29"}})})
    assert {"react", "nextjs", "testing"} <= set(manifest)
    repo = extract_repository_skills(["a.py", "b.py", "c.py", "tests/test_a.py", "tests/test_b.py", "tests/test_c.py"])
    assert repo["python"]["weight"] > 0.5 and "testing" in repo
    issue = extract_issue_skills("Fix React hook warning", "useEffect runs twice", [], ["src/components/Button.tsx"])
    assert "react" in issue and "typescript" in issue


def test_skill_matching_with_prerequisite_credit():
    required = {"javascript": {"weight": 0.8}, "rust": {"weight": 0.6}}
    result = match_skills({"typescript": {"weight": 0.9}}, required)
    assert 0 < result["score"] < 1
    assert any(item["id"] == "javascript" for item in result["matched"])  # implied by TypeScript
    assert any(item["id"] == "rust" for item in result["gaps"])


def test_contributor_recommendation_components():
    profile = ContributorProfile.from_contributions("dev", [{"files": ["src/pkg/parser.py"], "title": "Fix parser", "created_at": "2024-01-01"}], fake_embed(["parser bug"]))
    issue_skills = extract_issue_skills("Parser bug", "", [], ["src/pkg/parser.py"])
    result = score_contributor_for_issue(profile, issue_skills, [{"path": "src/pkg/parser.py", "relative_confidence": 1.0}], fake_embed(["parser bug"])[0], {"Easy": 0.6, "Medium": 0.3, "Hard": 0.1}, 0.8)
    assert result["components"]["files"] == 1.0 and result["components"]["semantic"] > 0.99
    assert difficulty_fit("beginner", {"Easy": 1.0}) > difficulty_fit("beginner", {"Hard": 1.0})


def test_profile_learning_and_path():
    profile = UserProfile.from_dict({"level": "beginner", "tech_stack": ["Python"], "learning_goals": ["testing"], "time_budget_hours": 1})
    assert resolve_skills(["TS", "React", "type hints"])[:2] == ["typescript", "react"]
    issue_skills = {"python": {"weight": 0.8}, "testing": {"weight": 0.9}}
    easy = learning_opportunity(profile, issue_skills, {"Easy": 0.8, "Medium": 0.2, "Hard": 0.0}, 0.8)
    off_goal = learning_opportunity(profile, {"python": {"weight": 0.8}}, {"Easy": 0.8, "Medium": 0.2, "Hard": 0.0}, 0.8)
    assert easy["score"] > off_goal["score"] and easy["practised_goals"][0]["id"] == "testing"
    commands = detect_commands(["pyproject.toml", "tox.ini", "package.json", "yarn.lock", "go.mod"])
    assert "tox" in commands["test"] and "yarn install" in commands["install"] and "go test ./..." in commands["test"]
    analysis = {"files": [{"path": "src/pkg/parser.py"}], "related_tests": ["tests/test_parser.py"], "effort_hours": 2.0, "skill_gaps": [{"id": "typescript", "name": "TypeScript"}]}
    path = contribution_path({"number": 7}, analysis, {"files": ["pyproject.toml"], "readme": "README.md"}, profile=profile)
    ids = [step["id"] for step in path["steps"]]
    assert ids[0] == "learn" and "reproduce" in ids and path["fits_time_budget"] is False
    assert any("pytest tests/test_parser.py" in (step.get("commands") or []) for step in path["steps"])
    assert "Fixes #7" in path["steps"][-1]["detail"]


# ---------------------------------------------------------------------------
# Ranking and success
# ---------------------------------------------------------------------------
def test_rank_issues_orders_by_weighted_components():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fresh = {"number": 1, "title": "Fix crash", "body": "Steps to reproduce: ...", "labels": ["good first issue"], "updated_at": (now - timedelta(days=1)).isoformat()}
    stale = {"number": 2, "title": "Question?", "body": "", "labels": [], "assignees": ["someone"], "updated_at": (now - timedelta(days=400)).isoformat()}
    easy = {"difficulty_distribution": {"Easy": 0.8, "Medium": 0.2, "Hard": 0.0}, "files": []}
    hard = {"difficulty_distribution": {"Easy": 0.0, "Medium": 0.2, "Hard": 0.8}, "files": []}
    ranked = rank_issues([stale, fresh], [hard, easy], actionability=[0.1, 0.9], now=now)
    assert ranked[0]["issue"]["number"] == 1 and ranked[0]["rank"] == 1
    assert availability_score(stale) < availability_score(fresh)


def test_success_examples_are_point_in_time():
    prs = [
        {"user": {"login": "a"}, "created_at": "2024-01-01T00:00:00Z", "closed_at": "2024-01-02T00:00:00Z", "merged_at": "2024-01-02T00:00:00Z", "title": "fix", "body": ""},
        {"user": {"login": "a"}, "created_at": "2024-01-01T12:00:00Z", "closed_at": "2024-01-05T00:00:00Z", "merged_at": None, "title": "feat", "body": ""},
        {"user": {"login": "a"}, "created_at": "2024-01-10T00:00:00Z", "closed_at": "2024-01-11T00:00:00Z", "merged_at": "2024-01-11T00:00:00Z", "title": "docs", "body": ""},
    ]
    rows, labels, _ = build_examples(prs)
    # The second PR was opened before the first closed: no known history yet.
    assert rows[1]["is_first_pr"] == 1.0
    assert rows[2]["prior_prs"] == pytest.approx(np.log1p(2)) and labels.tolist() == [1, 0, 1]
    assert history_features([], datetime.now(timezone.utc))["prior_merge_rate"] == pytest.approx(0.75)


def test_graphql_rows_follow_corpus_schema():
    pr = {"number": 9, "merged": True, "createdAt": "2024-01-02T00:00:00Z", "mergedAt": "2024-01-03T00:00:00Z", "author": {"login": "dev"}, "changedFiles": 2,
          "commits": {"totalCount": 1}, "reviews": {"totalCount": 2},
          "files": {"nodes": [{"path": "src/a.py", "additions": 3, "deletions": 1}, {"path": "tests/test_a.py", "additions": 5, "deletions": 0}]},
          "closingIssuesReferences": {"nodes": [{"number": 4, "title": "Bug", "body": "x", "createdAt": "2024-01-01T00:00:00Z", "labels": {"nodes": [{"name": "bug"}]}}]}}
    [row] = pull_request_rows("acme/tool", pr)
    assert row["target_files"] == ["src/a.py"] and row["test_files"] == ["tests/test_a.py"]
    assert row["loc_added"] == 3 and row["labels"] == ["bug"] and row["author"] == "dev" and row["uid"] == "gh:acme/tool#4"


# ---------------------------------------------------------------------------
# API (service layer mocked)
# ---------------------------------------------------------------------------
def test_api_routes_with_mocked_service(monkeypatch):
    from fastapi.testclient import TestClient

    from contrimap_ml import api, service

    monkeypatch.setattr(service, "trending", lambda language, limit: {"source": "github", "repositories": [{"full_name": "a/b"}]})
    monkeypatch.setattr(service, "ranked_issues", lambda owner, repo, profile, mode="balanced", limit=30: {"repository": f"{owner}/{repo}", "personalized": bool(profile), "issues": [{"score": 0.5, "issue": {"number": 1}}]})

    def missing(owner, repo):
        raise service.GitHubError("Not found on GitHub.", 404)

    monkeypatch.setattr(service, "repository_overview", missing)
    client = TestClient(api.app)
    assert client.get("/api/trending?language=Python").json()["repositories"][0]["full_name"] == "a/b"
    assert client.get("/api/trending?language=%3Cscript%3E").status_code == 422
    assert client.get("/api/repos/a/b").status_code == 404
    assert client.get("/api/repos/a/b/issues").json()["personalized"] is False
    response = client.post("/api/repos/a/b/issues/ranked", json={"profile": {"level": "beginner", "tech_stack": ["Python"]}})
    assert response.status_code == 200 and response.json()["personalized"] is True
    assert client.post("/api/repos/a/b/issues/ranked", json={"profile": {"level": "guru"}}).status_code == 422
    merged = client.post("/api/recommendations", json={"profile": {"tech_stack": ["Go"]}, "repositories": ["a/b", "c/d"]}).json()
    assert len(merged["issues"]) == 2 and merged["issues"][0]["rank"] == 1
    assert client.post("/api/skills/extract", json={"text": "Rust tokio runtime panics"}).json()["skills"]
