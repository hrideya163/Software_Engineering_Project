"""Point-in-time feature construction shared by all supervised models."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Features available at inference time (when user selects an open issue)
# ---------------------------------------------------------------------------
NUMERIC_FEATURES = [
    "label_count", "issue_body_chars", "issue_title_chars",
]

# Common GitHub labels that carry signal about difficulty / scope
KNOWN_LABEL_PREFIXES = [
    "bug", "feature", "enhancement", "documentation", "good first issue",
    "help wanted", "question", "security", "performance", "breaking",
    "dependencies", "refactor", "test", "ci", "build",
]

# ---------------------------------------------------------------------------
# Candidate file filtering for the localization index
# ---------------------------------------------------------------------------
# Paths containing these segments anywhere are excluded from the localization index.
_EXCLUDED_PATH_SEGMENTS = {
    "node_modules", ".git", "__pycache__", ".next", ".nuxt",
    ".cache", ".turbo", "dist", ".vercel",
    "coverage", ".nyc_output", ".tsbuildinfo",
}

# Directories that are build outputs when at the root or top-level of a package
_EXCLUDED_ROOT_SEGMENTS = {
    "build", "out", "target",
}

_EXCLUDED_EXACT_NAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "composer.lock", "Gemfile.lock", "Cargo.lock",
    "poetry.lock", "go.sum", "shrinkwrap.json",
    "npm-shrinkwrap.json",
}

_BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp", ".avif",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".exe", ".dll", ".so", ".dylib", ".o", ".a",
    ".pyc", ".pyo", ".class", ".jar",
    ".map",  # source maps
}


def is_valid_candidate(file_path: str) -> bool:
    """Return True if a file path should be included in the localization index.

    Filters out vendored dependencies, build outputs, binary files, lockfiles,
    and other non-source artifacts that should not be localization targets.
    """
    if not file_path or not file_path.strip():
        return False

    normalized = file_path.replace("\\", "/").strip()

    # Exclude paths with banned segments anywhere
    parts = normalized.split("/")
    for part in parts:
        if part in _EXCLUDED_PATH_SEGMENTS:
            return False

    # Exclude root-level build directories (e.g. build/output/main.js)
    if parts and parts[0] in _EXCLUDED_ROOT_SEGMENTS:
        return False

    # Exclude dotfiles/dotdirs at root (e.g. .github is OK, but .git is not)
    basename = parts[-1] if parts else ""

    # Exclude known lockfiles by exact name
    if basename in _EXCLUDED_EXACT_NAMES:
        return False

    # Exclude binary files by extension
    suffix = Path(basename).suffix.lower()
    if suffix in _BINARY_EXTENSIONS:
        return False

    # Exclude files that are clearly generated or vendored
    if normalized.startswith("vendor/") or "/vendor/" in normalized:
        return False

    return True


def file_corpus(frame: pd.DataFrame) -> list[str]:
    """Return sorted, deduplicated, filtered list of candidate file paths."""
    files: set[str] = set()
    for values in frame.changed_files:
        if not values:
            continue
        for f in values:
            f_str = str(f).replace("\\", "/").strip()
            if f_str and is_valid_candidate(f_str):
                files.add(f_str)
    result = sorted(files)
    logger.info(
        "file_corpus: %d candidate files after filtering (from %d raw unique paths)",
        len(result),
        len(set(str(f) for vals in frame.changed_files for f in (vals or []))),
    )
    return result


def file_texts(files: list[str]) -> list[str]:
    """Create a textual representation for embedding each candidate file.

    Includes the full path hierarchy so that embeddings capture directory context.
    """
    texts = []
    for file_path in files:
        parts = file_path.replace("\\", "/").split("/")
        stem = Path(parts[-1]).stem.replace("_", " ").replace("-", " ")
        dirs = " ".join(parts[:-1]).replace("_", " ").replace("-", " ")
        extension = Path(parts[-1]).suffix.lstrip(".")
        text = f"{stem} {extension} {dirs} {file_path}"
        texts.append(text)
    return texts


# ---------------------------------------------------------------------------
# Dataset loading, cleaning, and splitting
# ---------------------------------------------------------------------------

def load_dataset(path: str | Path) -> pd.DataFrame:
    records = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    if not records:
        raise ValueError("The historical dataset is empty.")
    frame = pd.DataFrame(records)
    if "issue_labels" not in frame.columns:
        frame["issue_labels"] = [[] for _ in range(len(frame))]
    if "changed_files" not in frame.columns:
        frame["changed_files"] = [[] for _ in range(len(frame))]
    frame["issue_labels"] = frame["issue_labels"].apply(lambda value: value if isinstance(value, list) else [])
    frame["changed_files"] = frame["changed_files"].apply(lambda value: value if isinstance(value, list) else [])
    frame["issue_text"] = (frame.issue_title.fillna("") + "\n" + frame.issue_body.fillna("")).str.strip()
    frame["label_count"] = frame.issue_labels.map(len)
    frame["issue_body_chars"] = frame.issue_body.fillna("").str.len()
    frame["issue_title_chars"] = frame.issue_title.fillna("").str.len()

    # Filter changed_files through the candidate filter for cleaner labels
    frame["changed_files_filtered"] = frame["changed_files"].apply(
        lambda files: [f for f in files if is_valid_candidate(str(f))]
    )

    # Add label-based boolean features (available at inference time)
    for prefix in KNOWN_LABEL_PREFIXES:
        col_name = f"has_label_{prefix.replace(' ', '_')}"
        frame[col_name] = frame.issue_labels.apply(
            lambda labels: float(any(prefix in str(l).lower() for l in labels))
        )

    # Log-transform effort_hours to reduce skew (keep original for reporting)
    if "effort_hours" in frame.columns:
        frame["effort_hours_raw"] = frame["effort_hours"].copy()
        frame["effort_hours_log"] = np.log1p(frame["effort_hours"].clip(lower=0))

    initial_count = len(frame)
    logger.info("Loaded %d records from %s", initial_count, path)
    return frame


def deduplicate_dataset(frame: pd.DataFrame) -> pd.DataFrame:
    """Handle issues linked to multiple PRs.

    When one issue has multiple resolving PRs, keep the one with the earliest
    merge date (the first resolution). Union their changed_files.
    """
    if "issue_number" not in frame.columns or "repository" not in frame.columns:
        return frame

    initial = len(frame)
    groups = frame.groupby(["repository", "issue_number"])

    merged_rows = []
    for (repo, issue_num), group in groups:
        if len(group) == 1:
            merged_rows.append(group.iloc[0])
            continue

        # Sort by pr_merged_at, take earliest
        sorted_group = group.sort_values("pr_merged_at")
        primary = sorted_group.iloc[0].copy()

        # Union changed files from all PRs for this issue
        all_files = set()
        for files in sorted_group["changed_files"]:
            all_files.update(files or [])
        primary["changed_files"] = sorted(all_files)

        # Union filtered files too
        if "changed_files_filtered" in sorted_group.columns:
            all_filtered = set()
            for files in sorted_group["changed_files_filtered"]:
                all_filtered.update(files or [])
            primary["changed_files_filtered"] = sorted(all_filtered)

        merged_rows.append(primary)

    result = pd.DataFrame(merged_rows).reset_index(drop=True)
    dropped = initial - len(result)
    logger.info(
        "Deduplication: %d records -> %d records (%d duplicate issue entries merged)",
        initial, len(result), dropped,
    )
    return result


def append_graph_features(frame: pd.DataFrame, graph: object | None = None) -> pd.DataFrame:
    """Append graph features using ONLY issue-text-derived nodes, not changed_files.

    This prevents target leakage: changed_files are post-hoc labels, not
    available at inference time.
    """
    if graph is None:
        return frame.copy()
    from .graph_features import GRAPH_FEATURE_COLUMNS, graph_aware_features_safe

    frame = frame.copy()
    graph_frame = graph_aware_features_safe(frame, graph)
    for column in GRAPH_FEATURE_COLUMNS:
        frame[column] = graph_frame.get(column, 0.0).fillna(0.0)
    return frame


def tabular_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Extract tabular features available at inference time."""
    numeric_columns = [name for name in NUMERIC_FEATURES if name in frame.columns]

    # Add label-based features
    label_columns = [name for name in frame.columns if name.startswith("has_label_")]

    # Add embedding columns
    embedding_columns = [name for name in frame.columns if name.startswith("issue_emb_")]

    # Only include graph features that are safe (don't depend on changed_files)
    safe_graph_columns = [name for name in frame.columns if name.startswith("graph_")]

    available = list(dict.fromkeys(
        numeric_columns + label_columns + safe_graph_columns + embedding_columns
    ))
    if not available:
        raise ValueError("The dataset does not contain any usable tabular features.")
    return frame[available].fillna(0).astype(float)


def training_split(
    frame: pd.DataFrame,
    test_size: float = 0.2,
    stratify_column: str = "difficulty_label",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Temporal split with approximate stratification.

    Sorts by pr_merged_at (temporal order), then picks the last `test_size`
    fraction as the test set. This prevents future PRs from leaking into
    training. For difficulty, we verify that all classes appear in both splits.
    """
    if "pr_merged_at" not in frame.columns:
        raise ValueError("Dataset must have 'pr_merged_at' for temporal splitting.")

    ordered = frame.sort_values("pr_merged_at").reset_index(drop=True)
    cutoff = max(1, int(len(ordered) * (1 - test_size)))
    if cutoff >= len(ordered):
        raise ValueError("At least two historical records are required for a holdout split.")

    train = ordered.iloc[:cutoff].copy()
    test = ordered.iloc[cutoff:].copy()

    # Verify all classes present in both sets
    if stratify_column in train.columns:
        train_classes = set(train[stratify_column].unique())
        test_classes = set(test[stratify_column].unique())
        missing_in_test = train_classes - test_classes
        if missing_in_test:
            logger.warning(
                "Classes %s present in train but missing in test. "
                "Test set may be too small for reliable per-class evaluation.",
                missing_in_test,
            )

    logger.info(
        "Split: %d train, %d test (cutoff at index %d)",
        len(train), len(test), cutoff,
    )
    return train, test
