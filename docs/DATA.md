# Data and leakage controls

## Sources

| Dataset | Origin | Use |
|---|---|---|
| SWE-bench train / dev / test | `princeton-nlp/SWE-bench` (Hugging Face, parquet) | 47 Python repositories; issue text + gold patch. Train, dev and test repositories are disjoint. |
| SWE-bench Verified | `princeton-nlp/SWE-bench_Verified` | 500 test issues with human "time to fix" annotations - effort ground truth and difficulty validation. |
| SWE-bench Multilingual | `SWE-bench/SWE-bench_Multilingual` | 300 issues, 41 repositories, 9 languages - cross-language evaluation. |
| vercel/next.js crawl | `data/historical_contributions.jsonl`, `data/raw/` (original project data) | Cleaned linked issues; 10k issues for actionability; 10k PRs for success prediction; contributor recommendation. |
| Repository trees | `git fetch --depth 1 --filter=blob:none <base_commit>` | Full file lists at each evaluation/training issue's base commit (`data/trees`). |

Place the parquet files in `data/external/` (`swebench_{train,dev,test,verified,multilingual}.parquet`).

## Repairs to the original next.js data

| Problem found in the audit | Fix |
|---|---|
| Issue↔PR link regex made the closing keyword optional; 39% of links were bare `#N` mentions | Closing keyword required (`corpus.CLOSING_REFERENCE`, `github_ingest.PR_REFERENCE`); GraphQL ingestion uses GitHub's own `closingIssuesReferences`. |
| `pr_additions`, `pr_deletions`, `pr_commits` were 0 for every record (list endpoint omits them) | Treated as missing; the REST collector now fetches PR details; GraphQL ingestion records them. |
| Multi-PR issues and sweeping refactors (up to 254 files) | One row per issue (earliest merge); PRs touching > 50 files dropped. |
| Difficulty tertiles computed on the full dataset (test leaked into label thresholds) | Thresholds fitted on training repositories only. |
| Effort = calendar time issue-open → merge (queueing, not work; no signal over the median) | Replaced by human-calibrated hands-on time (SWE-bench Verified). |
| Localization index = files changed in training PRs, so only next.js paths could ever be predicted | Ranking over the target repository's own file tree. |
| Directory snapshots included `node_modules` (two 400 MB artifacts) | Snapshot walker skips vendored/build paths. |

## Leakage controls

- Features use only issue title, body and labels; patches, PR data and comments are labels or excluded.
- Train / dev / test / multilingual groups have disjoint repositories; models never see an evaluation repository.
- Localization history features (frequency, recency, similar past issues) use only issues created before the query issue.
- Success features use only the author's PRs closed before the PR was opened; `author_association` (a current-state field) is excluded.
- Hyper-parameters and blends are selected with repository-grouped CV or the dev split - never on test.
- Known residual risk: GitHub labels are as of crawl time and may have been added during triage (affects next.js actionability only).
