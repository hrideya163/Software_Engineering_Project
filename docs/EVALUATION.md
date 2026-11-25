# ContriMap evaluation report

Generated from `artifacts/v2/evaluation_report.json` (2026-11-11T18:19:44.565699+00:00). Regenerate with `python -m contrimap_ml.report`.

## Data

22481 resolved issues from 95 repositories.

| Group | Records | Repositories |
|---|---|---|
| dev | 225 | 6 |
| multilingual | 300 | 41 |
| nextjs | 1134 | 1 |
| test | 2294 | 12 |
| train | 18528 | 35 |

Train, dev, test and multilingual groups use **disjoint repositories** (SWE-bench design), so every headline number is measured on repositories the models never saw.

## Difficulty classification

Label: tertiles of log1p(LOC)+log1p(files) of non-test changes on train repositories; thresholds [3.178, 4.868]. Model selection by repository-grouped 5-fold CV on training repositories (selected linear blend 0.3).

| Model / split | Accuracy | Macro-F1 | Spearman vs true size |
|---|---|---|---|
| **ContriMap** - dev (6 repos, n=225) | 0.476 | 0.472 | 0.509 |
| stratified random - dev | 0.431 | 0.421 | - |
| majority class - dev | 0.333 | 0.167 | - |
| body-length tertiles - dev | 0.302 | 0.277 | - |
| **ContriMap** - test (12 repos, n=2294) | 0.427 | 0.406 | 0.250 |
| stratified random - test | 0.332 | 0.320 | - |
| majority class - test | 0.379 | 0.183 | - |
| body-length tertiles - test | 0.331 | 0.316 | - |
| **ContriMap** - multilingual (41 repos, n=300) | 0.387 | 0.367 | 0.095 |
| stratified random - multilingual | 0.333 | 0.326 | - |
| majority class - multilingual | 0.387 | 0.186 | - |
| body-length tertiles - multilingual | 0.270 | 0.245 | - |

Change-size regressor (Huber): test MAE 1.187 vs train-median baseline 1.225; Spearman 0.223.

## Effort estimation

5-fold repository-grouped CV on SWE-bench Verified human annotations (n=500, 12 repositories).

| Model | Bucket accuracy | Macro-F1 | MAE (levels) | Spearman vs human hours |
|---|---|---|---|---|
| **ContriMap** | 0.536 | 0.310 | 0.468 | 0.124 |
| majority bucket | 0.522 | - | 0.478 | - |

The difficulty score alone correlates with human time-to-fix at Spearman 0.166. **Effort is a weak signal from issue text alone** and is presented as a bucket with a range.

## Issue-to-file localization

Hit = at least one file changed by the gold fix appears in the top k. Candidates are all files in the repository at the issue's base commit (tree mode) or files changed earlier in the repository (history mode).

### dev (n=225, median 262 candidate files)

| Method | acc@1 | acc@5 | acc@10 | MRR |
|---|---|---|---|---|
| **ContriMap ranker** | 0.520 | 0.782 | 0.867 | 0.624 |

Oracle coverage (a gold file exists among candidates): 0.991; prefilter coverage: 0.982.

### test_verified_tree (n=500, median 1604 candidate files)

| Method | acc@1 | acc@5 | acc@10 | MRR |
|---|---|---|---|---|
| **ContriMap ranker** | 0.492 | 0.760 | 0.842 | 0.605 |
| random | 0.000 | 0.012 | 0.020 | 0.004 |
| history frequency | 0.064 | 0.216 | 0.312 | 0.129 |
| bm25 | 0.192 | 0.424 | 0.508 | 0.291 |
| embedding | 0.246 | 0.454 | 0.578 | 0.336 |
| similar issues knn | 0.196 | 0.492 | 0.598 | 0.315 |
| legacy formula | 0.272 | 0.584 | 0.716 | 0.409 |

Oracle coverage (a gold file exists among candidates): 1.000; prefilter coverage: 0.970.

### multilingual_tree (n=300, median 685 candidate files)

| Method | acc@1 | acc@5 | acc@10 | MRR |
|---|---|---|---|---|
| **ContriMap ranker** | 0.363 | 0.647 | 0.733 | 0.481 |
| random | 0.013 | 0.043 | 0.073 | 0.028 |
| history frequency | 0.097 | 0.210 | 0.240 | 0.142 |
| bm25 | 0.207 | 0.430 | 0.543 | 0.306 |
| embedding | 0.167 | 0.360 | 0.450 | 0.249 |
| similar issues knn | 0.110 | 0.227 | 0.243 | 0.159 |
| legacy formula | 0.213 | 0.423 | 0.527 | 0.298 |

Oracle coverage (a gold file exists among candidates): 1.000; prefilter coverage: 0.917.

### nextjs_history_last20pct (n=227, median 1326 candidate files)

| Method | acc@1 | acc@5 | acc@10 | MRR |
|---|---|---|---|---|
| **ContriMap ranker** | 0.344 | 0.564 | 0.643 | 0.442 |
| random | 0.004 | 0.018 | 0.022 | 0.011 |
| history frequency | 0.115 | 0.225 | 0.361 | 0.174 |
| bm25 | 0.093 | 0.220 | 0.304 | 0.146 |
| embedding | 0.075 | 0.172 | 0.242 | 0.117 |
| similar issues knn | 0.330 | 0.511 | 0.573 | 0.409 |
| legacy formula | 0.154 | 0.322 | 0.423 | 0.224 |

Oracle coverage (a gold file exists among candidates): 0.828; prefilter coverage: 0.762.

Legacy model on its own next.js temporal split (history candidates, all changed files as targets): recall@5 0.178, recall@10 0.238, MRR 0.117 - not directly comparable (different target definition and candidate set), and it could not localize in any other repository.

Top ranker features by gain: knn_sum (0.29), bm25_rel (0.25), mention_path (0.11), knn_max (0.07), emb_pct (0.05), hist_recency (0.04), lang_match (0.04), mention_basename (0.03).

## Issue ranking - actionability component

vercel/next.js closed issues 2016-2021; positive = resolved by merged PR with closing keyword; temporal split (train 8000, test 2000, positive rate 0.075).

| Model | ROC-AUC | Average precision |
|---|---|---|
| **ContriMap** | 0.706 | 0.192 |
| keyword heuristic | 0.500 | 0.077 |
| body length | 0.488 | - |
| random | 0.500 | 0.075 |

Precision@50: 0.320. Single repository; labels are current GitHub labels (some may have been added during triage). The other ranking components (availability, freshness, clarity, community, focus) are transparent rules, not learned, and are not separately evaluated.

### Actionability across repositories (deployed model)

leave-one-repository-out ROC-AUC; positive = closed issue resolved by a merged pull request; selected **tfidf_lr** (mean AUC by candidate: tfidf_lr 0.699, heuristic 0.579).

| Held-out repository | Issues | Positive rate | Model AUC | Heuristic AUC |
|---|---|---|---|---|
| clap-rs/clap | 204.000 | 0.304 | 0.700 | 0.639 |
| cli/cli | 600.000 | 0.073 | 0.887 | 0.662 |
| expressjs/express | 266.000 | 0.071 | 0.706 | 0.472 |
| pallets/flask | 195.000 | 0.113 | 0.631 | 0.485 |
| psf/black | 351.000 | 0.419 | 0.723 | 0.581 |
| pydantic/pydantic | 600.000 | 0.395 | 0.614 | 0.559 |
| spf13/cobra | 67.000 | 0.104 | 0.760 | 0.577 |
| vitejs/vite | 600.000 | 0.352 | 0.725 | 0.559 |
| astral-sh/uv | 600.000 | 0.413 | 0.721 | 0.668 |
| charmbracelet/bubbletea | 305.000 | 0.259 | 0.717 | 0.719 |
| composer/composer | 600.000 | 0.203 | 0.734 | 0.596 |
| encode/httpx | 239.000 | 0.188 | 0.794 | 0.507 |
| eslint/eslint | 600.000 | 0.345 | 0.748 | 0.513 |
| go-gitea/gitea | 600.000 | 0.560 | 0.638 | 0.589 |
| helix-editor/helix | 600.000 | 0.197 | 0.620 | 0.547 |
| Homebrew/brew | 600.000 | 0.532 | 0.701 | 0.721 |
| junegunn/fzf | 600.000 | 0.107 | 0.554 | 0.515 |
| microsoft/playwright | 600.000 | 0.478 | 0.636 | 0.592 |
| pallets/click | 492.000 | 0.319 | 0.611 | 0.552 |
| prettier/prettier | 600.000 | 0.438 | 0.736 | 0.555 |
| python-poetry/poetry | 600.000 | 0.255 | 0.698 | 0.525 |
| starship/starship | 600.000 | 0.247 | 0.718 | 0.467 |
| Textualize/rich | 600.000 | 0.178 | 0.709 | 0.628 |
| webpack/webpack | 600.000 | 0.377 | 0.847 | 0.680 |
| withastro/astro | 600.000 | 0.625 | 0.671 | 0.609 |
| vercel/next.js | 3000.000 | 0.116 | 0.583 | 0.532 |
| **mean** | - | - | 0.699 | 0.579 |

Labels are GitHub's closing-PR links; issues fixed without a linked PR count as negatives. GitHub labels are as of crawl time. next.js capped at 3,000 issues.

## Contribution success prediction

vercel/next.js closed pull requests; temporal 80/20 split (train 8000, test 2000, merge rate 0.805).

| Model | ROC-AUC | Average precision | Brier |
|---|---|---|---|
| **ContriMap** (calibrated GBM) | 0.746 | 0.914 | 0.150 |
| author prior merge rate | 0.726 | - | - |
| constant merge rate | 0.500 | - | 0.157 |

Single repository; generalisation to other repositories is not measured.

### Cross-repository success prediction (deployed model)

leave-one-repository-out ROC-AUC (each score on a repository unseen in training); selected: **gbm**. Data: uniform samples of closed PRs per repository plus next.js (PR bodies blanked everywhere for comparability).

| Held-out repository | PRs | Merge rate | GBM AUC | Logistic AUC | Author-rate rule AUC |
|---|---|---|---|---|---|
| clap-rs/clap | 558.000 | 0.695 | 0.818 | 0.811 | 0.793 |
| cli/cli | 600.000 | 0.635 | 0.880 | 0.864 | 0.849 |
| expressjs/express | 600.000 | 0.198 | 0.811 | 0.791 | 0.777 |
| pallets/flask | 405.000 | 0.252 | 0.861 | 0.784 | 0.703 |
| psf/black | 600.000 | 0.718 | 0.721 | 0.709 | 0.683 |
| pydantic/pydantic | 600.000 | 0.575 | 0.898 | 0.866 | 0.821 |
| spf13/cobra | 110.000 | 0.555 | 0.683 | 0.664 | 0.617 |
| vitejs/vite | 600.000 | 0.623 | 0.834 | 0.825 | 0.809 |
| vercel/next.js | 10000.000 | 0.791 | 0.722 | 0.722 | 0.710 |
| **mean** |  | - | 0.803 | 0.782 | 0.751 |

Ingested repositories use the 600 most recent closed PRs since 2024 (merged and unmerged together), so author histories only cover that window.

## Fresh repositories (2023+, ingested via GraphQL)

Localization on the last 20% of issues per repository (n=274); history from earlier issues only. Candidates are each repository's current tree (files added or removed since the issue make this slightly pessimistic).

| Method | acc@1 | acc@5 | acc@10 | MRR |
|---|---|---|---|---|
| **ContriMap ranker** | 0.474 | 0.763 | 0.850 | 0.601 |
| random | 0.000 | 0.018 | 0.066 | 0.012 |
| history frequency | 0.117 | 0.318 | 0.423 | 0.206 |
| bm25 | 0.193 | 0.434 | 0.526 | 0.293 |
| embedding | 0.150 | 0.383 | 0.500 | 0.252 |
| similar issues knn | 0.288 | 0.547 | 0.679 | 0.407 |
| legacy formula | 0.230 | 0.529 | 0.664 | 0.358 |

acc@5 per repository: clap-rs/clap 0.65 (n=26), cli/cli 0.77 (n=48), pallets/flask 0.78 (n=9), psf/black 0.79 (n=61), pydantic/pydantic 0.82 (n=66), vitejs/vite 0.72 (n=64).

## Contributor-issue recommendation

rank active contributors for each next.js issue; hit = the actual resolver; candidate pool 65 contributors; weights chosen on a validation window: {'skill': 0.0, 'files': 0.0, 'semantic': 0.5, 'success': 1.0, 'difficulty_fit': 0.0} (validation MRR 0.587).

| Method | acc@1 | acc@5 | acc@10 | MRR |
|---|---|---|---|---|
| **ContriMap combined** | 0.430 | 0.785 | 0.861 | 0.590 |
| only skill | 0.380 | 0.785 | 0.823 | 0.579 |
| only files | 0.329 | 0.785 | 0.873 | 0.538 |
| only semantic | 0.203 | 0.671 | 0.797 | 0.397 |
| only success | 0.291 | 0.797 | 0.823 | 0.531 |
| only difficulty fit | 0.152 | 0.494 | 0.494 | 0.328 |
| baseline popularity | 0.278 | 0.797 | 0.835 | 0.536 |
| baseline random | 0.000 | 0.114 | 0.177 | 0.072 |

Single repository (next.js 2016-2021); pool = contributors with >= 2 resolved issues before the window.

## Not evaluated offline

- Personalised ranking and learning-opportunity scores have no ground truth; they are transparent combinations of the evaluated components and profile matching.
- LLM explanations are constrained to model outputs (file references are validated) but their quality is not measured.
