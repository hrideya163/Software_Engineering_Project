"""Compare saved localization models on the same cached evaluation splits.

    python -m contrimap_ml.compare_localization baseline.joblib artifacts/v2/localization.joblib [--output report.json]

Each model is scored with stage 1 alone and, if it has one, with its stage-2 code re-ranker, on the
history and no-history variants of dev, SWE-bench Verified and the multilingual set (the cached
features written by ``train_v2``).  The no-history variants are what the live service sees for
repositories without ingested resolved-issue history.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from .corpus import load_corpus
from .train_v2 import ROOT, _attach_code_features, _evaluate, _evaluate_rerank

SPLITS = ("dev", "test_verified_tree", "multilingual_tree", "dev_nohist", "test_verified_nohist", "multilingual_nohist")


def load_splits() -> dict[str, list[dict[str, Any]]]:
    splits = joblib.load(ROOT / "data" / "processed" / "localization_featurized.joblib")["splits"]
    splits.update(joblib.load(ROOT / "data" / "processed" / "localization_featurized_nohist.joblib")["splits"])
    return {name: splits[name] for name in SPLITS if name in splits}


def compare(model_paths: list[str]) -> dict[str, Any]:
    corpus = load_corpus()
    splits = load_splits()
    report: dict[str, Any] = {}
    for path in model_paths:
        model = joblib.load(path)
        rows: dict[str, Any] = {}
        for name, entries in splits.items():
            rows[name] = {"stage1": _evaluate(model, entries)["model"]}
            if getattr(model, "reranker", None) is not None:
                copies = [copy.copy(entry) for entry in entries]
                _attach_code_features(copies, corpus, [model.score(entry["x"]) for entry in copies], model.rerank_depth)
                rows[name]["stage2"] = _evaluate_rerank(model.reranker, copies)["model"]
        report[Path(path).name] = rows
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("models", nargs="+")
    parser.add_argument("--output")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    report = compare(args.models)
    table = [{"model": model, "split": split, "stage": stage, **{k: round(v, 3) for k, v in metrics.items() if k != "n"}, "n": metrics["n"]}
             for model, rows in report.items() for split, stages in rows.items() for stage, metrics in stages.items()]
    print(pd.DataFrame(table).to_string(index=False))
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
