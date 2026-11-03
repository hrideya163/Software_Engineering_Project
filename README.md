# ContriMap

ContriMap helps people find, understand and complete open-source contributions. For any public GitHub repository it:

- shows a **dashboard of trending repositories** with beginner-friendly issues;
- snapshots the repository with git and builds a **knowledge graph** (files, directories, imports, tests, dependencies, skills) with an **interactive architecture visualizer**;
- **ranks open issues** by actionability, approachability, clarity, availability and freshness - or **personally**, by your stack, interests, skill level and learning goals;
- **analyses an issue**: difficulty, effort, the files most likely to change (highlighted on the code graph and file tree), related tests, required skills, a step-by-step **contribution path**, and an LLM-written **explanation** grounded in those outputs;
- builds **contributor profiles** from GitHub activity and recommends issues across several repositories, including **learning opportunities**.

Every model is evaluated on repositories it never saw during training, against baselines - see [docs/EVALUATION.md](docs/EVALUATION.md) or the in-app *Model Card* page.

## Architecture

```
React + Vite (src/)  ──►  FastAPI  contrimap_ml/api.py  ──►  service.py ──► models (artifacts/v2)
        │                                                   ├─ git trees/blobs (repo_trees.py, no token)
        └──► Express server/ (GitHub / Google sign-in)      └─ GitHub REST (metadata, issues, trending)
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

# 3. Optional: sign-in server
cd server && npm install && cp .env.example .env && npm run dev
```

Copy `.env.example` to `.env`. A valid `GITHUB_TOKEN` raises the GitHub API limit from 60 to 5,000 requests/hour (repository code itself is read with git and needs no token). `ANTHROPIC_API_KEY` enables Claude-written explanations (`ANTHROPIC_MODEL`, default `claude-opus-5-5`); without it a deterministic template is used.

### Docker

```bash
docker compose up --build                # http://localhost:8001 (frontend + API)
docker compose --profile auth up         # also start the sign-in server
```

## Training and evaluation

```bash
python -m contrimap_ml.train_v2 --stages difficulty,localization,success,actionability,recommendation
python -m contrimap_ml.report            # regenerates docs/EVALUATION.md from the measured report
python -m pytest contrimap_ml -q         # unit + API tests (no network needed)
```

Multi-repository ingestion of fresh data (requires `GITHUB_TOKEN`):

```bash
python -m contrimap_ml.ingest pallets/flask fastapi/fastapi --since 2023-01-01 --max-prs 400
```

Ingested repositories automatically provide history features (similar past issues, change frequency) to localization at inference time.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/trending?language=` | trending repositories with good-first-issues |
| GET | `/api/repos/{o}/{r}` | overview: languages, skills, core files, structure |
| GET / POST | `/api/repos/{o}/{r}/issues` · `/issues/ranked` | ranked issues (POST with `profile`, `mode`) |
| GET / POST | `/api/repos/{o}/{r}/issues/{n}/analysis` | full issue analysis (POST adds personal fit) |
| POST | `/api/repos/{o}/{r}/analyze` | analyse draft issue text |
| GET | `/api/repos/{o}/{r}/architecture` · `/tree` | visualizer payloads |
| POST | `/api/repos/{o}/{r}/learning` | learning-opportunity ranking |
| GET | `/api/contributors/{login}` | contributor profile and extracted skills |
| POST | `/api/recommendations` | personalised issues across repositories |
| GET | `/api/model-card` | evaluation report |

Legacy `/api/predict`, `/api/analyze` and `/api/repositories/issues` remain available (`contrimap_ml.inference_api:app` still works).

## Known limitations

- **Effort** estimates from issue text are weak (Spearman ≈ 0.16 with human time-to-fix; bucket accuracy barely above the majority baseline). They are shown as buckets with ranges, never as precise hours.
- **Difficulty** generalises across repositories (macro-F1 0.41 vs 0.32 random) but per-issue confidence is often low.
- **Localization** is trained mostly on Python bug fixes; documentation-only and feature-scale issues are under-represented. It transfers well to fresh repositories (acc@5 0.76 on 274 issues from 6 repositories ingested in 2023+, changelog files excluded), but repositories without ingested history run in text-only mode and score lower.
- **Success prediction** is trained on 9 repositories and evaluated leave-one-repository-out (mean AUC 0.80 vs 0.75 for the author's merge rate).
- **Actionability and contributor recommendation** are trained/evaluated on next.js only; cross-repository generalisation is not measured.
- **Personalised ranking, learning opportunities and LLM explanations** have no offline ground truth; they combine evaluated components with transparent rules.
- Without a valid `GITHUB_TOKEN` the anonymous GitHub quota (60 requests/hour) is quickly exhausted; repository structure still works via git.
