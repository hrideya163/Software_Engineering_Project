# ContriMap

ContriMap helps people find, understand and complete open-source contributions. For any public GitHub repository it:

- shows a **dashboard of trending repositories** with beginner-friendly issues;
- snapshots the repository with git and builds a **knowledge graph** (files, directories, imports, tests, dependencies, skills) with an **interactive architecture visualizer**;
- **ranks open issues** by actionability, approachability, clarity, availability and freshness - or **personally**, by your stack, interests, skill level and learning goals;
- **analyses an issue**: difficulty, effort, the files most likely to change (highlighted on the code graph and file tree), related tests, required skills, a step-by-step **contribution path**, and an LLM-written **explanation** grounded in those outputs;
- builds **contributor profiles** from GitHub activity and recommends issues across several repositories, including **learning opportunities**.

Every model is evaluated on repositories it never saw during training, against baselines - see [docs/EVALUATION.md](docs/EVALUATION.md). [docs/EVALUATION_v2.2.md](docs/EVALUATION_v2.2.md) covers the v2.2 changes (code-reading localization, structural difficulty, no-history evaluation).

## Architecture

```
React + Vite (src/)  ──►  FastAPI  contrimap_ml/api.py  ──►  service.py ──► models (artifacts/v2)
                               └─ auth.py (GitHub / Google    ├─ git trees/blobs (repo_trees.py, no token)
                                  sign-in, signed cookies)    └─ GitHub REST (metadata, issues, trending)
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for modules and data flow, and [docs/DATA.md](docs/DATA.md) for datasets and leakage controls.

## Quick start

```bash
# 1. Python backend
pip install -r requirements-ml.txt
python -m contrimap_ml.train_v2          # downloads nothing; needs data/ (see docs/DATA.md); writes artifacts/v2
uvicorn contrimap_ml.api:app --port 8001

# 2. Frontend
npm install
npm run dev                              # http://localhost:5173/ContriMap-website/
```

Copy `.env.example` to `.env`. A valid `GITHUB_TOKEN` raises the GitHub API limit from 60 to 5,000 requests/hour (repository code itself is read with git and needs no token). `ANTHROPIC_API_KEY` enables Claude-written explanations (`ANTHROPIC_MODEL`, default `claude-opus-5-5`); without it a deterministic template is used.

### Persistent storage (Supabase)

Computed results are stored so they are reused across page loads and backend restarts: repository snapshots and graph metrics (per commit), issue predictions and analyses (per issue content, commit and model version), similar-issue results (6 hours), Claude explanations, contributor profiles and feedback. Keys contain the commit SHA, an issue-content hash and the model version, so a new commit, an edited issue or retrained models never serve stale results.

1. Create a Supabase project and run both files in `supabase/migrations/` in order in its SQL editor (or `supabase db push`): the tables, then the grants that let the backend's secret key use them.
2. Set `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in `.env` (backend only; row level security blocks browser keys).
3. Optionally copy existing local data: `python scripts/migrate_to_store.py`.

Without Supabase the same tables live in a local SQLite file (`data/contrimap_store.sqlite3`); if Supabase becomes unreachable the backend keeps working from memory and retries after a minute. `GET /api/health` reports the store and its hit counts.

An LLM, Claude (`ANTHROPIC_API_KEY`) or Gemini (`GEMINI_API_KEY`, model `gemini-2.5-flash`), is used only to write an issue's summary and contribution guidance when the user presses *Explain with …* on an issue page; the result is stored and reused. Every other page, and every prediction, works without it.

Sign-in is optional and served by the same API (`contrimap_ml/auth.py`). Set `GITHUB_OAUTH_CLIENT_ID`/`GITHUB_OAUTH_CLIENT_SECRET` and/or `GOOGLE_OAUTH_CLIENT_ID`/`GOOGLE_OAUTH_CLIENT_SECRET`, with callback URLs `http://localhost:8001/api/auth/github/callback` and `.../google/callback`. Sessions are HMAC-signed cookies (14 days) that survive server restarts; signing out revokes the session. Without credentials the *Sign in* button is hidden and everything works signed-out.

### Docker

```bash
docker compose up --build                # http://localhost:8001 (frontend + API + sign-in)
```

## Training and evaluation

```bash
python -m contrimap_ml.prepare_data      # base-commit file trees for training/evaluation (git, no token; ~15 min)
python -m contrimap_ml.train_v2 --stages difficulty,localization,success,actionability,recommendation
python -m contrimap_ml.report            # regenerates docs/EVALUATION.md from the measured report
python -m pytest contrimap_ml -q         # unit + API tests (no network needed)
```

The localization stage also trains the stage-2 code re-ranker (reads the top-50 files of each shortlist; `--no-rerank` skips it) and writes per-issue localization signals that the difficulty stage stacks on the text model. Both are kept only if they beat the simpler model on dev / grouped CV.

Multi-repository ingestion of fresh data (requires `GITHUB_TOKEN`):

```bash
python -m contrimap_ml.ingest pallets/flask fastapi/fastapi --since 2023-01-01 --max-prs 400
```

Ingested repositories automatically provide history features (similar past issues, change frequency) to localization at inference time.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/trending?language=` | trending repositories with good-first-issues |
| POST · GET | `/api/repos/{o}/{r}/prepare` · `/status` | start the snapshot + graph build in the background; poll its stage and progress |
| GET | `/api/repos/{o}/{r}` | overview: languages, skills, core files, structure |
| GET / POST | `/api/repos/{o}/{r}/issues` · `/issues/ranked` | ranked issues (POST with `profile`, `mode`; `user` applies that user's feedback) |
| GET / POST | `/api/repos/{o}/{r}/issues/{n}/analysis` | full issue analysis (POST adds personal fit) |
| POST | `/api/repos/{o}/{r}/analyze` | analyse draft issue text |
| GET | `/api/repos/{o}/{r}/architecture` · `/tree` | visualizer payloads |
| GET | `/api/repos/{o}/{r}/module?directory=&tests=&issue=` | one directory's files in import layers, with outside importers/dependencies |
| GET | `/api/repos/{o}/{r}/file?path=` | file inspector: code preview, imports, dependents, tests, functions/classes and which files use them, recent commits |
| GET | `/api/repos/{o}/{r}/issues/{n}/similar` | similar closed issues and merged PRs, the files their fixes changed, agreement with the localizer |
| GET | `/api/repos/{o}/{r}/activity` | repository health: weekly commits, maintainer spread, PR merge speed and acceptance, issue responsiveness |
| POST · GET | `/api/feedback` · `/api/feedback/{user}` | record opened / saved / dismissed / completed issues; summary per user |
| POST | `/api/repos/{o}/{r}/learning` | learning-opportunity ranking |
| GET | `/api/contributors/{login}` | contributor profile and extracted skills |
| POST | `/api/recommendations` | personalised issues across repositories |
| GET | `/api/model-card` | evaluation report |

Legacy `/api/predict`, `/api/analyze` and `/api/repositories/issues` remain available (`contrimap_ml.inference_api:app` still works).

## Known limitations

- **Effort** estimates from issue text are weak (Spearman ≈ 0.12-0.16 with human time-to-fix; bucket accuracy barely above the majority baseline). Neither a 3x larger embedder (BGE-large) nor 5k more training PRs changed this. Estimates are shown as buckets with ranges, never as precise hours.
- **Difficulty** generalises across repositories (macro-F1 0.41 vs 0.32 random; 0.37 vs 0.33 across 9 unseen languages after adding 17 multi-language training repositories) but per-issue confidence is often low; text-only difficulty appears close to its ceiling. Adding where-the-fix-lands signals from localization and code reading improved rank correlation with fix size and human time-to-fix, but not class accuracy on dev, so it is not used.
- **Localization** reads the code of its top 50 candidates (v2.2): on SWE-bench Verified acc@5 rose from 0.75 to 0.87, and on 9 other languages from 0.64 to 0.77. Without repository history (most live repositories) it reaches acc@5 0.83 on Verified (0.62 before code reading). A file that defines a symbol named in the issue is still missed when stage 1 does not shortlist it (for example a generic name like `core.py`). It is trained mostly on Python bug fixes; none of the evaluation sets contains a documentation-only fix, so docs requests are unmeasured.
- **Success prediction** is trained on 9 repositories and evaluated leave-one-repository-out (mean AUC 0.80 vs 0.75 for the author's merge rate).
- **Actionability** is trained on 26 repositories and evaluated leave-one-repository-out (mean AUC 0.70 vs 0.58 for a keyword heuristic).
- **Contributor recommendation** is evaluated on next.js only; cross-repository generalisation is not measured.
- **Personalised ranking, learning opportunities and LLM explanations** have no offline ground truth; they combine evaluated components with transparent rules.
- Without a valid `GITHUB_TOKEN` the anonymous GitHub quota (60 requests/hour) is quickly exhausted; repository structure still works via git.
