"""Issue ranking: which open issues are worth a contributor's time.

The ranking score combines independently estimated components, each in [0, 1]:

* ``actionability``  - learned P(issue gets resolved by a merged code change)
  rather than closed as a question/duplicate/stale (trained on 10k next.js
  issues, temporal split);
* ``approachability`` - from the difficulty model (P(Easy) + 0.5 P(Medium));
* ``clarity``        - reproduction steps, expected behaviour, code, moderate length;
* ``focus``          - the localizer found a concentrated, explicitly referenced fix site;
* ``availability``   - unassigned, no open linked PR, not locked;
* ``freshness``      - recently active (half-life 60 days);
* ``community``      - "good first issue"/"help wanted" labels, reactions.

Only actionability is learnable from available history; the weights of the
other components are explicit, documented defaults and can be overridden.
Personalised ranking (Phase 4) adds profile-dependent components on top.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.preprocessing import StandardScaler

from .textfeat import HANDCRAFTED_COLUMNS, handcrafted_features

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent

DEFAULT_WEIGHTS = {
    "actionability": 0.25,
    "approachability": 0.20,
    "clarity": 0.15,
    "focus": 0.10,
    "availability": 0.15,
    "freshness": 0.10,
    "community": 0.05,
}


def _labels(issue: Mapping[str, Any]) -> list[str]:
    return [str(label.get("name") if isinstance(label, Mapping) else label) for label in issue.get("labels") or []]


def _hand_matrix(issues: Sequence[Mapping[str, Any]]) -> np.ndarray:
    rows = [handcrafted_features(str(issue.get("title") or ""), str(issue.get("body") or ""), _labels(issue)) for issue in issues]
    return np.asarray([[row[column] for column in HANDCRAFTED_COLUMNS] for row in rows], dtype="float32")


@dataclass
class ActionabilityModel:
    tfidf: TfidfVectorizer
    scaler: StandardScaler
    classifier: LogisticRegression
    base_rate: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def _inputs(self, issues: Sequence[Mapping[str, Any]]):
        text = [f"{issue.get('title') or ''}\n{issue.get('body') or ''}" for issue in issues]
        return hstack([self.tfidf.transform(text), csr_matrix(self.scaler.transform(_hand_matrix(issues)))]).tocsr()

    def predict(self, issues: Sequence[Mapping[str, Any]]) -> np.ndarray:
        if not issues:
            return np.zeros(0)
        return self.classifier.predict_proba(self._inputs(issues))[:, 1]


def train_actionability(raw_issues_path: Path = ROOT / "data" / "raw" / "issues.json", corpus: pd.DataFrame | None = None) -> tuple[ActionabilityModel, dict[str, Any]]:
    """Positives: issues resolved by a merged PR with a closing keyword (cleaned corpus)."""
    from .corpus import load_nextjs

    issues = [issue for issue in json.loads(raw_issues_path.read_text(encoding="utf-8")) if "pull_request" not in issue]
    resolved = set()
    nextjs = corpus[corpus.source == "nextjs"] if corpus is not None else load_nextjs()
    resolved = {int(uid.split(":")[1]) for uid in nextjs.uid}
    issues.sort(key=lambda issue: issue["created_at"])
    y = np.asarray([issue["number"] in resolved for issue in issues], dtype=int)
    cutoff = int(len(issues) * 0.8)
    train, test = issues[:cutoff], issues[cutoff:]
    tfidf = TfidfVectorizer(ngram_range=(1, 2), min_df=3, max_features=40000, sublinear_tf=True)
    tfidf.fit([f"{issue['title']}\n{issue.get('body') or ''}" for issue in train])
    scaler = StandardScaler().fit(_hand_matrix(train))
    model = ActionabilityModel(tfidf=tfidf, scaler=scaler, classifier=None, base_rate=float(y[:cutoff].mean()))  # type: ignore[arg-type]
    model.classifier = LogisticRegression(C=0.5, max_iter=2000, class_weight="balanced").fit(model._inputs(train), y[:cutoff])
    scores = model.predict(test)
    y_test = y[cutoff:]
    hand_test = _hand_matrix(test)
    column = {name: index for index, name in enumerate(HANDCRAFTED_COLUMNS)}
    heuristic = hand_test[:, column["title_bug"]] + hand_test[:, column["has_repro"]] + hand_test[:, column["label_bug"]] - hand_test[:, column["title_is_question"]]
    metrics = {
        "dataset": "vercel/next.js closed issues 2016-2021; positive = resolved by merged PR with closing keyword",
        "train": int(cutoff), "test": int(len(test)), "test_positive_rate": float(y_test.mean()),
        "roc_auc": float(roc_auc_score(y_test, scores)),
        "average_precision": float(average_precision_score(y_test, scores)),
        "precision_at_50": float(y_test[np.argsort(-scores)[:50]].mean()),
        "baseline_random_ap": float(y_test.mean()),
        "baseline_heuristic_auc": float(roc_auc_score(y_test, heuristic)),
        "baseline_heuristic_ap": float(average_precision_score(y_test, heuristic)),
        "baseline_body_length_auc": float(roc_auc_score(y_test, [len(issue.get("body") or "") for issue in test])),
        "caveat": "Single repository; labels are current GitHub labels (some may have been added during triage).",
    }
    model.metadata = metrics
    return model, metrics


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------
def _age_days(timestamp: str | None, now: datetime) -> float | None:
    if not timestamp:
        return None
    try:
        return max(0.0, (now - datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))).total_seconds() / 86400)
    except ValueError:
        return None


def clarity_score(issue: Mapping[str, Any]) -> float:
    features = handcrafted_features(str(issue.get("title") or ""), str(issue.get("body") or ""), _labels(issue))
    length = len(str(issue.get("body") or ""))
    length_score = 1.0 - abs(math.log1p(length) - math.log(1200)) / math.log(1200) if length else 0.0
    return float(np.clip(0.35 * max(length_score, 0) + 0.2 * features["has_repro"] + 0.15 * features["has_expected"] + 0.15 * min(features["code_blocks"], 1) + 0.15 * min(features["path_mentions"] + features["inline_code"], 1), 0, 1))


def availability_score(issue: Mapping[str, Any]) -> float:
    score = 1.0
    if issue.get("assignees") or issue.get("assignee"):
        score -= 0.6
    if issue.get("linked_pull_requests") or issue.get("has_open_pr"):
        score -= 0.5
    if issue.get("locked"):
        score -= 0.5
    return float(max(score, 0.0))


def freshness_score(issue: Mapping[str, Any], now: datetime | None = None) -> float:
    age = _age_days(issue.get("updated_at") or issue.get("created_at"), now or datetime.now(timezone.utc))
    return 0.5 if age is None else float(0.5 ** (age / 60.0))


def community_score(issue: Mapping[str, Any]) -> float:
    labels = " ".join(_labels(issue)).lower()
    score = 0.5 * bool(re.search(r"good.first|beginner|starter|easy", labels)) + 0.3 * bool(re.search(r"help.wanted|contributions? welcome|up for grabs", labels))
    reactions = issue.get("reactions")
    total = reactions.get("total_count", 0) if isinstance(reactions, Mapping) else int(reactions or 0)
    score += 0.2 * min(math.log1p(total) / math.log(20), 1.0)
    return float(min(score, 1.0))


def focus_score(analysis: Mapping[str, Any] | None) -> float:
    files = (analysis or {}).get("files") or []
    if not files:
        return 0.3
    top = files[0]
    mentioned = 0.4 if "mentioned in issue" in (top.get("signals") or []) else 0.0
    return float(min(1.0, 0.6 * float(top.get("relative_confidence") or 0) + mentioned + 0.2))


def rank_issues(
    issues: Sequence[Mapping[str, Any]],
    analyses: Sequence[Mapping[str, Any]],
    actionability: Sequence[float] | None = None,
    weights: Mapping[str, float] | None = None,
    extra_components: Sequence[Mapping[str, float]] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Score and sort issues; returns each issue with its score and component breakdown."""
    weights = dict(DEFAULT_WEIGHTS if weights is None else weights)
    ranked = []
    for position, (issue, analysis) in enumerate(zip(issues, analyses)):
        distribution = (analysis or {}).get("difficulty_distribution") or {}
        components = {
            "actionability": float(actionability[position]) if actionability is not None else 0.5,
            "approachability": float(distribution.get("Easy", 0.33) + 0.5 * distribution.get("Medium", 0.33)),
            "clarity": clarity_score(issue),
            "focus": focus_score(analysis),
            "availability": availability_score(issue),
            "freshness": freshness_score(issue, now),
            "community": community_score(issue),
        }
        if extra_components is not None:
            components.update(extra_components[position])
        total_weight = sum(weights.get(name, 0.0) for name in components) or 1.0
        score = sum(weights.get(name, 0.0) * value for name, value in components.items()) / total_weight
        ranked.append({"issue": dict(issue), "score": float(score), "components": components})
    ranked.sort(key=lambda item: -item["score"])
    for rank, item in enumerate(ranked, 1):
        item["rank"] = rank
    return ranked


__all__ = ["ActionabilityModel", "DEFAULT_WEIGHTS", "availability_score", "clarity_score", "community_score", "focus_score", "freshness_score", "rank_issues", "train_actionability"]
