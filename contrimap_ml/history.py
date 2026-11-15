"""Repository history: similar past issues, the pull requests that resolved them and the files they changed.

Live data comes from the GitHub REST API (closed issues and merged pull requests, linked through
"fixes #N" style references). Retrieval is a hybrid of MiniLM embeddings and TF-IDF over the
title and body; :func:`evaluate_retrieval` measures it on the corpus against simple baselines.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

# GitHub's closing keywords (https://docs.github.com/en/issues/tracking-your-work-with-issues/linking-a-pull-request-to-an-issue)
_CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+(?:[\w.-]+/[\w.-]+)?#(\d+)", re.I)
_REFERENCE = re.compile(r"(?<![\w/])#(\d+)\b")

# Retrieval weights, chosen on the validation repositories in evaluate_retrieval (see docs/EVALUATION_v2.3.md).
SEMANTIC_WEIGHT = 0.5
MIN_SIMILARITY = 0.25


def linked_issues(text: str | None, closing_only: bool = True) -> list[int]:
    """Issue numbers a pull request closes ("Fixes #12"); with ``closing_only=False`` also plain "#12" mentions."""
    text = text or ""
    numbers = [int(match) for match in _CLOSING.findall(text)]
    if not closing_only:
        numbers += [int(match) for match in _REFERENCE.findall(text)]
    return list(dict.fromkeys(numbers))


def history_text(title: str, body: str | None, limit: int = 1500) -> str:
    """Title plus the start of the body, without code fences and links (they swamp the similarity)."""
    body = re.sub(r"```.*?```", " ", body or "", flags=re.S)
    body = re.sub(r"https?://\S+|<!--.*?-->", " ", body, flags=re.S)
    return f"{title}\n{body}"[:limit].strip()


def link_history(issues: Sequence[Mapping[str, Any]], pulls: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One record per closed issue or merged PR, with each issue's resolving PRs attached.

    ``issues`` and ``pulls`` are mapped API items (``number``, ``title``, ``body``, ``closed_at``/``merged_at``, ``html_url``).
    PRs not linked to any fetched issue become records of their own (many fixes have no separate issue).
    """
    by_issue: defaultdict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for pull in pulls:
        for number in linked_issues(f"{pull.get('title') or ''}\n{pull.get('body') or ''}"):
            by_issue[number].append(pull)
    issue_numbers = {int(issue["number"]) for issue in issues}
    records = []
    for issue in issues:
        resolving = by_issue.get(int(issue["number"]), [])
        records.append({
            "kind": "issue", "number": int(issue["number"]), "title": issue.get("title") or "", "body": issue.get("body") or "",
            "closed_at": issue.get("closed_at"), "html_url": issue.get("html_url"), "labels": issue.get("labels") or [],
            "pull_requests": [_pull_summary(pull) for pull in resolving],
        })
    for pull in pulls:
        if any(number in issue_numbers for number in linked_issues(f"{pull.get('title') or ''}\n{pull.get('body') or ''}")):
            continue
        records.append({
            "kind": "pull_request", "number": int(pull["number"]), "title": pull.get("title") or "", "body": pull.get("body") or "",
            "closed_at": pull.get("merged_at"), "html_url": pull.get("html_url"), "labels": pull.get("labels") or [],
            "pull_requests": [_pull_summary(pull)],
        })
    return records


def _pull_summary(pull: Mapping[str, Any]) -> dict[str, Any]:
    return {"number": int(pull["number"]), "title": pull.get("title") or "", "html_url": pull.get("html_url"), "merged_at": pull.get("merged_at"), "author": pull.get("author")}


class HybridRetriever:
    """Cosine similarity of unit embeddings blended with TF-IDF cosine (word and identifier overlap)."""

    def __init__(self, texts: Sequence[str], embeddings: np.ndarray, semantic_weight: float = SEMANTIC_WEIGHT):
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.embeddings = np.asarray(embeddings, dtype="float32")
        self.semantic_weight = semantic_weight
        self.vectorizer = TfidfVectorizer(sublinear_tf=True, min_df=1, max_features=50000, token_pattern=r"(?u)\b[A-Za-z_][A-Za-z0-9_]{2,}\b") if len(texts) else None
        self.matrix = self.vectorizer.fit_transform(texts) if self.vectorizer is not None else None

    def scores(self, text: str, embedding: np.ndarray) -> np.ndarray:
        if self.matrix is None or not self.matrix.shape[0]:
            return np.zeros(0)
        semantic = self.embeddings @ np.asarray(embedding, dtype="float32")
        lexical = (self.matrix @ self.vectorizer.transform([text]).T).toarray().ravel()
        return self.semantic_weight * semantic + (1 - self.semantic_weight) * lexical

    def top(self, text: str, embedding: np.ndarray, k: int = 5, exclude: Iterable[int] = ()) -> list[tuple[int, float]]:
        scores = self.scores(text, embedding)
        skip = set(exclude)
        order = [int(i) for i in np.argsort(-scores) if int(i) not in skip]
        return [(i, float(scores[i])) for i in order[:k] if scores[i] >= MIN_SIMILARITY]


def changed_file_votes(similar: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Files changed by the resolving PRs of similar past issues, weighted by similarity."""
    votes: Counter = Counter()
    sources: defaultdict[str, list[int]] = defaultdict(list)
    for item in similar:
        for path in item.get("changed_files") or []:
            votes[path] += float(item.get("similarity") or 0.0)
            sources[path].append(int(item["number"]))
    return [{"path": path, "score": round(score, 4), "from": sources[path][:4]} for path, score in votes.most_common(12)]


# ---------------------------------------------------------------------------
# Offline evaluation on the corpus (resolved issues with their changed files)
# ---------------------------------------------------------------------------
def _overlap(a: Iterable[str], b: Iterable[str]) -> bool:
    return bool(set(a) & set(b))


def evaluate_retrieval(corpus, repos: Sequence[str], per_repo: int = 600, test_share: float = 0.2, k: int = 5, weights: Sequence[float] = (0.0, 0.3, 0.5, 0.7, 0.85, 1.0), seed: int = 7) -> dict[str, Any]:
    """Does retrieving similar *earlier* issues surface the files the new issue's fix changed?

    For each repository the latest ``per_repo`` issues are time-ordered; the last ``test_share`` are queries and
    only issues created before each query can be retrieved. Metrics over queries:
    * ``hit@k``: at least one of the top-k retrieved issues changed a file the query's fix changed;
    * ``file_recall@10``: share of the query's changed files among the 10 most similarity-voted files.
    Baselines: the k most recent earlier issues, and k random earlier issues.
    ``repos`` is split in half: weights are chosen on the first half and reported on the second.
    """
    from .textfeat import embed

    rng = np.random.default_rng(seed)
    half = max(1, len(repos) // 2)
    groups = {"validation": list(repos[:half]), "test": list(repos[half:])}
    prepared = {}
    for repo in repos:
        frame = corpus[corpus.repo == repo].sort_values("created_at").tail(per_repo)
        texts = [history_text(str(t), str(b)) for t, b in zip(frame.title.fillna(""), frame.body.fillna(""))]
        prepared[repo] = (texts, embed(texts), [list(files) for files in frame.target_files])

    def run(repo_list: Sequence[str], method: str, weight: float = SEMANTIC_WEIGHT) -> dict[str, float]:
        hits, recalls = [], []
        for repo in repo_list:
            texts, embeddings, targets = prepared[repo]
            start = int(len(texts) * (1 - test_share))
            for query in range(start, len(texts)):
                if not targets[query] or query < 20:
                    continue
                if method == "recent":
                    chosen = list(range(query - 1, max(-1, query - 1 - k), -1))
                    similarities = [1.0] * len(chosen)
                elif method == "random":
                    chosen = rng.choice(query, size=min(k, query), replace=False).tolist()
                    similarities = [1.0] * len(chosen)
                else:
                    retriever = HybridRetriever(texts[:query], embeddings[:query], semantic_weight=weight)
                    scores = retriever.scores(texts[query], embeddings[query])
                    chosen = [int(i) for i in np.argsort(-scores)[:k]]
                    similarities = [float(scores[i]) for i in chosen]
                hits.append(any(_overlap(targets[i], targets[query]) for i in chosen))
                votes = changed_file_votes([{"number": i, "similarity": s, "changed_files": targets[i]} for i, s in zip(chosen, similarities)])
                top_files = [vote["path"] for vote in votes[:10]]
                recalls.append(len(set(top_files) & set(targets[query])) / len(set(targets[query])))
        return {f"hit@{k}": round(float(np.mean(hits)), 4) if hits else 0.0, "file_recall@10": round(float(np.mean(recalls)), 4) if recalls else 0.0, "queries": len(hits)}

    validation = {f"hybrid_w{weight}": run(groups["validation"], "hybrid", weight) for weight in weights}
    best = max(weights, key=lambda weight: (validation[f"hybrid_w{weight}"][f"hit@{k}"], validation[f"hybrid_w{weight}"]["file_recall@10"]))
    test = {
        "hybrid_selected": run(groups["test"], "hybrid", best),
        "embedding_only": run(groups["test"], "hybrid", 1.0),
        "tfidf_only": run(groups["test"], "hybrid", 0.0),
        "most_recent": run(groups["test"], "recent"),
        "random_earlier": run(groups["test"], "random"),
    }
    return {"k": k, "repositories": groups, "per_repo": per_repo, "selected_semantic_weight": best, "validation": validation, "test": test}


__all__ = ["HybridRetriever", "changed_file_votes", "evaluate_retrieval", "history_text", "link_history", "linked_issues"]
