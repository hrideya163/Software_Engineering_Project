"""Three trained models: difficulty classification, effort regression, localization."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import faiss
import joblib
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error, mean_squared_error
from sklearn.preprocessing import LabelEncoder

from .features import file_corpus, file_texts, load_dataset, tabular_features, training_split

_EMBEDDER_CACHE: dict[str, SentenceTransformer] = {}


def _embedder(name: str) -> SentenceTransformer:
    if name not in _EMBEDDER_CACHE:
        _EMBEDDER_CACHE[name] = SentenceTransformer(name)
    return _EMBEDDER_CACHE[name]


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

    def save(self, directory: str | Path) -> None:
        output = Path(directory)
        output.mkdir(parents=True, exist_ok=True)
        joblib.dump({"classifier": self.classifier, "classifier_labels": self.classifier_labels,
                     "regressor": self.regressor}, output / "tabular_models.joblib")
        faiss.write_index(self.file_index, str(output / "file_index.faiss"))
        (output / "localization.json").write_text(json.dumps({"embedder_name": self.embedder_name, "file_names": self.file_names}), encoding="utf-8")

    @classmethod
    def load(cls, directory: str | Path) -> "ContriMapModels":
        directory = Path(directory)
        trained = joblib.load(directory / "tabular_models.joblib")
        metadata = json.loads((directory / "localization.json").read_text(encoding="utf-8"))
        return cls(**trained, embedder_name=metadata["embedder_name"], file_names=metadata["file_names"],
                   file_index=faiss.read_index(str(directory / "file_index.faiss")))

    def predict(self, issue_title: str, issue_body: str = "", labels: list[str] | None = None, top_k: int = 10) -> dict[str, Any]:
        labels = labels or []
        row = np.array([[len(labels), len(issue_body), len(issue_title)]], dtype=float)
        probabilities = self.classifier.predict_proba(row)[0]
        encoded = int(np.argmax(probabilities))
        embedding = _embedder(self.embedder_name).encode([f"{issue_title}\n{issue_body}"], normalize_embeddings=True)
        distances, indices = self.file_index.search(np.asarray(embedding, dtype="float32"), min(top_k, len(self.file_names)))
        return {
            "difficulty": self.classifier_labels.inverse_transform([encoded])[0],
            "difficulty_probability": float(probabilities[encoded]),
            "effort_hours": max(0.0, float(self.regressor.predict(row)[0])),
            "files": [{"path": self.file_names[int(index)], "similarity": float(distance)} for distance, index in zip(distances[0], indices[0]) if index >= 0],
        }


def train_models(dataset_path: str | Path, output_dir: str | Path, embedder_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> dict[str, Any]:
    frame = load_dataset(dataset_path)
    train, test = training_split(frame)
    x_train, x_test = tabular_features(train), tabular_features(test)
    labels = LabelEncoder().fit(frame.difficulty_label)
    classifier = _boosting_classifier().fit(x_train, labels.transform(train.difficulty_label))
    regressor = _boosting_regressor().fit(x_train, train.effort_hours)
    predicted = classifier.predict(x_test)
    effort_predicted = regressor.predict(x_test)

    files = file_corpus(frame)
    if not files:
        raise ValueError("The historical dataset contains no changed files for localization.")
    embedder = _embedder(embedder_name)
    index = faiss.IndexFlatIP(embedder.get_sentence_embedding_dimension())
    index.add(np.asarray(embedder.encode(file_texts(files), normalize_embeddings=True), dtype="float32"))
    artifact = ContriMapModels(classifier, labels, regressor, embedder_name, files, index)
    artifact.save(output_dir)
    evaluation_files = file_corpus(train)
    evaluation_index = faiss.IndexFlatIP(embedder.get_sentence_embedding_dimension())
    evaluation_index.add(np.asarray(embedder.encode(file_texts(evaluation_files), normalize_embeddings=True), dtype="float32"))
    localization_hits = []
    localization_ranks = []
    for _, record in test.iterrows():
        query = embedder.encode([record.issue_text], normalize_embeddings=True)
        _, indices = evaluation_index.search(np.asarray(query, dtype="float32"), min(10, len(evaluation_files)))
        retrieved = [evaluation_files[int(position)] for position in indices[0] if position >= 0]
        targets = set(record.changed_files)
        localization_hits.append(bool(targets.intersection(retrieved)))
        matching_ranks = [rank + 1 for rank, file in enumerate(retrieved) if file in targets]
        localization_ranks.append(min(matching_ranks) if matching_ranks else 0)
    recall_at_10 = sum(localization_hits) / len(localization_hits) if localization_hits else 0.0
    reciprocal_rank = sum(1 / rank for rank in localization_ranks if rank) / len(localization_ranks) if localization_ranks else 0.0
    return {
        "records": len(frame),
        "train_records": len(train),
        "test_records": len(test),
        "difficulty_accuracy": accuracy_score(labels.transform(test.difficulty_label), predicted),
        "difficulty_macro_f1": f1_score(labels.transform(test.difficulty_label), predicted, average="macro"),
        "effort_mae_hours": mean_absolute_error(test.effort_hours, effort_predicted),
        "effort_rmse_hours": mean_squared_error(test.effort_hours, effort_predicted) ** 0.5,
        "localization_index_files": len(files),
        "localization_recall_at_10": recall_at_10,
        "localization_mrr": reciprocal_rank,
        "artifact_dir": str(output_dir),
    }
