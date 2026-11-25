"""Three trained models: difficulty classification, effort regression, localization."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import faiss
import joblib
import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    median_absolute_error,
)
from sklearn.preprocessing import LabelEncoder

from .features import (
    append_graph_features,
    deduplicate_dataset,
    file_corpus,
    file_texts,
    is_valid_candidate,
    load_dataset,
    tabular_features,
    training_split,
)

logger = logging.getLogger(__name__)

_EMBEDDER_CACHE: dict[str, SentenceTransformer] = {}


def _embedder(name: str) -> SentenceTransformer:
    if name not in _EMBEDDER_CACHE:
        _EMBEDDER_CACHE[name] = SentenceTransformer(name)
    return _EMBEDDER_CACHE[name]


def _embedding_column_names(size: int) -> list[str]:
    return [f"issue_emb_{index}" for index in range(size)]


def _issue_embedding_matrix(issue_texts: list[str], embedder: SentenceTransformer) -> np.ndarray:
    if not issue_texts:
        return np.zeros((0, 0), dtype="float32")
    embeddings = np.asarray(embedder.encode(issue_texts, normalize_embeddings=True), dtype="float32")
    if embeddings.ndim == 1:
        embeddings = embeddings.reshape(1, -1)
    return embeddings


def _historical_file_scores(
    frame: pd.DataFrame,
    dampen: bool = True,
) -> dict[str, float]:
    """Compute historical file frequency scores with log-dampening.

    Without dampening, files that appear in many PRs (like package.json)
    dominate the ranking regardless of the query. Log-dampening reduces
    the advantage of extremely frequent files while preserving the signal
    that some files are changed more often.
    """
    # Use filtered changed_files if available
    col = "changed_files_filtered" if "changed_files_filtered" in frame.columns else "changed_files"

    counts: dict[str, float] = {}
    for file_names in frame.get(col, []):
        for file_name in file_names or []:
            f = str(file_name)
            if is_valid_candidate(f):
                counts[f] = counts.get(f, 0.0) + 1.0

    if not counts:
        return {}

    if dampen:
        # Log-dampening: score = log(1 + count) / log(1 + max_count)
        max_count = max(counts.values())
        log_max = np.log1p(max_count)
        if log_max > 0:
            return {path: float(np.log1p(value) / log_max) for path, value in counts.items()}

    # Fallback: linear normalization
    max_count = max(counts.values())
    return {path: value / max_count for path, value in counts.items()}


def _graph_file_scores(graph: Any | None, file_names: list[str]) -> dict[str, float]:
    if graph is None:
        return {}
    scores: dict[str, float] = {}
    try:
        import networkx as nx
        if hasattr(graph, "number_of_nodes") and graph.number_of_nodes() > 0:
            if hasattr(graph, "number_of_edges") and graph.number_of_edges():
                pagerank = nx.pagerank(graph, weight="weight")
            else:
                pagerank = {node: 0.0 for node in graph.nodes}
            for file_name in file_names:
                scores[file_name] = float(pagerank.get(file_name, 0.0))
    except Exception:
        pass
    return scores


def _normalize_scores(scores: np.ndarray) -> np.ndarray:
    """Min-max normalize an array of scores to [0, 1]."""
    if scores.size == 0:
        return scores
    s_min = scores.min()
    s_max = scores.max()
    if s_max - s_min < 1e-12:
        return np.zeros_like(scores)
    return (scores - s_min) / (s_max - s_min)


def _combine_localization_scores(
    query_embedding: np.ndarray,
    file_embeddings: np.ndarray,
    file_names: list[str],
    historical_file_scores: dict[str, float] | None = None,
    graph_file_scores: dict[str, float] | None = None,
) -> np.ndarray:
    """Combine semantic similarity, historical frequency, and graph scores.

    All component scores are normalized to [0, 1] before combining to prevent
    any single component from dominating due to scale differences.
    """
    file_embeddings = np.asarray(file_embeddings, dtype="float32")
    query_embedding = np.asarray(query_embedding, dtype="float32").reshape(-1)
    if file_embeddings.size == 0:
        return np.zeros(len(file_names), dtype="float32")

    # Semantic similarity (already normalized if embeddings are unit vectors)
    embedding_scores = np.asarray(file_embeddings @ query_embedding, dtype="float32")
    embedding_scores = _normalize_scores(embedding_scores)

    # Historical frequency (already dampened, but normalize for safety)
    historical_scores = np.asarray(
        [float((historical_file_scores or {}).get(file_name, 0.0)) for file_name in file_names],
        dtype="float32",
    )
    historical_scores = _normalize_scores(historical_scores)

    # Graph centrality
    graph_scores = np.asarray(
        [float((graph_file_scores or {}).get(file_name, 0.0)) for file_name in file_names],
        dtype="float32",
    )
    graph_scores = _normalize_scores(graph_scores)

    # Weighted combination: semantic similarity is primary signal
    combined = embedding_scores * 0.70 + historical_scores * 0.20 + graph_scores * 0.10
    return combined.astype("float32")


def _boosting_classifier():
    try:
        from lightgbm import LGBMClassifier
        return LGBMClassifier(n_estimators=120, learning_rate=0.05, num_leaves=15, verbosity=-1, random_state=42)
    except ImportError:
        from xgboost import XGBClassifier
        return XGBClassifier(n_estimators=120, max_depth=4, learning_rate=0.05, eval_metric="mlogloss", random_state=42)


def _boosting_regressor():
    try:
        from lightgbm import LGBMRegressor
        return LGBMRegressor(n_estimators=160, learning_rate=0.05, num_leaves=15, verbosity=-1, random_state=42)
    except ImportError:
        from xgboost import XGBRegressor
        return XGBRegressor(n_estimators=160, max_depth=4, learning_rate=0.05, objective="reg:squarederror", random_state=42)


@dataclass
class ContriMapModels:
    classifier: Any
    classifier_labels: LabelEncoder
    regressor: Any
    embedder_name: str
    file_names: list[str]
    file_index: Any
    feature_columns: list[str] = field(default_factory=list)
    graph_features: bool = False
    issue_embedding_dim: int = 0
    issue_embedding_columns: list[str] = field(default_factory=list)
    historical_issue_file_scores: dict[str, float] = field(default_factory=dict)
    graph_file_scores: dict[str, float] = field(default_factory=dict)
    effort_target_is_log: bool = False

    def save(self, directory: str | Path) -> None:
        output = Path(directory)
        output.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "classifier": self.classifier,
            "classifier_labels": self.classifier_labels,
            "regressor": self.regressor,
        }, output / "tabular_models.joblib")
        if self.file_index is not None:
            faiss.write_index(self.file_index, str(output / "file_index.faiss"))
        metadata = {
            "embedder_name": self.embedder_name,
            "file_names": self.file_names,
            "feature_columns": self.feature_columns,
            "graph_features": self.graph_features,
            "issue_embedding_dim": self.issue_embedding_dim,
            "issue_embedding_columns": self.issue_embedding_columns,
            "historical_issue_file_scores": self.historical_issue_file_scores,
            "graph_file_scores": self.graph_file_scores,
            "effort_target_is_log": self.effort_target_is_log,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        (output / "localization.json").write_text(json.dumps(metadata), encoding="utf-8")

    @classmethod
    def load(cls, directory: str | Path) -> "ContriMapModels":
        directory = Path(directory)
        trained = joblib.load(directory / "tabular_models.joblib")
        metadata_path = directory / "localization.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {
            "embedder_name": "sentence-transformers/all-MiniLM-L6-v2",
            "file_names": [],
            "feature_columns": [],
            "graph_features": False,
            "issue_embedding_dim": 0,
            "issue_embedding_columns": [],
            "historical_issue_file_scores": {},
            "graph_file_scores": {},
            "effort_target_is_log": False,
        }
        file_index_path = directory / "file_index.faiss"
        index = faiss.read_index(str(file_index_path)) if file_index_path.exists() else faiss.IndexFlatIP(1)
        return cls(
            **trained,
            embedder_name=metadata.get("embedder_name", "sentence-transformers/all-MiniLM-L6-v2"),
            file_names=list(metadata.get("file_names", [])),
            file_index=index,
            feature_columns=list(metadata.get("feature_columns") or []),
            graph_features=bool(metadata.get("graph_features", False)),
            issue_embedding_dim=int(metadata.get("issue_embedding_dim") or 0),
            issue_embedding_columns=list(metadata.get("issue_embedding_columns") or []),
            historical_issue_file_scores=dict(metadata.get("historical_issue_file_scores") or {}),
            graph_file_scores=dict(metadata.get("graph_file_scores") or {}),
            effort_target_is_log=bool(metadata.get("effort_target_is_log", False)),
        )

    def predict(self, issue_title: str, issue_body: str = "", labels: list[str] | None = None, top_k: int = 10) -> dict[str, Any]:
        labels = labels or []
        feature_columns = list(self.feature_columns or ["label_count", "issue_body_chars", "issue_title_chars"])
        values: dict[str, float] = {column: 0.0 for column in feature_columns}
        values["label_count"] = float(len(labels))
        values["issue_body_chars"] = float(len(issue_body))
        values["issue_title_chars"] = float(len(issue_title))

        # Add label-based features
        from .features import KNOWN_LABEL_PREFIXES
        for prefix in KNOWN_LABEL_PREFIXES:
            col_name = f"has_label_{prefix.replace(' ', '_')}"
            if col_name in values:
                values[col_name] = float(any(prefix in str(l).lower() for l in labels))

        if self.issue_embedding_columns:
            issue_text = f"{issue_title}\n{issue_body}".strip() or issue_title
            embedder = _embedder(self.embedder_name)
            embedding = np.asarray(embedder.encode([issue_text], normalize_embeddings=True), dtype="float32").reshape(-1)
            for name, value in zip(self.issue_embedding_columns, embedding.tolist()):
                if name in values:
                    values[name] = float(value)
        row = pd.DataFrame([values], columns=feature_columns)
        probabilities = self.classifier.predict_proba(row)[0]
        encoded = int(np.argmax(probabilities))
        max_prob = float(probabilities[encoded])

        # Effort prediction
        effort_raw = float(self.regressor.predict(row)[0])
        if self.effort_target_is_log:
            # Inverse log1p transform: expm1(log_value) = original_value
            effort_hours = max(0.0, float(np.expm1(effort_raw)))
        else:
            effort_hours = max(0.0, effort_raw)

        # Build localization results
        query_text = f"{issue_title}\n{issue_body}".strip() or issue_title
        file_scores: list[dict[str, Any]] = []
        if self.file_names:
            embedder = _embedder(self.embedder_name)
            if self.historical_issue_file_scores or self.graph_file_scores or self.issue_embedding_columns:
                candidate_embeddings = np.asarray(embedder.encode(file_texts(self.file_names), normalize_embeddings=True), dtype="float32")
                query_embedding = np.asarray(embedder.encode([query_text], normalize_embeddings=True), dtype="float32").reshape(-1)
                combined_scores = _combine_localization_scores(query_embedding, candidate_embeddings, self.file_names, self.historical_issue_file_scores, self.graph_file_scores)
                ranked_indices = np.argsort(combined_scores)[::-1][: min(top_k, len(self.file_names))]
                file_scores = [
                    {
                        "path": self.file_names[int(index)],
                        "similarity": float(combined_scores[int(index)]),
                    }
                    for index in ranked_indices
                    if index < len(self.file_names)
                ]
            elif self.file_index is not None:
                distances, indices = self.file_index.search(np.asarray(embedder.encode([query_text], normalize_embeddings=True), dtype="float32"), min(top_k, len(self.file_names)))
                file_scores = [{"path": self.file_names[int(index)], "similarity": float(distance)} for distance, index in zip(distances[0], indices[0]) if index >= 0]

        return {
            "difficulty": self.classifier_labels.inverse_transform([encoded])[0],
            "difficulty_probability": max_prob,
            "effort_hours": effort_hours,
            "effort_note": "Estimated elapsed calendar time (issue open to PR merge), not active engineering hours.",
            "confidence": "low" if max_prob < 0.45 else ("medium" if max_prob < 0.65 else "high"),
            "files": file_scores,
        }


def train_models(dataset_path: str | Path, output_dir: str | Path, embedder_name: str = "sentence-transformers/all-MiniLM-L6-v2", graph: Any | None = None) -> dict[str, Any]:
    frame = load_dataset(dataset_path)
    initial_count = len(frame)

    # Deduplicate before training
    frame = deduplicate_dataset(frame)
    deduped_count = len(frame)

    if graph is not None:
        frame = append_graph_features(frame, graph)

    embedder = _embedder(embedder_name)
    issue_texts = frame.issue_text.fillna("").astype(str).str.strip()
    issue_texts = issue_texts.where(issue_texts != "", frame.issue_title.fillna("").astype(str))
    issue_embeddings = _issue_embedding_matrix(issue_texts.tolist(), embedder)
    issue_embedding_columns: list[str] = []
    if issue_embeddings.size:
        issue_embedding_columns = _embedding_column_names(issue_embeddings.shape[1])
        emb_df = pd.DataFrame(issue_embeddings, columns=issue_embedding_columns, index=frame.index)
        frame = pd.concat([frame, emb_df], axis=1)

    train, test = training_split(frame)
    x_train, x_test = tabular_features(train), tabular_features(test)

    # --- Difficulty classification ---
    labels = LabelEncoder().fit(frame["difficulty_label"].astype(str))
    y_train_diff = labels.transform(train["difficulty_label"].astype(str))
    y_test_diff = labels.transform(test["difficulty_label"].astype(str))

    classifier = _boosting_classifier().fit(x_train, y_train_diff)
    predicted_diff = classifier.predict(x_test)

    # Baseline: majority class
    from collections import Counter
    majority_class = Counter(y_train_diff).most_common(1)[0][0]
    baseline_diff_pred = np.full_like(y_test_diff, majority_class)

    # --- Effort regression (log-transformed) ---
    y_train_effort = train["effort_hours_log"].values
    y_test_effort_log = test["effort_hours_log"].values
    y_test_effort_raw = test["effort_hours_raw"].values if "effort_hours_raw" in test.columns else test["effort_hours"].values

    regressor = _boosting_regressor().fit(x_train, y_train_effort)
    effort_predicted_log = regressor.predict(x_test)
    effort_predicted_raw = np.expm1(np.clip(effort_predicted_log, 0, 20))  # inverse log1p

    # Baseline: predict median (in log space)
    median_effort_log = np.median(y_train_effort)
    baseline_effort_pred = np.full_like(y_test_effort_log, median_effort_log)
    baseline_effort_raw = np.expm1(np.clip(baseline_effort_pred, 0, 20))

    # --- Localization ---
    # Build candidate index from filtered files (train only, to avoid leakage)
    files = file_corpus(train)
    if not files:
        # Fallback to full dataset if train has no files
        files = file_corpus(frame)
    if not files:
        raise ValueError("The historical dataset contains no changed files for localization.")

    file_embeddings = _issue_embedding_matrix(file_texts(files), embedder)
    if file_embeddings.size == 0:
        raise ValueError("The historical dataset contains no usable file embeddings for localization.")

    index = faiss.IndexFlatIP(file_embeddings.shape[1])
    index.add(np.asarray(file_embeddings, dtype="float32"))

    historical_file_scores = _historical_file_scores(train)
    graph_file_scores = _graph_file_scores(graph, files)

    artifact = ContriMapModels(
        classifier=classifier,
        classifier_labels=labels,
        regressor=regressor,
        embedder_name=embedder_name,
        file_names=files,
        file_index=index,
        feature_columns=list(x_train.columns),
        graph_features=graph is not None,
        issue_embedding_dim=file_embeddings.shape[1],
        issue_embedding_columns=issue_embedding_columns,
        historical_issue_file_scores=historical_file_scores,
        graph_file_scores=graph_file_scores,
        effort_target_is_log=True,
    )
    artifact.save(output_dir)

    # --- Localization Evaluation ---
    evaluation_files = files  # use train-derived candidates
    evaluation_embeddings = file_embeddings

    recall_at_5 = []
    recall_at_10 = []
    ranks: list[float] = []
    file_category_counts = {"source": 0, "config": 0, "test": 0, "other": 0}

    # Also compute semantic-only and frequency-only baselines
    recall_at_5_semantic = []
    recall_at_5_frequency = []

    for _, record in test.iterrows():
        query_embedding = _issue_embedding_matrix([str(record.issue_text)], embedder)[0]

        # Combined model scores
        evaluation_scores = _combine_localization_scores(
            query_embedding, evaluation_embeddings, evaluation_files,
            _historical_file_scores(train), _graph_file_scores(graph, evaluation_files),
        )
        ordered = np.argsort(evaluation_scores)[::-1]
        retrieved = [evaluation_files[int(position)] for position in ordered[:10]]

        # Use filtered changed_files as ground truth
        targets = set(
            record.changed_files_filtered
            if hasattr(record, "changed_files_filtered") and record.changed_files_filtered
            else record.changed_files
        )
        # Filter targets to only valid candidates
        targets = {t for t in targets if is_valid_candidate(str(t))}

        if not targets:
            continue  # Skip records with no valid target files

        recall_at_5.append(bool(targets.intersection(retrieved[:5])))
        recall_at_10.append(bool(targets.intersection(retrieved[:10])))
        matching_ranks = [rank + 1 for rank, file_name in enumerate(retrieved) if file_name in targets]
        ranks.append(min(matching_ranks) if matching_ranks else 0.0)

        # Track what types of files are in top-5 predictions
        for f in retrieved[:5]:
            if any(f.endswith(e) for e in [".js", ".jsx", ".ts", ".tsx", ".py", ".go", ".rs", ".java", ".vue", ".rb"]):
                if "test" in f.lower() or "spec" in f.lower():
                    file_category_counts["test"] += 1
                else:
                    file_category_counts["source"] += 1
            elif any(f.endswith(e) for e in [".json", ".yaml", ".yml", ".toml", ".lock"]):
                file_category_counts["config"] += 1
            else:
                file_category_counts["other"] += 1

        # Semantic-only baseline
        sem_scores = np.asarray(evaluation_embeddings @ query_embedding, dtype="float32")
        sem_ordered = np.argsort(sem_scores)[::-1]
        sem_retrieved = [evaluation_files[int(p)] for p in sem_ordered[:5]]
        recall_at_5_semantic.append(bool(targets.intersection(sem_retrieved)))

        # Frequency-only baseline
        freq_scores = np.asarray(
            [float(historical_file_scores.get(f, 0.0)) for f in evaluation_files],
            dtype="float32",
        )
        freq_ordered = np.argsort(freq_scores)[::-1]
        freq_retrieved = [evaluation_files[int(p)] for p in freq_ordered[:5]]
        recall_at_5_frequency.append(bool(targets.intersection(freq_retrieved)))

    # --- Compile all metrics ---
    class_report = classification_report(y_test_diff, predicted_diff, target_names=labels.classes_, output_dict=True)
    conf_mat = confusion_matrix(y_test_diff, predicted_diff).tolist()

    # Difficulty distribution
    train_diff_dist = Counter(train["difficulty_label"].astype(str).values)
    test_diff_dist = Counter(test["difficulty_label"].astype(str).values)

    metrics_result = {
        "dataset": {
            "initial_records": initial_count,
            "after_deduplication": deduped_count,
            "train_records": len(train),
            "test_records": len(test),
        },
        "difficulty": {
            "accuracy": accuracy_score(y_test_diff, predicted_diff),
            "macro_f1": f1_score(y_test_diff, predicted_diff, average="macro"),
            "baseline_accuracy": accuracy_score(y_test_diff, baseline_diff_pred),
            "baseline_macro_f1": f1_score(y_test_diff, baseline_diff_pred, average="macro"),
            "per_class_report": class_report,
            "confusion_matrix": conf_mat,
            "train_distribution": dict(train_diff_dist),
            "test_distribution": dict(test_diff_dist),
        },
        "effort": {
            "mae_hours": mean_absolute_error(y_test_effort_raw, effort_predicted_raw),
            "median_ae_hours": median_absolute_error(y_test_effort_raw, effort_predicted_raw),
            "rmse_hours": mean_squared_error(y_test_effort_raw, effort_predicted_raw) ** 0.5,
            "mae_log": mean_absolute_error(y_test_effort_log, effort_predicted_log),
            "baseline_mae_hours": mean_absolute_error(y_test_effort_raw, baseline_effort_raw),
            "baseline_median_ae_hours": median_absolute_error(y_test_effort_raw, baseline_effort_raw),
            "baseline_rmse_hours": mean_squared_error(y_test_effort_raw, baseline_effort_raw) ** 0.5,
            "target_is_log": True,
            "target_note": "Effort is elapsed calendar time (issue open to PR merge), NOT active engineering hours.",
            "test_effort_stats": {
                "min": float(y_test_effort_raw.min()),
                "median": float(np.median(y_test_effort_raw)),
                "mean": float(y_test_effort_raw.mean()),
                "max": float(y_test_effort_raw.max()),
                "std": float(y_test_effort_raw.std()),
            },
        },
        "localization": {
            "index_files": len(files),
            "recall_at_5": float(sum(recall_at_5) / len(recall_at_5)) if recall_at_5 else 0.0,
            "recall_at_10": float(sum(recall_at_10) / len(recall_at_10)) if recall_at_10 else 0.0,
            "mrr": float(sum(1.0 / rank for rank in ranks if rank) / len(ranks)) if ranks else 0.0,
            "evaluated_issues": len(recall_at_5),
            "skipped_issues_no_valid_targets": len(test) - len(recall_at_5),
            "baseline_semantic_recall_at_5": float(sum(recall_at_5_semantic) / len(recall_at_5_semantic)) if recall_at_5_semantic else 0.0,
            "baseline_frequency_recall_at_5": float(sum(recall_at_5_frequency) / len(recall_at_5_frequency)) if recall_at_5_frequency else 0.0,
            "top5_file_categories": file_category_counts,
        },
        "feature_columns": list(x_train.columns),
        "graph_features_used": graph is not None,
        "artifact_dir": str(output_dir),
    }

    try:
        metrics_file = Path(output_dir) / "evaluation_metrics.json"
        metrics_file.write_text(json.dumps(metrics_result, indent=2, default=str), encoding="utf-8")
        logger.info("Saved evaluation metrics to %s", metrics_file)
    except Exception as exc:
        logger.warning("Could not write evaluation_metrics.json: %s", exc)

    return metrics_result
