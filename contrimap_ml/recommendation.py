"""Contributor profiles and contributor-issue recommendation."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from .skills import as_public, contributor_skills, match_skills

LEVELS = ["beginner", "intermediate", "advanced"]
# Difficulty a contributor of each level handles comfortably (P(Easy), P(Medium), P(Hard) weights).
LEVEL_FIT = {"beginner": (1.0, 0.45, 0.1), "intermediate": (0.75, 1.0, 0.55), "advanced": (0.45, 0.85, 1.0)}
DEFAULT_RECOMMENDATION_WEIGHTS = {"skill": 0.30, "files": 0.25, "semantic": 0.20, "success": 0.10, "difficulty_fit": 0.15}


@dataclass
class ContributorProfile:
    login: str
    skills: dict[str, dict[str, Any]] = field(default_factory=dict)
    files: Counter = field(default_factory=Counter)
    directories: Counter = field(default_factory=Counter)
    centroid: np.ndarray | None = None
    contributions: int = 0
    merged: int = 0
    first_at: str | None = None
    last_at: str | None = None
    level: str = "intermediate"
    interests: list[str] = field(default_factory=list)

    @classmethod
    def from_contributions(cls, login: str, contributions: Sequence[Mapping[str, Any]], embeddings: np.ndarray | None = None, level: str | None = None) -> "ContributorProfile":
        files: Counter = Counter()
        directories: Counter = Counter()
        for item in contributions:
            for path in item.get("files") or []:
                files[path] += 1
                directories[path.rsplit("/", 1)[0] if "/" in path else ""] += 1
        times = sorted(str(item["created_at"]) for item in contributions if item.get("created_at"))
        merged = sum(1 for item in contributions if item.get("merged", True))
        centroid = None
        if embeddings is not None and len(embeddings):
            centroid = np.asarray(embeddings, dtype="float32").mean(axis=0)
            centroid /= max(float(np.linalg.norm(centroid)), 1e-9)
        return cls(
            login=login,
            skills=contributor_skills(contributions),
            files=files,
            directories=directories,
            centroid=centroid,
            contributions=len(contributions),
            merged=merged,
            first_at=times[0] if times else None,
            last_at=times[-1] if times else None,
            level=level or infer_level(merged, len(files)),
        )

    def to_public(self) -> dict[str, Any]:
        return {
            "login": self.login,
            "level": self.level,
            "contributions": self.contributions,
            "merged": self.merged,
            "first_contribution_at": self.first_at,
            "last_contribution_at": self.last_at,
            "skills": as_public(self.skills),
            "top_directories": [{"path": path or "(root)", "changes": count} for path, count in self.directories.most_common(8)],
            "interests": self.interests,
        }


def infer_level(merged_contributions: int, distinct_files: int = 0) -> str:
    if merged_contributions >= 15 or distinct_files >= 60:
        return "advanced"
    if merged_contributions >= 3 or distinct_files >= 10:
        return "intermediate"
    return "beginner"


def file_affinity(profile: ContributorProfile, predicted_files: Sequence[Mapping[str, Any]], top: int = 5) -> float:
    if not predicted_files or not profile.files:
        return 0.0
    score = 0.0
    total = 0.0
    for item in predicted_files[:top]:
        weight = float(item.get("relative_confidence") or 1.0 / top)
        path = str(item["path"])
        directory = path.rsplit("/", 1)[0] if "/" in path else ""
        familiarity = 1.0 if profile.files.get(path) else (0.5 * min(1.0, profile.directories.get(directory, 0) / 2) if directory in profile.directories else 0.0)
        score += weight * familiarity
        total += weight
    return float(score / total) if total else 0.0


def difficulty_fit(level: str, distribution: Mapping[str, float] | None) -> float:
    distribution = distribution or {"Easy": 1 / 3, "Medium": 1 / 3, "Hard": 1 / 3}
    weights = LEVEL_FIT.get(level, LEVEL_FIT["intermediate"])
    return float(sum(w * distribution.get(name, 0.0) for w, name in zip(weights, ("Easy", "Medium", "Hard"))))


def score_contributor_for_issue(
    profile: ContributorProfile,
    issue_skills: Mapping[str, Mapping[str, Any]],
    predicted_files: Sequence[Mapping[str, Any]],
    issue_embedding: np.ndarray | None,
    difficulty_distribution: Mapping[str, float] | None,
    success_probability: float | None = None,
    weights: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    weights = dict(weights or DEFAULT_RECOMMENDATION_WEIGHTS)
    skill = match_skills(profile.skills, issue_skills) if issue_skills else {"score": 0.0, "matched": [], "gaps": []}
    semantic = 0.0
    if issue_embedding is not None and profile.centroid is not None:
        semantic = float(max(0.0, np.dot(profile.centroid, issue_embedding)))
    components = {
        "skill": skill["score"],
        "files": file_affinity(profile, predicted_files),
        "semantic": semantic,
        "success": success_probability if success_probability is not None else 0.5,
        "difficulty_fit": difficulty_fit(profile.level, difficulty_distribution),
    }
    total = sum(weights.get(name, 0.0) for name in components) or 1.0
    return {
        "score": float(sum(weights.get(name, 0.0) * value for name, value in components.items()) / total),
        "components": components,
        "matched_skills": skill["matched"],
        "skill_gaps": skill["gaps"],
    }


def days_between(start: str | None, end: str | None = None) -> float | None:
    if not start:
        return None
    try:
        begin = datetime.fromisoformat(start.replace("Z", "+00:00"))
        finish = datetime.fromisoformat(end.replace("Z", "+00:00")) if end else datetime.now(timezone.utc)
        return max(0.0, (finish - begin).total_seconds() / 86400)
    except ValueError:
        return None


__all__ = ["ContributorProfile", "DEFAULT_RECOMMENDATION_WEIGHTS", "LEVELS", "days_between", "difficulty_fit", "file_affinity", "infer_level", "score_contributor_for_issue"]
