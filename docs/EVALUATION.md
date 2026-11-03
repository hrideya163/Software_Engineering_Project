# ContriMap evaluation report

Generated from `artifacts/v2/evaluation_report.json` (2026-11-03T08:53:47.057627+00:00). Regenerate with `python -m contrimap_ml.report`.

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

Label: tertiles of log1p(LOC)+log1p(files)+0.5*log1p(hunks) on train repositories; thresholds [3.679, 5.614]. Model selection by repository-grouped 5-fold CV on training repositories (selected linear blend 0.7).

| Model / split | Accuracy | Macro-F1 | Spearman vs true size |
|---|---|---|---|
| **ContriMap** - dev (6 repos, n=225) | 0.524 | 0.505 | 0.525 |
| stratified random - dev | 0.413 | 0.400 | - |
| majority class - dev | 0.293 | 0.151 | - |
| body-length tertiles - dev | 0.298 | 0.264 | - |
| **ContriMap** - test (12 repos, n=2294) | 0.434 | 0.414 | 0.281 |
| stratified random - test | 0.327 | 0.317 | - |
| majority class - test | 0.358 | 0.176 | - |
| body-length tertiles - test | 0.317 | 0.308 | - |
| **ContriMap** - multilingual (41 repos, n=300) | 0.410 | 0.383 | 0.137 |
| stratified random - multilingual | 0.330 | 0.324 | - |
| majority class - multilingual | 0.390 | 0.187 | - |
| body-length tertiles - multilingual | 0.273 | 0.246 | - |

Change-size regressor (Huber): test MAE 1.396 vs train-median baseline 1.434; Spearman 0.242.

## Effort estimation

5-fold repository-grouped CV on SWE-bench Verified human annotations (n=500, 12 repositories).

| Model | Bucket accuracy | Macro-F1 | MAE (levels) | Spearman vs human hours |
|---|---|---|---|---|
| **ContriMap** | 0.534 | 0.299 | 0.470 | 0.157 |
| majority bucket | 0.522 | - | 0.478 | - |

The difficulty score alone correlates with human time-to-fix at Spearman 0.171. **Effort is a weak signal from issue text alone** and is presented as a bucket with a range.

## Issue-to-file localization

Hit = at least one file changed by the gold fix appears in the top k. Candidates are all files in the repository at the issue's base commit (tree mode) or files changed earlier in the repository (history mode).

### dev (n=225, median 263 candidate files)

| Method | acc@1 | acc@5 | acc@10 | MRR |
|---|---|---|---|---|
| **ContriMap ranker** | 0.524 | 0.756 | 0.853 | 0.623 |

Oracle coverage (a gold file exists among candidates): 0.991; prefilter coverage: 0.982.

### test_verified_tree (n=500, median 1608 candidate files)

| Method | acc@1 | acc@5 | acc@10 | MRR |
|---|---|---|---|---|
| **ContriMap ranker** | 0.478 | 0.752 | 0.840 | 0.594 |
| random | 0.000 | 0.006 | 0.012 | 0.003 |
| history frequency | 0.064 | 0.216 | 0.312 | 0.129 |
| bm25 | 0.192 | 0.424 | 0.508 | 0.291 |
| embedding | 0.246 | 0.454 | 0.578 | 0.336 |
| similar issues knn | 0.196 | 0.492 | 0.598 | 0.315 |
| legacy formula | 0.272 | 0.584 | 0.716 | 0.409 |

Oracle coverage (a gold file exists among candidates): 1.000; prefilter coverage: 0.970.

### multilingual_tree (n=300, median 687 candidate files)

| Method | acc@1 | acc@5 | acc@10 | MRR |
|---|---|---|---|---|
| **ContriMap ranker** | 0.373 | 0.653 | 0.757 | 0.495 |
| random | 0.000 | 0.017 | 0.037 | 0.008 |
| history frequency | 0.153 | 0.247 | 0.277 | 0.191 |
| bm25 | 0.207 | 0.433 | 0.543 | 0.306 |
| embedding | 0.170 | 0.363 | 0.453 | 0.252 |
| similar issues knn | 0.163 | 0.263 | 0.280 | 0.206 |
| legacy formula | 0.220 | 0.433 | 0.530 | 0.305 |

Oracle coverage (a gold file exists among candidates): 1.000; prefilter coverage: 0.923.

### nextjs_history_last20pct (n=227, median 1326 candidate files)

| Method | acc@1 | acc@5 | acc@10 | MRR |
|---|---|---|---|---|
| **ContriMap ranker** | 0.308 | 0.546 | 0.639 | 0.407 |
| random | 0.004 | 0.018 | 0.022 | 0.011 |
| history frequency | 0.115 | 0.225 | 0.361 | 0.174 |
| bm25 | 0.093 | 0.220 | 0.304 | 0.146 |
| embedding | 0.075 | 0.172 | 0.242 | 0.117 |
| similar issues knn | 0.330 | 0.511 | 0.573 | 0.409 |
| legacy formula | 0.154 | 0.322 | 0.423 | 0.224 |

Oracle coverage (a gold file exists among candidates): 0.828; prefilter coverage: 0.762.

Legacy model on its own next.js temporal split (history candidates, all changed files as targets): recall@5 0.178, recall@10 0.238, MRR 0.117 - not directly comparable (different target definition and candidate set), and it could not localize in any other repository.

Top ranker features by gain: bm25_rel (0.24), knn_sum (0.23), lang_match (0.09), mention_path (0.08), emb_pct (0.07), knn_max (0.06), mention_stem (0.05), hist_recency (0.05).

## Issue ranking - actionability component

vercel/next.js closed issues 2016-2021; positive = resolved by merged PR with closing keyword; temporal split (train 8000, test 2000, positive rate 0.075).

| Model | ROC-AUC | Average precision |
|---|---|---|
| **ContriMap** | 0.706 | 0.192 |
| keyword heuristic | 0.500 | 0.077 |
| body length | 0.488 | - |
| random | 0.500 | 0.075 |

Precision@50: 0.320. Single repository; labels are current GitHub labels (some may have been added during triage). The other ranking components (availability, freshness, clarity, community, focus) are transparent rules, not learned, and are not separately evaluated.

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
| **ContriMap ranker** | 0.474 | 0.763 | 0.821 | 0.596 |
| random | 0.007 | 0.022 | 0.062 | 0.017 |
| history frequency | 0.117 | 0.318 | 0.423 | 0.206 |
| bm25 | 0.193 | 0.438 | 0.522 | 0.293 |
| embedding | 0.150 | 0.383 | 0.500 | 0.254 |
| similar issues knn | 0.288 | 0.547 | 0.679 | 0.407 |
| legacy formula | 0.237 | 0.533 | 0.664 | 0.362 |

acc@5 per repository: clap-rs/clap 0.62 (n=26), cli/cli 0.81 (n=48), pallets/flask 0.78 (n=9), psf/black 0.84 (n=61), pydantic/pydantic 0.80 (n=66), vitejs/vite 0.67 (n=64).

## Contributor-issue recommendation

rank active contributors for each next.js issue; hit = the actual resolver; candidate pool 65 contributors; weights chosen on a validation window: {'skill': 0.0, 'files': 0.0, 'semantic': 0.5, 'success': 1.0, 'difficulty_fit': 0.0} (validation MRR 0.587).

| Method | acc@1 | acc@5 | acc@10 | MRR |
|---|---|---|---|---|
| **ContriMap combined** | 0.430 | 0.785 | 0.861 | 0.590 |
| only skill | 0.367 | 0.785 | 0.835 | 0.573 |
| only files | 0.316 | 0.835 | 0.873 | 0.545 |
| only semantic | 0.203 | 0.671 | 0.797 | 0.397 |
| only success | 0.291 | 0.797 | 0.823 | 0.531 |
| only difficulty fit | 0.076 | 0.278 | 0.278 | 0.192 |
| baseline popularity | 0.278 | 0.797 | 0.835 | 0.536 |
| baseline random | 0.000 | 0.114 | 0.177 | 0.072 |

Single repository (next.js 2016-2021); pool = contributors with >= 2 resolved issues before the window.

## Not evaluated offline

- Personalised ranking and learning-opportunity scores have no ground truth; they are transparent combinations of the evaluated components and profile matching.
- LLM explanations are constrained to model outputs (file references are validated) but their quality is not measured.
