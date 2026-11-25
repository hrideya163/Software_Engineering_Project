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
    RANKER_CONFIGS,
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


def _featurize(instances: list[dict[str, Any]], corpus: pd.DataFrame, embeddings: np.ndarray, histories: dict[str, RepoHistory], cache: PathFeatureCache, languages: dict[str, str], with_baselines: bool = False, seed: int = 0, use_history: bool = True) -> list[dict[str, Any]]:
    rng = np.random.default_rng(seed)
    cache.ensure({path for item in instances for path in item["candidates"]})
    started = time.time()
    output = []
    for count, item in enumerate(instances, 1):
        record = corpus.iloc[item["index"]]
        query = embeddings[item["index"]]
        # use_history=False reproduces the live service for repositories without ingested history.
        stats = histories[record.repo].stats(query, item["time"]) if use_history else None
        features = candidate_features(record.text, query, item["candidates"], cache, stats, languages.get(record.repo))
        targets = set(record.target_files)
        labels = np.fromiter((path in targets for path in item["candidates"]), dtype="float32", count=len(item["candidates"]))
        kept = prefilter(features)
        entry = {"index": item["index"], "candidates": item["candidates"], "kept": kept, "x": features[kept], "y": labels[kept], "targets": targets}
        if with_baselines:
            entry["baselines"] = {name: [item["candidates"][i] for i in np.argsort(-scores, kind="stable")[:10]] for name, scores in baseline_scores(features, rng).items()}
        entry["time"] = item["time"]
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


def _featurize_all(corpus: pd.DataFrame, embeddings: np.ndarray) -> dict[str, list[dict[str, Any]]]:
    """Stage-1 features for every split, cached on disk (the slowest step of localization training)."""
    cache_path = ROOT / "data" / "processed" / "localization_featurized.joblib"
    signature = {"records": int(len(corpus)), "features": FEATURES, "trees": sum(1 for _ in (ROOT / "data" / "trees").glob("*/*.txt"))}
    if cache_path.exists():
        cached = joblib.load(cache_path)
        if cached.get("signature") == signature:
            logger.info("Loaded cached stage-1 features from %s", cache_path)
            return cached["splits"]
    histories = build_histories(corpus, embeddings)
    languages = repo_languages(corpus)
    cache = PathFeatureCache(embed)
    group = corpus.eval_group.to_numpy()
    verified = (group == "test") & corpus.human_level.notna().to_numpy()
    splits = {
        "train": _featurize(_instances(corpus, group == "train", "tree", histories), corpus, embeddings, histories, cache, languages),
        "dev": _featurize(_instances(corpus, group == "dev", "tree", histories), corpus, embeddings, histories, cache, languages),
        "test_verified_tree": _featurize(_instances(corpus, verified, "tree", histories), corpus, embeddings, histories, cache, languages, with_baselines=True),
        "multilingual_tree": _featurize(_instances(corpus, group == "multilingual", "tree", histories), corpus, embeddings, histories, cache, languages, with_baselines=True),
    }
    nextjs = group == "nextjs"
    if nextjs.any():
        cutoff = np.quantile(_epoch(corpus.created_at[nextjs]), 0.8)
        late = nextjs & (_epoch(corpus.created_at) >= cutoff)
        splits["nextjs_history_last20pct"] = _featurize(_instances(corpus, late, "history", histories), corpus, embeddings, histories, cache, languages, with_baselines=True)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"signature": signature, "splits": splits}, cache_path)
    return splits


NO_HISTORY_SPLITS = {"dev": "dev_nohist", "test_verified_tree": "test_verified_nohist", "multilingual_tree": "multilingual_nohist"}


def _add_no_history_splits(splits: dict[str, list[dict[str, Any]]], corpus: pd.DataFrame, embeddings: np.ndarray) -> None:
    """The same issues and candidates featurized *without* repository history (cached separately).

    Most repositories analysed live have no ingested resolved-issue history, so the service runs in
    this mode; every SWE-bench split has history, so it was never measured or trained for.
    """
    cache_path = ROOT / "data" / "processed" / "localization_featurized_nohist.joblib"
    signature = {name: [entry["index"] for entry in splits[name]] for name in NO_HISTORY_SPLITS}
    if cache_path.exists():
        cached = joblib.load(cache_path)
        if cached.get("signature") == signature:
            logger.info("Loaded cached no-history features from %s", cache_path)
            splits.update(cached["splits"])
            return
    histories = build_histories(corpus, embeddings)
    times = _epoch(corpus.created_at)
    languages = repo_languages(corpus)
    cache = PathFeatureCache(embed)
    added = {}
    for name, target in NO_HISTORY_SPLITS.items():
        instances = [{"index": entry["index"], "candidates": entry["candidates"], "time": float(times[entry["index"]])} for entry in splits[name]]
        added[target] = _featurize(instances, corpus, embeddings, histories, cache, languages, with_baselines=name != "dev", use_history=False)
    joblib.dump({"signature": signature, "splits": added}, cache_path)
    splits.update(added)


# ---------------------------------------------------------------------------
# Stage 2: reading the code of the stage-1 shortlist
# ---------------------------------------------------------------------------
def _attach_code_features(entries: list[dict[str, Any]], corpus: pd.DataFrame, stage1_scores: list[np.ndarray], depth: int, workers: int = 8) -> None:
    """Fetch the stage-1 top-``depth`` files at each issue's base commit and store stage-2 inputs on the entry.

    Contents come from the partial clones in ``data/trees/_git`` (one network round trip per issue the
    first time, local afterwards).  Repositories are processed in parallel, issues within one
    repository sequentially (concurrent fetches into one bare repository contend on its lock).
    """
    from concurrent.futures import ThreadPoolExecutor

    from .code_features import code_features
    from .localization import rerank_inputs
    from .repo_trees import fetch_blobs, prefetch_blobs

    by_repo: dict[str, list[int]] = {}
    for position, entry in enumerate(entries):
        by_repo.setdefault(corpus.repo.iloc[entry["index"]], []).append(position)
    started = time.time()
    done = [0]

    def shortlist_of(position: int) -> tuple[np.ndarray, list[str]]:
        entry = entries[position]
        order = np.argsort(-stage1_scores[position], kind="stable")[:depth]
        return order, [entry["candidates"][entry["kept"][i]] for i in order]

    def run(repo: str, positions: list[int]) -> None:
        requests = [(corpus.base_commit.iloc[entries[p]["index"]], shortlist_of(p)[1]) for p in positions if corpus.base_commit.iloc[entries[p]["index"]]]
        download = False
        try:
            prefetch_blobs(repo, requests)
        except Exception as error:  # fall back to per-issue downloads
            download = True
            logger.warning("Batched blob prefetch failed for %s: %s", repo, str(error)[:160])
        for position in positions:
            entry, scores = entries[position], stage1_scores[position]
            order, shortlist = shortlist_of(position)
            record = corpus.iloc[entry["index"]]
            try:
                contents = fetch_blobs(repo, record.base_commit, shortlist, download=download) if record.base_commit else {}
            except Exception as error:  # network failures: the issue keeps stage-1 order (code_missing = 1)
                logger.warning("Blob fetch failed for %s@%s: %s", repo, str(record.base_commit)[:10], str(error)[:120])
                contents = {}
            code = code_features(record.text, shortlist, contents)
            entry["rerank"] = {"order": order, "x": rerank_inputs(entry["x"][order], scores[order].astype("float32"), code), "y": entry["y"][order], "read": len(contents)}
            done[0] += 1
            if done[0] % 250 == 0:
                logger.info("Read shortlist code for %d/%d issues (%.0fs)", done[0], len(entries), time.time() - started)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for future in [pool.submit(run, repo, positions) for repo, positions in by_repo.items()]:
            future.result()


def _evaluate_rerank(reranker: Any, featurized: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = []
    for entry in featurized:
        rerank = entry["rerank"]
        order = rerank["order"][np.argsort(-reranker.predict(rerank["x"]), kind="stable")] if len(rerank["order"]) else rerank["order"]
        ranked.append([entry["candidates"][entry["kept"][i]] for i in order[:10]])
    report = {"model": ranking_metrics(ranked, [entry["targets"] for entry in featurized])}
    report["shortlist_coverage"] = float(np.mean([entry["rerank"]["y"].any() for entry in featurized])) if featurized else 0.0
    report["files_read_per_issue"] = float(np.mean([entry["rerank"]["read"] for entry in featurized])) if featurized else 0.0
    return report


def _cross_fitted_scores(train: list[dict[str, Any]], corpus: pd.DataFrame, dev_fit: list[dict[str, Any]], config: dict[str, Any], folds: int = 3) -> list[np.ndarray]:
    """Stage-1 scores for training issues from models that never saw that issue's repository."""
    from sklearn.model_selection import GroupKFold

    repos = np.asarray([corpus.repo.iloc[entry["index"]] for entry in train])
    scores: list[np.ndarray | None] = [None] * len(train)
    for fold, (fit_idx, held_idx) in enumerate(GroupKFold(n_splits=folds).split(np.zeros(len(train)), groups=repos)):
        ranker = train_ranker([train[i]["x"] for i in fit_idx], [train[i]["y"] for i in fit_idx], [e["x"] for e in dev_fit], [e["y"] for e in dev_fit], config=config)
        for i in held_idx:
            scores[i] = np.asarray(ranker.predict(train[i]["x"]), dtype="float64")
        logger.info("Cross-fitted stage-1 fold %d/%d", fold + 1, folds)
    return scores  # type: ignore[return-value]


def train_reranker(model: LocalizationModel, splits: dict[str, list[dict[str, Any]]], corpus: pd.DataFrame, config: dict[str, Any], depth: int = 50) -> dict[str, Any]:
    """Fit stage 2 on cross-fitted shortlists of the training repositories; keep it only if dev MRR improves."""
    from lightgbm import LGBMRanker, early_stopping, log_evaluation

    from .localization import RERANK_FEATURES

    eval_names = [name for name in ("dev", "test_verified_tree", "multilingual_tree", "dev_nohist", "test_verified_nohist", "multilingual_nohist") if splits.get(name)]
    train = [entry for entry in splits["train"] if entry["y"].any()]
    dev_all = splits["dev"]
    dev_fit = [entry for entry in dev_all if entry["y"].any()]
    _attach_code_features(train, corpus, _cross_fitted_scores(train, corpus, dev_fit, config), depth)
    for name in eval_names:
        entries = splits[name]
        _attach_code_features(entries, corpus, [model.score(entry["x"]) for entry in entries], depth)

    fit = [entry for entry in train if entry["rerank"]["y"].any()]
    valid = [entry for entry in dev_all if entry["rerank"]["y"].any()]
    results: dict[str, Any] = {"depth": depth, "features": RERANK_FEATURES, "train_groups": len(fit), "config_selection": []}
    best = None
    for params in ({"num_leaves": 15, "min_child_samples": 40, "learning_rate": 0.03}, {"num_leaves": 31, "min_child_samples": 30, "learning_rate": 0.03}):
        reranker = LGBMRanker(objective="lambdarank", n_estimators=1500, subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, lambdarank_truncation_level=10, verbosity=-1, random_state=42, **params)
        reranker.fit(
            np.vstack([e["rerank"]["x"] for e in fit]), np.concatenate([e["rerank"]["y"] for e in fit]), group=[len(e["rerank"]["y"]) for e in fit],
            eval_set=[(np.vstack([e["rerank"]["x"] for e in valid]), np.concatenate([e["rerank"]["y"] for e in valid]))], eval_group=[[len(e["rerank"]["y"]) for e in valid]],
            eval_at=[5, 10], callbacks=[early_stopping(50, verbose=False), log_evaluation(0)],
        )
        mrr = _evaluate_rerank(reranker, dev_all)["model"]["mrr"]
        results["config_selection"].append({**params, "dev_mrr": mrr, "best_iteration": int(getattr(reranker, "best_iteration_", 0) or 0)})
        if best is None or mrr > best[0]:
            best = (mrr, reranker)
    stage1_dev_mrr = _evaluate(model, dev_all)["model"]["mrr"]
    results["dev_stage1_mrr"] = stage1_dev_mrr
    results["dev_stage2_mrr"] = best[0]
    results["selected"] = bool(best[0] > stage1_dev_mrr)
    for name in eval_names:
        results[name] = _evaluate_rerank(best[1], splits[name])
    gain = best[1].booster_.feature_importance("gain")
    results["feature_importance_gain"] = dict(sorted(zip(RERANK_FEATURES, (gain / max(gain.sum(), 1e-9)).round(4).tolist()), key=lambda item: -item[1]))
    if results["selected"]:
        model.reranker, model.rerank_depth = best[1], depth
    logger.info("Stage-2 re-ranker: dev MRR %.4f vs stage-1 %.4f (selected=%s)", best[0], stage1_dev_mrr, results["selected"])
    return results


def train_localization(corpus: pd.DataFrame, embeddings: np.ndarray, rerank: bool = True) -> tuple[LocalizationModel, dict[str, Any]]:
    splits = _featurize_all(corpus, embeddings)
    # No-history variants are evaluated (the live service runs this way for most repositories). Training on
    # them as augmentation was tried and did not help on dev (stage 2 already closes most of the gap).
    _add_no_history_splits(splits, corpus, embeddings)
    splits.pop("train_nohist", None)
    train, dev = splits["train"], splits["dev"]
    train = [entry for entry in train if entry["y"].any()]
    dev_fit = [entry for entry in dev if entry["y"].any()]
    logger.info("Localization training groups: %d train, %d dev", len(train), len(dev_fit))
    # Hyper-parameters chosen by MRR on the dev repositories (never on test).
    best = None
    selection = []
    for config in RANKER_CONFIGS:
        ranker = train_ranker([e["x"] for e in train], [e["y"] for e in train], [e["x"] for e in dev_fit], [e["y"] for e in dev_fit], config=config)
        candidate = LocalizationModel(ranker=ranker)
        mrr = _evaluate(candidate, dev)["model"]["mrr"]
        selection.append({**config, "dev_mrr": mrr, "best_iteration": int(getattr(ranker, "best_iteration_", 0) or 0)})
        logger.info("Ranker config %s: dev MRR %.4f", config, mrr)
        if best is None or mrr > best[0]:
            best = (mrr, candidate)
    model = best[1]
    model.metadata = {"train_issues": len(train), "train_repositories": int(corpus.iloc[[e["index"] for e in train]].repo.nunique()), "config_selection": selection}

    metrics: dict[str, Any] = {"features": FEATURES, "dev": _evaluate(model, dev)}
    for name in ("test_verified_tree", "multilingual_tree", "nextjs_history_last20pct", "dev_nohist", "test_verified_nohist", "multilingual_nohist"):
        if splits.get(name):
            metrics[name] = _evaluate(model, splits[name])
    importance = dict(zip(FEATURES, (model.ranker.booster_.feature_importance("gain") / max(model.ranker.booster_.feature_importance("gain").sum(), 1e-9)).round(4).tolist()))
    metrics["feature_importance_gain"] = dict(sorted(importance.items(), key=lambda item: -item[1]))
    if rerank:
        best_config = {key: value for key, value in max(selection, key=lambda row: row["dev_mrr"]).items() if key in RANKER_CONFIGS[0]}
        metrics["code_reranker"] = train_reranker(model, splits, corpus, best_config)
        model.metadata["code_reranker"] = {key: metrics["code_reranker"][key] for key in ("depth", "selected", "dev_stage1_mrr", "dev_stage2_mrr")}
        _save_localization_signals(model, splits, corpus)
    return model, metrics


def _save_localization_signals(model: LocalizationModel, splits: dict[str, list[dict[str, Any]]], corpus: pd.DataFrame) -> None:
    """Per-issue summaries of the localization output, used as difficulty/effort features (``difficulty.LOC_COLUMNS``)."""
    from .localization import localization_signals

    rows = []
    for name, entries in splits.items():
        for entry in entries:
            if "rerank" not in entry:
                continue
            rerank = entry["rerank"]
            # Stage-1 scores only (cross-fitted for training issues) so training rows are not in-sample.
            rows.append({"uid": corpus.uid.iloc[entry["index"]], "split": name, **localization_signals(rerank["x"], [entry["candidates"][entry["kept"][i]] for i in rerank["order"]], len(entry["candidates"]))})
    path = ROOT / "data" / "processed" / "localization_signals.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    logger.info("Wrote %d localization signal rows to %s", len(rows), path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and evaluate ContriMap v2 models")
    parser.add_argument("--stages", default="difficulty,localization,success,actionability,recommendation")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--rebuild-corpus", action="store_true")
    parser.add_argument("--no-extra-train", action="store_true", help="ignore data/ingested_train (GraphQL training repositories)")
    parser.add_argument("--no-rerank", action="store_true", help="skip the stage-2 code-reading localization re-ranker")
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
    extra_dir = ROOT / "data" / "ingested_train"
    if not args.no_extra_train and extra_dir.exists():
        from .ingest import load_ingested

        extra = load_ingested(extra_dir)
        if not extra.empty:
            # Training-only repositories (disjoint from every evaluation group).
            extra = extra.assign(eval_group="train", source="github_train", human_level=np.nan)
            extra = extra[~extra.repo.isin(set(corpus[corpus.eval_group != "train"].repo))]
            corpus = pd.concat([corpus, extra[[c for c in extra.columns if c in corpus.columns]]], ignore_index=True)
            logger.info("Added %d training issues from %d ingested repositories", len(extra), extra.repo.nunique())
    embeddings = embed(corpus.text.fillna("").tolist())
    report["corpus"] = {
        "records": int(len(corpus)),
        "repositories": int(corpus.repo.nunique()),
        "by_group": corpus.groupby("eval_group").agg(records=("uid", "size"), repositories=("repo", "nunique")).to_dict(orient="index"),
        "languages": corpus.language.value_counts().to_dict(),
    }

    if "difficulty" in stages:
        from .difficulty import train_difficulty, train_effort

        difficulty_model, metrics = train_difficulty(corpus, embeddings)
        metrics["effort"] = train_effort(difficulty_model, corpus, embeddings)
        report["difficulty"] = metrics
    if "localization" in stages:
        model, metrics = train_localization(corpus, embeddings, rerank=not args.no_rerank)
        joblib.dump(model, output / "localization.joblib")
        report["localization"] = metrics
    if "difficulty" in stages:
        # "Localization into difficulty": stack where-the-fix-lands signals on the text model.
        signals_path = ROOT / "data" / "processed" / "localization_signals.parquet"
        if signals_path.exists():
            from .difficulty import train_effort_structural, train_structural

            signals = pd.read_parquet(signals_path)
            report["difficulty"]["structural"] = train_structural(difficulty_model, corpus, embeddings, signals)
            report["difficulty"]["effort_structural"] = train_effort_structural(difficulty_model, corpus, embeddings, signals)
        if hasattr(difficulty_model, "oof_"):
            del difficulty_model.oof_
        joblib.dump(difficulty_model, output / "difficulty.joblib")
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
    if "actionability_multirepo" in stages:
        from .ingest import OUTPUT as INGESTED, load_issue_outcomes
        from .issue_ranking import train_actionability_multirepo

        model, metrics = train_actionability_multirepo(load_issue_outcomes(INGESTED, ROOT / "data" / "ingested_train"))
        joblib.dump(model, output / "actionability.joblib")
        report["actionability_multirepo"] = metrics
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
