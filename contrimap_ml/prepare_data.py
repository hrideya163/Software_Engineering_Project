"""Fetch the point-in-time file trees that localization training and evaluation need.

    python -m contrimap_ml.prepare_data [--train-per-repo 120] [--workers 6]

Every evaluation issue (dev, SWE-bench Verified, multilingual) gets its tree at
its base commit.  Training issues are capped per repository with a fixed seed,
so the training set is reproducible and large repositories (pandas has 4,600
SWE-bench train issues) do not dominate.  Trees are cached in ``data/trees``
and reused by ``train_v2``, which skips any issue whose tree is missing.
"""

from __future__ import annotations

import argparse
import logging

import numpy as np
import pandas as pd

from .corpus import load_corpus
from .repo_trees import fetch_trees, tree_cache_path

logger = logging.getLogger(__name__)


def select_tree_instances(corpus: pd.DataFrame, train_per_repo: int = 120, seed: int = 13) -> pd.DataFrame:
    """Rows whose base-commit tree is needed: all dev/Verified/multilingual rows plus a capped train sample."""
    has_commit = corpus.base_commit.notna().to_numpy()
    group = corpus.eval_group.to_numpy()
    verified = (group == "test") & corpus.human_level.notna().to_numpy()
    keep = has_commit & ((group == "dev") | (group == "multilingual") | verified)
    rng = np.random.default_rng(seed)
    for _, index in corpus[has_commit & (group == "train")].groupby("repo").indices.items():
        positions = np.flatnonzero(has_commit & (group == "train"))[index]
        chosen = positions if len(positions) <= train_per_repo else rng.choice(positions, train_per_repo, replace=False)
        keep[chosen] = True
    return corpus[keep]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--train-per-repo", type=int, default=120)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    corpus = load_corpus()
    selected = select_tree_instances(corpus, args.train_per_repo)
    pairs = [(repo, sha) for repo, sha in zip(selected.repo, selected.base_commit) if not tree_cache_path(repo, sha).exists()]
    logger.info("%d instances selected (%s); %d trees to fetch", len(selected), selected.eval_group.value_counts().to_dict(), len(pairs))
    fetched = fetch_trees(pairs, workers=args.workers)
    logger.info("Fetched %d/%d trees", len(fetched), len(pairs))


if __name__ == "__main__":
    main()
