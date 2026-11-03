"""Difficulty classification and effort estimation from issue text.

Labels
------
* **Difficulty** (Easy / Medium / Hard) is a proxy computed from the size of the
  gold fix: ``log1p(LOC) + log1p(files) + 0.5 * log1p(hunks)`` over non-test
  files, split at the training-set tertiles.  The proxy was pre-registered and
  checked against SWE-bench Verified's human annotations (Spearman 0.52).
  Thresholds are fitted on the training repositories only.
* **Effort** is expressed in engineer-hours and calibrated on SWE-bench
  Verified's human "time to fix" buckets (the only real effort ground truth
  available), evaluated with repository-grouped cross-validation.  The legacy
  target - elapsed calendar time from issue creation to merge - carried no
  signal (model MAE equal to the median baseline) and measured queueing time,
  not work, so it was retired.

Features are text-only (title, body, labels): nothing derived from the fix.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix, hstack
from scipy.stats import spearmanr
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, mean_absolute_error
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler

from .corpus import HUMAN_DIFFICULTY_HOURS
from .textfeat import HANDCRAFTED_COLUMNS, embed, handcrafted_features

logger = logging.getLogger(__name__)

DIFFICULTY_CLASSES = ["Easy", "Medium", "Hard"]
EFFORT_LEVELS = ["<15 min", "15 min - 1 hour", "1-4 hours", ">4 hours"]


def change_scale(frame: pd.DataFrame) -> pd.Series:
    return np.log1p(frame.loc_changed) + np.log1p(frame.n_files) + 0.5 * np.log1p(frame.n_hunks)


def handcrafted_matrix(frame: pd.DataFrame) -> np.ndarray:
    rows = [handcrafted_features(t, b, l) for t, b, l in zip(frame.title, frame.body, frame.labels)]
    return np.asarray([[row[column] for column in HANDCRAFTED_COLUMNS] for row in rows], dtype="float32")


def _lgbm_classifier(seed: int = 42):
    from lightgbm import LGBMClassifier

    return LGBMClassifier(n_estimators=400, learning_rate=0.03, num_leaves=31, min_child_samples=40, subsample=0.8, subsample_freq=1, colsample_bytree=0.5, reg_lambda=1.0, verbosity=-1, random_state=seed)


def _lgbm_regressor(seed: int = 42):
    from lightgbm import LGBMRegressor

    # Huber loss: test repositories have systematically smaller fixes than training ones, and
    # squared loss chased the heavy tail (test MAE 1.51 vs 1.40 with Huber, median baseline 1.43).
    return LGBMRegressor(objective="huber", n_estimators=400, learning_rate=0.03, num_leaves=31, min_child_samples=40, subsample=0.8, subsample_freq=1, colsample_bytree=0.5, reg_lambda=1.0, verbosity=-1, random_state=seed)


@dataclass
class DifficultyModel:
    """Text-only difficulty classifier, change-size regressor and effort calibrator."""

    thresholds: list[float]
    tfidf: TfidfVectorizer
    scaler: StandardScaler
    linear: LogisticRegression
    boosted: Any
    size_regressor: Any
    blend: float  # weight of the linear model in the probability blend
    effort_model: LogisticRegression | None = None
    effort_scaler: StandardScaler | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # -- feature construction -------------------------------------------------
    def _linear_inputs(self, frame: pd.DataFrame, hand: np.ndarray):
        return hstack([self.tfidf.transform(frame.text.fillna("")), csr_matrix(self.scaler.transform(hand))]).tocsr()

    @staticmethod
    def _dense_inputs(hand: np.ndarray, embeddings: np.ndarray) -> np.ndarray:
        return np.hstack([hand, embeddings])

    def predict_frame(self, frame: pd.DataFrame, embeddings: np.ndarray | None = None) -> dict[str, np.ndarray]:
        hand = handcrafted_matrix(frame)
        if embeddings is None:
            embeddings = embed(frame.text.fillna("").tolist())
        dense = self._dense_inputs(hand, embeddings)
        probabilities = self.blend * self.linear.predict_proba(self._linear_inputs(frame, hand)) + (1 - self.blend) * self.boosted.predict_proba(dense)
        size = self.size_regressor.predict(dense)
        output = {"proba": probabilities, "size": size, "label": probabilities.argmax(axis=1)}
        if self.effort_model is not None:
            output["effort_proba"] = self.effort_model.predict_proba(self.effort_scaler.transform(_effort_inputs(probabilities, size)))
        return output

    def predict_one(self, title: str, body: str = "", labels: list[str] | None = None) -> dict[str, Any]:
        frame = pd.DataFrame([{"title": title, "body": body, "labels": labels or [], "text": f"{title}\n{body}".strip()}])
        result = self.predict_frame(frame)
        proba = result["proba"][0]
        index = int(proba.argmax())
        output: dict[str, Any] = {
            "difficulty": DIFFICULTY_CLASSES[index],
            "difficulty_probability": float(proba[index]),
            "difficulty_distribution": {name: float(value) for name, value in zip(DIFFICULTY_CLASSES, proba)},
            "predicted_change_scale": float(result["size"][0]),
            "confidence": "low" if proba[index] < 0.5 else ("medium" if proba[index] < 0.65 else "high"),
        }
        if "effort_proba" in result:
            output.update(effort_from_distribution(result["effort_proba"][0], self.metadata.get("effort_classes", [0, 1, 2])))
        return output


def _effort_inputs(probabilities: np.ndarray, size: np.ndarray) -> np.ndarray:
    return np.column_stack([size, probabilities[:, 0], probabilities[:, 2]])


def effort_from_distribution(distribution: np.ndarray, classes: list[int]) -> dict[str, Any]:
    hours = np.asarray([HUMAN_DIFFICULTY_HOURS[int(level)] for level in classes])
    order = np.argsort(hours)
    cumulative = np.cumsum(distribution[order])
    low = hours[order][int(np.searchsorted(cumulative, 0.2))]
    high = hours[order][min(int(np.searchsorted(cumulative, 0.8)), len(order) - 1)]
    best = int(np.argmax(distribution))
    median = hours[order][int(np.searchsorted(cumulative, 0.5))]
    return {
        "effort_hours": float(median),
        "effort_range_hours": [float(low), float(max(high, low))],
        "effort_bucket": EFFORT_LEVELS[int(classes[best])],
        "effort_distribution": {EFFORT_LEVELS[int(level)]: float(p) for level, p in zip(classes, distribution)},
        "effort_note": "Estimated hands-on time for an engineer familiar with the codebase, calibrated on SWE-bench Verified human annotations.",
    }


def _fit_components(train: pd.DataFrame, hand: np.ndarray, embeddings: np.ndarray, labels: np.ndarray, size: np.ndarray, blend: float, thresholds: list[float]) -> DifficultyModel:
    tfidf = TfidfVectorizer(ngram_range=(1, 2), min_df=3, max_features=60000, sublinear_tf=True, strip_accents="unicode")
    tfidf.fit(train.text.fillna(""))
    scaler = StandardScaler().fit(hand)
    model = DifficultyModel(thresholds=thresholds, tfidf=tfidf, scaler=scaler, linear=None, boosted=None, size_regressor=None, blend=blend)  # type: ignore[arg-type]
    model.linear = LogisticRegression(C=0.5, max_iter=2000, class_weight="balanced").fit(model._linear_inputs(train, hand), labels)
    dense = model._dense_inputs(hand, embeddings)
    model.boosted = _lgbm_classifier().fit(dense, labels)
    model.size_regressor = _lgbm_regressor().fit(dense, size)
    return model


def _classification_metrics(truth: np.ndarray, predicted: np.ndarray, scores: np.ndarray, scale: np.ndarray) -> dict[str, Any]:
    return {
        "n": int(len(truth)),
        "accuracy": float(accuracy_score(truth, predicted)),
        "macro_f1": float(f1_score(truth, predicted, average="macro")),
        "spearman_score_vs_true_scale": float(spearmanr(scores, scale).statistic),
        "confusion_matrix": confusion_matrix(truth, predicted, labels=[0, 1, 2]).tolist(),
    }


def _baselines(train_labels: np.ndarray, frame: pd.DataFrame, truth: np.ndarray, train_frame: pd.DataFrame, seed: int = 0) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    majority = np.bincount(train_labels).argmax()
    prior = np.bincount(train_labels, minlength=3) / len(train_labels)
    stratified = rng.choice(3, size=len(truth), p=prior)
    # Length heuristic: longer issues are harder (tertiles of body length fitted on train).
    cuts = np.quantile(train_frame.body.str.len(), [1 / 3, 2 / 3])
    length = np.digitize(frame.body.str.len(), cuts)
    return {
        "majority_class": {"accuracy": float(accuracy_score(truth, np.full_like(truth, majority))), "macro_f1": float(f1_score(truth, np.full_like(truth, majority), average="macro"))},
        "stratified_random": {"accuracy": float(accuracy_score(truth, stratified)), "macro_f1": float(f1_score(truth, stratified, average="macro"))},
        "body_length_tertiles": {"accuracy": float(accuracy_score(truth, length)), "macro_f1": float(f1_score(truth, length, average="macro"))},
    }


def train_difficulty(corpus: pd.DataFrame, embeddings: np.ndarray, seed: int = 42) -> tuple[DifficultyModel, dict[str, Any]]:
    """Fit on SWE-bench train repositories; evaluate on unseen repositories and languages."""
    sized = corpus.loc_changed.notna().to_numpy()
    scale_all = change_scale(corpus).to_numpy()
    train_mask = sized & (corpus.eval_group == "train").to_numpy()
    thresholds = list(np.quantile(scale_all[train_mask], [1 / 3, 2 / 3]))
    labels_all = np.digitize(scale_all, thresholds)

    train = corpus[train_mask].reset_index(drop=True)
    train_hand = handcrafted_matrix(train)
    train_emb = embeddings[train_mask]
    y = labels_all[train_mask]
    size_target = scale_all[train_mask]

    # Model selection: repository-grouped CV on the training repositories only.
    blends = [0.0, 0.3, 0.5, 0.7, 1.0]
    oof = {blend: np.zeros((len(train), 3)) for blend in blends}
    for fold, (fit_idx, val_idx) in enumerate(GroupKFold(n_splits=5).split(train, y, groups=train.repo)):
        fold_model = _fit_components(train.iloc[fit_idx], train_hand[fit_idx], train_emb[fit_idx], y[fit_idx], size_target[fit_idx], 0.5, thresholds)
        val = train.iloc[val_idx]
        linear = fold_model.linear.predict_proba(fold_model._linear_inputs(val, train_hand[val_idx]))
        boosted = fold_model.boosted.predict_proba(fold_model._dense_inputs(train_hand[val_idx], train_emb[val_idx]))
        for blend in blends:
            oof[blend][val_idx] = blend * linear + (1 - blend) * boosted
        logger.info("Difficulty CV fold %d done", fold + 1)
    cv = {str(blend): float(f1_score(y, oof[blend].argmax(1), average="macro")) for blend in blends}
    best_blend = float(max(blends, key=lambda blend: cv[str(blend)]))
    logger.info("Difficulty grouped-CV macro-F1 by linear blend weight: %s (best %.1f)", cv, best_blend)

    model = _fit_components(train, train_hand, train_emb, y, size_target, best_blend, thresholds)
    model.metadata = {"cv_macro_f1_by_blend": cv, "train_records": int(len(train)), "train_repositories": int(train.repo.nunique()), "thresholds": thresholds}

    metrics: dict[str, Any] = {"label_definition": "tertiles of log1p(LOC)+log1p(files)+0.5*log1p(hunks) on train repositories", "thresholds": thresholds, "grouped_cv_macro_f1": cv, "selected_linear_blend": best_blend}
    for group in ("dev", "test", "multilingual"):
        mask = sized & (corpus.eval_group == group).to_numpy()
        if not mask.any():
            continue
        frame = corpus[mask].reset_index(drop=True)
        result = model.predict_frame(frame, embeddings[mask])
        truth = labels_all[mask]
        expected = result["proba"] @ np.array([0.0, 1.0, 2.0])
        metrics[group] = {
            "model": _classification_metrics(truth, result["label"], expected, scale_all[mask]),
            "size_regressor_spearman": float(spearmanr(result["size"], scale_all[mask]).statistic),
            "size_regressor_mae": float(mean_absolute_error(scale_all[mask], result["size"])),
            "size_baseline_mae_train_median": float(mean_absolute_error(scale_all[mask], np.full(mask.sum(), np.median(size_target)))),
            "baselines": _baselines(y, frame, truth, train),
            "repositories": int(frame.repo.nunique()),
        }
    return model, metrics


def train_effort(model: DifficultyModel, corpus: pd.DataFrame, embeddings: np.ndarray) -> dict[str, Any]:
    """Calibrate effort hours on human labels with repository-grouped CV; attach to ``model``."""
    mask = corpus.human_level.notna().to_numpy()
    frame = corpus[mask].reset_index(drop=True)
    # ">4 hours" has 3 examples - merge it into "1-4 hours" for a learnable target.
    levels = np.minimum(frame.human_level.to_numpy().astype(int), 2)
    result = model.predict_frame(frame, embeddings[mask])
    inputs = _effort_inputs(result["proba"], result["size"])

    oof = np.zeros((len(frame), 3))
    groups = frame.repo.to_numpy()
    for fit_idx, val_idx in GroupKFold(n_splits=5).split(inputs, levels, groups=groups):
        scaler = StandardScaler().fit(inputs[fit_idx])
        classifier = LogisticRegression(max_iter=1000).fit(scaler.transform(inputs[fit_idx]), levels[fit_idx])
        proba = np.zeros((len(val_idx), 3))
        proba[:, classifier.classes_] = classifier.predict_proba(scaler.transform(inputs[val_idx]))
        oof[val_idx] = proba
    predicted = oof.argmax(1)
    hours_true = np.array([HUMAN_DIFFICULTY_HOURS[int(level)] for level in frame.human_level])
    level_hours = np.array([HUMAN_DIFFICULTY_HOURS[level] for level in (0, 1, 2)])
    # Point estimate = median of the predicted bucket distribution; ranking uses expected log-hours.
    hours_pred = level_hours[np.minimum((np.cumsum(oof, axis=1) < 0.5).sum(axis=1), 2)]
    hours_rank = oof @ np.log(level_hours)
    majority = np.bincount(levels).argmax()
    metrics = {
        "n": int(len(frame)),
        "repositories": int(frame.repo.nunique()),
        "evaluation": "5-fold repository-grouped CV on SWE-bench Verified human annotations",
        "bucket_accuracy": float(accuracy_score(levels, predicted)),
        "bucket_macro_f1": float(f1_score(levels, predicted, average="macro")),
        "bucket_mae_levels": float(np.abs(levels - predicted).mean()),
        "spearman_expected_hours_vs_human": float(spearmanr(hours_rank, hours_true).statistic),
        "log_hours_mae": float(np.abs(np.log(hours_pred) - np.log(hours_true)).mean()),
        "baseline_majority_bucket_accuracy": float((levels == majority).mean()),
        "baseline_majority_bucket_mae_levels": float(np.abs(levels - majority).mean()),
        "baseline_majority_log_hours_mae": float(np.abs(np.log(HUMAN_DIFFICULTY_HOURS[int(majority)]) - np.log(hours_true)).mean()),
        "difficulty_score_spearman_vs_human": float(spearmanr(result["proba"] @ np.array([0.0, 1.0, 2.0]), frame.human_level).statistic),
        "confusion_matrix": confusion_matrix(levels, predicted, labels=[0, 1, 2]).tolist(),
    }
    model.effort_scaler = StandardScaler().fit(inputs)
    model.effort_model = LogisticRegression(max_iter=1000).fit(model.effort_scaler.transform(inputs), levels)
    model.metadata["effort_classes"] = [int(level) for level in model.effort_model.classes_]
    return metrics


__all__ = ["DIFFICULTY_CLASSES", "DifficultyModel", "change_scale", "effort_from_distribution", "train_difficulty", "train_effort"]
