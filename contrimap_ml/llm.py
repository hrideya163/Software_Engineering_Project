"""Grounded issue explanations with Claude, plus a deterministic fallback.

The LLM only *phrases* what the models already computed: it receives the
difficulty/effort estimates, the ranked candidate files with their evidence
signals, skills, the contribution path and the user's profile, and is told not
to introduce files or facts outside that context.  Returned file references are
validated against the provided candidates; anything else is dropped.

Configuration: ``ANTHROPIC_API_KEY`` (or another SDK credential source) and
optional ``ANTHROPIC_MODEL`` (default ``claude-opus-5-5``).  Without
credentials the template explanation is returned with ``source="template"``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from functools import lru_cache
from typing import Any, Mapping

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
SYSTEM_PROMPT = """You explain GitHub issues to open-source contributors for ContriMap.
You are given model outputs (difficulty, effort, likely files with evidence, skills, a contribution path, and the reader's profile).
Rules:
- Ground every statement in the provided context. Do not invent file paths, APIs, maintainers or project facts.
- Only reference files from the provided candidate list, using their exact paths.
- Model estimates are uncertain; say "likely"/"estimated" where appropriate and never overstate confidence.
- Tailor tone and depth to the reader's skill level and learning goals when a profile is given.
Respond with a single JSON object and nothing else, with keys:
"summary" (2-3 sentences: what the issue asks and why it suits or challenges this reader),
"why_this_difficulty" (1-2 sentences referencing the evidence),
"where_to_start" (list of up to 3 objects {"path": str, "reason": str}),
"approach" (list of 3-6 short imperative steps),
"risks" (list of up to 3 short strings),
"learning_value" (1 sentence on what the reader would learn)."""

_cache: dict[str, dict[str, Any]] = {}


def _context(issue: Mapping[str, Any], analysis: Mapping[str, Any], profile: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        "issue": {"title": issue.get("title"), "body": str(issue.get("body") or "")[:4000], "labels": issue.get("labels") or []},
        "repository": analysis.get("repository"),
        "difficulty": {k: analysis.get(k) for k in ("difficulty", "difficulty_probability", "difficulty_distribution", "confidence")},
        "effort": {k: analysis.get(k) for k in ("effort_hours", "effort_range_hours", "effort_bucket")},
        "candidate_files": [{"path": f["path"], "rank": f.get("rank"), "signals": f.get("signals", [])} for f in (analysis.get("files") or [])[:8]],
        "skills_required": [s.get("name") for s in (analysis.get("skills") or [])[:8]],
        "related_tests": analysis.get("related_tests", [])[:5],
        "contribution_path": [step.get("title") for step in (analysis.get("contribution_path") or {}).get("steps", [])],
        "reader": dict(profile) if profile else None,
    }


def template_explanation(issue: Mapping[str, Any], analysis: Mapping[str, Any], profile: Mapping[str, Any] | None = None) -> dict[str, Any]:
    files = analysis.get("files") or []
    difficulty = analysis.get("difficulty") or "Medium"
    distribution = analysis.get("difficulty_distribution") or {}
    skills = [s.get("name") for s in (analysis.get("skills") or [])[:3]]
    level = (profile or {}).get("level")
    fit = ""
    if level:
        fit = {"beginner": " It is a good fit if you are starting out." if difficulty == "Easy" else " Expect to stretch beyond beginner territory.",
               "intermediate": " It should be within reach for an intermediate contributor." if difficulty != "Hard" else " It is a substantial task even for an intermediate contributor.",
               "advanced": " An experienced contributor should move quickly here." if difficulty != "Hard" else " It suits an experienced contributor."}.get(level, "")
    evidence = []
    if files and "mentioned in issue" in (files[0].get("signals") or []):
        evidence.append(f"the issue directly references {files[0]['path']}")
    if distribution:
        evidence.append(f"the model gives it {distribution.get(difficulty, 0):.0%} probability of being {difficulty.lower()}")
    return {
        "source": "template",
        "summary": f"“{issue.get('title')}” is estimated as {difficulty} (about {analysis.get('effort_bucket', 'unknown effort')}).{fit}" + (f" Relevant skills: {', '.join(skills)}." if skills else ""),
        "why_this_difficulty": ("Estimated from the issue text: " + "; ".join(evidence) + ".") if evidence else "Estimated from the issue text against thousands of resolved issues.",
        "where_to_start": [{"path": f["path"], "reason": ", ".join(f.get("signals") or []) or "ranked highly by the localizer"} for f in files[:3]],
        "approach": [step.get("title") for step in (analysis.get("contribution_path") or {}).get("steps", [])][:6],
        "risks": ["File predictions are estimates; confirm by reading the code before editing."] + (["Low model confidence on difficulty."] if analysis.get("confidence") == "low" else []),
        "learning_value": f"Practice with {', '.join(skills[:2])}." if skills else "Hands-on experience with this codebase.",
    }


@lru_cache(maxsize=1)
def _client():
    import anthropic

    return anthropic.Anthropic()


def _has_credentials() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv("CONTRIMAP_FORCE_LLM"))


def _parse_json(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
        return value if isinstance(value, dict) else None
    except ValueError:
        return None


def explain(issue: Mapping[str, Any], analysis: Mapping[str, Any], profile: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return an explanation dict; never raises (falls back to the template)."""
    fallback = template_explanation(issue, analysis, profile)
    if not _has_credentials():
        return fallback
    context = _context(issue, analysis, profile)
    model = os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)
    key = hashlib.sha1((model + json.dumps(context, sort_keys=True, default=str)).encode()).hexdigest()
    if key in _cache:
        return _cache[key]
    try:
        import anthropic

        response = _client().beta.messages.create(
            model=model,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(context, default=str)}],
            betas=["server-side-fallback-2026-07-01"],
            # Short grounded summarisation: low effort is sufficient; refusals fall back server-side.
            extra_body={"output_config": {"effort": "low"}, "fallbacks": "default"},
            timeout=45.0,
        )
        if response.stop_reason == "refusal":
            logger.warning("LLM explanation refused; using template")
            return fallback
        text = "".join(block.text for block in response.content if block.type == "text")
        parsed = _parse_json(text)
        if not parsed:
            return fallback
    except Exception as error:  # network, auth, rate limit: the template is always a valid answer
        logger.warning("LLM explanation failed (%s); using template", type(error).__name__)
        return fallback
    allowed = {item["path"] for item in context["candidate_files"]}
    starts = [item for item in parsed.get("where_to_start") or [] if isinstance(item, Mapping) and item.get("path") in allowed][:3]
    result = {
        "source": "llm",
        "model": model,
        "summary": str(parsed.get("summary") or fallback["summary"]),
        "why_this_difficulty": str(parsed.get("why_this_difficulty") or fallback["why_this_difficulty"]),
        "where_to_start": starts or fallback["where_to_start"],
        "approach": [str(step) for step in (parsed.get("approach") or [])][:6] or fallback["approach"],
        "risks": [str(risk) for risk in (parsed.get("risks") or [])][:3],
        "learning_value": str(parsed.get("learning_value") or fallback["learning_value"]),
    }
    _cache[key] = result
    return result


__all__ = ["DEFAULT_MODEL", "explain", "template_explanation"]
