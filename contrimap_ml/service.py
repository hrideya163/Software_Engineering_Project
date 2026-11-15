"""Application service: repositories, issues, analysis, ranking, profiles.

Combines the trained artifacts (``artifacts/v2``) with live data:
* repository trees/contents come from git (no token needed);
* metadata, issues, trending and user history come from the GitHub REST API
  (``GITHUB_TOKEN`` optional; an invalid token falls back to anonymous access).
"""

from __future__ import annotations

import logging
import os
import re
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
    """In-memory TTL cache with single-flight loading.

    Concurrent requests for the same missing key wait for one ``factory`` call instead of
    each running it: the repository page fires overview, issues and architecture requests
    at once, and each used to snapshot the same repository in parallel.
    """

    def __init__(self, max_entries: int = 2048) -> None:
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._inflight: dict[str, threading.Lock] = {}
        self._max_entries = max_entries

    def peek(self, key: str) -> Any | None:
        with self._lock:
            hit = self._data.get(key)
            return hit[1] if hit and hit[0] > time.time() else None

    def get_or_set(self, key: str, ttl: float, factory: Callable[[], Any]) -> Any:
        with self._lock:
            hit = self._data.get(key)
            if hit and hit[0] > time.time():
                return hit[1]
            key_lock = self._inflight.setdefault(key, threading.Lock())
        with key_lock:
            with self._lock:
                hit = self._data.get(key)
                if hit and hit[0] > time.time():
                    return hit[1]
            try:
                value = factory()
            finally:
                with self._lock:
                    self._inflight.pop(key, None)
            with self._lock:
                if len(self._data) >= self._max_entries:
                    now = time.time()
                    expired = [k for k, (expiry, _) in self._data.items() if expiry <= now]
                    for stale in expired or sorted(self._data, key=lambda k: self._data[k][0])[: self._max_entries // 10]:
                        self._data.pop(stale, None)
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
        self._etags: dict[str, tuple[str, Any]] = {}
        self._etag_lock = threading.Lock()
        self.quota: dict[str, Any] | None = None

    def get(self, path: str, /, **params: Any) -> Any:
        """GET with conditional requests: a ``304 Not Modified`` answer does not count against the rate limit."""
        key = path + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))
        with self._etag_lock:
            cached = self._etags.get(key)
        headers = {"Authorization": f"Bearer {self.token}"} if self._token_valid else {}
        if cached:
            headers["If-None-Match"] = cached[0]
        try:
            response = self.session.get(f"{GITHUB_API}{path}", params=params, headers=headers, timeout=20)
            if response.status_code == 401 and self._token_valid:
                logger.warning("GITHUB_TOKEN rejected (401); continuing anonymously")
                self._token_valid = False
                headers.pop("Authorization", None)
                response = self.session.get(f"{GITHUB_API}{path}", params=params, headers=headers, timeout=20)
        except requests.RequestException as error:
            if cached:  # stale data beats an error page when GitHub is unreachable
                return cached[1]
            raise GitHubError(f"Could not reach GitHub ({error.__class__.__name__}).", 504) from error
        self._remember_quota(response)
        if response.status_code == 304 and cached:
            return cached[1]
        if response.status_code in (403, 429) and response.headers.get("X-RateLimit-Remaining") == "0" and cached:
            return cached[1]
        if response.status_code == 404:
            raise GitHubError("Not found on GitHub.", 404)
        if response.status_code in (403, 429) and response.headers.get("X-RateLimit-Remaining") == "0":
            reset = response.headers.get("X-RateLimit-Reset")
            when = datetime.fromtimestamp(int(reset), tz=timezone.utc).isoformat() if reset else "later"
            raise GitHubError(f"GitHub API rate limit exceeded (resets {when}). Set a valid GITHUB_TOKEN for 5,000 requests/hour.", 429)
        if response.status_code >= 400:
            raise GitHubError(f"GitHub API error {response.status_code}: {response.text[:200]}", 502)
        payload = response.json()
        etag = response.headers.get("ETag")
        if etag:
            with self._etag_lock:
                if len(self._etags) >= 4096:
                    self._etags.pop(next(iter(self._etags)))
                self._etags[key] = (etag, payload)
        return payload

    def _remember_quota(self, response: requests.Response) -> None:
        remaining, limit, reset = (response.headers.get(name) for name in ("X-RateLimit-Remaining", "X-RateLimit-Limit", "X-RateLimit-Reset"))
        if remaining is not None and limit is not None:
            self.quota = {"remaining": int(remaining), "limit": int(limit), "reset": int(reset) if reset else None}

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

        for directory in (ROOT / "data" / "ingested", ROOT / "data" / "ingested_train"):
            ingested = load_ingested(directory) if directory.exists() else pd.DataFrame()
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


PREPARATION_STAGES = [
    ("queued", "Waiting to start"),
    ("tree", "Reading the file tree with git"),
    ("contents", "Downloading source files"),
    ("imports", "Resolving imports and the technology stack"),
    ("graph", "Building the knowledge graph"),
    ("metrics", "Ranking core files and detecting modules"),
    ("ready", "Ready"),
]
_STAGE_INDEX = {name: index for index, (name, _) in enumerate(PREPARATION_STAGES)}
_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()


def _job_update(key: str, stage: str, message: str | None = None, **extra: Any) -> None:
    with _JOBS_LOCK:
        job = _JOBS.setdefault(key, {"started_at": time.time()})
        step = _STAGE_INDEX.get(stage, job.get("step", 0))
        job.update({"stage": stage, "message": message or dict(PREPARATION_STAGES).get(stage, stage), "step": step, "steps": len(PREPARATION_STAGES) - 1, "updated_at": time.time(), **extra})


def repository_context(owner: str, repo: str) -> dict[str, Any]:
    """Snapshot + knowledge graph + metrics for the default branch (cached ~15 min, single-flight)."""
    full = f"{owner}/{repo}"
    key = f"context:{full}".lower()

    def load() -> dict[str, Any]:
        _job_update(key, "tree", started_at=time.time(), state="running", error=None)
        try:
            snapshot = build_git_snapshot(full, progress=lambda stage, message: _job_update(key, stage, message))
        except Exception as error:
            failure = GitHubError(f"Could not fetch {full} with git: {error}", 404 if "not found" in str(error).lower() or "could not read" in str(error).lower() else 502)
            _job_update(key, "error", str(failure), state="error", error=str(failure))
            raise failure from error
        _job_update(key, "graph", f"Building the knowledge graph ({snapshot['file_count']:,} files)")
        graph = build_repository_graph(snapshot)
        _job_update(key, "metrics")
        metrics = graph_metrics(graph)
        _job_update(key, "ready", state="ready", file_count=snapshot["file_count"], sha=snapshot["sha"])
        return {"snapshot": snapshot, "graph": graph, "metrics": metrics}

    return CACHE.get_or_set(key, 900, load)


def preparation_status(owner: str, repo: str) -> dict[str, Any]:
    """Progress of the background snapshot/graph build shown while a repository page loads."""
    key = f"context:{owner}/{repo}".lower()
    labels = [label for _, label in PREPARATION_STAGES[1:]]
    if CACHE.peek(key) is not None:
        return {"state": "ready", "stage": "ready", "message": "Ready", "step": len(PREPARATION_STAGES) - 1, "steps": len(PREPARATION_STAGES) - 1, "stages": labels}
    with _JOBS_LOCK:
        job = dict(_JOBS.get(key) or {"state": "idle", "stage": "queued", "message": "Not started", "step": 0, "steps": len(PREPARATION_STAGES) - 1})
    if job.get("state") == "ready":  # finished earlier but the cached context expired
        job = {"state": "idle", "stage": "queued", "message": "Not started", "step": 0, "steps": len(PREPARATION_STAGES) - 1}
    if "started_at" in job:
        job["elapsed_seconds"] = round(time.time() - job["started_at"], 1)
    job["stages"] = labels
    return job


def prepare_repository(owner: str, repo: str) -> dict[str, Any]:
    """Start building the repository context in the background (idempotent) and return its status."""
    key = f"context:{owner}/{repo}".lower()
    with _JOBS_LOCK:
        state = (_JOBS.get(key) or {}).get("state")
    if CACHE.peek(key) is not None or state in ("running", "queued"):
        return preparation_status(owner, repo)
    _job_update(key, "queued", state="queued", started_at=time.time(), error=None)

    def run() -> None:
        try:
            repository_context(owner, repo)
        except Exception as error:  # recorded in the job; the page shows it
            _job_update(key, "error", str(error), state="error", error=str(error))

    threading.Thread(target=run, name=f"prepare-{owner}/{repo}", daemon=True).start()
    return preparation_status(owner, repo)


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


READ_CODE = os.getenv("CONTRIMAP_READ_CODE", "1") != "0"


def _localize_many(full: str, context: Mapping[str, Any], issues: Sequence[Mapping[str, Any]], queries: np.ndarray, top_k: int = 10) -> list[tuple[list[dict[str, Any]], dict[str, float]]]:
    """Localize several issues; the code of every shortlist is downloaded in one git request, then read locally."""
    from .repo_trees import fetch_blobs, prefetch_blobs

    model = models().localization
    snapshot = context["snapshot"]
    history = repo_history(full)
    with _PATH_LOCK:
        states = [model.shortlist(issue["title"], issue.get("body") or "", snapshot["files"], query, PATH_CACHE, history, _repo_languages().get(full)) for issue, query in zip(issues, queries)]
    download = True
    if READ_CODE:
        try:
            prefetch_blobs(full, [(snapshot["sha"], state.paths) for state in states if state.paths])
            download = False
        except Exception as error:  # fall back to per-issue reads (or stage 1 if those fail too)
            logger.warning("Could not prefetch shortlist code for %s: %s", full, error)
    results = []
    for state in states:
        contents: Mapping[str, str] = {}
        if READ_CODE and state.paths:
            try:
                contents = fetch_blobs(full, snapshot["sha"], state.paths, download=download)
            except Exception as error:
                logger.warning("Could not read shortlist code for %s: %s", full, error)
        results.append(model.finish(state, contents, top_k, with_signals=True))
    return results


def _localize(full: str, context: Mapping[str, Any], issue: Mapping[str, Any], query: np.ndarray, top_k: int = 10) -> tuple[list[dict[str, Any]], dict[str, float]]:
    return _localize_many(full, context, [issue], query[None, :], top_k)[0]


def _difficulty_batch(issues: Sequence[Mapping[str, Any]], embeddings: np.ndarray, signals: Sequence[Mapping[str, float]] | None = None) -> list[dict[str, Any]]:
    from .difficulty import DIFFICULTY_CLASSES, effort_from_distribution
    from .localization import LOC_SIGNALS

    frame = pd.DataFrame([{"title": i["title"], "body": i.get("body") or "", "labels": i.get("labels") or [], "text": f"{i['title']}\n{i.get('body') or ''}".strip()} for i in issues])
    matrix = np.asarray([[row.get(name, 0.0) for name in LOC_SIGNALS] for row in signals], dtype="float64") if signals else None
    output = models().difficulty.predict_frame(frame, embeddings, loc_signals=matrix)

    results = []
    for index in range(len(issues)):
        proba = output["proba"][index]
        best = int(proba.argmax())
        row = {
            "difficulty": DIFFICULTY_CLASSES[best],
            "difficulty_probability": float(proba[best]),
            "difficulty_distribution": {name: float(p) for name, p in zip(DIFFICULTY_CLASSES, proba)},
            "confidence": "low" if proba[best] < 0.5 else ("medium" if proba[best] < 0.65 else "high"),
            "difficulty_inputs": "issue text + likely change site (code read)" if output.get("uses_code_signals") else "issue text",
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


def _result_key(kind: str, owner: str, repo: str, *parts: Any) -> str:
    """Cache key for a computed result: the repository snapshot is part of the key via the context TTL."""
    import hashlib
    import json

    digest = hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return f"{kind}:{owner}/{repo}:{digest}".lower()


def analyze_issue(owner: str, repo: str, issue: Mapping[str, Any], profile_data: Mapping[str, Any] | None = None, with_explanation: bool = True) -> dict[str, Any]:
    """Full analysis; cached for 10 minutes per (issue text and update time, profile, explanation flag)."""
    key = _result_key("analysis", owner, repo, issue.get("number"), issue.get("title"), issue.get("body"), issue.get("labels"), issue.get("updated_at"), profile_data, with_explanation)
    return CACHE.get_or_set(key, 600, lambda: _analyze_issue(owner, repo, issue, profile_data, with_explanation))


def _analyze_issue(owner: str, repo: str, issue: Mapping[str, Any], profile_data: Mapping[str, Any] | None = None, with_explanation: bool = True) -> dict[str, Any]:
    full = f"{owner}/{repo}"
    context = repository_context(owner, repo)
    graph, metrics, snapshot = context["graph"], context["metrics"], context["snapshot"]
    text = f"{issue['title']}\n{issue.get('body') or ''}".strip()
    query = embed([text], cache=False)[0]
    files, signals = _localize(full, context, issue, query)
    estimate = _difficulty_batch([issue], query[None, :], [signals])[0]
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
        "localization_mode": ("history+text" if repo_history(full) is not None else "text-only (no resolved-issue history ingested for this repository)") + (" + code of the top candidates read" if files and files[0].get("code_read") else ""),
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


def ranked_issues(owner: str, repo: str, profile_data: Mapping[str, Any] | None = None, mode: str = "balanced", limit: int = 30, user: str | None = None) -> dict[str, Any]:
    """Ranked open issues; cached for 5 minutes (as long as the issue list) per profile, mode, limit and feedback state."""
    from . import feedback

    version = len(feedback.events(user)) if user else 0
    key = _result_key("ranked", owner, repo, profile_data, mode, limit, user, version)
    return CACHE.get_or_set(key, 300, lambda: _ranked_issues(owner, repo, profile_data, mode, limit, user))


FEEDBACK_WEIGHT = 0.12


def _issue_batch(owner: str, repo: str, limit: int) -> dict[str, Any]:
    """The expensive, profile-independent part of ranking (embeddings, localization, difficulty), cached per repository."""
    def load() -> dict[str, Any]:
        full = f"{owner}/{repo}"
        issues = list_issues(owner, repo, limit=limit)
        if not issues:
            return {"issues": []}
        context = repository_context(owner, repo)
        texts = [f"{i['title']}\n{i.get('body') or ''}".strip() for i in issues]
        embeddings = embed(texts, cache=False)
        localized = _localize_many(full, context, issues, embeddings, top_k=5)
        return {
            "issues": issues,
            "embeddings": embeddings,
            "localized": localized,
            "estimates": _difficulty_batch(issues, embeddings, [signals for _, signals in localized]),
            "actionability": models().actionability.predict(issues) if models().actionability is not None else None,
            "repo_skills": {skill["id"]: {"weight": skill["weight"], "evidence": skill["evidence"]} for skill in context["snapshot"]["skills"]},
        }

    return CACHE.get_or_set(f"issue-batch:{owner}/{repo}:{limit}".lower(), 300, load)


def _ranked_issues(owner: str, repo: str, profile_data: Mapping[str, Any] | None = None, mode: str = "balanced", limit: int = 30, user: str | None = None) -> dict[str, Any]:
    full = f"{owner}/{repo}"
    batch = _issue_batch(owner, repo, limit)
    issues = batch["issues"]
    if not issues:
        return {"repository": full, "issues": [], "personalized": bool(profile_data)}
    embeddings, localized, actionability, repo_skills = batch["embeddings"], batch["localized"], batch["actionability"], batch["repo_skills"]
    estimates = [dict(estimate) for estimate in batch["estimates"]]  # copies: ranking adds fields per call
    profile = UserProfile.from_dict(profile_data) if profile_data else None
    interest = _interest_embedding(tuple(profile.interests)) if profile else None
    analyses, extras, personal_details = [], [], []
    for issue, estimate, query, (files, _) in zip(issues, estimates, embeddings, localized):
        issue_skills = extract_issue_skills(issue["title"], issue.get("body") or "", issue.get("labels") or [], [f["path"] for f in files], repo_skills)
        analyses.append({**estimate, "files": files, "skills": as_public(issue_skills, limit=6)})
        if profile is not None:
            details = personal_components(profile, issue_skills, estimate["difficulty_distribution"], query, interest, _success(profile, issue, (profile_data or {}).get("history")))
            extras.append(details["components"])
            personal_details.append(details)
    weights = dict(personal_weights(profile, mode) if profile else DEFAULT_WEIGHTS)
    flags: dict[str, dict[str, Any]] = {}
    if user:
        from . import feedback

        flags = feedback.state(user, full)
        preference = feedback.preference_vector(feedback.events(user), lambda texts: embed(texts, cache=False))
        if preference is not None:
            # Cosine similarity to issues the user saved, completed or opened (minus dismissed), mapped to [0, 1].
            similarity = np.clip((embeddings @ preference + 1.0) / 2.0, 0.0, 1.0)
            extras = extras if profile else [{} for _ in issues]
            for position, value in enumerate(similarity):
                extras[position]["feedback"] = float(value)
            weights["feedback"] = FEEDBACK_WEIGHT
    ranked = rank_issues(issues, analyses, actionability, weights, extras if (profile or "feedback" in weights) else None)
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
            "confidence": analysis.get("confidence"),
            "localization_confidence": round(float(analysis["files"][0].get("relative_confidence") or 0.0), 3) if analysis["files"] else None,
        }
        state = flags.get(f"{full.lower()}#{item['issue']['number']}")
        if state:
            entry["feedback"] = {k: state[k] for k in ("opened", "saved", "dismissed", "completed")}
        if profile is not None:
            details = personal_details[position]
            entry["learning"] = details["learning"]
            entry["matched_skills"] = details["matched_skills"]
            entry["skill_gaps"] = details["skill_gaps"]
        output.append(entry)
    hidden = [entry for entry in output if (entry.get("feedback") or {}).get("dismissed")]
    output = [entry for entry in output if not (entry.get("feedback") or {}).get("dismissed")]
    for rank, entry in enumerate(output, 1):
        entry["rank"] = rank
    return {"repository": full, "personalized": profile is not None, "mode": mode, "weights": weights, "issues": output,
            "hidden": [{"number": e["issue"]["number"], "title": e["issue"]["title"]} for e in hidden], "uses_feedback": "feedback" in weights}


def learning_opportunities(owner: str, repo: str, profile_data: Mapping[str, Any], limit: int = 10) -> dict[str, Any]:
    ranked = ranked_issues(owner, repo, profile_data, mode="learning")
    items = sorted(ranked["issues"], key=lambda item: -(item.get("learning") or {}).get("score", 0.0))[:limit]
    return {"repository": ranked["repository"], "issues": items}


# ---------------------------------------------------------------------------
# Contributors and trending
# ---------------------------------------------------------------------------
PROFILE_PR_FILES = int(os.getenv("CONTRIMAP_PROFILE_PR_FILES", "8"))


def _attach_changed_files(contributions: list[dict[str, Any]], limit: int = PROFILE_PR_FILES) -> None:
    """Add the files changed by the most recent merged PRs, so skills come from code paths, not titles only.

    Costs one request per PR; skipped when the remaining GitHub quota is low (anonymous: 60/hour).
    """
    client = github()
    quota = client.quota or {}
    budget = limit if client.authenticated else min(limit, max(0, int(quota.get("remaining", 0)) - 30) // 2)
    for item in contributions[:budget]:
        if not item.get("number") or "/" not in item.get("repository", ""):
            continue
        try:
            files = client.get(f"/repos/{item['repository']}/pulls/{int(item['number'])}/files", per_page=100)
        except GitHubError as error:
            logger.info("Changed files unavailable for %s#%s: %s", item["repository"], item["number"], error)
            if error.status == 429:
                break
            continue
        item["files"] = [entry["filename"] for entry in files if isinstance(entry, Mapping) and entry.get("filename")]


def contributor_profile(login: str) -> dict[str, Any]:
    def load() -> dict[str, Any]:
        user = github().get(f"/users/{login}")
        repos = github().get(f"/users/{login}/repos", per_page=100, sort="pushed")
        merged = github().get("/search/issues", q=f"author:{login} type:pr is:merged", per_page=50, sort="updated")
        contributions = []
        for item in merged.get("items") or []:
            repo_name = item.get("repository_url", "").split("/repos/")[-1]
            contributions.append({"title": item.get("title") or "", "files": [], "created_at": item.get("created_at"), "repository": repo_name, "number": item.get("number")})
        _attach_changed_files(contributions)
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
            "recent_contributions": [{"title": c["title"], "repository": c["repository"], "created_at": c["created_at"], "files_changed": len(c["files"])} for c in contributions[:10]],
            "skills_from_changed_files": sum(1 for c in contributions if c["files"]),
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
    reranker = localization.get("code_reranker") or {}
    shipped = reranker if reranker.get("selected") else localization
    return {
        "difficulty_macro_f1_unseen_repos": (difficulty.get("test") or {}).get("model", {}).get("macro_f1"),
        "difficulty_baseline_macro_f1": (difficulty.get("test") or {}).get("baselines", {}).get("stratified_random", {}).get("macro_f1"),
        "effort_spearman_vs_human": (difficulty.get("effort") or {}).get("spearman_expected_hours_vs_human"),
        # The shipped model's numbers: stage 2 (code reading) when it was selected, else stage 1.
        "localization_acc_at_5_verified": (shipped.get("test_verified_tree") or {}).get("model", {}).get("acc@5"),
        "localization_acc_at_5_multilingual": (shipped.get("multilingual_tree") or {}).get("model", {}).get("acc@5"),
        "localization_acc_at_5_verified_without_history": (shipped.get("test_verified_nohist") or {}).get("model", {}).get("acc@5"),
        "localization_reads_code": bool(reranker.get("selected")),
    }


def health() -> dict[str, Any]:
    client = github()
    token = "missing" if not client.token else ("rejected" if not client.authenticated else "configured")
    status = {"artifacts": str(ARTIFACTS), "github_token": token, "github_quota": client.quota, "read_code": READ_CODE, "llm_configured": bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))}
    try:
        models()
        status["models_loaded"] = True
    except Exception as error:
        status["models_loaded"] = False
        status["error"] = str(error)
    return status


# ---------------------------------------------------------------------------
# Repository history: similar issues, resolving pull requests, changed files
# ---------------------------------------------------------------------------
def _map_pull(pull: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "number": int(pull["number"]), "title": pull.get("title") or "", "body": (pull.get("body") or "")[:4000],
        "merged_at": pull.get("merged_at"), "created_at": pull.get("created_at"), "closed_at": pull.get("closed_at"),
        "html_url": pull.get("html_url"), "author": (pull.get("user") or {}).get("login"),
        "labels": [label.get("name") for label in pull.get("labels") or [] if isinstance(label, Mapping)],
    }


def _closed_items(owner: str, repo: str) -> dict[str, Any]:
    """The 100 most recently updated closed issues and pull requests (two requests, cached 30 minutes)."""
    def load() -> dict[str, Any]:
        raw_issues = github().get(f"/repos/{owner}/{repo}/issues", state="closed", per_page=100, sort="updated", direction="desc")
        raw_pulls = github().get(f"/repos/{owner}/{repo}/pulls", state="closed", per_page=100, sort="updated", direction="desc")
        issues = [{**_map_issue(item), "closed_at": item.get("closed_at"), "state_reason": item.get("state_reason")} for item in raw_issues if "pull_request" not in item]
        pulls = [_map_pull(item) for item in raw_pulls]
        return {"issues": issues, "pulls": pulls, "fetched_at": time.time()}

    return CACHE.get_or_set(f"closed:{owner}/{repo}".lower(), 1800, load)


def _history_index(owner: str, repo: str) -> dict[str, Any]:
    from .history import HybridRetriever, history_text, link_history

    def load() -> dict[str, Any]:
        closed = _closed_items(owner, repo)
        # Issues closed as "not planned" carry no implementation to learn from.
        issues = [issue for issue in closed["issues"] if issue.get("state_reason") != "not_planned"]
        records = link_history(issues, [pull for pull in closed["pulls"] if pull.get("merged_at")])
        texts = [history_text(record["title"], record["body"]) for record in records]
        embeddings = embed(texts, cache=False) if texts else np.zeros((0, 384), dtype="float32")
        return {"records": records, "texts": texts, "retriever": HybridRetriever(texts, embeddings)}

    return CACHE.get_or_set(f"history-index:{owner}/{repo}".lower(), 1800, load)


def _pull_files(owner: str, repo: str, number: int) -> list[dict[str, Any]]:
    def load() -> list[dict[str, Any]]:
        files = github().get(f"/repos/{owner}/{repo}/pulls/{int(number)}/files", per_page=100)
        return [{"path": f["filename"], "status": f.get("status"), "additions": f.get("additions", 0), "deletions": f.get("deletions", 0)} for f in files if isinstance(f, Mapping) and f.get("filename")]

    return CACHE.get_or_set(f"pull-files:{owner}/{repo}#{number}".lower(), 86400, load)


def similar_history(owner: str, repo: str, issue: Mapping[str, Any], k: int = 5, predicted: Sequence[str] = ()) -> dict[str, Any]:
    """Past issues and merged PRs most similar to ``issue``, with the files their fixes changed."""
    from .history import changed_file_votes, history_text

    index = _history_index(owner, repo)
    text = history_text(issue["title"], issue.get("body") or "")
    query = embed([text], cache=False)[0]
    exclude = [position for position, record in enumerate(index["records"]) if record["kind"] == "issue" and record["number"] == issue.get("number")]
    similar = []
    budget = 5 if github().authenticated else 3  # PR file lookups cost one request each
    for position, score in index["retriever"].top(text, query, k=k, exclude=exclude):
        record = index["records"][position]
        item = {key: record[key] for key in ("kind", "number", "title", "closed_at", "html_url", "labels", "pull_requests")}
        item["similarity"] = round(score, 3)
        item["changed_files"] = []
        if record["pull_requests"] and budget > 0:
            budget -= 1
            try:
                files = _pull_files(owner, repo, record["pull_requests"][0]["number"])
                item["changed_files"] = [f["path"] for f in files]
                item["change_size"] = {"files": len(files), "additions": sum(f["additions"] for f in files), "deletions": sum(f["deletions"] for f in files)}
            except GitHubError as error:
                logger.info("PR files unavailable for %s/%s#%s: %s", owner, repo, record["pull_requests"][0]["number"], error)
        similar.append(item)
    votes = changed_file_votes(similar)
    predicted_set = set(predicted)
    for vote in votes:
        vote["also_predicted"] = vote["path"] in predicted_set
    return {
        "repository": f"{owner}/{repo}",
        "searched": len(index["records"]),
        "similar": similar,
        "historical_files": votes,
        "agreement": sum(1 for vote in votes[:10] if vote["also_predicted"]),
        "method": "hybrid MiniLM + TF-IDF over the 100 most recently closed issues and merged pull requests",
    }


# ---------------------------------------------------------------------------
# Visualizer: module drill-down and file inspector
# ---------------------------------------------------------------------------
def module_graph(owner: str, repo: str, directory: str, include_tests: bool = False, highlight: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    from .insights import module_view

    context = repository_context(owner, repo)
    return module_view(context["graph"], context["metrics"], directory, highlight, include_tests=include_tests)


_PR_IN_MESSAGE = re.compile(r"\(#(\d+)\)\s*$|Merge pull request #(\d+)")


def _file_commits(owner: str, repo: str, path: str) -> list[dict[str, Any]]:
    def load() -> list[dict[str, Any]]:
        commits = github().get(f"/repos/{owner}/{repo}/commits", path=path, per_page=10)
        out = []
        for item in commits:
            message = ((item.get("commit") or {}).get("message") or "").split("\n")[0]
            pull = _PR_IN_MESSAGE.search(message)
            out.append({
                "sha": item.get("sha", "")[:10], "message": message[:200], "html_url": item.get("html_url"),
                "date": ((item.get("commit") or {}).get("author") or {}).get("date"),
                "author": (item.get("author") or {}).get("login") or ((item.get("commit") or {}).get("author") or {}).get("name"),
                "pull_request": int(pull.group(1) or pull.group(2)) if pull else None,
            })
        return out

    return CACHE.get_or_set(f"file-commits:{owner}/{repo}:{path}".lower(), 3600, load)


def file_inspector(owner: str, repo: str, path: str, preview_lines: int = 120) -> dict[str, Any]:
    from .insights import extract_symbols, file_details, symbol_dependents, symbol_usage
    from .repo_trees import fetch_blobs

    full = f"{owner}/{repo}"
    context = repository_context(owner, repo)
    graph, metrics, snapshot = context["graph"], context["metrics"], context["snapshot"]
    try:
        details = file_details(graph, metrics, path)
    except KeyError:
        raise GitHubError(f"{path} is not a source file of {full}.", 404) from None
    wanted = [path] + details["dependents"][:12]
    try:
        contents = fetch_blobs(full, snapshot["sha"], wanted)
    except Exception as error:  # the inspector still shows graph data without code
        logger.warning("Could not read %s from %s: %s", path, full, error)
        contents = {}
    content = contents.get(path, "")
    symbols = extract_symbols(path, content)
    usage = symbol_usage(symbols, {p: contents.get(p, "") for p in details["dependents"][:12]})
    lines = content.splitlines()
    try:
        commits = _file_commits(owner, repo, path)
    except GitHubError as error:
        commits, details["history_error"] = [], str(error)
    related_issues = []
    index = CACHE.peek(f"history-index:{owner}/{repo}".lower())
    if index:
        pulls = {c["pull_request"] for c in commits if c.get("pull_request")}
        related_issues = [{"number": r["number"], "title": r["title"], "html_url": r["html_url"], "kind": r["kind"]} for r in index["records"] if any(p["number"] in pulls for p in r["pull_requests"])][:6]
    return {
        **details,
        "repository": full,
        "sha": snapshot["sha"],
        "html_url": f"https://github.com/{full}/blob/{snapshot['sha']}/{path}",
        "lines": len(lines),
        "preview": "\n".join(lines[:preview_lines]),
        "preview_truncated": len(lines) > preview_lines,
        "symbols": symbols,
        "symbol_usage": usage,
        "symbol_dependents": symbol_dependents(usage)[:15],
        "commits": commits,
        "related_issues": related_issues,
    }


# ---------------------------------------------------------------------------
# Repository health and activity
# ---------------------------------------------------------------------------
_NEWCOMER_LABEL = re.compile(r"good.first|beginner|easy|help.wanted", re.I)


def _median(values: Sequence[float]) -> float | None:
    return float(np.median(values)) if values else None


def _parse_time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def repository_activity(owner: str, repo: str, days: int = 90) -> dict[str, Any]:
    """Commit activity, contributor concentration, PR merge speed and issue responsiveness (cached 30 minutes)."""
    def load() -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=days)
        commits = github().get(f"/repos/{owner}/{repo}/commits", since=since.isoformat(), per_page=100)
        contributors = github().get(f"/repos/{owner}/{repo}/contributors", per_page=30)
        closed = _closed_items(owner, repo)
        open_issues = list_issues(owner, repo, limit=40)

        weeks = [0] * (days // 7 + 1)
        authors: Counter = Counter()
        for item in commits:
            when = _parse_time(((item.get("commit") or {}).get("author") or {}).get("date"))
            if when:
                weeks[min(len(weeks) - 1, max(0, (now - when).days // 7))] += 1
            login = (item.get("author") or {}).get("login") or ((item.get("commit") or {}).get("author") or {}).get("name") or "unknown"
            if not login.endswith("[bot]"):  # automation is not a maintainer
                authors[login] += 1
        ranked_authors = authors.most_common()
        covered, bus_factor = 0, 0
        for _, count in ranked_authors:
            covered += count
            bus_factor += 1
            if covered >= 0.5 * max(sum(authors.values()), 1):
                break

        merged = [p for p in closed["pulls"] if p.get("merged_at")]
        merge_days = [(_parse_time(p["merged_at"]) - _parse_time(p["created_at"])).total_seconds() / 86400 for p in merged if p.get("created_at")]
        recent_merged = [p for p in merged if _parse_time(p["merged_at"]) >= since]
        close_days = [(_parse_time(i["closed_at"]) - _parse_time(i["created_at"])).total_seconds() / 86400 for i in closed["issues"] if i.get("closed_at") and i.get("created_at")]
        open_age = [(now - _parse_time(i["created_at"])).total_seconds() / 86400 for i in open_issues if i.get("created_at")]
        unanswered = sum(1 for i in open_issues if not i.get("comments"))
        newcomer = sum(1 for i in open_issues if any(_NEWCOMER_LABEL.search(label or "") for label in i.get("labels") or []))

        pushed = _parse_time(_repo_meta(owner, repo).get("pushed_at"))
        median_merge = _median(merge_days)
        components = {
            "activity": min(1.0, len(commits) / 60.0),
            "recency": 1.0 if pushed and (now - pushed).days <= 7 else (0.6 if pushed and (now - pushed).days <= 30 else 0.2),
            "merge_speed": 1.0 / (1.0 + (median_merge if median_merge is not None else 30.0) / 7.0),
            "acceptance": len(merged) / max(len(closed["pulls"]), 1),
            "contributor_diversity": min(1.0, bus_factor / 4.0),
            "responsiveness": 1.0 - unanswered / max(len(open_issues), 1),
        }
        weights = {"activity": 0.2, "recency": 0.1, "merge_speed": 0.2, "acceptance": 0.2, "contributor_diversity": 0.15, "responsiveness": 0.15}
        score = sum(weights[k] * v for k, v in components.items())
        return {
            "repository": f"{owner}/{repo}",
            "window_days": days,
            "commits": {"total": len(commits), "capped": len(commits) >= 100, "weekly": list(reversed(weeks))},
            "contributors": {
                "active": len(authors),
                "bus_factor": bus_factor,
                "top": [{"login": login, "commits": count} for login, count in ranked_authors[:6]],
                "all_time": [{"login": c.get("login"), "contributions": c.get("contributions"), "avatar_url": c.get("avatar_url")} for c in contributors if isinstance(c, Mapping) and not str(c.get("login") or "").endswith("[bot]")][:8],
            },
            "pull_requests": {
                "sample": len(closed["pulls"]), "merged": len(merged), "merged_in_window": len(recent_merged), "closed_unmerged": len(closed["pulls"]) - len(merged),
                "median_days_to_merge": round(median_merge, 1) if median_merge is not None else None,
            },
            "issues": {
                "open_sampled": len(open_issues), "unanswered": unanswered, "newcomer_labelled": newcomer,
                "median_open_age_days": round(_median(open_age), 1) if open_age else None,
                "median_days_to_close": round(_median(close_days), 1) if close_days else None,
            },
            "health": {"score": round(score, 3), "components": {k: round(v, 3) for k, v in components.items()}, "weights": weights,
                       "label": "healthy" if score >= 0.65 else ("moderate" if score >= 0.4 else "low activity")},
            "note": "From the last 100 commits, the 100 most recently closed PRs and issues, and 40 open issues. A heuristic summary, not a trained model.",
        }

    return CACHE.get_or_set(f"activity:{owner}/{repo}:{days}".lower(), 1800, load)
