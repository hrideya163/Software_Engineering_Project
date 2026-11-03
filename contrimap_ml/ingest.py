"""Multi-repository ingestion through the GitHub GraphQL API.

    python -m contrimap_ml.ingest owner/repo [owner/repo ...] --since 2023-01-01 --max-prs 400

For each repository this collects, in ~50-item pages:

* merged pull requests that GitHub itself links to the issues they close
  (``closingIssuesReferences``) - authoritative links instead of regex guesses;
* the PR's real size (additions, deletions, changed files, commits), the
  per-file paths, the author, and timestamps;
* unmerged closed PRs that reference issues (negatives for success prediction).

Output rows follow the unified corpus schema (``corpus.py``) and are written to
``data/ingested/<owner>__<repo>.jsonl``; ``load_ingested`` turns them into a
frame that can be concatenated with the corpus.  Requires ``GITHUB_TOKEN``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Iterator

import pandas as pd
import requests

from .corpus import _primary_language, is_test_path
from .features import is_valid_candidate

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "data" / "ingested"
GRAPHQL_URL = "https://api.github.com/graphql"

PR_QUERY = """
query($q: String!, $cursor: String) {
  rateLimit { remaining resetAt cost }
  search(query: $q, type: ISSUE, first: 40, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on PullRequest {
        number title createdAt mergedAt closedAt merged additions deletions changedFiles
        author { login }
        commits { totalCount }
        reviews { totalCount }
        closingIssuesReferences(first: 5) {
          nodes { number title body createdAt author { login } labels(first: 20) { nodes { name } } }
        }
        files(first: 100) { nodes { path additions deletions } }
      }
    }
  }
}
"""

Transport = Callable[[str, dict[str, Any]], dict[str, Any]]


class GraphQLError(RuntimeError):
    pass


def github_transport(token: str | None = None, timeout: int = 60) -> Transport:
    token = token or os.getenv("GITHUB_TOKEN")
    if not token:
        raise GraphQLError("GITHUB_TOKEN is required for GraphQL ingestion.")
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})

    def send(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(4):
            response = session.post(GRAPHQL_URL, json={"query": query, "variables": variables}, timeout=timeout)
            if response.status_code in (502, 503, 504) and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            if response.status_code == 401:
                raise GraphQLError("GitHub rejected GITHUB_TOKEN (401 Bad credentials).")
            response.raise_for_status()
            payload = response.json()
            if payload.get("errors"):
                raise GraphQLError(json.dumps(payload["errors"])[:500])
            limit = payload["data"].get("rateLimit") or {}
            if limit.get("remaining", 1000) < 50:
                raise GraphQLError(f"GraphQL rate limit nearly exhausted; resets at {limit.get('resetAt')}.")
            return payload["data"]
        raise GraphQLError("GitHub GraphQL API unavailable.")

    return send


def _search(transport: Transport, query: str, limit: int) -> Iterator[dict[str, Any]]:
    cursor = None
    fetched = 0
    while fetched < limit:
        data = transport(PR_QUERY, {"q": query, "cursor": cursor})
        page = data["search"]
        for node in page["nodes"]:
            if node:
                fetched += 1
                yield node
                if fetched >= limit:
                    return
        if not page["pageInfo"]["hasNextPage"]:
            return
        cursor = page["pageInfo"]["endCursor"]


def pull_request_rows(repo: str, pr: dict[str, Any]) -> list[dict[str, Any]]:
    """One corpus row per (merged PR, closed issue) pair."""
    files = [item for item in (pr.get("files") or {}).get("nodes") or [] if is_valid_candidate(item["path"])]
    source = [item for item in files if not is_test_path(item["path"])]
    rows = []
    for issue in (pr.get("closingIssuesReferences") or {}).get("nodes") or []:
        rows.append({
            "uid": f"gh:{repo}#{issue['number']}",
            "instance_id": f"{repo.replace('/', '__')}-{issue['number']}",
            "source": "github",
            "eval_group": "github",
            "repo": repo,
            "created_at": issue["createdAt"],
            "base_commit": None,
            "title": issue.get("title") or "",
            "body": issue.get("body") or "",
            "labels": [label["name"] for label in (issue.get("labels") or {}).get("nodes") or []],
            "target_files": [item["path"] for item in source],
            "test_files": [item["path"] for item in files if is_test_path(item["path"])],
            "new_target_files": [],
            "n_files": len(source),
            "loc_added": sum(int(item.get("additions") or 0) for item in source),
            "loc_deleted": sum(int(item.get("deletions") or 0) for item in source),
            "n_hunks": None,
            "language": _primary_language([item["path"] for item in files]),
            "author": (pr.get("author") or {}).get("login"),
            "human_difficulty": None,
            "pr_number": pr["number"],
            "pr_merged": bool(pr.get("merged")),
            "pr_created_at": pr.get("createdAt"),
            "pr_merged_at": pr.get("mergedAt"),
            "pr_commits": (pr.get("commits") or {}).get("totalCount"),
            "pr_reviews": (pr.get("reviews") or {}).get("totalCount"),
            "files_truncated": int(pr.get("changedFiles") or 0) > len((pr.get("files") or {}).get("nodes") or []),
        })
    return rows


def ingest_repository(repo: str, transport: Transport, since: str = "2022-01-01", max_prs: int = 400, output: Path = OUTPUT) -> Path:
    rows: list[dict[str, Any]] = []
    merged_query = f"repo:{repo} is:pr is:merged linked:issue merged:>={since} sort:created-desc"
    for pr in _search(transport, merged_query, max_prs):
        rows.extend(pull_request_rows(repo, pr))
    unmerged_query = f"repo:{repo} is:pr is:closed is:unmerged linked:issue created:>={since} sort:created-desc"
    attempts = [{"repo": repo, "pr_number": pr["number"], "author": (pr.get("author") or {}).get("login"), "created_at": pr["createdAt"], "closed_at": pr.get("closedAt"), "merged": False, "title": pr.get("title") or ""} for pr in _search(transport, unmerged_query, max_prs // 2)]
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"{repo.replace('/', '__')}.jsonl"
    with target.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")
    (output / f"{repo.replace('/', '__')}.unmerged.json").write_text(json.dumps(attempts), encoding="utf-8")
    logger.info("%s: %d issue-PR rows, %d unmerged attempts", repo, len(rows), len(attempts))
    return target


OUTCOME_QUERY = """
query($q: String!, $cursor: String) {
  rateLimit { remaining resetAt cost }
  search(query: $q, type: ISSUE, first: 100, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest { number title createdAt closedAt merged author { login } } }
  }
}
"""


def ingest_pr_outcomes(repo: str, transport: Transport, since: str = "2024-01-01", max_prs: int = 600, output: Path = OUTPUT) -> Path:
    """A uniform sample of closed PRs (merged and unmerged together, one time window, real PR titles).

    Used for success prediction; the issue-linked samples are unsuitable because merged and
    unmerged PRs come from different windows and merged rows carry issue titles.
    """
    cursor = None
    prs: list[dict[str, Any]] = []
    query = f"repo:{repo} is:pr is:closed created:>={since} sort:created-desc"
    while len(prs) < max_prs:
        page = transport(OUTCOME_QUERY, {"q": query, "cursor": cursor})["search"]
        for node in page["nodes"]:
            if node and node.get("author"):
                prs.append({"user": {"login": node["author"]["login"]}, "number": node["number"], "title": node.get("title") or "", "body": "", "created_at": node["createdAt"], "closed_at": node.get("closedAt") or node["createdAt"], "merged_at": node.get("closedAt") if node.get("merged") else None})
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    target = output / f"{repo.replace('/', '__')}.outcomes.json"
    output.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(prs[:max_prs]), encoding="utf-8")
    logger.info("%s: %d closed PRs (merge rate %.2f)", repo, len(prs[:max_prs]), sum(bool(p["merged_at"]) for p in prs[:max_prs]) / max(len(prs[:max_prs]), 1))
    return target


def load_pr_outcomes(directory: Path = OUTPUT) -> dict[str, list[dict[str, Any]]]:
    return {path.name.removesuffix(".outcomes.json").replace("__", "/", 1): json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.outcomes.json"))}


def load_ingested(directory: Path = OUTPUT) -> pd.DataFrame:
    frames = [pd.read_json(path, lines=True) for path in sorted(directory.glob("*.jsonl")) if path.stat().st_size]
    if not frames:
        return pd.DataFrame()
    frame = pd.concat(frames, ignore_index=True).drop_duplicates("uid")
    frame["created_at"] = pd.to_datetime(frame.created_at, utc=True)
    frame["text"] = (frame.title.fillna("") + "\n" + frame.body.fillna("")).str.strip()
    frame["loc_changed"] = frame.loc_added + frame.loc_deleted
    return frame[frame.target_files.map(len) > 0].reset_index(drop=True)


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT / "server" / ".env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Ingest issue-resolving pull requests from GitHub repositories")
    parser.add_argument("repositories", nargs="+", help="owner/name")
    parser.add_argument("--since", default="2022-01-01")
    parser.add_argument("--max-prs", type=int, default=400)
    args = parser.parse_args()
    transport = github_transport()
    for repo in args.repositories:
        try:
            ingest_repository(repo, transport, args.since, args.max_prs)
        except GraphQLError as error:
            parser.exit(1, f"{repo}: {error}\n")


if __name__ == "__main__":
    main()


__all__ = ["GraphQLError", "github_transport", "ingest_pr_outcomes", "ingest_repository", "load_ingested", "load_pr_outcomes", "pull_request_rows"]
