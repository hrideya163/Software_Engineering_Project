"""Break one cold ranked-issues computation into its parts (in-process, fresh interpreter).

    python scripts/profile_service.py pallets/click
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from contrimap_ml import service  # noqa: E402
from contrimap_ml.textfeat import embed  # noqa: E402

repo = sys.argv[1] if len(sys.argv) > 1 else "pallets/click"
owner, name = repo.split("/")
marks: list[tuple[str, float]] = []


def mark(label: str, start: float) -> float:
    now = time.perf_counter()
    marks.append((label, now - start))
    print(f"{label:48} {now - start:7.3f}s", flush=True)
    return now


t = time.perf_counter()
service.models()
t = mark("load trained models (joblib)", t)
embed(["warm up"], cache=False)
t = mark("load MiniLM embedder", t)
context = service.repository_context(owner, name)
t = mark("repository context (tree + snapshot + graph)", t)
issues = service.list_issues(owner, name, limit=40)
t = mark("GitHub: list open issues", t)
texts = [f"{i['title']}\n{i.get('body') or ''}".strip() for i in issues]
embeddings = embed(texts, cache=False)
t = mark(f"embed {len(issues)} issues", t)
localized = service._localize_many(repo, context, issues, embeddings, top_k=5)
t = mark("localize (stage 1 + code read + stage 2)", t)
service._difficulty_batch(issues, embeddings, [signals for _, signals in localized])
t = mark("difficulty and effort", t)
