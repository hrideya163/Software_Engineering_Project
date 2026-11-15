# Architecture

## Components

| Layer | Module | Role |
|---|---|---|
| Data | `corpus.py` | Unified multi-repository corpus (SWE-bench train/dev/test/Verified/Multilingual + cleaned next.js). |
| | `ingest.py` | GraphQL ingestion of issue-closing PRs for any repository (authoritative `closingIssuesReferences`). |
| | `repo_trees.py` | Blobless shallow git fetches: file trees at any commit (many commits per request) and batched file contents (`prefetch_blobs` for many shortlists at once), no API token. |
| | `prepare_data.py` | Fetches the base-commit trees that localization training/evaluation needs (all eval issues + a capped, seeded train sample). |
| | `snapshot.py` → `build_git_snapshot` | Immutable per-commit snapshot: files, imports, test links, manifests, packages, skills. |
| Graph | `codegraph.py` | Import resolution (Python, JS/TS, Go, Rust, Java/Kotlin, C/C++, Ruby, PHP), NetworkX knowledge graph, PageRank / Louvain / betweenness / impact radius, visualizer views. |
| Models | `difficulty.py` | Difficulty classifier (TF-IDF LR + LightGBM on embeddings, blended), change-size regressor, effort calibrated on human labels; optional *structural* heads that add localization/code signals. |
| | `localization.py` | Two-stage learning-to-rank. Stage 1: LightGBM LambdaRank over every file with lexical, semantic, mention, history and structural features. Stage 2: re-ranks the top 50 after reading their code. Also produces `LOC_SIGNALS` (where the fix lands) for difficulty/effort. |
| | `code_features.py` | Code-reading features: symbols the issue names that a file *defines* or uses, quoted error strings found in the file, BM25 over identifiers and definition names, file size. |
| | `issue_ranking.py` | Actionability classifier + transparent ranking components. |
| | `success.py` | Calibrated P(PR merged) from point-in-time contributor history and contribution intent. |
| | `skills.py` | Skill taxonomy, extraction from text/paths/manifests/history, weighted skill matching with prerequisites. |
| | `recommendation.py` | Contributor profiles and contributor–issue scoring. |
| | `guidance.py` | User profiles, learning-opportunity scoring, personalised weights, contribution paths. |
| | `llm.py` | Grounded Claude explanations with validated file references and a template fallback. |
| Serving | `service.py` | Single-flight TTL cache, background repository preparation with progress, GitHub access with ETag conditional requests (falls back to anonymous on a bad token, serves stale data when rate-limited), model orchestration. |
| | `api.py` | FastAPI routes (also serves the built frontend in Docker). |
| Training | `train_v2.py`, `recommendation_eval.py`, `report.py`, `compare_localization.py` | End-to-end training, evaluation and report rendering; side-by-side comparison of saved localization models on cached splits (with and without history). |
| Legacy | `models.py`, `features.py`, `inference.py`, … | v1 pipeline kept for reproducibility of the original baseline. |

## Request flow: issue analysis

0. The page first calls `POST /prepare` and polls `GET /status`: `repository_context` runs in a background thread and reports each stage (file tree, downloads, imports, graph, metrics); the frontend's `RepositoryGate` shows them.
1. `repository_context` → `build_git_snapshot` (cached per commit) → `build_repository_graph` → `graph_metrics` (single-flight: concurrent requests share one build).
2. Issue text → MiniLM embedding.
3. Localization stage 1 ranks all snapshot files (history features if the repository has ingested/corpus history); the code of the top 50 is downloaded (one git request for all issues on the ranked-issues page) and stage 2 re-ranks them. Without network access to blobs it degrades to stage 1.
4. Difficulty/effort from the issue text plus the localization signals (`DifficultyModel.predict_frame(..., loc_signals=...)`); the response says which inputs were used (`difficulty_inputs`).
5. Skills from text + predicted files + repository stack; related tests from `tests` edges; impact radius from reverse imports.
6. Optional profile → stack match, interest similarity, difficulty fit, learning opportunity, success probability.
7. Contribution path (commands detected from manifests, dependency-aware reading order) and grounded explanation.
8. Views: issue neighbourhood graph, highlighted file tree, architecture highlights.

## Design choices

- **Not everything is a trained model.** Ranking weights, availability/freshness rules, skill taxonomy, contribution paths and graph algorithms are transparent rules; models are used where labelled data exists (difficulty, effort, localization, actionability, success).
- **Git instead of the REST API for code.** Trees and blobs come from blobless shallow fetches, so repository analysis works without a token and without rate limits.
- **Point-in-time everywhere.** History features, contributor history and success features only use events before the prediction time.
- **Read code only where it pays.** Reading every file of a large repository per issue is too slow and too much traffic; stage 1 narrows to 50 candidates, whose contents are fetched in one batched partial-clone request and cached in the local object store.
- **Stacking, not retraining, for structural difficulty.** The text model keeps all 18k training issues; a small stacker on its out-of-fold probabilities adds the localization/code signals, which exist only for issues with fetched trees.

## Operations

- `CONTRIMAP_READ_CODE=0` disables stage 2 at inference (no blob downloads).
- `CONTRIMAP_PROFILE_PR_FILES` (default 8) - how many merged PRs per contributor profile have their changed files fetched (skipped when the anonymous GitHub quota is low).
- `/api/health` reports the remaining GitHub quota, whether models loaded and whether code reading is on; the Docker image has a `HEALTHCHECK` on it.
- CI (`.github/workflows/ci.yml`): Python tests, frontend build, and a Docker build that starts the container and checks `/api/health` and the served frontend.
