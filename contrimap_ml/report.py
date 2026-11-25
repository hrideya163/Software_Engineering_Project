"""Render ``artifacts/v2/evaluation_report.json`` as ``docs/EVALUATION.md``.

    python -m contrimap_ml.report

Numbers are copied from the report produced by ``train_v2`` - never edit them by hand.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def _f(value: Any) -> str:
    return f"{value:.3f}" if isinstance(value, (int, float)) and not isinstance(value, bool) else ("-" if value is None else str(value))


def _table(header: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join([str(row[0])] + [_f(cell) for cell in row[1:]]) + " |" for row in rows]
    return "\n".join(lines)


def render(report: dict[str, Any], legacy: dict[str, Any] | None = None) -> str:
    out = ["# ContriMap evaluation report", "", f"Generated from `artifacts/v2/evaluation_report.json` ({report.get('generated_at', 'unknown time')}). Regenerate with `python -m contrimap_ml.report`.", ""]
    if report.get("data_note"):
        out += [f"> {report['data_note']}", ""]
    corpus = report.get("corpus", {})
    if corpus:
        out += ["## Data", "", f"{corpus['records']} resolved issues from {corpus['repositories']} repositories.", "",
                _table(["Group", "Records", "Repositories"], [[group, values["records"], values["repositories"]] for group, values in corpus["by_group"].items()]).replace(".000", ""), "",
                "Train, dev, test and multilingual groups use **disjoint repositories** (SWE-bench design), so every headline number is measured on repositories the models never saw.", ""]
    d = report.get("difficulty")
    if d:
        out += ["## Difficulty classification", "", f"Label: {d['label_definition']}; thresholds {[round(t, 3) for t in d['thresholds']]}. Model selection by repository-grouped 5-fold CV on training repositories (selected linear blend {d['selected_linear_blend']}).", ""]
        rows = []
        for group in ("dev", "test", "multilingual"):
            if group in d:
                block = d[group]
                rows += [[f"**ContriMap** - {group} ({block['repositories']} repos, n={block['model']['n']})", block["model"]["accuracy"], block["model"]["macro_f1"], block["model"]["spearman_score_vs_true_scale"]]]
                rows += [[f"stratified random - {group}", block["baselines"]["stratified_random"]["accuracy"], block["baselines"]["stratified_random"]["macro_f1"], None],
                         [f"majority class - {group}", block["baselines"]["majority_class"]["accuracy"], block["baselines"]["majority_class"]["macro_f1"], None],
                         [f"body-length tertiles - {group}", block["baselines"]["body_length_tertiles"]["accuracy"], block["baselines"]["body_length_tertiles"]["macro_f1"], None]]
        out += [_table(["Model / split", "Accuracy", "Macro-F1", "Spearman vs true size"], rows), ""]
        if "test" in d:
            out += [f"Change-size regressor (Huber): test MAE {_f(d['test']['size_regressor_mae'])} vs train-median baseline {_f(d['test']['size_baseline_mae_train_median'])}; Spearman {_f(d['test']['size_regressor_spearman'])}.", ""]
        effort = d.get("effort")
        if effort:
            out += ["## Effort estimation", "", f"{effort['evaluation']} (n={effort['n']}, {effort['repositories']} repositories).", "",
                    _table(["Model", "Bucket accuracy", "Macro-F1", "MAE (levels)", "Spearman vs human hours"], [
                        ["**ContriMap**", effort["bucket_accuracy"], effort["bucket_macro_f1"], effort["bucket_mae_levels"], effort["spearman_expected_hours_vs_human"]],
                        ["majority bucket", effort["baseline_majority_bucket_accuracy"], None, effort["baseline_majority_bucket_mae_levels"], None]]), "",
                    f"The difficulty score alone correlates with human time-to-fix at Spearman {_f(effort['difficulty_score_spearman_vs_human'])}. **Effort is a weak signal from issue text alone** and is presented as a bucket with a range.", ""]
    loc = report.get("localization")
    if loc:
        out += ["## Issue-to-file localization", "", "Hit = at least one file changed by the gold fix appears in the top k. Candidates are all files in the repository at the issue's base commit (tree mode) or files changed earlier in the repository (history mode).", ""]
        for key in ("dev", "test_verified_tree", "multilingual_tree", "nextjs_history_last20pct"):
            block = loc.get(key)
            if not block:
                continue
            rows = [["**ContriMap ranker**", block["model"]["acc@1"], block["model"]["acc@5"], block["model"]["acc@10"], block["model"]["mrr"]]]
            rows += [[name.removeprefix("baseline_").replace("_", " "), m["acc@1"], m["acc@5"], m["acc@10"], m["mrr"]] for name, m in block.items() if name.startswith("baseline_")]
            out += [f"### {key} (n={block['model']['n']}, median {block['median_candidates']:.0f} candidate files)", "",
                    _table(["Method", "acc@1", "acc@5", "acc@10", "MRR"], rows), "",
                    f"Oracle coverage (a gold file exists among candidates): {_f(block['model'].get('oracle_candidate_coverage'))}; prefilter coverage: {_f(block['prefilter_coverage'])}.", ""]
        if legacy:
            out += [f"Legacy model on its own next.js temporal split (history candidates, all changed files as targets): recall@5 {_f(legacy.get('recall_at_5'))}, recall@10 {_f(legacy.get('recall_at_10'))}, MRR {_f(legacy.get('mrr'))} - not directly comparable (different target definition and candidate set), and it could not localize in any other repository.", ""]
        importance = loc.get("feature_importance_gain", {})
        out += ["Top ranker features by gain: " + ", ".join(f"{name} ({value:.2f})" for name, value in list(importance.items())[:8]) + ".", ""]
        rerank = loc.get("code_reranker")
        if rerank:
            out += ["### Stage 2: reading the code of the shortlist", "",
                    f"The stage-1 top {rerank['depth']} files are read at the issue's base commit and re-ranked with code features (definitions of symbols named in the issue, quoted error strings, BM25 over identifiers). "
                    f"Training shortlists come from cross-fitted stage-1 models (no in-sample scores); the re-ranker is kept only if it beats stage 1 on dev MRR (dev {_f(rerank['dev_stage1_mrr'])} -> {_f(rerank['dev_stage2_mrr'])}; selected: **{rerank['selected']}**).", ""]
            rows = []
            for key in ("dev", "test_verified_tree", "multilingual_tree"):
                if key in rerank and key in loc:
                    first, second = loc[key]["model"], rerank[key]["model"]
                    rows += [[f"{key} - stage 1 (paths/text/history)", first["acc@1"], first["acc@5"], first["acc@10"], first["mrr"]],
                             [f"**{key} - stage 2 (+ code)**", second["acc@1"], second["acc@5"], second["acc@10"], second["mrr"]]]
            out += [_table(["Split / model", "acc@1", "acc@5", "acc@10", "MRR"], rows), "",
                    "Top re-ranker features by gain: " + ", ".join(f"{name} ({value:.2f})" for name, value in list(rerank.get("feature_importance_gain", {}).items())[:8]) + ".", ""]
    comparison = report.get("localization_comparison")
    if comparison:
        out += ["### With and without repository history", "",
                "Same cached issues and candidates scored by each saved model (`python -m contrimap_ml.compare_localization`). "
                "`*_nohist` splits switch repository-history features off - the situation of most repositories analysed live, which have no ingested resolved-issue history.", ""]
        rows = []
        for model_name, splits in comparison.items():
            for split, stages in splits.items():
                for stage, m in stages.items():
                    rows.append([f"{model_name} · {split} · {stage}", m["acc@1"], m["acc@5"], m["acc@10"], m["mrr"]])
        out += [_table(["Model · split · stage", "acc@1", "acc@5", "acc@10", "MRR"], rows), ""]
    structural = (d or {}).get("structural")
    if structural and "grouped_cv_macro_f1" in structural:
        cv = structural["grouped_cv_macro_f1"]
        out += ["## Difficulty with localization and code signals", "",
                f"A stacker on out-of-fold text probabilities plus {len(structural.get('signals', [])) or 12} signals describing the likely change site (shortlist confidence and spread, mentioned files, symbol definitions found, size of the top files). "
                f"Grouped CV macro-F1 on {structural['train_issues']} training issues: text model {_f(cv['text_model_oof'])}, text-only stacker {_f(cv['text_stacker'])}, with signals {_f(cv['text_plus_code_signals'])}; selected: **{structural['selected']}**.", ""]
        rows = []
        for group in ("dev", "test", "multilingual"):
            block = structural.get(group)
            if block:
                rows += [[f"{group} (n={block['n']}) - text only", block["text_only"]["accuracy"], block["text_only"]["macro_f1"], block["text_only"]["spearman_score_vs_true_scale"]],
                         [f"**{group} - text + code signals**", block["text_plus_code_signals"]["accuracy"], block["text_plus_code_signals"]["macro_f1"], block["text_plus_code_signals"]["spearman_score_vs_true_scale"]]]
        out += [_table(["Split / model", "Accuracy", "Macro-F1", "Spearman vs true size"], rows), ""]
        human = (structural.get("test") or {}).get("spearman_vs_human_time_to_fix")
        if human:
            out += [f"Spearman with human time-to-fix (SWE-bench Verified): text only {_f(human['text_only'])}, with signals {_f(human['text_plus_code_signals'])}.", ""]
        if structural.get("selection_rule"):
            out += [f"Selection rule: {structural['selection_rule']}. {structural.get('note', '')}", ""]
    effort_structural = (d or {}).get("effort_structural")
    if effort_structural and "text_only" in effort_structural:
        rows = [[name.replace("_", " "), m["bucket_accuracy"], m["bucket_macro_f1"], m["spearman_expected_hours_vs_human"], m["log_loss"]] for name, m in ((k, effort_structural[k]) for k in ("text_only", "text_plus_code_signals"))]
        rows.append(["majority bucket", effort_structural["baseline_majority_bucket_accuracy"], None, None, None])
        out += ["## Effort with localization and code signals", "", f"{effort_structural['evaluation']} (n={effort_structural['n']}). Selected (lower log-loss without losing rank correlation): **{effort_structural['selected']}**.", "",
                _table(["Calibrator", "Bucket accuracy", "Macro-F1", "Spearman vs human hours", "Log-loss"], rows), ""]
    action = report.get("issue_ranking_actionability")
    if action:
        out += ["## Issue ranking - actionability component", "", f"{action['dataset']}; temporal split (train {action['train']}, test {action['test']}, positive rate {_f(action['test_positive_rate'])}).", "",
                _table(["Model", "ROC-AUC", "Average precision"], [["**ContriMap**", action["roc_auc"], action["average_precision"]], ["keyword heuristic", action["baseline_heuristic_auc"], action["baseline_heuristic_ap"]], ["body length", action["baseline_body_length_auc"], None], ["random", 0.5, action["baseline_random_ap"]]]), "",
                f"Precision@50: {_f(action['precision_at_50'])}. {action['caveat']} The other ranking components (availability, freshness, clarity, community, focus) are transparent rules, not learned, and are not separately evaluated.", ""]
    multi_action = report.get("actionability_multirepo")
    if multi_action:
        best = multi_action["selected"]
        rows = [[repo, info["n"], info["positive_rate"], multi_action["per_repository_auc"][best][repo], multi_action["per_repository_auc"]["heuristic"][repo]] for repo, info in multi_action["repositories"].items()]
        rows.append(["**mean**", None, None, multi_action["mean_auc"][best], multi_action["mean_auc"]["heuristic"]])
        out += ["### Actionability across repositories (deployed model)", "", f"{multi_action['evaluation']}; selected **{best}** (mean AUC by candidate: {', '.join(f'{k} {v:.3f}' for k, v in multi_action['mean_auc'].items())}).", "",
                _table(["Held-out repository", "Issues", "Positive rate", "Model AUC", "Heuristic AUC"], rows), "", multi_action["caveat"], ""]
    success = report.get("success")
    if success:
        out += ["## Contribution success prediction", "", f"{success['dataset']} (train {success['train']}, test {success['test']}, merge rate {_f(success['test_merge_rate'])}).", "",
                _table(["Model", "ROC-AUC", "Average precision", "Brier"], [["**ContriMap** (calibrated GBM)", success["roc_auc"], success["average_precision"], success["brier"]], ["author prior merge rate", success["baseline_author_merge_rate_auc"], None, None], ["constant merge rate", 0.5, None, success["baseline_constant_brier"]]]), "",
                success["caveat"], ""]
    multi = report.get("success_multirepo")
    if multi:
        rows = [[repo, info["n"], info["merge_rate"], multi["per_repository_auc"]["gbm"][repo], multi["per_repository_auc"]["logistic"][repo], multi["per_repository_auc"]["author_rate_rule"][repo]] for repo, info in multi["repositories"].items()]
        rows.append(["**mean**", None, None, multi["mean_auc"]["gbm"], multi["mean_auc"]["logistic"], multi["mean_auc"]["author_rate_rule"]])
        out += ["### Cross-repository success prediction (deployed model)", "", f"{multi['evaluation']}; selected: **{multi['selected']}**. Data: uniform samples of closed PRs per repository plus next.js (PR bodies blanked everywhere for comparability).", "",
                _table(["Held-out repository", "PRs", "Merge rate", "GBM AUC", "Logistic AUC", "Author-rate rule AUC"], rows).replace("| - |", "|  |"), "", multi["caveat"], ""]
    ingested = report.get("ingested_evaluation", {}).get("localization")
    if ingested:
        rows = [["**ContriMap ranker**", ingested["model"]["acc@1"], ingested["model"]["acc@5"], ingested["model"]["acc@10"], ingested["model"]["mrr"]]]
        rows += [[name.removeprefix("baseline_").replace("_", " "), m["acc@1"], m["acc@5"], m["acc@10"], m["mrr"]] for name, m in ingested.items() if name.startswith("baseline_")]
        per_repo = ", ".join(f"{repo} {m['acc@5']:.2f} (n={m['n']})" for repo, m in ingested["per_repository"].items())
        out += ["## Fresh repositories (2023+, ingested via GraphQL)", "", f"Localization on the last 20% of issues per repository (n={ingested['model']['n']}); history from earlier issues only. {ingested['note']}", "",
                _table(["Method", "acc@1", "acc@5", "acc@10", "MRR"], rows), "", f"acc@5 per repository: {per_repo}.", ""]
    rec = report.get("recommendation")
    if rec:
        rows = [[("**ContriMap combined**" if name == "combined" else name.replace("_", " ")), m["acc@1"], m["acc@5"], m["acc@10"], m["mrr"]] for name, m in rec["test"].items()]
        out += ["## Contributor-issue recommendation", "", f"{rec['task']}; candidate pool {rec['candidate_pool']} contributors; weights chosen on a validation window: {rec['selected_weights']} (validation MRR {_f(rec['validation_mrr'])}).", "",
                _table(["Method", "acc@1", "acc@5", "acc@10", "MRR"], rows), "", rec["caveat"], ""]
    out += ["## Not evaluated offline", "", "- Personalised ranking and learning-opportunity scores have no ground truth; they are transparent combinations of the evaluated components and profile matching.",
            "- LLM explanations are constrained to model outputs (file references are validated) but their quality is not measured.", ""]
    return "\n".join(out)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Render an evaluation report as Markdown")
    parser.add_argument("--report", default=str(ROOT / "artifacts" / "v2" / "evaluation_report.json"))
    parser.add_argument("--output", default=str(ROOT / "docs" / "EVALUATION.md"))
    args = parser.parse_args()
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    legacy_path = ROOT / "artifacts" / "evaluation_metrics.json"
    legacy = json.loads(legacy_path.read_text(encoding="utf-8")).get("localization") if legacy_path.exists() else None
    target = Path(args.output)
    target.parent.mkdir(exist_ok=True)
    target.write_text(render(report, legacy), encoding="utf-8")
    print(f"Wrote {target}")


if __name__ == "__main__":
    main()
