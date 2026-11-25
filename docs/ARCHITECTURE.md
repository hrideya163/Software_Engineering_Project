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
| Intelligence | `history.py` | Similar-issue and resolving-PR retrieval: links merged PRs to issues through closing keywords, hybrid MiniLM + TF-IDF retrieval, similarity-weighted votes for the files past fixes changed; `evaluate_retrieval` measures it on the corpus. |
| | `insights.py` | Visualizer helpers: functions/classes per file (8 language families), name-level symbol usage by importing files, file details, layered module (directory) views with outside neighbours. |
| | `feedback.py` | Recommendation feedback (opened / saved / dismissed / completed) as JSON lines per user; a preference vector from engaged issues feeds a `feedback` ranking component. |
| Serving | `service.py` | Single-flight TTL cache, background repository preparation with progress, GitHub access with ETag conditional requests (falls back to anonymous on a bad token, serves stale data when rate-limited), model orchestration. |
| | `api.py` | FastAPI routes (also serves the built frontend in Docker). |
| | `store.py` | Persistent store: Supabase (PostgREST over HTTPS, service-role key) or local SQLite, behind a small in-memory LRU. Versioned keys (commit SHA, issue-content hash, model version, LLM model, profile hash); a one-minute cool-down keeps the app working when the database is down. Schema in `supabase/migrations/`. |
| | `auth.py` | Optional GitHub / Google sign-in: OAuth with a signed state cookie, stateless HMAC-signed session cookies (survive restarts), revocation on sign-out, open-redirect-safe return paths. |
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
9. On demand (`/similar`, loaded when the *File localization*, *Similar history* or visualizer *Issue impact* views open): the 100 most recently closed issues and merged PRs are indexed, the most similar are returned with the files their PRs changed, and those files are marked on the localization list and the impact graph ("history" badge, or their own column when the localizer did not predict them).

## Frontend structure

- `Page` (non-repository pages) and `AppLayout` (repository pages, with the Overview / Issues / Visualizer rail) share one sticky `Navbar` with the account menu and sign-in notices.
- `AppContext` holds the session and the contributor profile, so every page sees the same state; `useAsync` gives every request a loading state and a retry.
- `utils/graphLayout.js` lays out import graphs in layers (Tarjan components, longest-path layers, barycenter ordering, wrapped tall columns); `utils/graphViews.js` builds the architecture, directory and issue-impact views from API payloads.

## Visualizer

- **Repository architecture**: directory map (`/architecture`) → double-click or "Open this directory" → layered file view of that directory (`/module`), with breadcrumbs, a tests toggle, module colour filters and search. Dashed boxes at the edges are other directories importing or imported by it; clicking one opens it.
- **Issue impact**: predicted files with importers, dependencies, tests, and files changed by similar past fixes.
- **File inspector** (any file click, or `?file=` in the URL): code preview, imports / imported by / tests, defined functions and classes with links to their lines, which importing files use which names, recent commits and related closed issues.
- Large repositories stay readable because each view is capped (30 directories, 40 files per module, 6 neighbours per predicted file) and tall layers wrap into sub-columns.

## Design choices

- **Not everything is a trained model.** Ranking weights, availability/freshness rules, skill taxonomy, contribution paths and graph algorithms are transparent rules; models are used where labelled data exists (difficulty, effort, localization, actionability, success).
- **Git instead of the REST API for code.** Trees and blobs come from blobless shallow fetches, so repository analysis works without a token and without rate limits.
- **Point-in-time everywhere.** History features, contributor history and success features only use events before the prediction time.
- **Read code only where it pays.** Reading every file of a large repository per issue is too slow and too much traffic; stage 1 narrows to 50 candidates, whose contents are fetched in one batched partial-clone request and cached in the local object store.
- **Stacking, not retraining, for structural difficulty.** The text model keeps all 18k training issues; a small stacker on its out-of-fold probabilities adds the localization/code signals, which exist only for issues with fetched trees.

## Operations

- `CONTRIMAP_READ_CODE=0` disables stage 2 at inference (no blob downloads).
- `CONTRIMAP_FEEDBACK_DIR` (default `data/feedback`) - where feedback events are stored. Users are identified by GitHub login when set in the profile, otherwise by a random id kept in the browser; nothing else is stored.
- GitHub request budget for the new views: `/activity` 3-4 requests (cached 30 min), `/similar` 2 + up to 3 (anonymous) or 5 PR-file requests (cached 30 min / 1 day), file inspector 1 commits request (cached 1 h). All go through the ETag cache, so repeats inside the cache window cost nothing.
- `CONTRIMAP_PROFILE_PR_FILES` (default 8) - how many merged PRs per contributor profile have their changed files fetched (skipped when the anonymous GitHub quota is low).
- `/api/health` reports the remaining GitHub quota, whether models loaded and whether code reading is on; the Docker image has a `HEALTHCHECK` on it.
- CI (`.github/workflows/ci.yml`): Python tests, frontend build, and a Docker build that starts the container and checks `/api/health` and the served frontend.

## Caching and persistence

| Data | Key (what invalidates it) | Where |
|---|---|---|
| Default-branch commit | repository; 10-minute expiry | store |
| Snapshot | repository + commit + snapshot version | store (and the on-disk git cache) |
| Graph metrics | repository + commit + graph version | store; the graph itself is rebuilt from the snapshot (< 0.3 s) |
| Issue predictions (embedding, top files, difficulty, effort, readiness) | repository + issue number + issue-content hash + commit + model version | store |
| Issue analysis | the same + profile hash | store |
| Similar issues and PR files | repository + issue number + issue-content hash; 6-hour expiry | store |
| Claude explanation | analysis key + LLM model | store (only real Claude output) |
| Profiles, feedback | user id | store (feedback is an append-only event log) |
| GitHub metadata, issue lists, activity | 5-30 minutes | memory only (ETag-revalidated) |

Model version = hash of the artifact files plus `INFERENCE_VERSION`. Ranked lists are computed once per repository for 40 (or 60) issues and sliced for smaller pages; only new or edited issues are re-predicted. `scripts/profile_api.py` times the page request sequence; `scripts/profile_service.py` breaks one ranking into its parts.
