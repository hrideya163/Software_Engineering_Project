"""Recommendation feedback: opened, saved, dismissed and completed issues per user.

Stored as an append-only event log in the store (Supabase ``feedback_events`` or the local SQLite fallback);
the latest action per issue wins for state. JSON lines under ``data/feedback`` are only a fallback.
Ranking uses it in two ways:
* dismissed issues are hidden and completed ones are marked done;
* a preference vector (mean embedding of saved/completed/opened issues minus dismissed ones) adds a
  "feedback" similarity component, so issues like the ones a user engaged with rank higher.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
FEEDBACK_DIR = Path(os.getenv("CONTRIMAP_FEEDBACK_DIR", ROOT / "data" / "feedback"))
ACTIONS = ("opened", "saved", "unsaved", "dismissed", "restored", "completed")
# Contribution of each action to the preference vector.
ACTION_WEIGHTS = {"completed": 1.0, "saved": 0.8, "opened": 0.25, "dismissed": -0.6}
_LOCK = threading.Lock()
_USER = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _path(user: str) -> Path:
    if not _USER.match(user or ""):
        raise ValueError("Invalid user id.")
    return FEEDBACK_DIR / f"{user.lower()}.jsonl"


_EVENT_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
EVENT_CACHE_SECONDS = 30


def _file_events(user: str) -> list[dict[str, Any]]:
    path = _path(user)
    if not path.exists():
        return []
    with _LOCK:
        lines = path.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _append_file(user: str, event: dict[str, Any]) -> None:
    path = _path(user)
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")


def record(user: str, repository: str, number: int, action: str, title: str = "", text: str = "") -> dict[str, Any]:
    """Append one event to the store (Supabase or SQLite); a local JSON-lines file is the fallback when it is down."""
    from . import store

    if action not in ACTIONS:
        raise ValueError(f"Unknown action {action!r}; expected one of {', '.join(ACTIONS)}.")
    _path(user)  # validates the id
    event = {"time": time.time(), "repository": repository.lower(), "number": int(number), "action": action, "title": title[:300], "text": text[:2000]}
    if not store.current().add_event({**event, "user_id": user.lower()}):
        _append_file(user, event)
    _EVENT_CACHE.pop(user.lower(), None)
    return event


def events(user: str) -> list[dict[str, Any]]:
    """The user's events, oldest first. Events left in JSON-lines files (older versions, or written while the
    store was down) are moved into the store the next time it is reachable."""
    from . import store

    _path(user)
    key = user.lower()
    cached = _EVENT_CACHE.get(key)
    if cached and cached[0] > time.time():
        return cached[1]
    stored = store.current().events(key)
    local = _file_events(user)
    if stored is None:  # store unavailable: the local file is all we have
        return local
    if local:
        moved = all(store.current().add_event({**event, "user_id": key}) for event in local)
        if moved:
            path = _path(user)
            path.replace(path.with_suffix(".jsonl.migrated"))
        stored = sorted(stored + local, key=lambda event: event["time"])
    _EVENT_CACHE[key] = (time.time() + EVENT_CACHE_SECONDS, stored)
    return stored


def state(user: str, repository: str | None = None) -> dict[str, dict[str, Any]]:
    """Per ``repo#number``: saved / dismissed / completed flags and whether it was opened."""
    result: dict[str, dict[str, Any]] = {}
    for event in events(user):
        if repository and event["repository"] != repository.lower():
            continue
        key = f"{event['repository']}#{event['number']}"
        entry = result.setdefault(key, {"repository": event["repository"], "number": event["number"], "title": event.get("title", ""), "opened": False, "saved": False, "dismissed": False, "completed": False, "updated": event["time"]})
        action = event["action"]
        if action == "opened":
            entry["opened"] = True
        elif action in ("saved", "unsaved"):
            entry["saved"] = action == "saved"
        elif action in ("dismissed", "restored"):
            entry["dismissed"] = action == "dismissed"
        elif action == "completed":
            entry["completed"] = True
        entry["updated"] = event["time"]
        entry["title"] = event.get("title") or entry["title"]
    return result


def summary(user: str) -> dict[str, Any]:
    items = list(state(user).values())
    return {
        "user": user,
        "counts": {flag: sum(1 for item in items if item[flag]) for flag in ("opened", "saved", "dismissed", "completed")},
        "saved": sorted([item for item in items if item["saved"] and not item["completed"]], key=lambda item: -item["updated"]),
        "completed": sorted([item for item in items if item["completed"]], key=lambda item: -item["updated"]),
    }


def preference_vector(user_events: Sequence[Mapping[str, Any]], embed_fn) -> np.ndarray | None:
    """Weighted mean of embeddings of issues the user acted on (latest action per issue)."""
    latest: dict[str, Mapping[str, Any]] = {}
    for event in user_events:
        if event["action"] in ACTION_WEIGHTS and event.get("text"):
            key = f"{event['repository']}#{event['number']}"
            # completed/saved/dismissed outrank a later "opened" of the same issue
            if key in latest and ACTION_WEIGHTS[latest[key]["action"]] ** 2 > ACTION_WEIGHTS[event["action"]] ** 2:
                continue
            latest[key] = event
    if not latest:
        return None
    items = list(latest.values())
    vectors = embed_fn([item["text"] for item in items])
    weights = np.asarray([ACTION_WEIGHTS[item["action"]] for item in items], dtype="float32")
    if not np.any(weights > 0):
        return None
    vector = (weights[:, None] * vectors).sum(axis=0)
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 1e-9 else None


__all__ = ["ACTIONS", "events", "preference_vector", "record", "state", "summary"]
