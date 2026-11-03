"""End-to-end training and evaluation for the v2 ContriMap models.

    python -m contrimap_ml.train_v2 [--stages difficulty,localization,success] [--output artifacts/v2]

Evaluation protocol (no leakage):
* models are fitted on SWE-bench *train* repositories only; ``dev`` repositories
  are used for early stopping / model selection; ``test`` (SWE-bench Verified)
  and ``multilingual`` repositories are never seen in training;
* difficulty thresholds are fitted on training repositories;
* localization history features only use issues created before the query issue;
* next.js is evaluated on its last 20% of issues by time (history mode), the
  same split as the legacy model.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from .corpus import load_corpus
from .localization import (
    FEATURES,
    LocalizationModel,
    PathFeatureCache,
    RepoHistory,
    baseline_scores,
    candidate_features,
    localization_candidates,
    prefilter,
    ranking_metrics,
    train_ranker,
)
from .repo_trees import tree_cache_path
from .textfeat import embed

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "artifacts" / "v2"


def _epoch(series: pd.Series) -> np.ndarray:
    return (pd.to_datetime(series, utc=True).astype("int64") // 10**9).to_numpy(dtype="float64")


def repo_languages(corpus: pd.DataFrame) -> dict[str, str]:
    known = corpus[corpus.language != "Unknown"]
    return known.groupby("repo").language.agg(lambda values: values.value_counts().index[0]).to_dict()


def build_histories(corpus: pd.DataFrame, embeddings: np.ndarray) -> dict[str, RepoHistory]:
    times = _epoch(corpus.created_at)
    histories = {}
    for repo, index in corpus.groupby("repo").indices.items():
        histories[repo] = RepoHistory.build(times[index], embeddings[index], [list(corpus.target_files.iloc[i]) for i in index])
    return histories


def _load_tree(repo: str, sha: str | None) -> list[str] | None:
    if not sha:
        return None
    path = tree_cache_path(repo, sha)
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else None


def _history_candidates(history: RepoHistory, before: float) -> list[str]:
    seen: dict[str, None] = {}
    for index in range(history.prior_count(before)):
        for path in history.targets[index]:
            seen.setdefault(path, None)
    return list(seen)


def _instances(corpus: pd.DataFrame, mask: np.ndarray, mode: str, histories: dict[str, RepoHistory]) -> list[dict[str, Any]]:
    times = _epoch(corpus.created_at)
    rows = []
    for index in np.flatnonzero(mask):
        record = corpus.iloc[index]
        if mode == "tree":
            files = _load_tree(record.repo, record.base_commit)
            if files is None:
                continue
            candidates = localization_candidates(files)
        else:
            candidates = localization_candidates(_history_candidates(histories[record.repo], times[index]))
        if candidates:
            rows.append({"index": int(index), "candidates": candidates, "time": float(times[index])})
    return rows


def _featurize(instances: list[dict[str, Any]], corpus: pd.DataFrame, embeddings: np.ndarray, histories: dict[str, RepoHistory], cache: PathFeatureCache, languages: dict[str, str], with_baselines: bool = False, seed: int = 0) -> list[dict[str, Any]]:
    rng = np.random.default_rng(seed)
    cache.ensure({path for item in instances for path in item["candidates"]})
    started = time.time()
    output = []
    for count, item in enumerate(instances, 1):
        record = corpus.iloc[item["index"]]
        query = embeddings[item["index"]]
        stats = histories[record.repo].stats(query, item["time"])
        features = candidate_features(record.text, query, item["candidates"], cache, stats, languages.get(record.repo))
        targets = set(record.target_files)
        labels = np.fromiter((path in targets for path in item["candidates"]), dtype="float32", count=len(item["candidates"]))
        kept = prefilter(features)
        entry = {"index": item["index"], "candidates": item["candidates"], "kept": kept, "x": features[kept], "y": labels[kept], "targets": targets}
        if with_baselines:
            entry["baselines"] = {name: [item["candidates"][i] for i in np.argsort(-scores, kind="stable")[:10]] for name, scores in baseline_scores(features, rng).items()}
        output.append(entry)
        if count % 250 == 0:
            logger.info("Featurized %d/%d issues (%.0fs)", count, len(instances), time.time() - started)
    return output


def _evaluate(model: LocalizationModel, featurized: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = []
    for entry in featurized:
        scores = model.score(entry["x"])
        ranked.append([entry["candidates"][entry["kept"][i]] for i in np.argsort(-scores)[:10]])
    targets = [entry["targets"] for entry in featurized]
    candidate_sets = [set(entry["candidates"]) for entry in featurized]
    report = {"model": ranking_metrics(ranked, targets, candidate_sets)}
    report["prefilter_coverage"] = float(np.mean([entry["y"].any() for entry in featurized])) if featurized else 0.0
    report["median_candidates"] = float(np.median([len(entry["candidates"]) for entry in featurized])) if featurized else 0.0
    if featurized and "baselines" in featurized[0]:
        for name in featurized[0]["baselines"]:
            report[f"baseline_{name}"] = ranking_metrics([entry["baselines"][name] for entry in featurized], targets)
    return report


def train_localization(corpus: pd.DataFrame, embeddings: np.ndarray) -> tuple[LocalizationModel, dict[str, Any]]:
    histories = build_histories(corpus, embeddings)
    languages = repo_languages(corpus)
    cache = PathFeatureCache(embed)
    group = corpus.eval_group.to_numpy()

    train = _featurize(_instances(corpus, group == "train", "tree", histories), corpus, embeddings, histories, cache, languages)
    dev = _featurize(_instances(corpus, group == "dev", "tree", histories), corpus, embeddings, histories, cache, languages)
    train = [entry for entry in train if entry["y"].any()]
    dev_fit = [entry for entry in dev if entry["y"].any()]
    logger.info("Localization training groups: %d train, %d dev", len(train), len(dev_fit))
    ranker = train_ranker([e["x"] for e in train], [e["y"] for e in train], [e["x"] for e in dev_fit], [e["y"] for e in dev_fit])
    model = LocalizationModel(ranker=ranker, metadata={"train_issues": len(train), "train_repositories": int(corpus.iloc[[e["index"] for e in train]].repo.nunique()), "best_iteration": int(getattr(ranker, "best_iteration_", 0) or 0)})

    metrics: dict[str, Any] = {"features": FEATURES, "dev": _evaluate(model, dev)}
    verified = (group == "test") & corpus.human_level.notna().to_numpy()
    metrics["test_verified_tree"] = _evaluate(model, _featurize(_instances(corpus, verified, "tree", histories), corpus, embeddings, histories, cache, languages, with_baselines=True))
    metrics["multilingual_tree"] = _evaluate(model, _featurize(_instances(corpus, group == "multilingual", "tree", histories), corpus, embeddings, histories, cache, languages, with_baselines=True))
    nextjs = group == "nextjs"
    if nextjs.any():
        cutoff = np.quantile(_epoch(corpus.created_at[nextjs]), 0.8)
        late = nextjs & (_epoch(corpus.created_at) >= cutoff)
        metrics["nextjs_history_last20pct"] = _evaluate(model, _featurize(_instances(corpus, late, "history", histories), corpus, embeddings, histories, cache, languages, with_baselines=True))
    importance = dict(zip(FEATURES, (model.ranker.booster_.feature_importance("gain") / max(model.ranker.booster_.feature_importance("gain").sum(), 1e-9)).round(4).tolist()))
    metrics["feature_importance_gain"] = dict(sorted(importance.items(), key=lambda item: -item[1]))
    return model, metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and evaluate ContriMap v2 models")
    parser.add_argument("--stages", default="difficulty,localization,success,actionability,recommendation")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--rebuild-corpus", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("faiss", "datasets", "sentence_transformers", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    stages = set(args.stages.split(","))
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "evaluation_report.json"
    report: dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}

    corpus = load_corpus(rebuild=args.rebuild_corpus)
    embeddings = embed(corpus.text.fillna("").tolist())
    report["corpus"] = {
        "records": int(len(corpus)),
        "repositories": int(corpus.repo.nunique()),
        "by_group": corpus.groupby("eval_group").agg(records=("uid", "size"), repositories=("repo", "nunique")).to_dict(orient="index"),
        "languages": corpus.language.value_counts().to_dict(),
    }

    if "difficulty" in stages:
        from .difficulty import train_difficulty, train_effort

        model, metrics = train_difficulty(corpus, embeddings)
        metrics["effort"] = train_effort(model, corpus, embeddings)
        joblib.dump(model, output / "difficulty.joblib")
        report["difficulty"] = metrics
    if "localization" in stages:
        model, metrics = train_localization(corpus, embeddings)
        joblib.dump(model, output / "localization.joblib")
        report["localization"] = metrics
    if "success" in stages:
        from .success import train_success_model

        model, metrics = train_success_model()
        joblib.dump(model, output / "success.joblib")
        report["success"] = metrics
    if "actionability" in stages:
        from .issue_ranking import train_actionability

        model, metrics = train_actionability(corpus=corpus)
        joblib.dump(model, output / "actionability.joblib")
        report["issue_ranking_actionability"] = metrics
    if "success_multirepo" in stages:
        from .ingest import load_pr_outcomes
        from .success import train_success_multirepo

        # Uniform closed-PR samples (ingest_pr_outcomes); bodies are blanked everywhere so the
        # next.js data does not carry a feature the other repositories lack.
        prs = load_pr_outcomes()
        prs["vercel/next.js"] = [{**pr, "body": ""} for pr in json.loads((ROOT / "data" / "raw" / "pull_requests.json").read_text(encoding="utf-8"))]
        model, metrics = train_success_multirepo(prs)
        joblib.dump(model, output / "success.joblib")
        report["success_multirepo"] = metrics
    if "ingested" in stages:
        from .ingested_eval import evaluate_ingested

        report["ingested_evaluation"] = evaluate_ingested(output)
    if "recommendation" in stages:
        from .recommendation_eval import evaluate_recommendation

        report["recommendation"] = evaluate_recommendation(corpus, embeddings)

    (output / "repo_languages.json").write_text(json.dumps(repo_languages(corpus), indent=1), encoding="utf-8")
    report["generated_at"] = pd.Timestamp.now(tz="UTC").isoformat()
    report_path.write_text(json.dumps(report, indent=2, default=float), encoding="utf-8")
    logger.info("Wrote %s", report_path)


if __name__ == "__main__":
    main()
