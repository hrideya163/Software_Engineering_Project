import json
from pathlib import Path

from contrimap_ml import (
    build_knowledge_graph,
    build_snapshot_from_directory,
    generate_explanation,
    normalize_snapshot,
    rank_repository_items,
    save_knowledge_graph,
    save_snapshot,
    train_models,
)

ROOT = Path(__file__).parent
DATASET = ROOT / "data" / "historical_contributions.jsonl"
OUTPUT = ROOT / "artifacts"

# Use the current repository as the source snapshot.
# For a separate cloned target repository, replace ROOT with that path.
snapshot = build_snapshot_from_directory(ROOT)

# Add the existing historical records to the snapshot.
records = [
    json.loads(line)
    for line in DATASET.read_text(encoding="utf-8").splitlines()
    if line.strip()
]

snapshot.issues = records
snapshot.pull_requests = [
    {
        "number": record["pr_number"],
        "title": record["pr_title"],
        "body": record["pr_body"],
        "changed_files": record["changed_files"],
        "merged_at": record["pr_merged_at"],
    }
    for record in records
]

snapshot_path = save_snapshot(snapshot, OUTPUT / "repository_snapshot.json")

graph = build_knowledge_graph(snapshot.to_dict())
graph_path = save_knowledge_graph(graph, OUTPUT / "knowledge_graph.json")

normalized_records = normalize_snapshot(snapshot.to_dict())
print(f"Normalized mining records: {len(normalized_records)}")
print(f"Graph nodes: {graph.number_of_nodes()}")
print(f"Graph edges: {graph.number_of_edges()}")

# Train using graph-aware features.
metrics = train_models(
    DATASET,
    OUTPUT,
    graph=graph,
)

metrics_path = OUTPUT / "evaluation_metrics.json"
metrics_path.write_text(
    json.dumps(metrics, indent=2, default=str),
    encoding="utf-8",
)
print(f"Evaluation metrics: {metrics_path}")

print(json.dumps(metrics, indent=2, default=str))

# Rank existing historical issues by a query.
ranked = rank_repository_items(
    snapshot.to_dict(),
    "routing validation middleware",
    graph=graph,
    top_k=10,
)

print(json.dumps(ranked, indent=2, default=str))

# Generate a structured explanation from model/ranking output.
if ranked:
    explanation = generate_explanation(
        {
            "difficulty": "Medium",
            "files": [
                {"path": item.get("path", "")}
                for item in ranked
                if item.get("path")
            ],
        },
        issue_title="Improve router error handling",
        issue_body="Add validation and regression tests for dynamic routing",
        snapshot=snapshot.to_dict(),
        graph=graph,
    )
    print(json.dumps(explanation, indent=2, default=str))

print(f"Snapshot: {snapshot_path}")
print(f"Knowledge graph: {graph_path}")