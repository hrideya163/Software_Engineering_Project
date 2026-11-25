"""Copy existing local data into the configured store (Supabase when SUPABASE_URL is set, else SQLite).

    python scripts/migrate_to_store.py            # snapshots + graph metrics + feedback events
    python scripts/migrate_to_store.py --dry-run  # only count what would be copied

What moves:
* data/snapshots/<owner>__<name>/<sha>.json  -> repository_snapshots (current snapshot version only)
  and their graph metrics                     -> repository_metrics (recomputed, ~0.3 s each)
* data/feedback/<user>.jsonl                  -> feedback_events (file renamed to .jsonl.migrated)
Everything else (predictions, analyses, similar issues, explanations, profiles) is created on first use.
Safe to run twice: cache rows are upserts and migrated feedback files are renamed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from contrimap_ml import store  # noqa: E402
from contrimap_ml.codegraph import build_repository_graph, graph_metrics  # noqa: E402
from contrimap_ml.service import GRAPH_VERSION, _jsonable  # noqa: E402
from contrimap_ml.snapshot import SNAPSHOT_VERSION  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    target = store.current()
    print(f"store: {target.name} ({'dry run' if args.dry_run else 'writing'})")
    counts = {"snapshots": 0, "metrics": 0, "skipped_old_snapshots": 0, "feedback_users": 0, "feedback_events": 0, "errors": 0}
    started = time.perf_counter()

    for path in sorted((ROOT / "data" / "snapshots").glob("*/*.json")):
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            counts["errors"] += 1
            continue
        if snapshot.get("version") != SNAPSHOT_VERSION:
            counts["skipped_old_snapshots"] += 1
            continue
        repository = str(snapshot["full_name"]).lower()
        sha = snapshot["sha"]
        written = True
        if not args.dry_run:
            target._down_until = 0  # a failed large upload must not skip the rest of the run
            written = target.put("repository_snapshots", f"{repository}@{sha}:v{SNAPSHOT_VERSION}", snapshot, wait=True, repository=repository, sha=sha)
            metrics = _jsonable(graph_metrics(build_repository_graph(snapshot)))
            target._down_until = 0
            metrics_written = target.put("repository_metrics", f"{repository}@{sha}:g{GRAPH_VERSION}", metrics, wait=True, repository=repository, sha=sha)
            counts["metrics"] += int(metrics_written)
            if not metrics_written:
                counts["errors"] += 1
        else:
            counts["metrics"] += 1
        if not written:
            counts["errors"] += 1
            print(f"  snapshot {repository}@{sha[:10]}: NOT stored")
            continue
        counts["snapshots"] += 1
        print(f"  snapshot {repository}@{sha[:10]} ({snapshot['file_count']:,} files, {len(json.dumps(snapshot)) // 1024:,} KB)")

    for path in sorted((ROOT / "data" / "feedback").glob("*.jsonl")):
        user = path.stem.lower()
        events = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                counts["errors"] += 1
        if not args.dry_run:
            target._down_until = 0
            if not all(target.add_event({**event, "user_id": user}) for event in events):
                print(f"  feedback {user}: store unavailable, left in place")
                counts["errors"] += 1
                continue
            path.replace(path.with_suffix(".jsonl.migrated"))
        counts["feedback_users"] += 1
        counts["feedback_events"] += len(events)
        print(f"  feedback {user}: {len(events)} events")

    counts["seconds"] = round(time.perf_counter() - started, 1)
    counts["store_errors"] = target.stats["errors"]
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
