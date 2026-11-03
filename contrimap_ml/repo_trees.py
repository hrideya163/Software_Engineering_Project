"""Token-free repository file trees and contents via blobless, shallow git fetches.

``git fetch --depth 1 --filter=blob:none <sha>`` downloads only the commit and
its trees (tens of KB), so a repository's complete file list at any commit can
be read without the GitHub REST API or its rate limits.  The cache directory is
a partial clone with a promisor remote, so selected file contents can then be
fetched in small batches (``fetch_blobs``).  Used both to build point-in-time
localization candidates for evaluation and to snapshot live repositories.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

DEFAULT_CACHE = Path(os.getenv("CONTRIMAP_TREE_CACHE", Path(__file__).resolve().parent.parent / "data" / "trees"))
_REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_NUL = b"\x00"


class TreeFetchError(RuntimeError):
    """Raised when git cannot fetch a repository tree."""


def _git(args: list[str], cwd: Path, timeout: int = 180) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if result.returncode != 0:
        raise TreeFetchError(result.stderr.strip()[:400] or f"git {' '.join(args)} failed")
    return result.stdout


def _bare_repo(repo: str, cache_dir: Path) -> Path:
    if not _REPO_PATTERN.match(repo):
        raise ValueError(f"Invalid repository name: {repo!r}")
    path = cache_dir / "_git" / repo.replace("/", "__")
    if not (path / "HEAD").exists():
        path.mkdir(parents=True, exist_ok=True)
        _git(["init", "-q", "--bare"], path)
    if "origin" not in _git(["remote"], path).split():
        # A promisor remote lets git fetch individual blobs on demand (partial clone).
        _git(["remote", "add", "origin", f"https://github.com/{repo}.git"], path)
        _git(["config", "remote.origin.promisor", "true"], path)
        _git(["config", "remote.origin.partialclonefilter", "blob:none"], path)
    return path


def tree_cache_path(repo: str, sha: str, cache_dir: Path = DEFAULT_CACHE) -> Path:
    return cache_dir / repo.replace("/", "__") / f"{sha}.txt"


def fetch_tree(repo: str, sha: str | None = None, cache_dir: str | Path = DEFAULT_CACHE) -> tuple[str, list[str]]:
    """Return ``(commit_sha, file_paths)`` for ``repo`` at ``sha`` (default branch HEAD when None)."""
    cache_dir = Path(cache_dir)
    if sha:
        cached = tree_cache_path(repo, sha, cache_dir)
        if cached.exists():
            return sha, [line for line in cached.read_text(encoding="utf-8").splitlines() if line]
    bare = _bare_repo(repo, cache_dir)
    _git(["fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", sha or "HEAD"], bare)
    resolved = _git(["rev-parse", "FETCH_HEAD"], bare).strip()
    files = [line for line in _git(["ls-tree", "-r", "--name-only", resolved], bare).splitlines() if line]
    target = tree_cache_path(repo, resolved, cache_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(files), encoding="utf-8")
    return resolved, files


def read_blob(repo: str, sha: str, path: str, cache_dir: str | Path = DEFAULT_CACHE, max_bytes: int = 200_000) -> str:
    """Read one file's content at ``sha``."""
    return fetch_blobs(repo, sha, [path], cache_dir, max_bytes).get(path, "")


def _parse_batch(stream: bytes) -> dict[str, bytes]:
    """Parse ``git cat-file --batch`` output into ``{oid: content}``."""
    blobs: dict[str, bytes] = {}
    position = 0
    while position < len(stream):
        header_end = stream.index(b"\n", position)
        header = stream[position:header_end].decode(errors="replace").split()
        if len(header) < 3 or header[1] == "missing":
            position = header_end + 1
            continue
        size = int(header[2])
        blobs[header[0]] = stream[header_end + 1: header_end + 1 + size]
        position = header_end + 1 + size + 1
    return blobs


def fetch_blobs(repo: str, sha: str, paths: Iterable[str], cache_dir: str | Path = DEFAULT_CACHE, max_bytes: int = 200_000, max_file_size: int = 400_000) -> dict[str, str]:
    """Fetch the contents of ``paths`` at ``sha`` in batched requests; oversized and binary files are skipped."""
    bare = _bare_repo(repo, Path(cache_dir))
    wanted = set(paths)
    listing: dict[str, str] = {}
    # Note: `ls-tree -l` would make git lazily download every blob just to report sizes.
    for line in _git(["ls-tree", "-r", sha], bare).splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if path in wanted and len(parts) == 3 and parts[1] == "blob":
            listing[path] = parts[2]
    if not listing:
        return {}
    oids = sorted(set(listing.values()))
    no_lazy = {**os.environ, "GIT_NO_LAZY_FETCH": "1"}
    check = subprocess.run(["git", "cat-file", "--batch-check"], cwd=bare, input="\n".join(oids), capture_output=True, text=True, env=no_lazy, timeout=120)
    present = {line.split()[0] for line in check.stdout.splitlines() if " blob " in line}
    missing = [oid for oid in oids if oid not in present]
    for start in range(0, len(missing), 200):
        _git(["fetch", "-q", "--no-tags", f"--filter=blob:limit={max_file_size}", "origin", *missing[start:start + 200]], bare, timeout=300)
    batch = subprocess.run(["git", "cat-file", "--batch"], cwd=bare, input="\n".join(oids).encode(), capture_output=True, env=no_lazy, timeout=300)
    blobs = _parse_batch(batch.stdout)
    contents: dict[str, str] = {}
    for path, oid in listing.items():
        data = blobs.get(oid, b"")
        if _NUL in data[:2048]:
            continue
        contents[path] = data[:max_bytes].decode("utf-8", errors="replace")
    return contents


def fetch_trees(pairs: Iterable[tuple[str, str]], cache_dir: str | Path = DEFAULT_CACHE, workers: int = 6) -> dict[tuple[str, str], list[str]]:
    """Fetch many (repo, sha) trees concurrently; failures are logged and skipped."""
    unique = sorted(set(pairs))
    results: dict[tuple[str, str], list[str]] = {}
    # One worker per repository at a time: concurrent fetches into one bare repo contend on its lock.
    by_repo: dict[str, list[str]] = {}
    for repo, sha in unique:
        by_repo.setdefault(repo, []).append(sha)

    def run(repo: str, shas: list[str]) -> list[tuple[tuple[str, str], list[str] | None]]:
        out = []
        for sha in shas:
            try:
                out.append(((repo, sha), fetch_tree(repo, sha, cache_dir)[1]))
            except (TreeFetchError, subprocess.TimeoutExpired) as error:
                logger.warning("Tree fetch failed for %s@%s: %s", repo, sha[:10], error)
                out.append(((repo, sha), None))
        return out

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run, repo, shas) for repo, shas in by_repo.items()]
        for done, future in enumerate(as_completed(futures), 1):
            for key, files in future.result():
                if files is not None:
                    results[key] = files
            logger.info("Fetched trees for %d/%d repositories", done, len(futures))
    return results


__all__ = ["TreeFetchError", "fetch_blobs", "fetch_tree", "fetch_trees", "read_blob", "tree_cache_path"]
