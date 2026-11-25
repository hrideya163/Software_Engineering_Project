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
"learning_value" (1 sentence on what the reader would learn),
"contribution_guide" (one object per step of the provided contribution_path, same order, {"id": the step's id, "title": short imperative title specific to this issue, "detail": 1-3 sentences of concrete guidance for this step on this issue}). Keep every step id; refer only to the files, tests and commands listed for that step or in the context."""

# Bump when the prompt or output format changes: stored explanations from an older prompt are not reused.
PROMPT_VERSION = 2

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
        "contribution_path": [{key: step.get(key) for key in ("id", "title", "detail", "files", "commands") if step.get(key)} for step in (analysis.get("contribution_path") or {}).get("steps", [])],
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


GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def provider() -> str | None:
    """Which LLM writes explanations: ``LLM_PROVIDER`` if set, else Anthropic when its key is set, else Gemini."""
    chosen = (os.getenv("LLM_PROVIDER") or "").lower()
    has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv("CONTRIMAP_FORCE_LLM"))
    has_gemini = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    if chosen in ("anthropic", "claude"):
        return "anthropic" if has_anthropic else None
    if chosen in ("gemini", "google"):
        return "gemini" if has_gemini else None
    return "anthropic" if has_anthropic else ("gemini" if has_gemini else None)


def active_model() -> str | None:
    """Model name used for explanations (part of the stored explanation key)."""
    name = provider()
    if name == "anthropic":
        return os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)
    if name == "gemini":
        return os.getenv("GEMINI_MODEL", GEMINI_DEFAULT_MODEL)
    return None


def _has_credentials() -> bool:
    return provider() is not None


def _gemini_text(context: Mapping[str, Any], model: str) -> str:
    """One generateContent call over HTTPS (the key stays on the server, sent as a header)."""
    import requests

    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": json.dumps(context, default=str)}]}],
        # Thinking is off: it would spend the output budget (cutting the JSON short) on a grounded rewrite task.
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.3, "maxOutputTokens": 4096, "thinkingConfig": {"thinkingBudget": 0}},
    }
    response = requests.post(GEMINI_URL.format(model=model), json=body, headers={"x-goog-api-key": key}, timeout=45)
    response.raise_for_status()
    data = response.json()
    candidates = data.get("candidates") or []
    if not candidates or (candidates[0].get("finishReason") not in (None, "STOP", "MAX_TOKENS")):
        raise RuntimeError(f"Gemini returned no usable answer ({(candidates[0].get('finishReason') if candidates else data.get('promptFeedback'))})")
    return "".join(part.get("text", "") for part in (candidates[0].get("content") or {}).get("parts") or [])


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
    model = active_model()
    key = hashlib.sha1((model + json.dumps(context, sort_keys=True, default=str)).encode()).hexdigest()
    if key in _cache:
        return _cache[key]
    if provider() == "gemini":
        try:
            parsed = _parse_json(_gemini_text(context, model))
        except Exception as error:  # network, auth, quota, safety block: the template is always a valid answer
            logger.warning("Gemini explanation failed (%s); using template", type(error).__name__)
            return fallback
        if not parsed:
            return fallback
        return _finish(parsed, context, fallback, model, key)
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
    return _finish(parsed, context, fallback, model, key)


def _guide_steps(parsed: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    """Rewritten title/detail per contribution-path step id; unknown ids and empty fields are dropped.

    Files and commands are never taken from the model: the page keeps the ones detected in the repository.
    """
    known = {step.get("id") for step in context.get("contribution_path") or []}
    steps: dict[str, dict[str, str]] = {}
    for item in parsed.get("contribution_guide") or []:
        if not isinstance(item, Mapping) or item.get("id") not in known:
            continue
        title, detail = str(item.get("title") or "").strip(), str(item.get("detail") or "").strip()
        if title or detail:
            steps[str(item["id"])] = {key: value[:600] for key, value in (("title", title[:120]), ("detail", detail)) if value}
    return steps


def _finish(parsed: Mapping[str, Any], context: Mapping[str, Any], fallback: Mapping[str, Any], model: str, key: str) -> dict[str, Any]:
    """Validate the model's JSON: only candidate files may be referenced; missing fields come from the template."""
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
        "guide_steps": _guide_steps(parsed, context),
    }
    _cache[key] = result
    return result


__all__ = ["DEFAULT_MODEL", "PROMPT_VERSION", "active_model", "explain", "explain_with_llm", "provider", "template_explanation"]


# The single entry point that may call an LLM (used by service.explanation when the user asks for it).
explain_with_llm = explain
