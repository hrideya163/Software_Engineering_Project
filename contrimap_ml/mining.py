from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


@dataclass
class NormalizedMiningRecord:
    repository: str
    issue_id: str
    issue_title: str
    issue_body: str
    labels: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    dependency_paths: list[str] = field(default_factory=list)
    test_paths: list[str] = field(default_factory=list)
    documentation_paths: list[str] = field(default_factory=list)
    contributor_ids: list[str] = field(default_factory=list)
    file_roles: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_record(raw_record: Mapping[str, Any], *, repository: str | None = None) -> NormalizedMiningRecord:
    issue_id = str(raw_record.get("issue_id") or raw_record.get("issue_number") or raw_record.get("id") or "unknown")
    title = str(raw_record.get("issue_title") or raw_record.get("title") or "")
    body = str(raw_record.get("issue_body") or raw_record.get("body") or "")
    labels = [str(label).strip() for label in raw_record.get("labels") or raw_record.get("issue_labels") or []]
    changed_files = [str(path) for path in raw_record.get("changed_files") or []]
    dependency_paths = [str(path) for path in raw_record.get("dependency_paths") or []]
    test_paths = [str(path) for path in raw_record.get("test_paths") or []]
    documentation_paths = [str(path) for path in raw_record.get("documentation_paths") or []]
    contributor_ids = [str(value) for value in raw_record.get("contributors") or raw_record.get("contributor_ids") or []]
    file_roles = {str(path): str(role) for path, role in (raw_record.get("file_roles") or {}).items()}
    return NormalizedMiningRecord(
        repository=str(repository or raw_record.get("repository") or "unknown"),
        issue_id=issue_id,
        issue_title=title,
        issue_body=body,
        labels=labels,
        changed_files=changed_files,
        dependency_paths=dependency_paths,
        test_paths=test_paths,
        documentation_paths=documentation_paths,
        contributor_ids=contributor_ids,
        file_roles=file_roles,
        metadata={k: v for k, v in raw_record.items() if k not in {"issue_id", "issue_number", "id", "title", "body", "labels", "changed_files", "issue_title", "issue_body"}},
    )


def normalize_snapshot(snapshot: Mapping[str, Any]) -> list[NormalizedMiningRecord]:
    records: list[NormalizedMiningRecord] = []
    repository = str((snapshot.get("repository") or {}).get("name") or (snapshot.get("repository") or {}).get("full_name") or "unknown")
    for issue in snapshot.get("issues") or []:
        issue_data = dict(issue)
        issue_data["repository"] = repository
        issue_data["labels"] = list(issue_data.get("labels") or issue_data.get("issue_labels") or [])
        issue_data["changed_files"] = list(issue_data.get("changed_files") or [])
        records.append(normalize_record(issue_data, repository=repository))
    for pull_request in snapshot.get("pullRequests") or snapshot.get("pull_requests") or []:
        pr_data = dict(pull_request)
        pr_data["repository"] = repository
        pr_data["labels"] = list(pr_data.get("labels") or [])
        pr_data["issue_title"] = pr_data.get("title") or ""
        pr_data["issue_body"] = pr_data.get("body") or ""
        pr_data["issue_id"] = pr_data.get("number") or pr_data.get("id") or "pr"
        pr_data["changed_files"] = list(pr_data.get("changed_files") or [])
        records.append(normalize_record(pr_data, repository=repository))
    return records


__all__ = ["NormalizedMiningRecord", "normalize_record", "normalize_snapshot"]
