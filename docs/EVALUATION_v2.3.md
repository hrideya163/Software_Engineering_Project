# ContriMap v2.3: repository intelligence, visualizer and feedback

This round adds similar-issue and resolving-PR retrieval, repository health, a file inspector with
function/class relationships, a layered module view, separate architecture and issue-impact views,
recommendation feedback, and reorganised issue analysis and dashboard pages.

## Similar-issue retrieval (measured)

**Question.** If we retrieve the past issues most similar to a new one, do the fixes of those past issues
touch the files the new issue's fix touches? That is what the *Similar history* tab and the
"changed by a similar past fix" overlay rely on.

**Protocol** (`history.evaluate_retrieval`, results in `data/history_retrieval_eval.json`):

- The 16 corpus repositories with at least 400 resolved issues, split alternately into 8 validation and 8 test repositories. The test repositories are Qiskit, meson, google-cloud-python, conan, django, conda, airflow and prefect.
- For each repository, the latest 600 issues are put in time order. The last 20% are queries, and only issues created before each query can be retrieved.
- `hit@5`: at least one of the 5 retrieved issues changed a file that the query's fix changed.
- `file_recall@10`: the share of the query's changed files among the 10 files with the most similarity-weighted votes.
- The blend weight was chosen on the validation repositories (0.5 had the best hit@5) and is reported once on the test repositories.

| Method (8 held-out repositories, 897 queries) | hit@5 | file_recall@10 |
|---|---|---|
| **Hybrid (0.5 MiniLM + 0.5 TF-IDF), shipped** | **0.544** | 0.396 |
| MiniLM embeddings only | 0.542 | **0.401** |
| TF-IDF only | 0.466 | 0.336 |
| 5 most recent earlier issues | 0.225 | 0.118 |
| 5 random earlier issues | 0.167 | 0.080 |

Validation (8 repositories, 923 queries): hybrid 0.5 scored hit@5 0.618, against 0.596 for embeddings only and 0.535 for TF-IDF only.

**Reading.**

- Retrieval is useful. For more than half of new issues, at least one of the five most similar past issues changed a file the new fix changes. That is about 2.4 times the recency baseline and 3.3 times random.
- The hybrid's validation gain over embeddings alone did **not** carry over to the held-out repositories. It ties them (+0.002 hit@5, -0.005 recall), so we do not claim the blend improves on embeddings.
- We shipped the validation-selected weight, as the protocol says. Keyword overlap still helps when an issue names identifiers.

**Caveats.**

- The live feature searches only the 100 most recently closed issues and merged PRs; the evaluation searches up to 600 earlier corpus issues.
- Live links between issues and PRs come from closing keywords ("fixes #N"), which miss fixes that do not reference their issue.
- The display threshold (similarity ≥ 0.25) was not tuned.

## Changes that are engineering, not model improvements

These have no accuracy claim; they were checked by tests and in the browser.

- **Ranking performance.** Per-user feedback re-ranking reuses a cached, profile-independent batch (embeddings, localization, difficulty). On pallets/click, a new user's ranked list of 40 issues takes 0.9 s instead of 32 s.
- **Repository health** (`/activity`) is a transparent heuristic over recent commits, PR merge times and acceptance, maintainer spread and issue replies. It is labelled as such in the UI.
- **Symbol relationships** are name matches in importing files, not type-resolved references.
- **Feedback** re-ranks with a preference vector of the issues a user saved, completed or opened, minus the ones they dismissed (weight 0.12). Dismissed issues are hidden. There is no outcome data yet, so its effect on recommendation quality is **not measured**.
- **Confidence display.**
  - Difficulty and effort show the probability of the predicted class with a high/medium/low dot.
  - File localization percentages are now described as relative shares among the shown candidates, because they are a softmax over the shortlist, not calibrated probabilities.

## Tests

`contrimap_ml/test_v4.py` (15 tests, no network) covers:

- closing-keyword linking, retrieval and file voting;
- symbol extraction across languages and symbol usage;
- file details;
- module layering and wrapping;
- the feedback store, validation and preference vector;
- the feedback and file API routes.

All 62 tests in `test_v2`, `test_v3` and `test_v4` pass; CI runs all three.

## Not done in this round

- Difficulty and effort models were not retrained. Better labels, repository/code context and calibrated uncertainty need new human-labelled data or a calibration set; the numbers in `EVALUATION_v2.2.md` still apply.
- Localization confidence is not calibrated. The next step is to fit P(top-1 correct) against the softmax weight on the dev split.
- Function-level *localization* (ranking functions instead of files) is not implemented. The inspector lists functions and classes and which files use them, but the model still ranks files.
- Docs and feature-request localization, and recommendation evaluation across several repositories with feedback outcomes, remain open.
- There is no end-to-end browser test suite. The pages were checked manually at 1440 px and 375 px.
