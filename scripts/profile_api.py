"""Time the API calls the web app makes, in page order, against a running server.

    python scripts/profile_api.py --repo pallets/click --issue 3914 --out data/profile_before.json

Run it right after starting the API to measure a cold process (repository snapshots may still be on disk),
then again to measure warm caches. Every request is timed end to end; nothing is mocked.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import requests

PROFILE = {"level": "intermediate", "tech_stack": ["Python", "Testing"], "interests": [], "learning_goals": ["type hints"], "time_budget_hours": None, "login": None}


def timed(session: requests.Session, method: str, url: str, **kwargs) -> tuple[float, int, int]:
    start = time.perf_counter()
    response = session.request(method, url, timeout=600, **kwargs)
    return round(time.perf_counter() - start, 3), response.status_code, len(response.content)


def run(base: str, repo: str, issue: int, label: str) -> list[dict]:
    session = requests.Session()
    owner, name = repo.split("/")
    api = f"{base}/api/repos/{owner}/{name}"
    rows = []

    def record(step: str, method: str, url: str, **kwargs) -> None:
        seconds, status, size = timed(session, method, url, **kwargs)
        rows.append({"run": label, "step": step, "seconds": seconds, "status": status, "bytes": size})
        print(f"{label:6} {step:44} {seconds:8.3f}s  {status}  {size:>9,} B", flush=True)

    start = time.perf_counter()
    session.post(f"{api}/prepare", timeout=60)
    while session.get(f"{api}/status", timeout=60).json().get("state") not in ("ready", "error"):
        time.sleep(0.5)
    rows.append({"run": label, "step": "prepare repository (until ready)", "seconds": round(time.perf_counter() - start, 3), "status": 200, "bytes": 0})
    print(f"{label:6} {'prepare repository (until ready)':44} {rows[-1]['seconds']:8.3f}s", flush=True)

    # Dashboard
    record("dashboard: overview", "GET", api)
    record("dashboard: activity", "GET", f"{api}/activity")
    record("dashboard: ranked issues (limit 20)", "GET", f"{api}/issues?limit=20")
    # Issue explorer
    record("explorer: ranked issues (limit 40)", "GET", f"{api}/issues?limit=40")
    # Issue analysis page
    record("analysis: issue analysis", "GET", f"{api}/issues/{issue}/analysis")
    record("analysis: similar history", "GET", f"{api}/issues/{issue}/similar")
    # Visualizer
    record("visualizer: architecture", "GET", f"{api}/architecture")
    record("visualizer: issue picker (limit 30)", "GET", f"{api}/issues?limit=30")
    record("visualizer: directory view", "GET", f"{api}/module?directory=src/click")
    record("visualizer: file inspector", "GET", f"{api}/file?path=src/click/core.py")
    # For You
    record("for you: recommendations", "POST", f"{base}/api/recommendations", json={"profile": PROFILE, "repositories": [repo], "mode": "balanced"})
    record("for you: recommendations (learning)", "POST", f"{base}/api/recommendations", json={"profile": PROFILE, "repositories": [repo], "mode": "learning"})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8001")  # localhost adds about 2 s of IPv6 fallback per connection on Windows
    parser.add_argument("--repo", default="pallets/click")
    parser.add_argument("--issue", type=int, default=3914)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--label", default="")
    args = parser.parse_args()
    rows = run(args.base, args.repo, args.issue, f"{args.label}cold") + run(args.base, args.repo, args.issue, f"{args.label}warm")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(rows, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
