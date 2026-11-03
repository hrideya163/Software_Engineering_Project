import { getModelCard } from '../api/contrimapApi'
import ErrorMessage from '../components/ErrorMessage'
import Loading from '../components/Loading'
import Navbar from '../components/Navbar'
import { useAsync } from '../hooks/useProfile'

const f = value => (typeof value === 'number' ? value.toFixed(3) : '-')

function Table({ rows, columns }) {
  return <div className="overflow-x-auto"><table className="mt-3 w-full text-left text-sm">
    <thead><tr className="border-b text-xs uppercase text-slate-500">{columns.map(column => <th key={column} className="py-2 pr-4 font-bold">{column}</th>)}</tr></thead>
    <tbody>{rows.map(row => <tr key={row[0]} className={`border-b last:border-0 ${row[0].startsWith('ContriMap') ? 'font-bold text-ink' : 'text-slate-600'}`}>{row.map((cell, i) => <td key={i} className="py-2 pr-4">{i ? f(cell) : cell}</td>)}</tr>)}</tbody>
  </table></div>
}

function Section({ title, children, note }) {
  return <section className="card mt-5 p-6"><h2 className="text-lg font-extrabold">{title}</h2>{children}{note && <p className="mt-3 text-xs leading-5 text-slate-500">{note}</p>}</section>
}

// Renders artifacts/v2/evaluation_report.json - every number is measured, held-out, against baselines.
export default function ModelCard() {
  const { data, loading, error } = useAsync(getModelCard, [])
  const d = data?.difficulty || {}
  const loc = data?.localization || {}
  const locRows = key => {
    const block = loc[key] || {}
    return [['ContriMap ranker', block.model?.['acc@1'], block.model?.['acc@5'], block.model?.['acc@10'], block.model?.mrr],
      ...['legacy_formula', 'bm25', 'embedding', 'similar_issues_knn', 'history_frequency', 'random'].filter(name => block[`baseline_${name}`]).map(name => [name.replace(/_/g, ' '), block[`baseline_${name}`]['acc@1'], block[`baseline_${name}`]['acc@5'], block[`baseline_${name}`]['acc@10'], block[`baseline_${name}`].mrr])]
  }
  return <><Navbar /><main className="mx-auto max-w-5xl px-5 py-12">
    <p className="eyebrow">Model card</p>
    <h1 className="mt-2 text-3xl font-extrabold">How well do the models work?</h1>
    <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">Trained on SWE-bench training repositories; evaluated on repositories and languages never seen in training (SWE-bench test / Verified, SWE-bench Multilingual) and on the last 20% of next.js history. Baselines are reported next to every metric.</p>
    {loading && <Loading />}
    {error && <div className="mt-5"><ErrorMessage message={error} /></div>}
    {data && <>
      <Section title="Difficulty classification (Easy / Medium / Hard)" note={`Labels: ${d.label_definition}. Proxy validated against human time-to-fix annotations (Spearman ≈ 0.52).`}>
        <Table columns={['Model', 'Accuracy', 'Macro-F1']} rows={['test', 'multilingual'].flatMap(group => d[group] ? [[`ContriMap - ${group}`, d[group].model.accuracy, d[group].model.macro_f1], [`stratified random - ${group}`, d[group].baselines.stratified_random.accuracy, d[group].baselines.stratified_random.macro_f1], [`majority class - ${group}`, d[group].baselines.majority_class.accuracy, d[group].baselines.majority_class.macro_f1]] : [])} />
      </Section>
      {d.effort && <Section title="Effort estimation (hours, human-calibrated)" note={`${d.effort.evaluation}. Text-only effort prediction carries weak signal; treat estimates as rough buckets.`}>
        <Table columns={['Model', 'Bucket accuracy', 'Spearman vs human', 'MAE (levels)']} rows={[['ContriMap', d.effort.bucket_accuracy, d.effort.spearman_expected_hours_vs_human, d.effort.bucket_mae_levels], ['majority bucket', d.effort.baseline_majority_bucket_accuracy, null, d.effort.baseline_majority_bucket_mae_levels]]} />
      </Section>}
      {['test_verified_tree', 'multilingual_tree', 'nextjs_history_last20pct'].filter(key => loc[key]).map(key => <Section key={key} title={`File localization - ${key.replace(/_/g, ' ')}`} note={`acc@k = at least one changed file in the top k. Median ${loc[key].median_candidates} candidate files per issue; oracle coverage ${f(loc[key].model.oracle_candidate_coverage)} (files created by the fix cannot be predicted).`}>
        <Table columns={['Method', 'acc@1', 'acc@5', 'acc@10', 'MRR']} rows={locRows(key)} />
      </Section>)}
      {data.issue_ranking_actionability && <Section title="Issue ranking - actionability" note={data.issue_ranking_actionability.caveat}>
        <Table columns={['Model', 'ROC-AUC', 'Average precision']} rows={[['ContriMap', data.issue_ranking_actionability.roc_auc, data.issue_ranking_actionability.average_precision], ['keyword heuristic', data.issue_ranking_actionability.baseline_heuristic_auc, data.issue_ranking_actionability.baseline_heuristic_ap], ['random', 0.5, data.issue_ranking_actionability.baseline_random_ap]]} />
      </Section>}
      {data.success && <Section title="Contribution success (PR merged)" note={data.success.caveat}>
        <Table columns={['Model', 'ROC-AUC', 'Brier']} rows={[['ContriMap', data.success.roc_auc, data.success.brier], ['author merge rate only', data.success.baseline_author_merge_rate_auc, null], ['constant rate', 0.5, data.success.baseline_constant_brier]]} />
      </Section>}
      {data.success_multirepo && <Section title="Contribution success - unseen repositories (deployed model)" note={`${data.success_multirepo.evaluation}. ${data.success_multirepo.caveat}`}>
        <Table columns={['Held-out repository', 'GBM AUC', 'Author-rate rule AUC']} rows={[['ContriMap mean', data.success_multirepo.mean_auc.gbm, data.success_multirepo.mean_auc.author_rate_rule], ...Object.keys(data.success_multirepo.repositories).map(repo => [repo, data.success_multirepo.per_repository_auc.gbm[repo], data.success_multirepo.per_repository_auc.author_rate_rule[repo]])]} />
      </Section>}
      {data.ingested_evaluation?.localization && <Section title="File localization - fresh repositories (2023+)" note={data.ingested_evaluation.localization.note}>
        <Table columns={['Method', 'acc@1', 'acc@5', 'acc@10', 'MRR']} rows={[['ContriMap ranker', ...['acc@1', 'acc@5', 'acc@10', 'mrr'].map(k => data.ingested_evaluation.localization.model[k])], ...['legacy_formula', 'similar_issues_knn', 'bm25', 'embedding'].map(name => [name.replace(/_/g, ' '), ...['acc@1', 'acc@5', 'acc@10', 'mrr'].map(k => data.ingested_evaluation.localization[`baseline_${name}`][k])])]} />
      </Section>}
      {data.recommendation &&<Section title="Contributor-issue recommendation" note={`${data.recommendation.task}. ${data.recommendation.caveat}`}>
        <Table columns={['Method', 'acc@1', 'acc@5', 'acc@10', 'MRR']} rows={Object.entries(data.recommendation.test).map(([name, m]) => [name === 'combined' ? 'ContriMap combined' : name.replace(/_/g, ' '), m['acc@1'], m['acc@5'], m['acc@10'], m.mrr])} />
      </Section>}
      <p className="mt-5 text-xs text-slate-400">Report generated {data.generated_at}.</p>
    </>}
  </main></>
}
