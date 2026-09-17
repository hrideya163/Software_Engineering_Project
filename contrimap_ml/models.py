"""Three trained models: difficulty classification, effort regression, localization."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import faiss
import joblib
import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer
from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error, mean_squared_error
from sklearn.preprocessing import LabelEncoder

from .features import append_graph_features, file_corpus, file_texts, load_dataset, tabular_features, training_split

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


def _historical_file_scores(frame: pd.DataFrame) -> dict[str, float]:
    counts: dict[str, float] = {}
    for file_names in frame.get("changed_files", []):
        for file_name in file_names or []:
            counts[str(file_name)] = counts.get(str(file_name), 0.0) + 1.0
    if not counts:
        return {}
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


def _combine_localization_scores(
    query_embedding: np.ndarray,
    file_embeddings: np.ndarray,
    file_names: list[str],
    historical_file_scores: dict[str, float] | None = None,
    graph_file_scores: dict[str, float] | None = None,
) -> np.ndarray:
    file_embeddings = np.asarray(file_embeddings, dtype="float32")
    query_embedding = np.asarray(query_embedding, dtype="float32").reshape(-1)
    if file_embeddings.size == 0:
        return np.zeros(len(file_names), dtype="float32")
    embedding_scores = np.asarray(file_embeddings @ query_embedding, dtype="float32")
    historical_scores = np.asarray([float((historical_file_scores or {}).get(file_name, 0.0)) for file_name in file_names], dtype="float32")
    graph_scores = np.asarray([float((graph_file_scores or {}).get(file_name, 0.0)) for file_name in file_names], dtype="float32")
    combined = embedding_scores * 0.7 + historical_scores * 0.25 + graph_scores * 0.05
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
        )

    def predict(self, issue_title: str, issue_body: str = "", labels: list[str] | None = None, top_k: int = 10) -> dict[str, Any]:
        labels = labels or []
        feature_columns = list(self.feature_columns or ["label_count", "issue_body_chars", "issue_title_chars"])
        values: dict[str, float] = {column: 0.0 for column in feature_columns}
        values["label_count"] = float(len(labels))
        values["issue_body_chars"] = float(len(issue_body))
        values["issue_title_chars"] = float(len(issue_title))
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
                    {"path": self.file_names[int(index)], "similarity": float(combined_scores[int(index)])}
                    for index in ranked_indices
                    if index < len(self.file_names)
                ]
            elif self.file_index is not None:
                distances, indices = self.file_index.search(np.asarray(embedder.encode([query_text], normalize_embeddings=True), dtype="float32"), min(top_k, len(self.file_names)))
                file_scores = [{"path": self.file_names[int(index)], "similarity": float(distance)} for distance, index in zip(distances[0], indices[0]) if index >= 0]
        return {
            "difficulty": self.classifier_labels.inverse_transform([encoded])[0],
            "difficulty_probability": float(probabilities[encoded]),
            "effort_hours": max(0.0, float(self.regressor.predict(row)[0])),
            "files": file_scores,
        }


def train_models(dataset_path: str | Path, output_dir: str | Path, embedder_name: str = "sentence-transformers/all-MiniLM-L6-v2", graph: Any | None = None) -> dict[str, Any]:
    frame = load_dataset(dataset_path)
    if graph is not None:
        frame = append_graph_features(frame, graph)
    embedder = _embedder(embedder_name)
    issue_texts = frame.issue_text.fillna("").astype(str).str.strip()
    issue_texts = issue_texts.where(issue_texts != "", frame.issue_title.fillna("").astype(str))
    issue_embeddings = _issue_embedding_matrix(issue_texts.tolist(), embedder)
    issue_embedding_columns: list[str] = []
    if issue_embeddings.size:
        issue_embedding_columns = _embedding_column_names(issue_embeddings.shape[1])
        frame[issue_embedding_columns] = issue_embeddings
    train, test = training_split(frame)
    x_train, x_test = tabular_features(train), tabular_features(test)
    labels = LabelEncoder().fit(frame["difficulty_label"].astype(str))
    classifier = _boosting_classifier().fit(x_train, labels.transform(train["difficulty_label"].astype(str)))
    regressor = _boosting_regressor().fit(x_train, train["effort_hours"])
    predicted = classifier.predict(x_test)
    effort_predicted = regressor.predict(x_test)

    files = file_corpus(frame)
    if not files:
        raise ValueError("The historical dataset contains no changed files for localization.")
    file_embeddings = _issue_embedding_matrix(file_texts(files), embedder)
    if file_embeddings.size == 0:
        raise ValueError("The historical dataset contains no usable file embeddings for localization.")
    index = faiss.IndexFlatIP(file_embeddings.shape[1])
    index.add(np.asarray(file_embeddings, dtype="float32"))
    historical_file_scores = _historical_file_scores(frame)
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
    )
    artifact.save(output_dir)

    evaluation_files = file_corpus(train)
    evaluation_embeddings = _issue_embedding_matrix(file_texts(evaluation_files), embedder)
    if evaluation_embeddings.size == 0:
        evaluation_files = file_corpus(frame)
        evaluation_embeddings = file_embeddings

    recall_at_5 = []
    recall_at_10 = []
    ranks: list[float] = []
    for _, record in test.iterrows():
        query_embedding = _issue_embedding_matrix([str(record.issue_text)], embedder)[0]
        evaluation_scores = _combine_localization_scores(query_embedding, evaluation_embeddings, evaluation_files, _historical_file_scores(train), _graph_file_scores(graph, evaluation_files))
        ordered = np.argsort(evaluation_scores)[::-1]
        retrieved = [evaluation_files[int(position)] for position in ordered[:10]]
        targets = set(record.changed_files)
        recall_at_5.append(bool(targets.intersection(retrieved[:5])))
        recall_at_10.append(bool(targets.intersection(retrieved[:10])))
        matching_ranks = [rank + 1 for rank, file_name in enumerate(retrieved) if file_name in targets]
        ranks.append(min(matching_ranks) if matching_ranks else 0.0)

    return {
        "records": len(frame),
        "train_records": len(train),
        "test_records": len(test),
        "difficulty_accuracy": accuracy_score(labels.transform(test["difficulty_label"].astype(str)), predicted),
        "difficulty_macro_f1": f1_score(labels.transform(test["difficulty_label"].astype(str)), predicted, average="macro"),
        "effort_mae_hours": mean_absolute_error(test["effort_hours"], effort_predicted),
        "effort_rmse_hours": mean_squared_error(test["effort_hours"], effort_predicted) ** 0.5,
        "localization_index_files": len(files),
        "localization_recall_at_5": float(sum(recall_at_5) / len(recall_at_5)) if recall_at_5 else 0.0,
        "localization_recall_at_10": float(sum(recall_at_10) / len(recall_at_10)) if recall_at_10 else 0.0,
        "localization_mrr": float(sum(1.0 / rank for rank in ranks if rank) / len(ranks)) if ranks else 0.0,
        "feature_columns": list(x_train.columns),
        "graph_features_used": graph is not None,
        "artifact_dir": str(output_dir),
    }
