"""Issue-to-file localization as learning-to-rank over a repository's file tree.

Candidates are *all* files of the repository at the issue's base commit (or the
current default branch at inference time), not a memorised list of historically
changed files - the legacy index could only ever return vercel/next.js paths.

Each candidate gets features from five families:

* lexical  - BM25 between issue tokens and identifier-split path tokens;
* semantic - cosine between issue and path sentence embeddings;
* mention  - paths, tracebacks, dotted modules and file stems named in the issue;
* history  - point-in-time repository history: how often / how recently a file
  (or its directory) was changed by earlier fixes, and which files the most
  similar *earlier* issues touched;
* structure - depth, ``__init__``, language match, docs/config flags.

A cheap union-of-top-k prefilter keeps ~250 candidates per issue, then a
LightGBM LambdaRank model orders them.  History only ever looks at issues
created strictly before the query issue.
"""

from __future__ import annotations

import bisect
import logging
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Iterable, Sequence

import numpy as np

from .corpus import is_test_path, language_of
from .features import is_valid_candidate
from .textfeat import extract_mentions, path_text, path_tokens, text_tokens

logger = logging.getLogger(__name__)

FEATURES = [
    "emb_sim", "emb_rel", "emb_pct", "bm25", "bm25_rel", "bm25_name", "mention_path", "mention_basename",
    "mention_stem", "stem_idf", "mention_module", "same_dir_as_mention", "hist_seen", "hist_freq",
    "hist_recency", "dir_hist", "knn_sum", "knn_max", "depth", "is_init", "lang_match", "is_doc",
    "is_config", "n_path_tokens",
]
GENERIC_STEMS = {
    "index", "__init__", "init", "utils", "util", "base", "core", "main", "setup", "conftest", "types", "common",
    "helpers", "helper", "models", "model", "views", "view", "api", "app", "config", "settings", "constants",
    "errors", "exceptions", "test", "tests", "mod", "lib", "readme", "changelog", "options", "compat", "version",
}
DOC_PATH = re.compile(r"(^|/)(docs?|documentation)/|\.(md|rst|txt|adoc)$", re.I)
CONFIG_PATH = re.compile(r"\.(json|ya?ml|toml|cfg|ini|lock|xml)$|(^|/)(setup\.py|Makefile|Dockerfile)$", re.I)
_BM25_K1, _BM25_B = 1.2, 0.5


# Changelogs are touched by most PRs in some projects; predicting them is accurate but useless guidance.
CHANGELOG_PATH = re.compile(r"(^|/)(CHANGES|CHANGELOG|HISTORY|NEWS|RELEASE[_-]?NOTES)(\.\w+)?$|(^|/)(changelog\.d|changes|newsfragments)/", re.I)


def is_changelog(path: str) -> bool:
    return bool(CHANGELOG_PATH.search(path))


def localization_candidates(files: Iterable[str]) -> list[str]:
    """Files eligible as localization targets: valid, non-test, non-changelog source/doc/config files."""
    return [path for path in files if is_valid_candidate(path) and not is_test_path(path) and not is_changelog(path)]


# ---------------------------------------------------------------------------
# Repository history (point-in-time)
# ---------------------------------------------------------------------------
@dataclass
class RepoHistory:
    """Resolved issues of one repository ordered by creation time."""

    times: list[float] = field(default_factory=list)
    embeddings: np.ndarray = field(default_factory=lambda: np.zeros((0, 384), dtype="float32"))
    targets: list[list[str]] = field(default_factory=list)

    @classmethod
    def build(cls, times: Sequence[float], embeddings: np.ndarray, targets: Sequence[Sequence[str]]) -> "RepoHistory":
        order = np.argsort(np.asarray(times, dtype="float64"), kind="stable")
        return cls(
            times=[float(times[i]) for i in order],
            embeddings=np.asarray(embeddings, dtype="float32")[order] if len(order) else np.zeros((0, 384), dtype="float32"),
            targets=[list(targets[i]) for i in order],
        )

    def prior_count(self, before: float | None) -> int:
        return len(self.times) if before is None else bisect.bisect_left(self.times, before)

    def stats(self, query_embedding: np.ndarray, before: float | None, k: int = 20) -> dict[str, Any]:
        """File/dir change counts, recency and similar-issue scores using issues before ``before``."""
        m = self.prior_count(before)
        counts: Counter[str] = Counter()
        dir_counts: Counter[str] = Counter()
        last_seen: dict[str, int] = {}
        for index in range(m):
            for path in self.targets[index]:
                counts[path] += 1
                dir_counts[path.rsplit("/", 1)[0] if "/" in path else ""] += 1
                last_seen[path] = index
        knn_sum: defaultdict[str, float] = defaultdict(float)
        knn_max: defaultdict[str, float] = defaultdict(float)
        if m:
            similarities = self.embeddings[:m] @ np.asarray(query_embedding, dtype="float32")
            for index in np.argsort(-similarities)[:k]:
                similarity = float(similarities[index])
                if similarity <= 0.2:
                    continue
                for path in self.targets[index]:
                    knn_sum[path] += similarity
                    knn_max[path] = max(knn_max[path], similarity)
        return {"m": m, "counts": counts, "dir_counts": dir_counts, "last_seen": last_seen, "knn_sum": knn_sum, "knn_max": knn_max}


# ---------------------------------------------------------------------------
# Feature construction
# ---------------------------------------------------------------------------
class PathFeatureCache:
    """Memoises per-path tokens and embeddings (paths repeat across commits and issues)."""

    def __init__(self, embed_fn):
        self._embed_fn = embed_fn
        self.tokens: dict[str, list[str]] = {}
        self.index: dict[str, int] = {}
        self.matrix = np.zeros((0, 384), dtype="float32")

    def ensure(self, paths: Iterable[str]) -> None:
        missing = sorted({path for path in paths if path not in self.index})
        if not missing:
            return
        vectors = self._embed_fn([path_text(path) for path in missing])
        start = len(self.index)
        self.matrix = np.vstack([self.matrix, vectors]) if len(self.matrix) else vectors
        for offset, path in enumerate(missing):
            self.index[path] = start + offset
            self.tokens[path] = path_tokens(path)

    def embeddings(self, paths: Sequence[str]) -> np.ndarray:
        self.ensure(paths)
        return self.matrix[[self.index[path] for path in paths]]


def _bm25(query: Counter[str], documents: list[list[str]]) -> np.ndarray:
    n = len(documents)
    scores = np.zeros(n, dtype="float32")
    if not n or not query:
        return scores
    postings: defaultdict[str, list[tuple[int, int]]] = defaultdict(list)
    lengths = np.fromiter((len(doc) for doc in documents), dtype="float32", count=n)
    average = float(lengths.mean()) or 1.0
    for doc_index, doc in enumerate(documents):
        for token, tf in Counter(doc).items():
            if token in query:
                postings[token].append((doc_index, tf))
    for token, hits in postings.items():
        idf = math.log(1 + (n - len(hits) + 0.5) / (len(hits) + 0.5))
        weight = idf * (1 + math.log(query[token]))
        for doc_index, tf in hits:
            scores[doc_index] += weight * tf * (_BM25_K1 + 1) / (tf + _BM25_K1 * (1 - _BM25_B + _BM25_B * lengths[doc_index] / average))
    return scores


def _module_key(path: str) -> str:
    key = re.sub(r"\.[A-Za-z0-9]+$", "", path)
    return key[: -len("/__init__")] if key.endswith("/__init__") else key


def candidate_features(
    text: str,
    query_embedding: np.ndarray,
    candidates: list[str],
    cache: PathFeatureCache,
    history: dict[str, Any] | None = None,
    repo_language: str | None = None,
) -> np.ndarray:
    """Return an ``(n_candidates, len(FEATURES))`` feature matrix."""
    n = len(candidates)
    matrix = np.zeros((n, len(FEATURES)), dtype="float32")
    if not n:
        return matrix
    column = {name: index for index, name in enumerate(FEATURES)}
    cache.ensure(candidates)

    # Semantic.
    emb = cache.embeddings(candidates) @ np.asarray(query_embedding, dtype="float32")
    matrix[:, column["emb_sim"]] = emb
    matrix[:, column["emb_rel"]] = emb - emb.max()
    matrix[:, column["emb_pct"]] = np.argsort(np.argsort(emb)) / max(n - 1, 1)

    # Lexical.
    query = Counter(text_tokens(text))
    documents = [cache.tokens[path] for path in candidates]
    bm25 = _bm25(query, documents)
    matrix[:, column["bm25"]] = bm25
    matrix[:, column["bm25_rel"]] = bm25 / bm25.max() if bm25.max() > 0 else 0.0
    matrix[:, column["bm25_name"]] = _bm25(query, [path_tokens(path.rsplit("/", 1)[-1]) for path in candidates])

    # Explicit mentions.
    mentions = extract_mentions(text)
    words = {word.lower() for word in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text)}
    basenames_mentioned = {PurePosixPath(path).name.lower() for path in mentions["paths"]}
    by_basename: defaultdict[str, list[int]] = defaultdict(list)
    by_suffix2: defaultdict[str, list[int]] = defaultdict(list)
    by_module_suffix: defaultdict[str, list[int]] = defaultdict(list)
    stems = []
    for index, path in enumerate(candidates):
        parts = path.split("/")
        by_basename[parts[-1].lower()].append(index)
        if len(parts) >= 2:
            by_suffix2["/".join(parts[-2:])].append(index)
        module_parts = _module_key(path).split("/")
        for length in range(2, min(5, len(module_parts)) + 1):
            by_module_suffix["/".join(module_parts[-length:])].append(index)
        stems.append(PurePosixPath(parts[-1]).stem.lower())
    stem_counts = Counter(stems)

    for mentioned in mentions["paths"]:
        mentioned = mentioned.strip("/")
        parts = mentioned.split("/")
        hits = by_suffix2.get("/".join(parts[-2:]), []) if len(parts) >= 2 else by_basename.get(parts[-1].lower(), [])
        for index in hits:
            matrix[index, column["mention_path"]] = 1.0
    for index, stem in enumerate(stems):
        basename = candidates[index].rsplit("/", 1)[-1].lower()
        if basename in basenames_mentioned:
            matrix[index, column["mention_basename"]] = 1.0
        if stem not in GENERIC_STEMS and len(stem) >= 4 and stem in words:
            matrix[index, column["mention_stem"]] = 1.0
        matrix[index, column["stem_idf"]] = math.log(n / stem_counts[stem])
    for dotted in mentions["dotted"]:
        parts = dotted.split(".")
        for start in range(len(parts)):
            for end in range(start + 2, len(parts) + 1):
                for index in by_module_suffix.get("/".join(parts[start:end]), []):
                    matrix[index, column["mention_module"]] = max(matrix[index, column["mention_module"]], float(end - start))
    strong = (matrix[:, column["mention_path"]] > 0) | (matrix[:, column["mention_module"]] >= 2)
    if strong.any():
        mentioned_dirs = {candidates[index].rsplit("/", 1)[0] for index in np.flatnonzero(strong) if "/" in candidates[index]}
        for index, path in enumerate(candidates):
            if "/" in path and path.rsplit("/", 1)[0] in mentioned_dirs:
                matrix[index, column["same_dir_as_mention"]] = 1.0

    # History.
    if history and history["m"]:
        m = history["m"]
        for index, path in enumerate(candidates):
            count = history["counts"].get(path, 0)
            if count:
                matrix[index, column["hist_seen"]] = 1.0
                matrix[index, column["hist_freq"]] = math.log1p(count)
                matrix[index, column["hist_recency"]] = math.exp(-(m - 1 - history["last_seen"][path]) / 50.0)
            matrix[index, column["dir_hist"]] = math.log1p(history["dir_counts"].get(path.rsplit("/", 1)[0] if "/" in path else "", 0))
            matrix[index, column["knn_sum"]] = history["knn_sum"].get(path, 0.0)
            matrix[index, column["knn_max"]] = history["knn_max"].get(path, 0.0)

    # Structure.
    for index, path in enumerate(candidates):
        matrix[index, column["depth"]] = path.count("/")
        matrix[index, column["is_init"]] = float(path.endswith("__init__.py") or path.rsplit("/", 1)[-1].startswith("index."))
        matrix[index, column["lang_match"]] = float(repo_language is not None and language_of(path) == repo_language)
        matrix[index, column["is_doc"]] = float(bool(DOC_PATH.search(path)))
        matrix[index, column["is_config"]] = float(bool(CONFIG_PATH.search(path)))
        matrix[index, column["n_path_tokens"]] = len(documents[index])
    return matrix


def prefilter(features: np.ndarray, limit_each: int = 60) -> np.ndarray:
    """Indices kept for re-ranking: union of top-k per signal plus every explicit mention."""
    column = {name: index for index, name in enumerate(FEATURES)}
    n = len(features)
    if n <= 4 * limit_each:
        return np.arange(n)
    keep: set[int] = set()
    for name, k in (("emb_sim", limit_each), ("bm25", limit_each), ("bm25_name", limit_each // 2), ("knn_sum", limit_each // 2), ("hist_freq", limit_each // 2), ("dir_hist", limit_each // 3)):
        values = features[:, column[name]]
        if values.max() > 0 or name == "emb_sim":
            keep.update(np.argsort(-values, kind="stable")[:k].tolist())
    for name in ("mention_path", "mention_basename", "mention_stem", "mention_module"):
        keep.update(np.flatnonzero(features[:, column[name]] > 0)[:100].tolist())
    return np.asarray(sorted(keep), dtype=int)


# ---------------------------------------------------------------------------
# Heuristic baselines (over the full candidate set)
# ---------------------------------------------------------------------------
def baseline_scores(features: np.ndarray, rng: np.random.Generator) -> dict[str, np.ndarray]:
    column = {name: index for index, name in enumerate(FEATURES)}

    def norm(values: np.ndarray) -> np.ndarray:
        spread = values.max() - values.min()
        return (values - values.min()) / spread if spread > 1e-12 else np.zeros_like(values)

    return {
        "random": rng.random(len(features)),
        "history_frequency": features[:, column["hist_freq"]] + 1e-3 * features[:, column["hist_recency"]],
        "bm25": features[:, column["bm25"]],
        "embedding": features[:, column["emb_sim"]],
        "similar_issues_knn": features[:, column["knn_sum"]] + 1e-3 * features[:, column["hist_freq"]],
        # Legacy production formula: 0.7 semantic + 0.2 log-dampened frequency (+0.1 graph, unavailable).
        "legacy_formula": 0.7 * norm(features[:, column["emb_sim"]]) + 0.2 * norm(features[:, column["hist_freq"]]),
    }


# ---------------------------------------------------------------------------
# Ranker
# ---------------------------------------------------------------------------
@dataclass
class LocalizationModel:
    ranker: Any
    features: list[str] = field(default_factory=lambda: list(FEATURES))
    metadata: dict[str, Any] = field(default_factory=dict)

    def score(self, features: np.ndarray) -> np.ndarray:
        return np.asarray(self.ranker.predict(features), dtype="float64")

    def rank(
        self,
        title: str,
        body: str,
        files: Iterable[str],
        query_embedding: np.ndarray,
        cache: PathFeatureCache,
        history: RepoHistory | None = None,
        repo_language: str | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        candidates = localization_candidates(files)
        if not candidates:
            return []
        text = f"{title}\n{body}".strip()
        stats = history.stats(query_embedding, None) if history is not None else None
        features = candidate_features(text, query_embedding, candidates, cache, stats, repo_language)
        kept = prefilter(features)
        scores = self.score(features[kept])
        order = kept[np.argsort(-scores)][:top_k]
        top = np.sort(scores)[::-1][:top_k]
        # Softmax over the shortlist gives a relative, not calibrated, confidence.
        weights = np.exp(top - top.max())
        weights = weights / weights.sum()
        column = {name: index for index, name in enumerate(FEATURES)}
        results = []
        for rank, (index, score, weight) in enumerate(zip(order, top, weights), 1):
            row = features[index]
            signals = [name for name, flag in (
                ("mentioned in issue", row[column["mention_path"]] or row[column["mention_basename"]] or row[column["mention_module"]] >= 2),
                ("name matches issue terms", row[column["mention_stem"]] or row[column["bm25_rel"]] > 0.6),
                ("semantically similar", row[column["emb_pct"]] > 0.97),
                ("changed by similar past issues", row[column["knn_max"]] > 0),
                ("frequently changed", row[column["hist_freq"]] >= math.log1p(3)),
            ) if flag]
            results.append({"path": candidates[int(index)], "rank": rank, "score": float(score), "relative_confidence": float(weight), "signals": signals})
        return results


def train_ranker(groups_x: list[np.ndarray], groups_y: list[np.ndarray], valid_x: list[np.ndarray] | None = None, valid_y: list[np.ndarray] | None = None, seed: int = 42):
    from lightgbm import LGBMRanker, early_stopping, log_evaluation

    x = np.vstack(groups_x)
    y = np.concatenate(groups_y)
    ranker = LGBMRanker(
        objective="lambdarank", n_estimators=600, learning_rate=0.05, num_leaves=31, min_child_samples=50,
        subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, lambdarank_truncation_level=20,
        verbosity=-1, random_state=seed,
    )
    fit_kwargs: dict[str, Any] = {"group": [len(group) for group in groups_y]}
    if valid_x:
        fit_kwargs.update(
            eval_set=[(np.vstack(valid_x), np.concatenate(valid_y))],
            eval_group=[[len(group) for group in valid_y]],
            eval_at=[5, 10],
            callbacks=[early_stopping(50, verbose=False), log_evaluation(0)],
        )
    ranker.fit(x, y, **fit_kwargs)
    return ranker


def ranking_metrics(ranked_lists: list[list[str]], targets: list[set[str]], candidate_sets: list[set[str]] | None = None) -> dict[str, float]:
    hits = {1: 0, 5: 0, 10: 0}
    reciprocal = 0.0
    coverage = 0
    for index, (ranked, target) in enumerate(zip(ranked_lists, targets)):
        position = next((rank for rank, path in enumerate(ranked, 1) if path in target), None)
        if position:
            reciprocal += 1.0 / position
            for k in hits:
                hits[k] += position <= k
        if candidate_sets is not None and target & candidate_sets[index]:
            coverage += 1
    n = max(len(targets), 1)
    result = {f"acc@{k}": hits[k] / n for k in hits}
    result["mrr"] = reciprocal / n
    result["n"] = len(targets)
    if candidate_sets is not None:
        result["oracle_candidate_coverage"] = coverage / n
    return result


__all__ = [
    "FEATURES", "LocalizationModel", "PathFeatureCache", "RepoHistory", "baseline_scores", "candidate_features",
    "localization_candidates", "prefilter", "ranking_metrics", "train_ranker",
]
