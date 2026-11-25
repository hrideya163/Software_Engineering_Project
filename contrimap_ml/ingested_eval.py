"""Out-of-distribution evaluation on freshly ingested repositories (``data/ingested``).

Data from ``python -m contrimap_ml.ingest`` (2023+) was never used for training,
so this measures how the trained models transfer to new repositories and years:

* localization - per repository, the last 20% of issues by time; candidates are
  the repository's current file tree, history features use only earlier issues;
* success prediction - see ``success.train_success_multirepo`` (uniform PR samples).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from .ingest import OUTPUT, load_ingested
from .localization import PathFeatureCache, is_changelog, RepoHistory, baseline_scores, candidate_features, localization_candidates, prefilter, ranking_metrics
from .repo_trees import fetch_tree
from .success import SUCCESS_FEATURES, build_examples
from .textfeat import embed

logger = logging.getLogger(__name__)


def evaluate_localization(frame: pd.DataFrame, artifacts: Path, min_issues: int = 30, seed: int = 0) -> dict[str, Any]:
    model = joblib.load(artifacts / "localization.joblib")
    languages = json.loads((artifacts / "repo_languages.json").read_text(encoding="utf-8")) if (artifacts / "repo_languages.json").exists() else {}
    cache = PathFeatureCache(embed)
    rng = np.random.default_rng(seed)
    report: dict[str, Any] = {"per_repository": {}}
    ranked_all, targets_all, candidates_all = [], [], []
    baselines_all: dict[str, list[list[str]]] = {}
    for repo, group in frame.groupby("repo"):
        if len(group) < min_issues:
            continue
        group = group.sort_values("created_at").reset_index(drop=True)
        times = (group.created_at.astype("int64") // 10**9).to_numpy(dtype="float64")
        embeddings = embed(group.text.fillna("").tolist())
        history = RepoHistory.build(times, embeddings, [list(files) for files in group.target_files])
        _, tree = fetch_tree(repo)
        candidates = localization_candidates(tree)
        cache.ensure(candidates)
        ranked, targets, candidate_sets = [], [], []
        for index in range(int(len(group) * 0.8), len(group)):
            target = {path for path in group.target_files.iloc[index] if not is_changelog(path)}
            if not target:
                continue  # changelog-only fixes are not localization targets
            stats = history.stats(embeddings[index], times[index])
            features = candidate_features(group.text.iloc[index], embeddings[index], candidates, cache, stats, languages.get(repo, group.language.iloc[index]))
            kept = prefilter(features)
            scores = model.score(features[kept])
            ranked.append([candidates[kept[i]] for i in np.argsort(-scores)[:10]])
            targets.append(target)
            candidate_sets.append(set(candidates))
            for name, values in baseline_scores(features, rng).items():
                baselines_all.setdefault(name, []).append([candidates[i] for i in np.argsort(-values, kind="stable")[:10]])
        report["per_repository"][repo] = {**ranking_metrics(ranked, targets, candidate_sets), "candidates": len(candidates)}
        ranked_all += ranked
        targets_all += targets
        candidates_all += candidate_sets
        logger.info("Ingested localization %s: acc@5 %.3f", repo, report["per_repository"][repo]["acc@5"])
    report["model"] = ranking_metrics(ranked_all, targets_all, candidates_all)
    for name, lists in baselines_all.items():
        report[f"baseline_{name}"] = ranking_metrics(lists, targets_all)
    report["note"] = "Candidates are each repository's current tree (files added or removed since the issue make this slightly pessimistic)."
    return report


def ingested_pull_requests(frame: pd.DataFrame, directory: Path = OUTPUT) -> dict[str, list[dict[str, Any]]]:
    """Merged (from issue-PR rows) and unmerged PRs per repository in the REST-like shape ``build_examples`` expects."""
    output: dict[str, list[dict[str, Any]]] = {}
    for repo, group in frame.groupby("repo"):
        merged = group.drop_duplicates("pr_number")
        prs = [{"user": {"login": row.author}, "created_at": str(row.pr_created_at), "closed_at": str(row.pr_merged_at), "merged_at": str(row.pr_merged_at), "title": row.title, "body": "Fixes #1"} for row in merged.itertuples()]
        unmerged_path = directory / f"{repo.replace('/', '__')}.unmerged.json"
        if unmerged_path.exists():
            prs += [{"user": {"login": item.get("author") or "ghost"}, "created_at": item["created_at"], "closed_at": item.get("closed_at") or item["created_at"], "merged_at": None, "title": item.get("title") or "", "body": "Fixes #1"} for item in json.loads(unmerged_path.read_text(encoding="utf-8"))]
        output[repo] = prs
    return output


def evaluate_success(frame: pd.DataFrame, artifacts: Path, directory: Path = OUTPUT) -> dict[str, Any]:
    model = joblib.load(artifacts / "success.joblib")
    report: dict[str, Any] = {"per_repository": {}}
    all_scores, all_labels, all_rates = [], [], []
    for repo, prs in ingested_pull_requests(frame, directory).items():
        rows, labels, _ = build_examples(prs)
        if len(set(labels.tolist())) < 2:
            continue
        scores = model.predict(rows)
        rates = np.asarray([row["prior_merge_rate"] for row in rows])
        report["per_repository"][repo] = {"n": len(rows), "merge_rate": float(labels.mean()), "roc_auc": float(roc_auc_score(labels, scores)), "baseline_author_rate_auc": float(roc_auc_score(labels, rates))}
        all_scores += scores.tolist()
        all_labels += labels.tolist()
        all_rates += rates.tolist()
    report["pooled"] = {"n": len(all_labels), "roc_auc": float(roc_auc_score(all_labels, all_scores)), "baseline_author_rate_auc": float(roc_auc_score(all_labels, all_rates))}
    report["caveat"] = "Merged and unmerged PRs are capped samples per repository, so author histories are incomplete; PR titles are used, issue-closing intent is assumed for all."
    return report


def evaluate_ingested(artifacts: Path) -> dict[str, Any]:
    frame = load_ingested()
    if frame.empty:
        return {"note": "No ingested data; run python -m contrimap_ml.ingest first."}
    return {
        "repositories": frame.repo.value_counts().to_dict(),
        "localization": evaluate_localization(frame, artifacts),
        # Success prediction is evaluated in train_v2's success_multirepo stage on uniform PR samples;
        # evaluate_success here mixes issue-linked samples from different windows and is kept for reference only.
    }


__all__ = ["evaluate_ingested", "evaluate_localization", "evaluate_success"]
