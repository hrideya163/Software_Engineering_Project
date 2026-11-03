"""Application service: repositories, issues, analysis, ranking, profiles.

Combines the trained artifacts (``artifacts/v2``) with live data:
* repository trees/contents come from git (no token needed);
* metadata, issues, trending and user history come from the GitHub REST API
  (``GITHUB_TOKEN`` optional; an invalid token falls back to anonymous access).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import joblib
import numpy as np
import pandas as pd
import requests

from .codegraph import architecture_view, build_repository_graph, file_tree, graph_metrics, impact_radius, issue_view
from .guidance import UserProfile, contribution_path, personal_components, personal_weights
from .issue_ranking import DEFAULT_WEIGHTS, rank_issues
from .llm import explain
from .localization import LocalizationModel, PathFeatureCache, RepoHistory
from .recommendation import ContributorProfile, infer_level
from .skills import as_public, combine, extract_issue_skills, skills_from_text
from .snapshot import build_git_snapshot
from .textfeat import embed

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = Path(os.getenv("CONTRIMAP_ARTIFACT_DIR", ROOT / "artifacts" / "v2"))
GITHUB_API = "https://api.github.com"


class GitHubError(RuntimeError):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# Small TTL cache
# ---------------------------------------------------------------------------
class TTLCache:
    def __init__(self) -> None:
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def peek(self, key: str) -> Any | None:
        with self._lock:
            hit = self._data.get(key)
            return hit[1] if hit and hit[0] > time.time() else None

    def get_or_set(self, key: str, ttl: float, factory: Callable[[], Any]) -> Any:
        with self._lock:
            hit = self._data.get(key)
            if hit and hit[0] > time.time():
                return hit[1]
        value = factory()
        with self._lock:
            self._data[key] = (time.time() + ttl, value)
        return value


CACHE = TTLCache()


# ---------------------------------------------------------------------------
# GitHub REST
# ---------------------------------------------------------------------------
class GitHub:
    def __init__(self, token: str | None = None):
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
        self.token = token if token is not None else os.getenv("GITHUB_TOKEN")
        self._token_valid = bool(self.token)

    def get(self, path: str, **params: Any) -> Any:
        headers = {"Authorization": f"Bearer {self.token}"} if self._token_valid else {}
        try:
            response = self.session.get(f"{GITHUB_API}{path}", params=params, headers=headers, timeout=20)
            if response.status_code == 401 and self._token_valid:
                logger.warning("GITHUB_TOKEN rejected (401); continuing anonymously")
                self._token_valid = False
                response = self.session.get(f"{GITHUB_API}{path}", params=params, timeout=20)
        except requests.RequestException as error:
            raise GitHubError(f"Could not reach GitHub ({error.__class__.__name__}).", 504) from error
        if response.status_code == 404:
            raise GitHubError("Not found on GitHub.", 404)
        if response.status_code in (403, 429) and response.headers.get("X-RateLimit-Remaining") == "0":
            reset = response.headers.get("X-RateLimit-Reset")
            when = datetime.fromtimestamp(int(reset), tz=timezone.utc).isoformat() if reset else "later"
            raise GitHubError(f"GitHub API rate limit exceeded (resets {when}). Set a valid GITHUB_TOKEN for 5,000 requests/hour.", 429)
        if response.status_code >= 400:
            raise GitHubError(f"GitHub API error {response.status_code}: {response.text[:200]}", 502)
        return response.json()

    @property
    def authenticated(self) -> bool:
        return self._token_valid


@lru_cache(maxsize=1)
def github() -> GitHub:
    return GitHub()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
@dataclass
class Models:
    difficulty: Any
    localization: LocalizationModel
    success: Any | None
    actionability: Any | None
    report: dict[str, Any]


@lru_cache(maxsize=1)
def models() -> Models:
    import json

    report_path = ARTIFACTS / "evaluation_report.json"
    return Models(
        difficulty=joblib.load(ARTIFACTS / "difficulty.joblib"),
        localization=joblib.load(ARTIFACTS / "localization.joblib"),
        success=joblib.load(ARTIFACTS / "success.joblib") if (ARTIFACTS / "success.joblib").exists() else None,
        actionability=joblib.load(ARTIFACTS / "actionability.joblib") if (ARTIFACTS / "actionability.joblib").exists() else None,
        report=json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {},
    )


PATH_CACHE = PathFeatureCache(embed)
_PATH_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def _repo_languages() -> dict[str, str]:
    import json

    path = ARTIFACTS / "repo_languages.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


@lru_cache(maxsize=64)
def repo_history(repo: str) -> RepoHistory | None:
    """Resolved-issue history for ``repo`` from the corpus or ``data/ingested`` (point-in-time = now)."""
    frames = []
    corpus_path = ROOT / "data" / "processed" / "corpus.parquet"
    if corpus_path.exists():
        corpus = pd.read_parquet(corpus_path, columns=["repo", "created_at", "text", "target_files"])
        frames.append(corpus[corpus.repo.str.lower() == repo.lower()])
    try:
        from .ingest import load_ingested

        ingested = load_ingested()
        if not ingested.empty:
            frames.append(ingested[ingested.repo.str.lower() == repo.lower()][["repo", "created_at", "text", "target_files"]])
    except Exception:  # ingestion data is optional
        pass
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if frame.empty:
        return None
    times = (pd.to_datetime(frame.created_at, utc=True).astype("int64") // 10**9).tolist()
    return RepoHistory.build(times, embed(frame.text.fillna("").tolist()), [list(files) for files in frame.target_files])


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------
def _repo_meta(owner: str, repo: str) -> dict[str, Any]:
    def load() -> dict[str, Any]:
        data = github().get(f"/repos/{owner}/{repo}")
        languages = github().get(f"/repos/{owner}/{repo}/languages")
        return {
            "available": True,
            "full_name": data["full_name"],
            "owner": data["owner"]["login"],
            "name": data["name"],
            "description": data.get("description") or "",
            "stars": data.get("stargazers_count", 0),
            "forks": data.get("forks_count", 0),
            "open_issues": data.get("open_issues_count", 0),
            "language": data.get("language"),
            "topics": data.get("topics") or [],
            "default_branch": data.get("default_branch"),
            "license": (data.get("license") or {}).get("spdx_id"),
            "pushed_at": data.get("pushed_at"),
            "html_url": data.get("html_url"),
            "languages": languages,
        }

    try:
        return CACHE.get_or_set(f"meta:{owner}/{repo}".lower(), 600, load)
    except GitHubError as error:
        # Not cached: metadata reappears as soon as the rate limit resets.
        if error.status == 404:
            raise
        return {"full_name": f"{owner}/{repo}", "available": False, "reason": str(error)}


def repository_context(owner: str, repo: str) -> dict[str, Any]:
    """Snapshot + knowledge graph + metrics for the default branch (cached ~15 min)."""
    full = f"{owner}/{repo}"

    def load() -> dict[str, Any]:
        try:
            snapshot = build_git_snapshot(full)
        except Exception as error:
            raise GitHubError(f"Could not fetch {full} with git: {error}", 404 if "not found" in str(error).lower() or "could not read" in str(error).lower() else 502) from error
        graph = build_repository_graph(snapshot)
        return {"snapshot": snapshot, "graph": graph, "metrics": graph_metrics(graph)}

    return CACHE.get_or_set(f"context:{full}".lower(), 900, load)


def repository_overview(owner: str, repo: str) -> dict[str, Any]:
    meta = _repo_meta(owner, repo)
    context = repository_context(owner, repo)
    snapshot, metrics = context["snapshot"], context["metrics"]
    total = sum((meta.get("languages") or {}).values()) or 1
    languages = [{"name": name, "share": round(size / total, 4)} for name, size in sorted((meta.get("languages") or {}).items(), key=lambda item: -item[1])[:8]]
    if not languages:
        counts = Counter(str(context["graph"].nodes[path].get("language")) for path in snapshot["files"] if context["graph"].nodes[path].get("language"))
        languages = [{"name": name, "share": round(count / max(sum(counts.values()), 1), 4)} for name, count in counts.most_common(8)]
    top_dirs = Counter(path.split("/")[0] for path in snapshot["files"] if "/" in path)
    return {
        **meta,
        "sha": snapshot["sha"],
        "file_count": snapshot["file_count"],
        "languages_breakdown": languages,
        "skills": snapshot["skills"],
        "packages": snapshot["packages"][:40],
        "tests": len(snapshot["tests"]),
        "documentation": len(snapshot["documentation"]),
        "contributing": snapshot.get("contributing"),
        "readme": snapshot.get("readme"),
        "structure": [{"name": name, "files": count} for name, count in top_dirs.most_common(12)],
        "graph_summary": metrics["summary"],
        "core_files": [{"path": path, "importance": round(metrics["pagerank"].get(path, 0.0), 5)} for path in metrics["summary"].get("core_files", [])],
        "history_available": repo_history(f"{owner}/{repo}") is not None,
    }


def architecture(owner: str, repo: str, highlight: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    context = repository_context(owner, repo)
    return architecture_view(context["graph"], context["metrics"], highlight)


# ---------------------------------------------------------------------------
# Issues
# ---------------------------------------------------------------------------
def _map_issue(issue: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "number": int(issue["number"]),
        "title": str(issue.get("title") or ""),
        "body": str(issue.get("body") or "")[:20000],
        "labels": [str(label.get("name") if isinstance(label, Mapping) else label) for label in issue.get("labels") or []],
        "author": (issue.get("user") or {}).get("login"),
        "comments": issue.get("comments", 0),
        "assignees": [a.get("login") for a in issue.get("assignees") or []],
        "created_at": issue.get("created_at"),
        "updated_at": issue.get("updated_at"),
        "html_url": issue.get("html_url"),
        "locked": bool(issue.get("locked")),
        "reactions": (issue.get("reactions") or {}).get("total_count", 0),
    }


def list_issues(owner: str, repo: str, limit: int = 40) -> list[dict[str, Any]]:
    def load() -> list[dict[str, Any]]:
        # The issues endpoint also returns pull requests; fetch a full page so filtering them out leaves enough issues.
        raw = github().get(f"/repos/{owner}/{repo}/issues", state="open", per_page=100, sort="updated", direction="desc")
        return [_map_issue(item) for item in raw if "pull_request" not in item][:limit]

    return CACHE.get_or_set(f"issues:{owner}/{repo}:{limit}".lower(), 300, load)


def get_issue(owner: str, repo: str, number: int) -> dict[str, Any]:
    for issue in CACHE.peek(f"issues:{owner}/{repo}:40".lower()) or []:
        if issue["number"] == number:
            return issue
    return CACHE.get_or_set(f"issue:{owner}/{repo}#{number}".lower(), 300, lambda: _map_issue(github().get(f"/repos/{owner}/{repo}/issues/{number}")))


def _localize(full: str, context: Mapping[str, Any], issue: Mapping[str, Any], query: np.ndarray, top_k: int = 10) -> list[dict[str, Any]]:
    with _PATH_LOCK:
        return models().localization.rank(issue["title"], issue.get("body") or "", context["snapshot"]["files"], query, PATH_CACHE, repo_history(full), _repo_languages().get(full), top_k=top_k)


def _difficulty_batch(issues: Sequence[Mapping[str, Any]], embeddings: np.ndarray) -> list[dict[str, Any]]:
    frame = pd.DataFrame([{"title": i["title"], "body": i.get("body") or "", "labels": i.get("labels") or [], "text": f"{i['title']}\n{i.get('body') or ''}".strip()} for i in issues])
    output = models().difficulty.predict_frame(frame, embeddings)
    from .difficulty import DIFFICULTY_CLASSES, effort_from_distribution

    results = []
    for index in range(len(issues)):
        proba = output["proba"][index]
        best = int(proba.argmax())
        row = {
            "difficulty": DIFFICULTY_CLASSES[best],
            "difficulty_probability": float(proba[best]),
            "difficulty_distribution": {name: float(p) for name, p in zip(DIFFICULTY_CLASSES, proba)},
            "confidence": "low" if proba[best] < 0.5 else ("medium" if proba[best] < 0.65 else "high"),
        }
        if "effort_proba" in output:
            row.update(effort_from_distribution(output["effort_proba"][index], models().difficulty.metadata.get("effort_classes", [0, 1, 2])))
        results.append(row)
    return results


def _success(profile: UserProfile | None, issue: Mapping[str, Any], history: Mapping[str, Any] | None = None) -> float | None:
    if models().success is None:
        return None
    history = history or {}
    return models().success.predict_attempt(int(history.get("prior_prs", 0)), int(history.get("prior_merged", 0)), issue["title"], issue.get("body") or "", login=(profile.login if profile and profile.login else ""))


def analyze_issue(owner: str, repo: str, issue: Mapping[str, Any], profile_data: Mapping[str, Any] | None = None, with_explanation: bool = True) -> dict[str, Any]:
    full = f"{owner}/{repo}"
    context = repository_context(owner, repo)
    graph, metrics, snapshot = context["graph"], context["metrics"], context["snapshot"]
    text = f"{issue['title']}\n{issue.get('body') or ''}".strip()
    query = embed([text], cache=False)[0]
    estimate = _difficulty_batch([issue], query[None, :])[0]
    files = _localize(full, context, issue, query)
    for item in files:
        item["importance"] = round(metrics["pagerank"].get(item["path"], 0.0), 5)
    repo_skills = {skill["id"]: {"weight": skill["weight"], "evidence": skill["evidence"]} for skill in snapshot["skills"]}
    issue_skills = extract_issue_skills(issue["title"], issue.get("body") or "", issue.get("labels") or [], [f["path"] for f in files[:5]], repo_skills)
    related_tests = sorted({u for f in files[:3] if f["path"] in graph for u, _, d in graph.in_edges(f["path"], data=True) if d.get("type") == "tests"})[:6]
    impact = impact_radius(graph, [f["path"] for f in files[:3]])
    actionability = float(models().actionability.predict([issue])[0]) if models().actionability is not None else None
    profile = UserProfile.from_dict(profile_data) if profile_data else None
    success = _success(profile, issue, (profile_data or {}).get("history"))
    analysis: dict[str, Any] = {
        "repository": full,
        "sha": snapshot["sha"],
        "issue": {k: issue.get(k) for k in ("number", "title", "labels", "html_url", "created_at", "updated_at", "author", "comments")},
        **estimate,
        "files": files,
        "related_tests": related_tests,
        "impact": {"dependents_within_2_hops": len(impact), "examples": sorted(impact, key=lambda p: impact[p])[:5]},
        "skills": as_public(issue_skills, limit=10),
        "actionability": actionability,
        "success_probability": success,
        "localization_mode": "history+text" if repo_history(full) is not None else "text-only (no resolved-issue history ingested for this repository)",
    }
    if profile is not None:
        personal = personal_components(profile, issue_skills, estimate["difficulty_distribution"], query, _interest_embedding(tuple(profile.interests)), success)
        analysis["personal"] = personal
        analysis["skill_gaps"] = personal["skill_gaps"]
    manifests = {}
    analysis["contribution_path"] = contribution_path(issue, analysis, snapshot, graph, metrics, profile, manifests)
    analysis["graph"] = issue_view(graph, files, metrics)
    analysis["architecture_highlight"] = [{"path": f["path"], "rank": f["rank"], "relative_confidence": f["relative_confidence"]} for f in files[:5]]
    analysis["tree"] = file_tree(snapshot["files"], files[:10])
    if with_explanation:
        analysis["explanation"] = explain(issue, analysis, profile.to_public() if profile else None)
    analysis["model_card"] = model_card_summary()
    return analysis


@lru_cache(maxsize=256)
def _interest_embedding(interests: tuple[str, ...]) -> np.ndarray | None:
    if not interests:
        return None
    vector = embed([" ; ".join(interests)], cache=False)[0]
    return vector / max(float(np.linalg.norm(vector)), 1e-9)


def ranked_issues(owner: str, repo: str, profile_data: Mapping[str, Any] | None = None, mode: str = "balanced", limit: int = 30) -> dict[str, Any]:
    full = f"{owner}/{repo}"
    issues = list_issues(owner, repo, limit=limit)
    if not issues:
        return {"repository": full, "issues": [], "personalized": bool(profile_data)}
    context = repository_context(owner, repo)
    texts = [f"{i['title']}\n{i.get('body') or ''}".strip() for i in issues]
    embeddings = embed(texts, cache=False)
    estimates = _difficulty_batch(issues, embeddings)
    actionability = models().actionability.predict(issues) if models().actionability is not None else None
    repo_skills = {skill["id"]: {"weight": skill["weight"], "evidence": skill["evidence"]} for skill in context["snapshot"]["skills"]}
    profile = UserProfile.from_dict(profile_data) if profile_data else None
    interest = _interest_embedding(tuple(profile.interests)) if profile else None
    analyses, extras, personal_details = [], [], []
    for issue, estimate, query in zip(issues, estimates, embeddings):
        files = _localize(full, context, issue, query, top_k=5)
        issue_skills = extract_issue_skills(issue["title"], issue.get("body") or "", issue.get("labels") or [], [f["path"] for f in files], repo_skills)
        analyses.append({**estimate, "files": files, "skills": as_public(issue_skills, limit=6)})
        if profile is not None:
            details = personal_components(profile, issue_skills, estimate["difficulty_distribution"], query, interest, _success(profile, issue, (profile_data or {}).get("history")))
            extras.append(details["components"])
            personal_details.append(details)
    weights = personal_weights(profile, mode) if profile else DEFAULT_WEIGHTS
    ranked = rank_issues(issues, analyses, actionability, weights, extras if profile else None)
    index_of = {issue["number"]: position for position, issue in enumerate(issues)}
    output = []
    for item in ranked:
        position = index_of[item["issue"]["number"]]
        analysis = analyses[position]
        entry = {
            "rank": item["rank"],
            "score": round(item["score"], 4),
            "components": {k: round(v, 4) for k, v in item["components"].items()},
            "issue": {k: item["issue"].get(k) for k in ("number", "title", "labels", "html_url", "comments", "created_at", "updated_at", "assignees")},
            "summary": (item["issue"].get("body") or "")[:220],
            "difficulty": analysis["difficulty"],
            "difficulty_distribution": analysis["difficulty_distribution"],
            "effort_bucket": analysis.get("effort_bucket"),
            "effort_hours": analysis.get("effort_hours"),
            "top_files": [f["path"] for f in analysis["files"][:3]],
            "skills": analysis["skills"],
        }
        if profile is not None:
            details = personal_details[position]
            entry["learning"] = details["learning"]
            entry["matched_skills"] = details["matched_skills"]
            entry["skill_gaps"] = details["skill_gaps"]
        output.append(entry)
    return {"repository": full, "personalized": profile is not None, "mode": mode, "weights": weights, "issues": output}


def learning_opportunities(owner: str, repo: str, profile_data: Mapping[str, Any], limit: int = 10) -> dict[str, Any]:
    ranked = ranked_issues(owner, repo, profile_data, mode="learning")
    items = sorted(ranked["issues"], key=lambda item: -(item.get("learning") or {}).get("score", 0.0))[:limit]
    return {"repository": ranked["repository"], "issues": items}


# ---------------------------------------------------------------------------
# Contributors and trending
# ---------------------------------------------------------------------------
def contributor_profile(login: str) -> dict[str, Any]:
    def load() -> dict[str, Any]:
        user = github().get(f"/users/{login}")
        repos = github().get(f"/users/{login}/repos", per_page=100, sort="pushed")
        merged = github().get("/search/issues", q=f"author:{login} type:pr is:merged", per_page=50, sort="updated")
        contributions = []
        for item in merged.get("items") or []:
            repo_name = item.get("repository_url", "").split("/repos/")[-1]
            contributions.append({"title": item.get("title") or "", "files": [], "created_at": item.get("created_at"), "repository": repo_name})
        languages = Counter(r.get("language") for r in repos if r.get("language") and not r.get("fork"))
        topics = [topic for r in repos for topic in (r.get("topics") or [])]
        profile = ContributorProfile.from_contributions(login, contributions)
        language_skills = combine(*[skills_from_text(language, weight=min(1.0, 0.3 + 0.1 * count)) for language, count in languages.most_common(6)], skills_from_text(" ".join(topics), weight=0.5))
        profile.skills = combine(profile.skills, language_skills)
        total_merged = int(merged.get("total_count") or 0)
        profile.level = infer_level(total_merged)
        public = profile.to_public()
        public.update({
            "name": user.get("name"), "avatar_url": user.get("avatar_url"), "html_url": user.get("html_url"), "bio": user.get("bio"),
            "public_repos": user.get("public_repos"), "followers": user.get("followers"), "merged_pull_requests": total_merged,
            "top_languages": [{"name": name, "repositories": count} for name, count in languages.most_common(6)],
            "recent_contributions": [{"title": c["title"], "repository": c["repository"], "created_at": c["created_at"]} for c in contributions[:10]],
            "suggested_profile": {"level": profile.level, "tech_stack": [s["name"] for s in as_public(profile.skills, 6) if s["category"] in {"language", "framework"}], "interests": topics[:6]},
        })
        return public

    return CACHE.get_or_set(f"user:{login}".lower(), 900, load)


# Shown only when the GitHub search API is unreachable or rate-limited; flagged as such.
CURATED_REPOSITORIES = [
    ("vercel/next.js", "TypeScript"), ("facebook/react", "JavaScript"), ("pallets/flask", "Python"), ("fastapi/fastapi", "Python"),
    ("pandas-dev/pandas", "Python"), ("scikit-learn/scikit-learn", "Python"), ("rust-lang/rust", "Rust"), ("tokio-rs/tokio", "Rust"),
    ("golang/go", "Go"), ("spf13/cobra", "Go"), ("vitejs/vite", "TypeScript"), ("microsoft/vscode", "TypeScript"),
]


def trending(language: str | None = None, limit: int = 12, window_days: int = 30) -> dict[str, Any]:
    language = (language or "").strip()

    def load() -> dict[str, Any]:
        since = (datetime.now(timezone.utc) - timedelta(days=window_days)).date().isoformat()
        query = f"pushed:>{since} stars:>1000 archived:false good-first-issues:>0" + (f' language:"{language}"' if language else "")
        try:
            result = github().get("/search/repositories", q=query, sort="stars", order="desc", per_page=min(50, limit * 2))
        except GitHubError as error:
            curated = [{"full_name": name, "owner": name.split("/")[0], "name": name.split("/")[1], "language": lang} for name, lang in CURATED_REPOSITORIES if not language or lang.lower() == language.lower()]
            return {"source": "curated", "note": f"Live trending unavailable: {error}", "repositories": curated[:limit]}
        repos = []
        for item in result.get("items") or []:
            # Momentum: stars weighted by recency of activity (GitHub has no trending API).
            pushed = datetime.fromisoformat(item["pushed_at"].replace("Z", "+00:00"))
            days = max((datetime.now(timezone.utc) - pushed).total_seconds() / 86400, 0)
            repos.append({
                "full_name": item["full_name"], "owner": item["owner"]["login"], "name": item["name"],
                "description": item.get("description") or "", "stars": item["stargazers_count"], "forks": item["forks_count"],
                "open_issues": item["open_issues_count"], "language": item.get("language"), "topics": (item.get("topics") or [])[:5],
                "pushed_at": item["pushed_at"], "html_url": item["html_url"],
                "momentum": round(float(np.log10(item["stargazers_count"] + 1) * 0.5 ** (days / 7)), 4),
            })
        repos.sort(key=lambda repo: -repo["momentum"])
        return {"source": "github", "window_days": window_days, "repositories": repos[:limit]}

    return CACHE.get_or_set(f"trending:{language}:{limit}:{window_days}".lower(), 900, load)


def model_card_summary() -> dict[str, Any]:
    report = models().report
    difficulty = report.get("difficulty", {})
    localization = report.get("localization", {})
    return {
        "difficulty_macro_f1_unseen_repos": (difficulty.get("test") or {}).get("model", {}).get("macro_f1"),
        "difficulty_baseline_macro_f1": (difficulty.get("test") or {}).get("baselines", {}).get("stratified_random", {}).get("macro_f1"),
        "effort_spearman_vs_human": (difficulty.get("effort") or {}).get("spearman_expected_hours_vs_human"),
        "localization_acc_at_5_verified": (localization.get("test_verified_tree") or {}).get("model", {}).get("acc@5"),
        "localization_acc_at_5_multilingual": (localization.get("multilingual_tree") or {}).get("model", {}).get("acc@5"),
    }


def health() -> dict[str, Any]:
    client = github()
    token = "missing" if not client.token else ("rejected" if not client.authenticated else "configured")
    status = {"artifacts": str(ARTIFACTS), "github_token": token, "llm_configured": bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))}
    try:
        models()
        status["models_loaded"] = True
    except Exception as error:
        status["models_loaded"] = False
        status["error"] = str(error)
    return status
