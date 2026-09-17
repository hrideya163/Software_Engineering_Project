"""Point-in-time feature construction shared by all supervised models."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

NUMERIC_FEATURES = [
    "label_count", "issue_body_chars", "issue_title_chars",
]


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
    return frame


def append_graph_features(frame: pd.DataFrame, graph: object | None = None) -> pd.DataFrame:
    if graph is None:
        return frame.copy()
    from .graph_features import GRAPH_FEATURE_COLUMNS, graph_aware_features

    frame = frame.copy()
    graph_frame = graph_aware_features(frame, graph)
    for column in GRAPH_FEATURE_COLUMNS:
        frame[column] = graph_frame.get(column, 0.0).fillna(0.0)
    return frame


def tabular_features(frame: pd.DataFrame) -> pd.DataFrame:
    numeric_columns = [name for name in NUMERIC_FEATURES if name in frame.columns]
    embedding_columns = [name for name in frame.columns if name.startswith("issue_emb_")]
    available = list(dict.fromkeys(numeric_columns + [name for name in frame.columns if name.startswith("graph_")] + embedding_columns))
    if not available:
        raise ValueError("The dataset does not contain any usable tabular features.")
    return frame[available].fillna(0).astype(float)


def file_corpus(frame: pd.DataFrame) -> list[str]:
    files: set[str] = set()
    for values in frame.changed_files:
        if not values:
            continue
        files.update(values)
    return sorted(files)


def file_texts(files: list[str]) -> list[str]:
    return [f"{Path(file).stem.replace('_', ' ')} {file.replace('/', ' ')}" for file in files]


def training_split(frame: pd.DataFrame, test_size: float = 0.2) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Time split prevents future PRs leaking into earlier training examples."""
    ordered = frame.sort_values("pr_merged_at").reset_index(drop=True)
    cutoff = max(1, int(len(ordered) * (1 - test_size)))
    if cutoff >= len(ordered):
        raise ValueError("At least two historical records are required for a holdout split.")
    return ordered.iloc[:cutoff].copy(), ordered.iloc[cutoff:].copy()
