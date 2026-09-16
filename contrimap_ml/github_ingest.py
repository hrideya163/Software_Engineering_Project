"""GitHub REST ingestion for historical issue -> resolving PR -> files records.

The collector is intentionally API-only and stores raw responses alongside a
normalized JSONL dataset so training can be reproduced from a dated snapshot.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests


PR_REFERENCE = re.compile(r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)?\s*#(\d+)", re.I)


@dataclass
class HistoricalContribution:
    repository: str
    issue_number: int
    issue_title: str
    issue_body: str
    issue_labels: list[str]
    issue_created_at: str
    issue_closed_at: str
    pr_number: int
    pr_title: str
    pr_body: str
    pr_created_at: str
    pr_merged_at: str
    pr_closed_at: str
    pr_review_comments: int
    pr_commits: int
    pr_additions: int
    pr_deletions: int
    changed_files: list[str]
    effort_hours: float
    difficulty_label: str


class GitHubClient:
    def __init__(self, token: str | None = None, api_url: str = "https://api.github.com", timeout: int = 30):
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout

    def get(self, path: str, **params: Any) -> Any:
        response = self.session.get(f"{self.api_url}{path}", params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def paginate(self, path: str, **params: Any) -> Iterable[dict[str, Any]]:
        page = 1
        while True:
            values = self.get(path, per_page=100, page=page, **params)
            if not values:
                return
            yield from values
            if len(values) < 100:
                return
            page += 1


def _hours(start: str | None, end: str | None) -> float:
    if not start or not end:
        return 0.0
    return max(0.25, (datetime.fromisoformat(end.replace("Z", "+00:00")) -
                      datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds() / 3600)


def _difficulty(hours: float, files: int, review_comments: int) -> str:
    """Create an observed training label; this is not used at inference time."""
    workload = hours + files * 2 + review_comments * 0.5
    if workload <= 8:
        return "Easy"
    if workload <= 32:
        return "Medium"
    return "Hard"


def _linked_issue_numbers(pr: dict[str, Any]) -> set[int]:
    text = f"{pr.get('title', '')}\n{pr.get('body') or ''}"
    return {int(match.group(1)) for match in PR_REFERENCE.finditer(text)}


def collect_repository(
    owner: str,
    repo: str,
    output_dir: str | Path,
    token: str | None = None,
    max_issues: int | None = None,
    sleep_seconds: float = 0.0,
) -> Path:
    """Collect closed issues, merged PRs and changed files into JSONL."""
    client = GitHubClient(token)
    repository = f"{owner}/{repo}"
    issues = list(client.paginate(f"/repos/{repository}/issues", state="closed", sort="created", direction="asc"))
    issues = [issue for issue in issues if "pull_request" not in issue]
    if max_issues:
        issues = issues[:max_issues]
    issue_by_number = {issue["number"]: issue for issue in issues}
    pull_requests = list(client.paginate(f"/repos/{repository}/pulls", state="closed", sort="created", direction="asc"))
    records: list[HistoricalContribution] = []
    raw_dir = Path(output_dir) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "issues.json").write_text(json.dumps(issues), encoding="utf-8")
    (raw_dir / "pull_requests.json").write_text(json.dumps(pull_requests), encoding="utf-8")

    for pr in pull_requests:
        if not pr.get("merged_at"):
            continue
        linked = _linked_issue_numbers(pr)
        linked &= issue_by_number.keys()
        for issue_number in linked:
            issue = issue_by_number[issue_number]
            files = [item["filename"] for item in client.paginate(f"/repos/{repository}/pulls/{pr['number']}/files")]
            reviews = client.get(f"/repos/{repository}/pulls/{pr['number']}/reviews")
            effort = _hours(issue.get("created_at"), pr.get("merged_at"))
            record = HistoricalContribution(
                repository=repository,
                issue_number=issue_number,
                issue_title=issue.get("title", ""),
                issue_body=issue.get("body") or "",
                issue_labels=[label["name"] for label in issue.get("labels", [])],
                issue_created_at=issue.get("created_at", ""),
                issue_closed_at=issue.get("closed_at", ""),
                pr_number=pr["number"],
                pr_title=pr.get("title", ""),
                pr_body=pr.get("body") or "",
                pr_created_at=pr.get("created_at", ""),
                pr_merged_at=pr["merged_at"],
                pr_closed_at=pr.get("closed_at") or "",
                pr_review_comments=len(reviews),
                pr_commits=int(pr.get("commits", 0)),
                pr_additions=int(pr.get("additions", 0)),
                pr_deletions=int(pr.get("deletions", 0)),
                changed_files=files,
                effort_hours=effort,
                difficulty_label=_difficulty(effort, len(files), len(reviews)),
            )
            records.append(record)
            if sleep_seconds:
                time.sleep(sleep_seconds)

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    dataset = output / "historical_contributions.jsonl"
    with dataset.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(asdict(record)) + "\n")
    manifest = {
        "repository": repository,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "records": len(records),
        "source": "GitHub REST API",
        "label_note": "Difficulty labels are observed training labels from elapsed time, files, and review comments.",
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return dataset
