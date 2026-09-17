from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

SOURCE_PATTERN = re.compile(r"\.(c|cc|cpp|cs|go|java|js|jsx|kt|py|rb|rs|swift|ts|tsx|vue)$", re.I)
TEST_PATTERN = re.compile(r"(^|/)(__tests__|test|tests|spec)(/|$)|\.(test|spec)\.[^.]+$", re.I)
DOC_PATTERN = re.compile(r"(^|/)(readme|docs?|documentation|contributing)(/|\.|$)", re.I)
DEPENDENCY_FILES = [
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "pyproject.toml", "requirements.txt", "Cargo.toml", "go.mod",
]


@dataclass
class RepositorySnapshot:
    repository: dict[str, str] = field(default_factory=dict)
    files: list[dict[str, Any]] = field(default_factory=list)
    dependency_manifests: list[str] = field(default_factory=list)
    dependency_packages: list[str] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    dependency_edges: list[dict[str, str]] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    documentation: list[str] = field(default_factory=list)
    commits: list[dict[str, Any]] = field(default_factory=list)
    pull_requests: list[dict[str, Any]] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    contributors: list[str] = field(default_factory=list)
    snapshot_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["repository"] = dict(self.repository)
        payload["pullRequests"] = list(payload.get("pull_requests") or [])
        payload["dependencyEdges"] = list(payload.get("dependency_edges") or [])
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RepositorySnapshot":
        filtered = {key: value for key, value in payload.items() if key in cls.__annotations__}
        for alias, canonical in (("pullRequests", "pull_requests"), ("dependencyEdges", "dependency_edges")):
            if canonical not in filtered and alias in payload:
                filtered[canonical] = payload[alias]
        return cls(**filtered)


def _normalize_file(file: Mapping[str, Any]) -> dict[str, Any]:
    path = str(file.get("path") or file.get("name") or "")
    path = path.replace("\\", "/")
    path = re.sub(r"^\./+", "", path)
    return {
        "path": path,
        "content": str(file.get("content") or ""),
        "language": file.get("language") or (path.rsplit(".", 1)[-1] if "." in path else None),
    }


def _dependency_packages(manifests: Iterable[Mapping[str, Any]]) -> list[str]:
    deps: set[str] = set()
    for manifest in manifests:
        content = str(manifest.get("content") or "")
        if not content:
            continue
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                deps.update((parsed.get("dependencies") or {}).keys())
                deps.update((parsed.get("devDependencies") or {}).keys())
        except json.JSONDecodeError:
            for line in content.splitlines():
                match = re.match(r"^([A-Za-z0-9_.-]+)(?:[<>=!~].*)?$", line.strip())
                if match:
                    deps.add(match.group(1))
    return sorted(deps)


def _dependency_edges(files: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    source_paths = [item["path"] for item in files if SOURCE_PATTERN.search(item["path"])]
    edges: list[dict[str, str]] = []
    for file in files:
        path = file["path"]
        if not SOURCE_PATTERN.search(path):
            continue
        content = file.get("content") or ""
        matches = re.findall(r"(?:from|import|require)\s+[\"'`]?([A-Za-z0-9_./-]+)", content)
        for import_path in matches:
            normalized_import = import_path.replace("\\", "/").replace("@/", "")
            target = None
            for candidate in source_paths:
                normalized_candidate = candidate.replace("\\", "/")
                if normalized_candidate == normalized_import or normalized_candidate.endswith(f"/{normalized_import}") or normalized_candidate.endswith(f"/{normalized_import}.js") or normalized_candidate.endswith(f"/{normalized_import}.ts"):
                    target = normalized_candidate
                    break
            if target and target != path:
                edges.append({"source": path, "target": target, "type": "imports"})
    return edges


def _snapshot_id(repository: Mapping[str, Any]) -> str:
    owner = str(repository.get("owner") or "repository").strip()
    name = str(repository.get("name") or "unknown").strip()
    slug = re.sub(r"[^a-z0-9]+", "-", f"{owner}-{name}".lower()).strip("-")
    return slug or "repository"


def build_snapshot(input_data: Mapping[str, Any] | None = None) -> RepositorySnapshot:
    input_data = input_data or {}
    files = [_normalize_file(file) for file in input_data.get("files") or []]
    dependency_manifests = [file for file in files if any(file["path"].lower().endswith(name.lower()) for name in DEPENDENCY_FILES)]
    tests = [file["path"] for file in files if TEST_PATTERN.search(file["path"])]
    documentation = [file["path"] for file in files if DOC_PATTERN.search(file["path"])]
    source_files = [file["path"] for file in files if SOURCE_PATTERN.search(file["path"])]
    modules = sorted({path.split("/", 1)[0] for path in source_files if "/" in path})
    contributor_names = sorted({
        str(item.get("author") or "")
        for item in list(input_data.get("commits") or []) + list(input_data.get("pullRequests") or [])
        if item.get("author")
    })
    snapshot = RepositorySnapshot(
        repository=dict(input_data.get("repository") or {}),
        files=files,
        dependency_manifests=[file["path"] for file in dependency_manifests],
        dependency_packages=_dependency_packages(dependency_manifests),
        modules=modules,
        source_files=source_files,
        dependency_edges=_dependency_edges(files),
        tests=tests,
        documentation=documentation,
        commits=list(input_data.get("commits") or []),
        pull_requests=list(input_data.get("pullRequests") or input_data.get("pull_requests") or []),
        issues=list(input_data.get("issues") or []),
        contributors=contributor_names,
        snapshot_id=str(input_data.get("snapshotId") or _snapshot_id(input_data.get("repository") or {})),
        metadata=dict(input_data.get("metadata") or {}),
    )
    return snapshot


def build_snapshot_from_directory(directory: str | Path) -> RepositorySnapshot:
    root = Path(directory)
    files: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_dir() or path.name.startswith("."):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel_path = path.relative_to(root).as_posix()
        files.append({"path": rel_path, "content": content, "language": rel_path.rsplit(".", 1)[-1] if "." in rel_path else None})
    return build_snapshot({
        "repository": {"owner": root.name, "name": root.name},
        "files": files,
        "snapshotId": root.name,
    })


def save_snapshot(snapshot: RepositorySnapshot, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(snapshot.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return target


def load_snapshot(path: str | Path) -> RepositorySnapshot:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return RepositorySnapshot.from_dict(data)


__all__ = [
    "RepositorySnapshot",
    "build_snapshot",
    "build_snapshot_from_directory",
    "save_snapshot",
    "load_snapshot",
]
