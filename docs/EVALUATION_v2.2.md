# ContriMap evaluation report

Generated from `artifacts/v2/evaluation_report.json` (2026-11-14T21:42:00.691680+00:00). Regenerate with `python -m contrimap_ml.report`.

> Reduced re-run on this machine: SWE-bench train/dev/test/Verified/Multilingual only (no next.js crawl, no GraphQL-ingested repositories), localization trained on a seeded sample of at most 120 issues per training repository.

## Data

21347 resolved issues from 94 repositories.

| Group | Records | Repositories |
|---|---|---|
| dev | 225 | 6 |
| multilingual | 300 | 41 |
| test | 2294 | 12 |
| train | 18528 | 35 |

Train, dev, test and multilingual groups use **disjoint repositories** (SWE-bench design), so every headline number is measured on repositories the models never saw.

## Difficulty classification

Label: tertiles of log1p(LOC)+log1p(files) of non-test changes on train repositories; thresholds [3.091, 4.754]. Model selection by repository-grouped 5-fold CV on training repositories (selected linear blend 0.3).

| Model / split | Accuracy | Macro-F1 | Spearman vs true size |
|---|---|---|---|
| **ContriMap** - dev (6 repos, n=225) | 0.449 | 0.439 | 0.524 |
| stratified random - dev | 0.431 | 0.419 | - |
| majority class - dev | 0.320 | 0.162 | - |
| body-length tertiles - dev | 0.298 | 0.264 | - |
| **ContriMap** - test (12 repos, n=2294) | 0.407 | 0.401 | 0.258 |
| stratified random - test | 0.334 | 0.324 | - |
| majority class - test | 0.400 | 0.191 | - |
| body-length tertiles - test | 0.321 | 0.310 | - |
| **ContriMap** - multilingual (41 repos, n=300) | 0.387 | 0.353 | 0.112 |
| stratified random - multilingual | 0.320 | 0.314 | - |
| majority class - multilingual | 0.403 | 0.192 | - |
| body-length tertiles - multilingual | 0.280 | 0.251 | - |

Change-size regressor (Huber): test MAE 1.172 vs train-median baseline 1.190; Spearman 0.231.

## Effort estimation

5-fold repository-grouped CV on SWE-bench Verified human annotations (n=500, 12 repositories).

| Model | Bucket accuracy | Macro-F1 | MAE (levels) | Spearman vs human hours |
|---|---|---|---|---|
| **ContriMap** | 0.522 | 0.302 | 0.484 | 0.118 |
| majority bucket | 0.522 | - | 0.478 | - |

The difficulty score alone correlates with human time-to-fix at Spearman 0.163. **Effort is a weak signal from issue text alone** and is presented as a bucket with a range.

## Issue-to-file localization

Hit = at least one file changed by the gold fix appears in the top k. Candidates are all files in the repository at the issue's base commit (tree mode) or files changed earlier in the repository (history mode).

### dev (n=225, median 262 candidate files)

| Method | acc@1 | acc@5 | acc@10 | MRR |
|---|---|---|---|---|
| **ContriMap ranker** | 0.511 | 0.782 | 0.867 | 0.624 |

Oracle coverage (a gold file exists among candidates): 0.991; prefilter coverage: 0.982.

### test_verified_tree (n=500, median 1604 candidate files)

| Method | acc@1 | acc@5 | acc@10 | MRR |
|---|---|---|---|---|
| **ContriMap ranker** | 0.506 | 0.750 | 0.836 | 0.615 |
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
| **ContriMap ranker** | 0.363 | 0.640 | 0.743 | 0.484 |
| random | 0.013 | 0.043 | 0.073 | 0.028 |
| history frequency | 0.097 | 0.210 | 0.240 | 0.142 |
| bm25 | 0.207 | 0.430 | 0.543 | 0.306 |
| embedding | 0.167 | 0.360 | 0.450 | 0.249 |
| similar issues knn | 0.110 | 0.227 | 0.243 | 0.159 |
| legacy formula | 0.213 | 0.423 | 0.527 | 0.298 |

Oracle coverage (a gold file exists among candidates): 1.000; prefilter coverage: 0.917.

Top ranker features by gain: bm25_rel (0.23), knn_sum (0.23), mention_path (0.10), lang_match (0.09), knn_max (0.07), hist_recency (0.06), emb_pct (0.06), emb_rel (0.04).

### Stage 2: reading the code of the shortlist

The stage-1 top 50 files are read at the issue's base commit and re-ranked with code features (definitions of symbols named in the issue, quoted error strings, BM25 over identifiers). Training shortlists come from cross-fitted stage-1 models (no in-sample scores); the re-ranker is kept only if it beats stage 1 on dev MRR (dev 0.624 -> 0.734; selected: **True**).

| Split / model | acc@1 | acc@5 | acc@10 | MRR |
|---|---|---|---|---|
| dev - stage 1 (paths/text/history) | 0.511 | 0.782 | 0.867 | 0.624 |
| **dev - stage 2 (+ code)** | 0.627 | 0.893 | 0.924 | 0.734 |
| test_verified_tree - stage 1 (paths/text/history) | 0.506 | 0.750 | 0.836 | 0.615 |
| **test_verified_tree - stage 2 (+ code)** | 0.620 | 0.870 | 0.914 | 0.725 |
| multilingual_tree - stage 1 (paths/text/history) | 0.363 | 0.640 | 0.743 | 0.484 |
| **multilingual_tree - stage 2 (+ code)** | 0.523 | 0.773 | 0.837 | 0.634 |

Top re-ranker features by gain: stage1_gap (0.38), code_bm25_rel (0.21), stage1_rank (0.17), code_def_bm25 (0.03), code_def_idf (0.02), code_bm25 (0.02), stage1_score (0.02), code_lines (0.01).

### With and without repository history

Same cached issues and candidates scored by each saved model (`python -m contrimap_ml.compare_localization`). `*_nohist` splits switch repository-history features off - the situation of most repositories analysed live, which have no ingested resolved-issue history.

| Model · split · stage | acc@1 | acc@5 | acc@10 | MRR |
|---|---|---|---|---|
| shipped (trained with history) · dev · stage1 | 0.511 | 0.782 | 0.867 | 0.624 |
| shipped (trained with history) · dev · stage2 | 0.627 | 0.893 | 0.924 | 0.734 |
| shipped (trained with history) · test_verified_tree · stage1 | 0.506 | 0.750 | 0.836 | 0.615 |
| shipped (trained with history) · test_verified_tree · stage2 | 0.620 | 0.870 | 0.914 | 0.725 |
| shipped (trained with history) · multilingual_tree · stage1 | 0.363 | 0.640 | 0.743 | 0.484 |
| shipped (trained with history) · multilingual_tree · stage2 | 0.523 | 0.773 | 0.837 | 0.634 |
| shipped (trained with history) · dev_nohist · stage1 | 0.502 | 0.724 | 0.773 | 0.598 |
| shipped (trained with history) · dev_nohist · stage2 | 0.631 | 0.809 | 0.844 | 0.708 |
| shipped (trained with history) · test_verified_nohist · stage1 | 0.424 | 0.622 | 0.712 | 0.510 |
| shipped (trained with history) · test_verified_nohist · stage2 | 0.588 | 0.832 | 0.884 | 0.692 |
| shipped (trained with history) · multilingual_nohist · stage1 | 0.333 | 0.590 | 0.707 | 0.447 |
| shipped (trained with history) · multilingual_nohist · stage2 | 0.520 | 0.770 | 0.830 | 0.624 |
| experiment: + no-history training variants · dev · stage1 | 0.511 | 0.787 | 0.876 | 0.628 |
| experiment: + no-history training variants · dev · stage2 | 0.622 | 0.893 | 0.916 | 0.728 |
| experiment: + no-history training variants · test_verified_tree · stage1 | 0.500 | 0.752 | 0.834 | 0.608 |
| experiment: + no-history training variants · test_verified_tree · stage2 | 0.602 | 0.858 | 0.910 | 0.709 |
| experiment: + no-history training variants · multilingual_tree · stage1 | 0.353 | 0.640 | 0.753 | 0.475 |
| experiment: + no-history training variants · multilingual_tree · stage2 | 0.523 | 0.777 | 0.840 | 0.632 |
| experiment: + no-history training variants · dev_nohist · stage1 | 0.498 | 0.729 | 0.773 | 0.595 |
| experiment: + no-history training variants · dev_nohist · stage2 | 0.613 | 0.818 | 0.849 | 0.696 |
| experiment: + no-history training variants · test_verified_nohist · stage1 | 0.432 | 0.626 | 0.734 | 0.513 |
| experiment: + no-history training variants · test_verified_nohist · stage2 | 0.600 | 0.828 | 0.882 | 0.695 |
| experiment: + no-history training variants · multilingual_nohist · stage1 | 0.317 | 0.607 | 0.713 | 0.441 |
| experiment: + no-history training variants · multilingual_nohist · stage2 | 0.500 | 0.763 | 0.823 | 0.612 |

## Difficulty with localization and code signals

A stacker on out-of-fold text probabilities plus 12 signals describing the likely change site (shortlist confidence and spread, mentioned files, symbol definitions found, size of the top files). Grouped CV macro-F1 on 3753 training issues: text model 0.411, text-only stacker 0.386, with signals 0.426; selected: **False**.

| Split / model | Accuracy | Macro-F1 | Spearman vs true size |
|---|---|---|---|
| dev (n=225) - text only | 0.449 | 0.439 | 0.524 |
| **dev - text + code signals** | 0.449 | 0.415 | 0.490 |
| test (n=500) - text only | 0.428 | 0.368 | 0.191 |
| **test - text + code signals** | 0.410 | 0.338 | 0.207 |
| multilingual (n=300) - text only | 0.387 | 0.353 | 0.112 |
| **multilingual - text + code signals** | 0.407 | 0.364 | 0.199 |

Spearman with human time-to-fix (SWE-bench Verified): text only 0.163, with signals 0.192.

Selection rule: grouped-CV macro-F1 above both text baselines and dev macro-F1 above text-only. Rule tightened after the first run: grouped CV alone selected the head; dev rejects it. Test numbers were not used for the decision.

## Effort with localization and code signals

5-fold repository-grouped CV on SWE-bench Verified human annotations (same folds for both variants) (n=500). Selected (lower log-loss without losing rank correlation): **False**.

| Calibrator | Bucket accuracy | Macro-F1 | Spearman vs human hours | Log-loss |
|---|---|---|---|---|
| text only | 0.522 | 0.302 | 0.118 | 0.929 |
| text plus code signals | 0.534 | 0.334 | 0.129 | 0.946 |
| majority bucket | 0.522 | - | - | - |

## Not evaluated offline

- Personalised ranking and learning-opportunity scores have no ground truth; they are transparent combinations of the evaluated components and profile matching.
- LLM explanations are constrained to model outputs (file references are validated) but their quality is not measured.
