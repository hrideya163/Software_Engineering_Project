from __future__ import annotations

from typing import Any, Mapping


def generate_explanation(prediction: Mapping[str, Any], *, issue_title: str = "", issue_body: str = "", snapshot: Mapping[str, Any] | None = None, graph: Any | None = None) -> dict[str, Any]:
    difficulty = str(prediction.get("difficulty") or "Unknown")
    reasons: list[str] = []
    if difficulty == "Hard":
        reasons.append("The issue appears complex based on its length and impact profile.")
    elif difficulty == "Easy":
        reasons.append("The issue looks narrow and low-risk relative to the historical training curve.")
    else:
        reasons.append("The model combines textual and repository context to form this estimate.")

    if snapshot:
        files = list(prediction.get("files") or [])
        if files:
            top_paths = ", ".join(item.get("path", "") for item in files[:3] if item.get("path"))
            reasons.append(f"The highest-scoring file matches are {top_paths or 'not available'}.")
        if snapshot.get("tests"):
            reasons.append(f"The repository provides {len(snapshot.get('tests') or [])} tests aligned with the codebase surface.")
    if graph is not None and prediction.get("files"):
        reasons.append("Graph centrality increases confidence for files with strong import and change connectivity.")

    return {
        "difficulty": difficulty,
        "summary": f"Difficulty is estimated as {difficulty} because the issue description and repository context match the learned historical patterns.",
        "reasons": reasons,
        "issue_title": issue_title,
        "issue_body": issue_body,
    }


__all__ = ["generate_explanation"]
