from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests  # pyright: ignore[reportMissingImports]


logger = logging.getLogger(__name__)
PR_REFERENCE = re.compile(r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)?\s*#(\d+)", re.I)


class GitHubRateLimitError(RuntimeError):
    """Raised when GitHub refuses a request because the API rate limit is exhausted."""

    def __init__(self, reset_at: str | None):
        detail = f"API rate limit exceeded; reset at {reset_at}" if reset_at else "API rate limit exceeded"
        super().__init__(detail)
        self.reset_at = reset_at


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

    def _request(self, url: str, **params: Any) -> requests.Response:
        response = self.session.get(url, params=params, timeout=self.timeout)
        remaining = response.headers.get("X-RateLimit-Remaining")
        if response.status_code == 429 or (response.status_code == 403 and remaining == "0"):
            reset_epoch = response.headers.get("X-RateLimit-Reset")
            reset_at = datetime.fromtimestamp(int(reset_epoch), tz=timezone.utc).isoformat() if reset_epoch else None
            raise GitHubRateLimitError(reset_at)
        response.raise_for_status()
        return response

    def get(self, path: str, **params: Any) -> Any:
        response = self._request(f"{self.api_url}{path}", **params)
        return response.json()

    def paginate(self, path: str, *, max_items: int | None = None, **params: Any) -> Iterable[dict[str, Any]]:
        if max_items is not None and max_items <= 0:
            return
        url = f"{self.api_url}{path}"
        request_params: dict[str, Any] = {"per_page": 100, "page": 1, **params}
        fetched = 0
        page = 0
        while True:
            response = self._request(url, **request_params)
            values = response.json()
            if not values:
                return
            page += 1
            remaining = max_items - fetched if max_items is not None else len(values)
            batch = values[:remaining]
            fetched += len(batch)
            logger.info("Fetched %d items from %s (page %d)", len(batch), path, page)
            yield from batch
            if max_items is not None and fetched >= max_items:
                return
            link_header = response.headers.get("Link", "")
            next_link = re.search(r'<([^>]+)>[^,]*rel="next"', link_header)
            if not next_link:
                return
            url = next_link.group(1)
            request_params = {}


def _hours(start: str | None, end: str | None) -> float:
    if not start or not end:
        return 0.0
    return max(0.25, (datetime.fromisoformat(end.replace("Z", "+00:00")) -
                      datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds() / 3600)


def _workload(record: HistoricalContribution) -> float:
    return record.effort_hours + len(record.changed_files) * 2 + record.pr_review_comments * 0.5


def _percentile(values: list[float], percentage: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("Cannot calculate workload percentiles for an empty dataset.")
    position = (len(ordered) - 1) * percentage / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _label_records(records: list[HistoricalContribution]) -> tuple[float | None, float | None, Counter[str]]:
    if not records:
        logger.info("No records collected; workload percentiles and difficulty distribution are empty.")
        return None, None, Counter()
    workloads = [_workload(record) for record in records]
    p33 = _percentile(workloads, 33)
    p66 = _percentile(workloads, 66)
    for record, workload in zip(records, workloads):
        if workload <= p33:
            record.difficulty_label = "Easy"
        elif workload <= p66:
            record.difficulty_label = "Medium"
        else:
            record.difficulty_label = "Hard"
    counts = Counter(record.difficulty_label for record in records)
    logger.info("Workload percentiles:\nP33 = %.1f\nP66 = %.1f", p33, p66)
    logger.info(
        "Difficulty distribution:\nEasy   = %d (%.1f%%)\nMedium = %d (%.1f%%)\nHard   = %d (%.1f%%)",
        counts["Easy"], counts["Easy"] / len(records) * 100,
        counts["Medium"], counts["Medium"] / len(records) * 100,
        counts["Hard"], counts["Hard"] / len(records) * 100,
    )
    return p33, p66, counts


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
    issues: list[dict[str, Any]] = []
    for issue in client.paginate(f"/repos/{repository}/issues", state="closed", sort="created", direction="asc"):
        if "pull_request" in issue:
            continue
        issues.append(issue)
        if max_issues is not None and len(issues) >= max_issues:
            break
    logger.info("Collected %d closed issues for %s", len(issues), repository)
    issue_by_number = {issue["number"]: issue for issue in issues}
    pull_requests = list(client.paginate(
        f"/repos/{repository}/pulls",
        max_items=max_issues,
        state="closed",
        sort="created",
        direction="asc",
    ))
    logger.info("Collected %d closed pull requests for %s", len(pull_requests), repository)
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
                difficulty_label="",
            )
            records.append(record)
            if sleep_seconds:
                time.sleep(sleep_seconds)

    p33, p66, counts = _label_records(records)
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
        "workload_percentiles": {"p33": p33, "p66": p66},
        "difficulty_distribution": dict(counts),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return dataset
