"""Contribution success prediction: P(a contributor's pull request gets merged).

Trained on 10,000 closed vercel/next.js pull requests (7,909 merged).  Features
are computed point-in-time from the author's *earlier* pull requests in the
repository plus the intent of the contribution (title/body), so the same model
scores "contributor X attempts issue Y" before any PR exists.

Deliberately excluded: ``author_association`` (GitHub reports the *current*
role, so a first-timer who later joined the org would leak), review counts,
labels added during review, and anything after PR creation.
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from sklearn.metrics import accuracy_score, average_precision_score, brier_score_loss, roc_auc_score

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent

SUCCESS_FEATURES = [
    "prior_prs", "prior_merged", "prior_merge_rate", "is_first_pr", "days_since_first_pr", "days_since_last_pr",
    "title_chars", "body_chars", "links_issue", "kind_docs", "kind_fix", "kind_feature", "kind_test",
    "kind_chore", "kind_example", "kind_revert", "is_bot",
]
_PRIOR_ALPHA, _PRIOR_BETA = 3.0, 1.0  # Beta prior for the author's merge rate (~global 0.75 merge rate)


def _parse(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


def intent_features(title: str, body: str = "") -> dict[str, float]:
    lowered = (title or "").lower()
    return {
        "title_chars": float(len(title or "")),
        "body_chars": float(math.log1p(len(body or ""))),
        "links_issue": float(bool(re.search(r"\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\b[:\s]+#\d+", body or "", re.I))),
        "kind_docs": float(bool(re.search(r"\b(docs?|documentation|readme|typo|comment)\b", lowered))),
        "kind_fix": float(bool(re.search(r"\b(fix|bug|error|crash|issue|broken)\b", lowered))),
        "kind_feature": float(bool(re.search(r"\b(add|feat|feature|support|implement|new)\b", lowered))),
        "kind_test": float(bool(re.search(r"\btests?\b", lowered))),
        "kind_chore": float(bool(re.search(r"\b(chore|bump|upgrade|update|deps?|dependenc)", lowered))),
        "kind_example": float("example" in lowered),
        "kind_revert": float(lowered.startswith("revert")),
    }


def history_features(prior: list[tuple[datetime, bool]], at: datetime, login: str = "") -> dict[str, float]:
    merged = sum(1 for _, was_merged in prior if was_merged)
    return {
        "prior_prs": float(math.log1p(len(prior))),
        "prior_merged": float(math.log1p(merged)),
        "prior_merge_rate": float((merged + _PRIOR_ALPHA) / (len(prior) + _PRIOR_ALPHA + _PRIOR_BETA)),
        "is_first_pr": float(not prior),
        "days_since_first_pr": float(math.log1p((at - prior[0][0]).total_seconds() / 86400)) if prior else 0.0,
        "days_since_last_pr": float(math.log1p((at - prior[-1][0]).total_seconds() / 86400)) if prior else 0.0,
        "is_bot": float(login.endswith("[bot]") or login.endswith("-bot")),
    }


@dataclass
class SuccessModel:
    classifier: Any
    metadata: dict[str, Any] = field(default_factory=dict)

    def predict(self, feature_rows: list[Mapping[str, float]]) -> np.ndarray:
        if not feature_rows:
            return np.zeros(0)
        matrix = np.asarray([[row.get(name, 0.0) for name in SUCCESS_FEATURES] for row in feature_rows], dtype="float32")
        return self.classifier.predict_proba(matrix)[:, 1]

    def predict_attempt(self, prior_prs: int, prior_merged: int, title: str, body: str = "", days_since_first: float | None = None, days_since_last: float | None = None, login: str = "") -> float:
        """Score a hypothetical contribution by a contributor with the given history."""
        row = intent_features(title, body)
        rate = (prior_merged + _PRIOR_ALPHA) / (prior_prs + _PRIOR_ALPHA + _PRIOR_BETA)
        row.update({
            "prior_prs": math.log1p(prior_prs), "prior_merged": math.log1p(prior_merged), "prior_merge_rate": rate,
            "is_first_pr": float(prior_prs == 0), "days_since_first_pr": math.log1p(days_since_first or 0.0),
            "days_since_last_pr": math.log1p(days_since_last or 0.0), "is_bot": float(login.endswith("[bot]")),
            # A recommendation links to the issue it resolves.
            "links_issue": 1.0,
        })
        return float(self.predict([row])[0])


def build_examples(pull_requests: list[dict[str, Any]]) -> tuple[list[dict[str, float]], np.ndarray, list[str]]:
    prs = sorted(pull_requests, key=lambda pr: pr["created_at"])
    history: defaultdict[str, list[tuple[datetime, bool]]] = defaultdict(list)
    rows, labels, times = [], [], []
    for pr in prs:
        login = (pr.get("user") or {}).get("login") or "ghost"
        created = _parse(pr["created_at"])
        # Only PRs *closed* before this one was opened have a known outcome at that time.
        known = [(when, merged) for when, merged, closed in history[login] if closed <= created]
        row = history_features(known, created, login)
        row.update(intent_features(pr.get("title") or "", pr.get("body") or ""))
        rows.append(row)
        labels.append(int(bool(pr.get("merged_at"))))
        times.append(pr["created_at"])
        history[login].append((created, bool(pr.get("merged_at")), _parse(pr.get("closed_at") or pr["created_at"])))
    return rows, np.asarray(labels), times


def train_success_model(path: Path = ROOT / "data" / "raw" / "pull_requests.json", seed: int = 42) -> tuple[SuccessModel, dict[str, Any]]:
    from lightgbm import LGBMClassifier
    from sklearn.calibration import CalibratedClassifierCV

    pull_requests = json.loads(path.read_text(encoding="utf-8"))
    rows, y, times = build_examples(pull_requests)
    x = np.asarray([[row[name] for name in SUCCESS_FEATURES] for row in rows], dtype="float32")
    cutoff = int(len(rows) * 0.8)
    base = LGBMClassifier(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=40, subsample=0.8, subsample_freq=1, verbosity=-1, random_state=seed)
    # Calibrate on the tail of the training period (time-ordered, no shuffling).
    classifier = CalibratedClassifierCV(base, method="isotonic", cv=[(np.arange(0, int(cutoff * 0.8)), np.arange(int(cutoff * 0.8), cutoff))])
    classifier.fit(x[:cutoff], y[:cutoff])
    scores = classifier.predict_proba(x[cutoff:])[:, 1]
    y_test = y[cutoff:]
    column = {name: index for index, name in enumerate(SUCCESS_FEATURES)}
    prior_rate = x[cutoff:, column["prior_merge_rate"]]
    majority = float(y[:cutoff].mean())
    metrics = {
        "dataset": "vercel/next.js closed pull requests; temporal 80/20 split",
        "train": int(cutoff), "test": int(len(y_test)), "test_merge_rate": float(y_test.mean()),
        "test_period": [times[cutoff], times[-1]],
        "roc_auc": float(roc_auc_score(y_test, scores)),
        "average_precision": float(average_precision_score(y_test, scores)),
        "brier": float(brier_score_loss(y_test, scores)),
        "accuracy_at_0.5": float(accuracy_score(y_test, scores >= 0.5)),
        "baseline_majority_accuracy": float(accuracy_score(y_test, np.full_like(y_test, int(majority >= 0.5)))),
        "baseline_constant_brier": float(brier_score_loss(y_test, np.full(len(y_test), majority))),
        "baseline_author_merge_rate_auc": float(roc_auc_score(y_test, prior_rate)),
        "unmerged_recall_at_0.5": float(((scores < 0.5) & (y_test == 0)).sum() / max((y_test == 0).sum(), 1)),
        "caveat": "Single repository; generalisation to other repositories is not measured.",
    }
    logger.info("Success model: AUC %.3f (author-rate baseline %.3f)", metrics["roc_auc"], metrics["baseline_author_merge_rate_auc"])
    return SuccessModel(classifier=classifier, metadata=metrics), metrics


__all__ = ["SUCCESS_FEATURES", "SuccessModel", "build_examples", "history_features", "intent_features", "train_success_model"]


class AuthorRateRule:
    """Fallback scorer: the author's smoothed prior merge rate (sklearn-style ``predict_proba``)."""

    def predict_proba(self, matrix: np.ndarray) -> np.ndarray:
        rate = matrix[:, SUCCESS_FEATURES.index("prior_merge_rate")]
        return np.column_stack([1 - rate, rate])


def train_success_multirepo(pull_requests_by_repo: dict[str, list[dict[str, Any]]], seed: int = 42) -> tuple[SuccessModel, dict[str, Any]]:
    """Choose between GBM, logistic regression and the author-rate rule by leave-one-repository-out AUC.

    Every candidate is scored only on repositories it was not trained on; the winner is refitted on all.
    """
    from lightgbm import LGBMClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    data = {}
    for repo, prs in pull_requests_by_repo.items():
        rows, y, _ = build_examples(prs)
        if len(set(y.tolist())) == 2:
            data[repo] = (np.asarray([[row[name] for name in SUCCESS_FEATURES] for row in rows], dtype="float32"), y)
    candidates = {
        "gbm": lambda: LGBMClassifier(n_estimators=200, learning_rate=0.03, num_leaves=15, min_child_samples=40, subsample=0.8, subsample_freq=1, verbosity=-1, random_state=seed),
        "logistic": lambda: make_pipeline(StandardScaler(), LogisticRegression(C=0.3, max_iter=2000)),
        "author_rate_rule": lambda: AuthorRateRule(),
    }
    results: dict[str, dict[str, float]] = {name: {} for name in candidates}
    for held_out in data:
        x_train = np.vstack([data[r][0] for r in data if r != held_out])
        y_train = np.concatenate([data[r][1] for r in data if r != held_out])
        x_test, y_test = data[held_out]
        for name, factory in candidates.items():
            model = factory()
            if hasattr(model, "fit"):
                model.fit(x_train, y_train)
            results[name][held_out] = float(roc_auc_score(y_test, model.predict_proba(x_test)[:, 1]))
    mean = {name: float(np.mean(list(scores.values()))) for name, scores in results.items()}
    best = max(mean, key=mean.get)
    final = candidates[best]()
    if hasattr(final, "fit"):
        final.fit(np.vstack([data[r][0] for r in data]), np.concatenate([data[r][1] for r in data]))
    metrics = {
        "evaluation": "leave-one-repository-out ROC-AUC (each score on a repository unseen in training)",
        "repositories": {repo: {"n": int(len(y)), "merge_rate": float(y.mean())} for repo, (_, y) in data.items()},
        "mean_auc": mean,
        "per_repository_auc": results,
        "selected": best,
        "caveat": "Ingested repositories use the 600 most recent closed PRs since 2024 (merged and unmerged together), so author histories only cover that window.",
    }
    logger.info("Multi-repo success model: %s (mean LORO AUC %s)", best, {k: round(v, 3) for k, v in mean.items()})
    return SuccessModel(classifier=final, metadata=metrics), metrics
