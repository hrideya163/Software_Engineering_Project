# ContriMap Repository Understanding Architecture

## Purpose

The repository-understanding pipeline turns source snapshots, contribution history, and issue metadata into a structured mining representation that can be scored, explained, and consumed by the supervised ML models already shipped in `contrimap_ml`.

## Components

1. Snapshot builder
   - Normalizes repository files and metadata into a shared `RepositorySnapshot` object.
   - Captures dependency manifests, source files, tests, docs, contributors, and historical PR/issue payloads.
2. Mining representation
   - Flattens snapshot data into `NormalizedMiningRecord` entries.
   - Keeps a canonical file list, labels, and graph-related context while preserving the older issue/PR JSONL contract used for model training.
3. Knowledge graph
   - Materializes a NetworkX directed graph with repository, issue, PR, contributor, label, and file nodes.
   - Stores edges such as `contains`, `changes`, `imports`, and `tagged_with`.
4. Graph-aware features
   - Aggregates centrality and connectivity stats from the graph into feature vectors consumed by the tabular model pipeline.
   - These features are additive and optional so existing artifact formats remain compatible.
5. Model training and evaluation
   - Reuses the existing LightGBM/XGBoost training flow and chronologically split historical dataset.
   - Preserves the public `train_models()` API and output artifact naming while exposing richer evaluation metadata.
6. Ranking and explanation
   - Ranks files and issues against a query using text relevance and graph connectivity.
   - Produces summary explanations that describe why a prediction or ranking was reached.

## Serialization

The repository graph is persisted as a JSON adjacency payload; older model artifacts remain readable because metadata is optional and the original `tabular_models.joblib` + `localization.json` contract stays intact.

## Operational notes

- The pipeline is intentionally additive: the legacy CLI commands `ingest`, `train`, and `predict` are retained.
- Training still uses historical time splits to avoid leakage across repositories or future PRs.
- Explanation and ranking components do not replace the underlying model; they interpret it.
