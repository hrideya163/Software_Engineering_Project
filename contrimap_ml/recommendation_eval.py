"""Offline evaluation of contributor-issue recommendation on vercel/next.js.

Task: for an issue in the evaluation window, rank every active contributor
(>= 2 resolved issues before the window); success = the person who actually
resolved it ranks high.  Profiles use only contributions *before* the window,
issue files are the localizer's *predictions* (never the true changed files).
Component weights are chosen on a validation window (60-80% of the timeline)
and reported on the test window (last 20%).
"""

from __future__ import annotations

import itertools
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from .localization import PathFeatureCache, RepoHistory, candidate_features, prefilter
from .recommendation import ContributorProfile, score_contributor_for_issue
from .skills import extract_issue_skills
from .textfeat import embed

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent
COMPONENTS = ["skill", "files", "semantic", "success", "difficulty_fit"]


def _metrics(ranks: list[int | None]) -> dict[str, float]:
    n = max(len(ranks), 1)
    return {
        "acc@1": sum(1 for r in ranks if r and r <= 1) / n,
        "acc@5": sum(1 for r in ranks if r and r <= 5) / n,
        "acc@10": sum(1 for r in ranks if r and r <= 10) / n,
        "mrr": sum(1.0 / r for r in ranks if r) / n,
        "n": len(ranks),
    }


def _window(frame: pd.DataFrame, start: float, end: float) -> pd.DataFrame:
    times = frame.created_at.rank(method="first", pct=True)
    return frame[(times > start) & (times <= end)]


def _prepare(corpus: pd.DataFrame, embeddings: np.ndarray, artifacts: Path, profile_end: float, eval_start: float, eval_end: float) -> dict[str, Any]:
    nextjs_mask = (corpus.source == "nextjs").to_numpy() & corpus.author.notna().to_numpy()
    frame = corpus[nextjs_mask].copy()
    frame["emb_row"] = np.flatnonzero(nextjs_mask)
    frame = frame.sort_values("created_at")
    history_frame = _window(frame, 0.0, profile_end)
    evaluation = _window(frame, eval_start, eval_end)

    by_author: dict[str, list[int]] = defaultdict(list)
    for position, row in enumerate(history_frame.itertuples()):
        by_author[row.author].append(position)
    profiles: dict[str, ContributorProfile] = {}
    for author, positions in by_author.items():
        if len(positions) < 2 or author.endswith("[bot]"):
            continue
        rows = history_frame.iloc[positions]
        contributions = [{"files": list(r.target_files) + list(r.test_files), "title": r.title, "created_at": str(r.created_at)} for r in rows.itertuples()]
        profiles[author] = ContributorProfile.from_contributions(author, contributions, embeddings[rows.emb_row.to_numpy()])
    evaluation = evaluation[evaluation.author.isin(profiles)]

    localizer = joblib.load(artifacts / "localization.joblib")
    difficulty = joblib.load(artifacts / "difficulty.joblib")
    success = joblib.load(artifacts / "success.joblib") if (artifacts / "success.joblib").exists() else None
    history = RepoHistory.build((history_frame.created_at.astype("int64") // 10**9).tolist(), embeddings[history_frame.emb_row.to_numpy()], [list(t) for t in history_frame.target_files])
    candidates = sorted({path for files in history_frame.target_files for path in files})
    cache = PathFeatureCache(embed)
    difficulty_out = difficulty.predict_frame(evaluation.reset_index(drop=True), embeddings[evaluation.emb_row.to_numpy()])

    raw_prs = json.loads((ROOT / "data" / "raw" / "pull_requests.json").read_text(encoding="utf-8"))
    pr_history: dict[str, list[tuple[str, bool]]] = defaultdict(list)
    for pr in sorted(raw_prs, key=lambda item: item["created_at"]):
        pr_history[(pr.get("user") or {}).get("login") or ""].append((pr.get("closed_at") or pr["created_at"], bool(pr.get("merged_at"))))

    issues = []
    for position, row in enumerate(evaluation.itertuples()):
        query = embeddings[row.emb_row]
        features = candidate_features(row.text, query, candidates, cache, history.stats(query, None), "JavaScript")
        kept = prefilter(features)
        scores = localizer.score(features[kept])
        order = np.argsort(-scores)[:5]
        weights = np.exp(scores[order] - scores[order].max())
        predicted = [{"path": candidates[kept[i]], "relative_confidence": float(w / weights.sum())} for i, w in zip(order, weights)]
        distribution = dict(zip(("Easy", "Medium", "Hard"), difficulty_out["proba"][position].tolist()))
        issue_skills = extract_issue_skills(row.title, row.body, list(row.labels), [item["path"] for item in predicted])
        success_scores = {}
        if success is not None:
            at = row.created_at.isoformat()
            for author in profiles:
                prior = [merged for closed, merged in pr_history.get(author, []) if closed < at]
                success_scores[author] = success.predict_attempt(len(prior), sum(prior), row.title, row.body, login=author)
        issues.append({"author": row.author, "embedding": query, "files": predicted, "skills": issue_skills, "difficulty": distribution, "success": success_scores})
    popularity = {author: profile.contributions for author, profile in profiles.items()}
    return {"profiles": profiles, "issues": issues, "popularity": popularity}


def _component_table(prepared: dict[str, Any]) -> list[dict[str, Any]]:
    table = []
    for issue in prepared["issues"]:
        rows = {}
        for author, profile in prepared["profiles"].items():
            rows[author] = score_contributor_for_issue(profile, issue["skills"], issue["files"], issue["embedding"], issue["difficulty"], issue["success"].get(author))["components"]
        table.append({"author": issue["author"], "components": rows})
    return table


def _rank_with(table: list[dict[str, Any]], weights: dict[str, float], popularity: dict[str, int]) -> list[int | None]:
    ranks = []
    for issue in table:
        # Popularity as a tiny tie-breaker so zero-score ties are not ordered arbitrarily.
        scored = {author: sum(weights.get(name, 0.0) * value for name, value in components.items()) + 1e-6 * popularity[author] for author, components in issue["components"].items()}
        ordered = sorted(scored, key=lambda author: -scored[author])
        ranks.append(ordered.index(issue["author"]) + 1 if issue["author"] in scored else None)
    return ranks


def evaluate_recommendation(corpus: pd.DataFrame, embeddings: np.ndarray, artifacts: Path = ROOT / "artifacts" / "v2", seed: int = 0) -> dict[str, Any]:
    validation = _prepare(corpus, embeddings, artifacts, 0.6, 0.6, 0.8)
    validation_table = _component_table(validation)
    grid = [0.0, 0.5, 1.0]
    best_weights, best_mrr = None, -1.0
    for values in itertools.product(grid, repeat=len(COMPONENTS)):
        if not any(values):
            continue
        weights = dict(zip(COMPONENTS, values))
        mrr = _metrics(_rank_with(validation_table, weights, validation["popularity"]))["mrr"]
        if mrr > best_mrr:
            best_weights, best_mrr = weights, mrr
    logger.info("Recommendation weights chosen on validation: %s (MRR %.3f)", best_weights, best_mrr)

    test = _prepare(corpus, embeddings, artifacts, 0.8, 0.8, 1.0)
    table = _component_table(test)
    rng = np.random.default_rng(seed)
    popularity_ranks = []
    random_ranks = []
    for issue in table:
        ordered = sorted(test["popularity"], key=lambda author: -test["popularity"][author])
        popularity_ranks.append(ordered.index(issue["author"]) + 1)
        shuffled = list(rng.permutation(list(test["popularity"])))
        random_ranks.append(shuffled.index(issue["author"]) + 1)
    report = {
        "task": "rank active contributors for each next.js issue; hit = the actual resolver",
        "candidate_pool": len(test["profiles"]),
        "selected_weights": best_weights,
        "validation_mrr": best_mrr,
        "test": {"combined": _metrics(_rank_with(table, best_weights, test["popularity"]))},
        "caveat": "Single repository (next.js 2016-2021); pool = contributors with >= 2 resolved issues before the window.",
    }
    for name in COMPONENTS:
        report["test"][f"only_{name}"] = _metrics(_rank_with(table, {name: 1.0}, test["popularity"]))
    report["test"]["baseline_popularity"] = _metrics(popularity_ranks)
    report["test"]["baseline_random"] = _metrics(random_ranks)
    return report


__all__ = ["evaluate_recommendation"]
