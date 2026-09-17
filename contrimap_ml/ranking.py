from __future__ import annotations

import re
from typing import Any, Iterable, Mapping


def _tokenize(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[a-z0-9_./-]+", text.lower()) if token}


def score_candidate(candidate: Mapping[str, Any], query: str, *, graph: Any | None = None, metadata: Mapping[str, Any] | None = None) -> float:
    text = " ".join([str(candidate.get("title") or candidate.get("path") or candidate.get("name") or ""), str(candidate.get("body") or "")]).lower()
    tokens = _tokenize(query)
    if not tokens:
        return 0.0
    score = sum(1.0 for token in tokens if token in text)
    score += 0.1 * len(tokens.intersection(_tokenize(text)))
    if graph is not None and candidate.get("path") is not None:
        node = str(candidate["path"])
        degree = graph.degree(node) if node in graph else 0
        score += 0.1 * degree
    if metadata:
        score += float(metadata.get("boost", 0.0))
    return score


def rank_candidates(candidates: Iterable[Mapping[str, Any]], query: str, *, graph: Any | None = None, top_k: int = 5) -> list[dict[str, Any]]:
    ranked = []
    for candidate in candidates:
        item = dict(candidate)
        item["score"] = score_candidate(candidate, query, graph=graph, metadata=item.get("metadata"))
        ranked.append(item)
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked[: max(1, top_k)]


def rank_repository_items(snapshot: Mapping[str, Any], query: str, *, graph: Any | None = None, top_k: int = 5) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for issue in snapshot.get("issues") or []:
        items.append({"type": "issue", "title": issue.get("title") or "", "body": issue.get("body") or "", "id": issue.get("id") or issue.get("number") or ""})
    for file in snapshot.get("files") or []:
        items.append({"type": "file", "path": file.get("path") or file.get("name") or "", "title": file.get("path") or file.get("name") or "", "body": file.get("content") or ""})
    return rank_candidates(items, query, graph=graph, top_k=top_k)


__all__ = ["rank_candidates", "rank_repository_items", "score_candidate"]
