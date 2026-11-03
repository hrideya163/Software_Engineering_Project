# Architecture

## Components

| Layer | Module | Role |
|---|---|---|
| Data | `corpus.py` | Unified multi-repository corpus (SWE-bench train/dev/test/Verified/Multilingual + cleaned next.js). |
| | `ingest.py` | GraphQL ingestion of issue-closing PRs for any repository (authoritative `closingIssuesReferences`). |
| | `repo_trees.py` | Blobless shallow git fetches: file trees at any commit and batched file contents, no API token. |
| | `snapshot.py` → `build_git_snapshot` | Immutable per-commit snapshot: files, imports, test links, manifests, packages, skills. |
| Graph | `codegraph.py` | Import resolution (Python, JS/TS, Go, Rust, Java/Kotlin, C/C++, Ruby, PHP), NetworkX knowledge graph, PageRank / Louvain / betweenness / impact radius, visualizer views. |
| Models | `difficulty.py` | Difficulty classifier (TF-IDF LR + LightGBM on embeddings, blended), change-size regressor, effort calibrated on human labels. |
| | `localization.py` | Learning-to-rank (LightGBM LambdaRank) over every file in the repository with lexical, semantic, mention, history and structural features. |
| | `issue_ranking.py` | Actionability classifier + transparent ranking components. |
| | `success.py` | Calibrated P(PR merged) from point-in-time contributor history and contribution intent. |
| | `skills.py` | Skill taxonomy, extraction from text/paths/manifests/history, weighted skill matching with prerequisites. |
| | `recommendation.py` | Contributor profiles and contributor–issue scoring. |
| | `guidance.py` | User profiles, learning-opportunity scoring, personalised weights, contribution paths. |
| | `llm.py` | Grounded Claude explanations with validated file references and a template fallback. |
| Serving | `service.py` | Caching, GitHub access (falls back to anonymous on a bad token), model orchestration. |
| | `api.py` | FastAPI routes (also serves the built frontend in Docker). |
| Training | `train_v2.py`, `recommendation_eval.py`, `report.py` | End-to-end training, evaluation and report rendering. |
| Legacy | `models.py`, `features.py`, `inference.py`, … | v1 pipeline kept for reproducibility of the original baseline. |

## Request flow: issue analysis

1. `repository_context` → `build_git_snapshot` (cached per commit) → `build_repository_graph` → `graph_metrics`.
2. Issue text → MiniLM embedding → difficulty/effort (`DifficultyModel.predict_frame`).
3. Localization ranks all snapshot files (history features if the repository has ingested/corpus history).
4. Skills from text + predicted files + repository stack; related tests from `tests` edges; impact radius from reverse imports.
5. Optional profile → stack match, interest similarity, difficulty fit, learning opportunity, success probability.
6. Contribution path (commands detected from manifests, dependency-aware reading order) and grounded explanation.
7. Views: issue neighbourhood graph, highlighted file tree, architecture highlights.

## Design choices

- **Not everything is a trained model.** Ranking weights, availability/freshness rules, skill taxonomy, contribution paths and graph algorithms are transparent rules; models are used where labelled data exists (difficulty, effort, localization, actionability, success).
- **Git instead of the REST API for code.** Trees and blobs come from blobless shallow fetches, so repository analysis works without a token and without rate limits.
- **Point-in-time everywhere.** History features, contributor history and success features only use events before the prediction time.
