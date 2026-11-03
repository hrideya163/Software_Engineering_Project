"""Contribution paths, user profiles, learning opportunities and personalised ranking."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from .recommendation import LEVEL_FIT, difficulty_fit
from .skills import SKILLS, TAXONOMY, match_skills, skill_name, skills_from_text

# ---------------------------------------------------------------------------
# User profile (explicit preferences, optionally merged with GitHub history)
# ---------------------------------------------------------------------------
_ALIASES = {skill.name.lower(): skill.id for skill in TAXONOMY} | {skill.id: skill.id for skill in TAXONOMY} | {
    "js": "javascript", "ts": "typescript", "node": "node", "nodejs": "node", "golang": "go", "c++": "cpp", "c#": "csharp",
    "next": "nextjs", "next.js": "nextjs", "ml": "machine_learning", "docs": "documentation", "tests": "testing", "ci": "ci_cd",
    "css": "html_css", "html": "html_css", "frontend": "ui", "front-end": "ui", "backend": "api_design", "devops": "devops_cloud",
}


def resolve_skills(values: Iterable[str]) -> list[str]:
    """Map free-text stack/goal entries ("React", "type hints") to taxonomy ids."""
    resolved: list[str] = []
    for value in values:
        key = str(value).strip().lower()
        if not key:
            continue
        if key in _ALIASES:
            resolved.append(_ALIASES[key])
            continue
        hits = skills_from_text(key)
        resolved.extend(sorted(hits, key=lambda skill_id: -hits[skill_id]["weight"])[:2])
    return list(dict.fromkeys(resolved))


@dataclass
class UserProfile:
    level: str = "intermediate"
    tech_stack: list[str] = field(default_factory=list)
    interests: list[str] = field(default_factory=list)
    learning_goals: list[str] = field(default_factory=list)
    time_budget_hours: float | None = None
    login: str | None = None
    history_skills: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "UserProfile":
        data = data or {}
        level = str(data.get("level") or data.get("skill_level") or "intermediate").lower()
        return cls(
            level=level if level in LEVEL_FIT else "intermediate",
            tech_stack=list(data.get("tech_stack") or data.get("techStack") or []),
            interests=list(data.get("interests") or []),
            learning_goals=list(data.get("learning_goals") or data.get("learningGoals") or []),
            time_budget_hours=float(data["time_budget_hours"]) if data.get("time_budget_hours") else None,
            login=data.get("login"),
        )

    def skill_vector(self) -> dict[str, dict[str, Any]]:
        base = {"beginner": 0.45, "intermediate": 0.7, "advanced": 0.9}[self.level]
        vector = {skill_id: {"weight": base, "evidence": ["declared in profile"]} for skill_id in resolve_skills(self.tech_stack)}
        for skill_id, entry in self.history_skills.items():
            current = vector.get(skill_id, {"weight": 0.0, "evidence": []})
            vector[skill_id] = {"weight": max(current["weight"], entry["weight"]), "evidence": current["evidence"] + entry.get("evidence", [])[:2]}
        return vector

    def goal_skills(self) -> list[str]:
        return resolve_skills(self.learning_goals)

    def to_public(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "login": self.login,
            "tech_stack": [{"id": s, "name": skill_name(s)} for s in resolve_skills(self.tech_stack)],
            "interests": self.interests,
            "learning_goals": [{"id": s, "name": skill_name(s)} for s in self.goal_skills()],
            "time_budget_hours": self.time_budget_hours,
        }


# ---------------------------------------------------------------------------
# Learning opportunity
# ---------------------------------------------------------------------------
# Desired difficulty for growth: one notch above comfort ("zone of proximal development").
_STRETCH = {"beginner": (0.55, 0.9, 0.15), "intermediate": (0.25, 0.75, 0.85), "advanced": (0.1, 0.5, 1.0)}


def learning_opportunity(profile: UserProfile, issue_skills: Mapping[str, Mapping[str, Any]], distribution: Mapping[str, float] | None, success_probability: float | None = None) -> dict[str, Any]:
    known = profile.skill_vector()
    goals = profile.goal_skills()
    required = {skill_id: float(entry["weight"]) for skill_id, entry in issue_skills.items()}
    goal_coverage = sum(required.get(goal, 0.0) for goal in goals) / max(len(goals), 1) if goals else 0.0
    novel = [skill_id for skill_id, weight in required.items() if weight >= 0.4 and known.get(skill_id, {}).get("weight", 0.0) < 0.35]
    novelty = min(1.0, len(novel) / 3)
    distribution = distribution or {"Easy": 1 / 3, "Medium": 1 / 3, "Hard": 1 / 3}
    stretch = sum(w * distribution.get(name, 0.0) for w, name in zip(_STRETCH[profile.level], ("Easy", "Medium", "Hard")))
    achievable = 0.5 * difficulty_fit(profile.level, distribution) + 0.5 * (success_probability if success_probability is not None else 0.6)
    # Goal alignment dominates when goals exist; otherwise novelty drives exploration.
    alignment = goal_coverage if goals else 0.5 * novelty
    score = (0.5 * alignment + 0.2 * novelty + 0.3 * stretch) * (0.4 + 0.6 * achievable)
    return {
        "score": float(min(1.0, score)),
        "goal_coverage": float(goal_coverage),
        "new_skills": [{"id": s, "name": skill_name(s)} for s in novel[:4]],
        "practised_goals": [{"id": g, "name": skill_name(g)} for g in goals if required.get(g, 0.0) >= 0.3],
        "stretch": float(stretch),
        "achievability": float(achievable),
    }


def personal_components(profile: UserProfile, issue_skills: Mapping[str, Mapping[str, Any]], distribution: Mapping[str, float] | None, issue_embedding: np.ndarray | None, interest_embedding: np.ndarray | None, success_probability: float | None) -> dict[str, Any]:
    stack = match_skills(profile.skill_vector(), issue_skills) if issue_skills else {"score": 0.0, "matched": [], "gaps": []}
    interest = float(max(0.0, np.dot(issue_embedding, interest_embedding))) if issue_embedding is not None and interest_embedding is not None else 0.0
    learning = learning_opportunity(profile, issue_skills, distribution, success_probability)
    # Cosine similarity of short interests vs issues rarely exceeds ~0.6; rescale to [0, 1].
    return {
        "components": {
            "stack_match": stack["score"],
            "interest": float(min(1.0, interest / 0.6)),
            "difficulty_fit": difficulty_fit(profile.level, distribution),
            "learning": learning["score"],
            "success": success_probability if success_probability is not None else 0.5,
        },
        "matched_skills": stack["matched"],
        "skill_gaps": stack["gaps"],
        "learning": learning,
    }


PERSONAL_WEIGHTS = {
    "actionability": 0.12, "approachability": 0.0, "clarity": 0.08, "focus": 0.05, "availability": 0.10, "freshness": 0.05, "community": 0.03,
    "stack_match": 0.17, "interest": 0.12, "difficulty_fit": 0.12, "learning": 0.10, "success": 0.06,
}


def personal_weights(profile: UserProfile, mode: str = "balanced") -> dict[str, float]:
    weights = dict(PERSONAL_WEIGHTS)
    if mode == "learning":
        weights.update({"learning": 0.30, "stack_match": 0.08, "difficulty_fit": 0.10})
    elif mode == "quick_win":
        weights.update({"difficulty_fit": 0.20, "success": 0.12, "learning": 0.03, "stack_match": 0.20})
    return weights


# ---------------------------------------------------------------------------
# Contribution path
# ---------------------------------------------------------------------------
def detect_commands(files: Sequence[str], manifests: Mapping[str, str] | None = None) -> dict[str, list[str]]:
    names = {PurePosixPath(path).name for path in files if "/" not in path}
    manifests = manifests or {}
    install, test, lint = [], [], []
    package_json = manifests.get("package.json")
    scripts: dict[str, str] = {}
    if package_json:
        try:
            scripts = json.loads(package_json).get("scripts") or {}
        except ValueError:
            scripts = {}
    if "package.json" in names:
        runner = "pnpm" if "pnpm-lock.yaml" in names else "yarn" if "yarn.lock" in names else "npm"
        install.append(f"{runner} install")
        if "test" in scripts or not scripts:
            test.append(f"{runner} test" if runner != "npm" else "npm test")
        if "lint" in scripts:
            lint.append(f"{runner} run lint")
    if names & {"pyproject.toml", "setup.py", "setup.cfg", "requirements.txt"}:
        install.append("python -m venv .venv && pip install -e .[dev]" if names & {"pyproject.toml", "setup.py"} else "pip install -r requirements.txt")
        test.append("tox" if "tox.ini" in names else "pytest")
        if ".pre-commit-config.yaml" in names:
            lint.append("pre-commit run --all-files")
    if "go.mod" in names:
        install.append("go mod download")
        test.append("go test ./...")
        lint.append("go vet ./...")
    if "Cargo.toml" in names:
        install.append("cargo build")
        test.append("cargo test")
        lint.append("cargo clippy")
    if "Gemfile" in names:
        install.append("bundle install")
        test.append("bundle exec rake test" if "Rakefile" in names else "bundle exec rspec")
    if "composer.json" in names:
        install.append("composer install")
        test.append("vendor/bin/phpunit")
    if "pom.xml" in names:
        install.append("mvn -q install -DskipTests")
        test.append("mvn test")
    if names & {"build.gradle", "build.gradle.kts"}:
        test.append("./gradlew test")
    if "Makefile" in names and not test:
        test.append("make test")
    return {"install": install, "test": test, "lint": lint}


def _focused_test_command(test_commands: list[str], tests: list[str]) -> str | None:
    if not tests:
        return None
    first = tests[0]
    if first.endswith(".py"):
        return f"pytest {first}"
    if first.endswith((".js", ".ts", ".tsx", ".jsx", ".mjs")):
        return f"{test_commands[0]} -- {first}" if test_commands else None
    if first.endswith(".go"):
        parent = str(PurePosixPath(first).parent)
        return "go test ./..." if parent == "." else f"go test ./{parent}/..."
    if first.endswith(".rs"):
        return f"cargo test --test {PurePosixPath(first).stem}" if "/tests/" in f"/{first}" else "cargo test"
    if first.endswith("_spec.rb"):
        return f"bundle exec rspec {first}"
    return None


def reading_order(files: Sequence[Mapping[str, Any]], graph: Any | None, metrics: Mapping[str, Any] | None) -> list[dict[str, str]]:
    """Dependencies of the top targets first (core abstractions), then targets, then their callers."""
    targets = [item["path"] for item in files[:3]]
    pagerank = (metrics or {}).get("pagerank") or {}
    order: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(path: str, why: str) -> None:
        if path not in seen:
            seen.add(path)
            order.append({"path": path, "why": why})

    if graph is not None:
        for target in targets:
            if target not in graph:
                continue
            dependencies = sorted((v for _, v, d in graph.out_edges(target, data=True) if d.get("type") == "imports"), key=lambda node: -pagerank.get(node, 0.0))[:2]
            for dependency in dependencies:
                add(dependency, f"core module imported by {PurePosixPath(target).name}")
    for target in targets:
        add(target, "likely needs the change")
    if graph is not None and targets and targets[0] in graph:
        callers = sorted((u for u, _, d in graph.in_edges(targets[0], data=True) if d.get("type") == "imports"), key=lambda node: -pagerank.get(node, 0.0))[:2]
        for caller in callers:
            add(caller, "uses the target - check behaviour is preserved")
    return order[:7]


def contribution_path(issue: Mapping[str, Any], analysis: Mapping[str, Any], snapshot: Mapping[str, Any] | None = None, graph: Any | None = None, metrics: Mapping[str, Any] | None = None, profile: UserProfile | None = None, manifests: Mapping[str, str] | None = None) -> dict[str, Any]:
    snapshot = snapshot or {}
    files = list(analysis.get("files") or [])
    commands = detect_commands(snapshot.get("files") or [], manifests)
    tests = list(analysis.get("related_tests") or [])
    number = issue.get("number")
    steps: list[dict[str, Any]] = []
    gaps = analysis.get("skill_gaps") or []
    if gaps:
        prerequisites = []
        for gap in gaps[:3]:
            prerequisites.extend(skill_name(pre) for pre in (SKILLS[gap["id"]].prerequisites if gap["id"] in SKILLS else ()))
        steps.append({"id": "learn", "title": "Fill skill gaps first", "detail": "Brush up on " + ", ".join(g["name"] for g in gaps[:3]) + (f" (builds on {', '.join(dict.fromkeys(prerequisites))})" if prerequisites else "") + ".", "skills": [g["name"] for g in gaps[:3]]})
    setup_reads = [path for path in (snapshot.get("contributing"), snapshot.get("readme")) if path]
    steps.append({"id": "setup", "title": "Set up the project locally", "detail": "Fork and clone the repository" + (f", read {' and '.join(setup_reads)}" if setup_reads else "") + ".", "commands": commands["install"]})
    order = reading_order(files, graph, metrics)
    if order:
        steps.append({"id": "understand", "title": "Read the relevant code", "detail": "Suggested reading order, from the abstractions the fix builds on to the code that calls it.", "files": order})
    reproduce_command = _focused_test_command(commands["test"], tests)
    steps.append({"id": "reproduce", "title": "Reproduce the problem with a test", "detail": (f"Start from the existing tests in {', '.join(tests[:2])}." if tests else "Write a failing test that captures the issue before changing code."), "commands": [reproduce_command] if reproduce_command else commands["test"][:1]})
    if files:
        steps.append({"id": "implement", "title": "Implement the change", "detail": f"Begin in {files[0]['path']}" + (f"; {files[1]['path']} is the next most likely location" if len(files) > 1 else "") + ". Keep the change focused on the issue.", "files": [item["path"] for item in files[:3]]})
    impact = (analysis.get("impact") or {}).get("dependents_within_2_hops")
    steps.append({"id": "verify", "title": "Run the full checks", "detail": "Run the test suite and linters" + (f"; {impact} files depend on the changed code, so watch for regressions" if impact else "") + ".", "commands": commands["test"] + commands["lint"]})
    steps.append({"id": "submit", "title": "Open the pull request", "detail": f"Describe the change, link the issue with “Fixes #{number}”, and mention the tests you added." if number else "Describe the change and the tests you added."})
    budget = profile.time_budget_hours if profile else None
    effort = analysis.get("effort_hours")
    fits_budget = None if budget is None or effort is None else bool(effort <= budget)
    return {"steps": steps, "commands": commands, "estimated_hours": effort, "fits_time_budget": fits_budget}


__all__ = ["PERSONAL_WEIGHTS", "UserProfile", "contribution_path", "detect_commands", "learning_opportunity", "personal_components", "personal_weights", "reading_order", "resolve_skills"]
