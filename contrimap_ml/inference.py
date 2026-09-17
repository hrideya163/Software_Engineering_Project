"""Frontend-facing inference services for ContriMap.

This module deliberately contains no training code.  The trained artifact is
loaded once per process and all repository data is fetched on demand.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .models import ContriMapModels
from .snapshot import RepositorySnapshot, build_snapshot


class GitHubInferenceError(RuntimeError):
    """Raised when a repository cannot be read from GitHub."""


def _repository_name(repository_url: str) -> str:
    parsed = urlparse(repository_url.strip())
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != "github.com":
        raise ValueError("repositoryUrl must be an https://github.com/{owner}/{repo} URL.")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2 or not re.fullmatch(r"[A-Za-z0-9_.-]+", parts[0]) or not re.fullmatch(r"[A-Za-z0-9_.-]+", parts[1]):
        raise ValueError("repositoryUrl must include exactly one GitHub owner and repository.")
    return f"{parts[0]}/{parts[1].removesuffix('.git')}"


def _github_get(session: requests.Session, path: str, **params: Any) -> Any:
    response = session.get(
        f"https://api.github.com{path}",
        params=params,
        timeout=30,
    )
    if response.status_code >= 400:
        try:
            detail = response.json().get("message", response.text)
        except ValueError:
            detail = response.text
        raise GitHubInferenceError(f"GitHub API request failed ({response.status_code}): {detail}")
    return response.json()


@lru_cache(maxsize=1)
def load_models(artifact_dir: str | Path | None = None) -> ContriMapModels:
    """Load all trained artifacts once and cache them for the process lifetime."""
    configured = artifact_dir or os.getenv("CONTRIMAP_ARTIFACT_DIR")
    directory = Path(configured) if configured else Path(__file__).resolve().parent.parent / "artifacts"
    return ContriMapModels.load(directory)


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    token = os.getenv("GITHUB_TOKEN")
    if token:
        session.headers["Authorization"] = f"Bearer {token}"
    return session


def fetchRepositoryIssues(repositoryUrl: str) -> list[dict[str, Any]]:
    """Return open, non-pull-request issues in a stable frontend shape."""
    repository = _repository_name(repositoryUrl)
    session = _session()
    issues: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = _github_get(session, f"/repos/{repository}/issues", state="open", per_page=100, page=page)
        issues.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return [
        {
            "number": int(issue["number"]),
            "title": str(issue.get("title") or ""),
            "body": str(issue.get("body") or ""),
            "labels": [str(label.get("name") or "") for label in issue.get("labels") or []],
            "author": str((issue.get("user") or {}).get("login") or ""),
            "created_at": str(issue.get("created_at") or ""),
        }
        for issue in issues
        if "pull_request" not in issue
    ]


def _repository_snapshot(session: requests.Session, repository: str, issues: list[dict[str, Any]]) -> RepositorySnapshot:
    repository_data = _github_get(session, f"/repos/{repository}")
    tree = _github_get(session, f"/repos/{repository_data['full_name']}/git/trees/{repository_data['default_branch']}", recursive="1")
    # The trained predictor uses the issue fields and its persisted localization
    # index. Keep the snapshot lightweight; downloading every blob serially
    # makes analysis needlessly slow for large repositories.
    files: list[dict[str, Any]] = []
    for item in tree.get("tree") or []:
        if item.get("type") != "blob" or not item.get("path") or item.get("size", 0) > 1_000_000:
            continue
        files.append({"path": item["path"]})
    return build_snapshot({
        "repository": {"owner": repository.split("/", 1)[0], "name": repository.split("/", 1)[1], "full_name": repository},
        "files": files,
        "issues": issues,
    })


def analyzeIssue(repositoryUrl: str, issue: dict[str, Any]) -> dict[str, Any]:
    """Build a repository snapshot and run the cached trained models."""
    repository = _repository_name(repositoryUrl)
    title = str(issue.get("title") or "").strip()
    if not title:
        raise ValueError("issue.title is required.")
    labels = [
        str(label.get("name") if isinstance(label, dict) else label)
        for label in issue.get("labels") or []
    ]
    normalized_issue = {
        "number": issue.get("number"),
        "title": title,
        "body": str(issue.get("body") or ""),
        "labels": labels,
        "author": str(issue.get("author") or ""),
        "created_at": str(issue.get("created_at") or issue.get("created_date") or ""),
    }
    # Snapshot construction is intentionally part of inference so repository
    # context is available to future feature additions without retraining.
    _repository_snapshot(_session(), repository, [normalized_issue])
    prediction = load_models().predict(title, normalized_issue["body"], labels, top_k=10)
    return {
        "difficulty": prediction["difficulty"],
        "difficulty_probability": float(prediction["difficulty_probability"]),
        "effort_hours": float(prediction["effort_hours"]),
        "affected_files": [
            {"path": item["path"], "similarity": float(item["similarity"])}
            for item in prediction.get("files", [])
        ],
    }


__all__ = ["GitHubInferenceError", "analyzeIssue", "fetchRepositoryIssues", "load_models"]
