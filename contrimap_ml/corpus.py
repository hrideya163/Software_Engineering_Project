"""Unified multi-repository, multi-language training corpus.

Sources (all public, see docs/DATA.md):

* SWE-bench train/dev/test (princeton-nlp/SWE-bench) - 47 Python repositories,
  issue text paired with the gold resolving patch.  Train, dev and test use
  disjoint repositories, which gives a clean cross-repository evaluation.
* SWE-bench Verified - a 500-issue subset of SWE-bench test with *human*
  annotations of how long an experienced engineer needs for the fix.
* SWE-bench Multilingual - 300 issues across 42 repositories in 9 languages
  (C, C++, Go, Java, JavaScript, TypeScript, PHP, Ruby, Rust).
* The original vercel/next.js crawl, cleaned (see ``load_nextjs``).

Every record is reduced to information available when the issue is opened
(title, body, labels, creation time) plus post-hoc *labels* (changed files,
patch size, human difficulty).  Labels are never used as features.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .features import is_valid_candidate

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
EXTERNAL = ROOT / "data" / "external"
PROCESSED = ROOT / "data" / "processed"

TEST_PATH = re.compile(
    r"(^|/)(__tests__|tests?|testing|spec|specs|testdata|fixtures?|e2e)(/|$)"
    r"|(^|/)test_[^/]+$|_test\.[a-z]+$|\.(test|spec)\.[a-z]+$|Tests?\.(java|kt|cs|php)$|_spec\.rb$",
    re.I,
)
EXTENSION_LANGUAGE = {
    ".py": "Python", ".pyx": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".go": "Go", ".rs": "Rust", ".java": "Java", ".kt": "Kotlin",
    ".rb": "Ruby", ".php": "PHP", ".c": "C", ".h": "C", ".cc": "C++", ".cpp": "C++", ".hpp": "C++", ".cxx": "C++",
    ".cs": "C#", ".swift": "Swift", ".scala": "Scala", ".vue": "Vue", ".svelte": "Svelte", ".lua": "Lua",
}
# Human "time to fix" annotations from SWE-bench Verified, as ordinal levels and representative hours.
HUMAN_DIFFICULTY_LEVEL = {"<15 min fix": 0, "15 min - 1 hour": 1, "1-4 hours": 2, ">4 hours": 3}
HUMAN_DIFFICULTY_HOURS = {0: 0.125, 1: 0.5, 2: 2.0, 3: 6.0}
CLOSING_REFERENCE = re.compile(r"\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\b[:\s]+(?:[\w.-]+/[\w.-]+)?#(\d+)", re.I)


def is_test_path(path: str) -> bool:
    return bool(TEST_PATH.search(path.replace("\\", "/")))


def language_of(path: str) -> str | None:
    return EXTENSION_LANGUAGE.get(Path(path).suffix.lower())


def parse_patch(patch: str) -> list[dict[str, Any]]:
    """Split a unified diff into per-file change statistics."""
    files: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in (patch or "").splitlines():
        if line.startswith("diff --git "):
            match = re.match(r"diff --git a/(.+?) b/(.+)$", line)
            current = {"path": match.group(2) if match else line.split()[-1][2:], "added": 0, "deleted": 0, "hunks": 0, "new": False, "removed": False}
            files.append(current)
        elif current is None:
            continue
        elif line.startswith("new file mode"):
            current["new"] = True
        elif line.startswith("deleted file mode"):
            current["removed"] = True
        elif line.startswith("@@"):
            current["hunks"] += 1
        elif line.startswith("+") and not line.startswith("+++"):
            current["added"] += 1
        elif line.startswith("-") and not line.startswith("---"):
            current["deleted"] += 1
    return files


def _primary_language(paths: list[str]) -> str:
    counts = Counter(language for language in map(language_of, paths) if language)
    return counts.most_common(1)[0][0] if counts else "Unknown"


def _split_problem_statement(text: str) -> tuple[str, str]:
    text = (text or "").strip()
    title, _, body = text.partition("\n")
    return title.strip()[:300], body.strip()


def _swebench_frame(path: Path, source: str, group: str) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    rows = []
    for record in frame.itertuples(index=False):
        changes = [item for item in parse_patch(record.patch) if is_valid_candidate(item["path"])]
        source_changes = [item for item in changes if not is_test_path(item["path"])]
        test_changes = [item["path"] for item in parse_patch(getattr(record, "test_patch", "") or "")]
        title, body = _split_problem_statement(record.problem_statement)
        rows.append({
            "uid": f"{source}:{record.instance_id}",
            "instance_id": record.instance_id,
            "source": source,
            "eval_group": group,
            "repo": record.repo,
            "created_at": pd.Timestamp(record.created_at).tz_convert("UTC") if pd.Timestamp(record.created_at).tzinfo else pd.Timestamp(record.created_at, tz="UTC"),
            "base_commit": record.base_commit,
            "title": title,
            "body": body,
            "labels": [],
            "target_files": [item["path"] for item in source_changes],
            "test_files": [path for path in test_changes if is_valid_candidate(path)],
            "new_target_files": [item["path"] for item in source_changes if item["new"]],
            "n_files": len(source_changes),
            "loc_added": sum(item["added"] for item in source_changes),
            "loc_deleted": sum(item["deleted"] for item in source_changes),
            "n_hunks": sum(item["hunks"] for item in source_changes),
            "language": _primary_language([item["path"] for item in source_changes]),
            "author": None,
            "human_difficulty": None,
        })
    return pd.DataFrame(rows)


def load_nextjs(dataset: Path = ROOT / "data" / "historical_contributions.jsonl", max_files: int = 50) -> pd.DataFrame:
    """Clean the original next.js crawl.

    Repairs relative to the legacy pipeline:
    * keep only issue/PR links made with a closing keyword ("fixes #12"); a bare
      "#12" mention was previously treated as a resolution, which mislinked ~39%;
    * keep one row per issue (earliest merged PR) and drop sweeping PRs touching
      more than ``max_files`` files, which are refactors rather than fixes;
    * the legacy crawl never fetched PR details, so additions/deletions/commits
      are all zero - they are recorded as missing instead of as zero.
    """
    if not dataset.exists():
        return pd.DataFrame()
    raw_authors: dict[int, str] = {}
    raw_prs = dataset.parent / "raw" / "pull_requests.json"
    if raw_prs.exists():
        raw_authors = {int(pr["number"]): (pr.get("user") or {}).get("login") for pr in json.loads(raw_prs.read_text(encoding="utf-8"))}
    records = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = []
    for record in records:
        referenced = {int(match.group(3)) for match in CLOSING_REFERENCE.finditer(f"{record['pr_title']}\n{record.get('pr_body') or ''}")}
        if record["issue_number"] not in referenced:
            continue
        files = [path for path in record["changed_files"] if is_valid_candidate(path)]
        if not files or len(files) > max_files:
            continue
        rows.append({
            "uid": f"nextjs:{record['issue_number']}",
            "instance_id": f"vercel__next.js-{record['issue_number']}",
            "source": "nextjs",
            "eval_group": "nextjs",
            "repo": record["repository"],
            "created_at": pd.Timestamp(record["issue_created_at"]),
            "pr_merged_at": record["pr_merged_at"],
            "base_commit": None,
            "title": record["issue_title"],
            "body": record.get("issue_body") or "",
            "labels": list(record.get("issue_labels") or []),
            "target_files": [path for path in files if not is_test_path(path)],
            "test_files": [path for path in files if is_test_path(path)],
            "new_target_files": [],
            "n_files": sum(not is_test_path(path) for path in files),
            "loc_added": np.nan,
            "loc_deleted": np.nan,
            "n_hunks": np.nan,
            "language": _primary_language(files),
            "author": raw_authors.get(int(record["pr_number"])),
            "human_difficulty": None,
        })
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame = frame.sort_values("pr_merged_at").drop_duplicates("uid", keep="first").drop(columns="pr_merged_at")
    logger.info("next.js: %d raw records -> %d cleaned issues", len(records), len(frame))
    return frame.reset_index(drop=True)


def build_corpus(external: Path = EXTERNAL) -> pd.DataFrame:
    parts = []
    for name, source, group in (
        ("swebench_train.parquet", "swebench_train", "train"),
        ("swebench_dev.parquet", "swebench_dev", "dev"),
        ("swebench_test.parquet", "swebench_test", "test"),
        ("swebench_multilingual.parquet", "multilingual", "multilingual"),
    ):
        if (external / name).exists():
            parts.append(_swebench_frame(external / name, source, group))
    parts.append(load_nextjs())
    corpus = pd.concat([part for part in parts if not part.empty], ignore_index=True)

    verified_path = external / "swebench_verified.parquet"
    if verified_path.exists():
        verified = pd.read_parquet(verified_path, columns=["instance_id", "difficulty"]).set_index("instance_id")["difficulty"]
        is_test = corpus.source == "swebench_test"
        corpus.loc[is_test, "human_difficulty"] = corpus.loc[is_test, "instance_id"].map(verified)
    corpus["human_level"] = corpus.human_difficulty.map(HUMAN_DIFFICULTY_LEVEL)
    corpus["text"] = (corpus.title.fillna("") + "\n" + corpus.body.fillna("")).str.strip()
    corpus["loc_changed"] = corpus.loc_added + corpus.loc_deleted
    # A record is usable for localization only if the fix touches at least one non-test file.
    corpus = corpus[corpus.target_files.map(len) > 0].reset_index(drop=True)
    corpus["created_at"] = pd.to_datetime(corpus.created_at, utc=True)
    logger.info("Corpus: %d records, %d repositories, groups=%s", len(corpus), corpus.repo.nunique(), corpus.eval_group.value_counts().to_dict())
    return corpus


def load_corpus(rebuild: bool = False) -> pd.DataFrame:
    path = PROCESSED / "corpus.parquet"
    if path.exists() and not rebuild:
        return pd.read_parquet(path)
    corpus = build_corpus()
    PROCESSED.mkdir(parents=True, exist_ok=True)
    corpus.to_parquet(path, index=False)
    return corpus


__all__ = ["HUMAN_DIFFICULTY_HOURS", "HUMAN_DIFFICULTY_LEVEL", "build_corpus", "is_test_path", "language_of", "load_corpus", "load_nextjs", "parse_patch"]
