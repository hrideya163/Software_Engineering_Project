# ContriMap supervised ML pipeline

The production analytics direction is **not** a heuristic scorer and does not
call an LLM, LangChain, or an agent. It starts from a reproducible GitHub
history snapshot and trains three measurable models.

## Data flow

```text
GitHub REST API
  -> closed Issues
  -> merged Pull Requests
  -> issue/PR links from closing references
  -> PR changed-files endpoint
  -> historical_contributions.jsonl
  -> time-based train/test split
      ├── LightGBM/XGBoost: Easy/Medium/Hard classifier
      ├── LightGBM/XGBoost: hours regressor
      └── Sentence Transformers + FAISS: issue -> top-K files
```

## Historical training dataset

`contrimap_ml.github_ingest.collect_repository` stores:

* issue title, body, labels, creation and closure timestamps;
* resolving merged PR title/body, timestamps, commits, review count,
  additions, and deletions;
* every changed file returned by the GitHub pull-request-files endpoint;
* observed effort in hours from issue creation to PR merge;
* an explicit training difficulty label.

The raw API payloads are preserved under `data/raw/`. The normalized
`historical_contributions.jsonl` is the training contract. A PR is linked to an
issue through closing references such as `Fixes #123` in its title or body.
Repositories with ambiguous links should be excluded or extended with GitHub
timeline/event linking before training.

Difficulty labels are **training labels only**, produced from observed
historical workload (elapsed hours, changed-file count, and review comments).
They are not used as inference rules. The model learns the mapping from
issue-time features to those labels.

## Models

### 1. Issue Difficulty Classification

* Inputs: issue label count, title length, body length.
* Model: LightGBM classifier, with XGBoost fallback.
* Output: `Easy`, `Medium`, or `Hard` plus class probability.
* Metrics: accuracy and macro-F1 on a chronological holdout.

No post-resolution PR fields are used as model inputs, preventing leakage.

### 2. Effort Prediction

* Inputs: the same issue-time feature vector.
* Model: LightGBM regressor, with XGBoost fallback.
* Output: predicted hours.
* Metrics: MAE and RMSE in hours.

### 3. Issue Localization

* File corpus: all changed files in the historical dataset.
* Encoder: `sentence-transformers/all-MiniLM-L6-v2`.
* Index: FAISS inner-product index over normalized embeddings.
* Query: issue title and body.
* Output: top-K files and similarity scores.
* Evaluation: Recall@K and MRR against held-out resolving-PR files.

The artifact index is built from the complete historical file vocabulary for
inference. Evaluation uses a train-only file index, so held-out issues cannot
retrieve file entries introduced only by their own resolving PR. This measures
localization over files known before the holdout period; report coverage when
new files are absent from the train vocabulary.

## Usage

```powershell
pip install -r requirements-ml.txt
$env:GITHUB_TOKEN = "..."
python -m contrimap_ml.cli ingest vercel next.js --output data
python -m contrimap_ml.cli train data/historical_contributions.jsonl --output artifacts
python -m contrimap_ml.cli predict artifacts "Improve router error handling" --body "Add a regression test"
```

Artifacts contain the trained tabular models, label encoder, FAISS index,
embedding model name, and file-name mapping. They are versionable and can be
served by the included FastAPI inference service without any LLM dependency.

## Inference deployment

Run the API from a directory containing the saved `artifacts/` directory:

```powershell
$env:CONTRIMAP_ARTIFACT_DIR = "artifacts"
$env:CONTRIMAP_MODEL_VERSION = "2026-09-16"
$env:CONTRIMAP_ALLOWED_ORIGINS = "https://your-frontend.example"
uvicorn contrimap_ml.inference_api:app --host 0.0.0.0 --port 8000
```

The service exposes:

* `GET /health`
* `POST /api/predict`

`POST /api/predict` accepts `title`, `body`, `labels`, and `top_k`, and returns
only `model_version`, difficulty classification/probability, effort hours, and
localized files. The React app points `VITE_API_URL` at this service, for
example `https://ml-api.example/api`; it never loads Python artifacts in the
browser.

## Evaluation protocol

Use repository- and time-based splits. Do not randomly split records from the
same repository because that leaks file names, issue vocabulary, and project
history. Report class distribution, accuracy, macro-F1, MAE, RMSE, Recall@1,
Recall@5, Recall@10, MRR, and the number of usable linked records. Keep the
dataset manifest and artifact metadata with every training run.
