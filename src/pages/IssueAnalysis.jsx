import { AlertTriangle, Bookmark, BookmarkCheck, CheckCircle2, ExternalLink, FileCode2, FlaskConical, GitMerge, GitPullRequest, History, Lightbulb, Network, Sparkles, Target } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { feedbackUser, getIssueAnalysis, getSimilarHistory, sendFeedback } from '../api/contrimapApi'
import AppLayout from '../components/AppLayout'
import DifficultyBadge from '../components/DifficultyBadge'
import ErrorMessage from '../components/ErrorMessage'
import FileTree from '../components/FileTree'
import FlowGraph, { Legend } from '../components/FlowGraph'
import { impactView } from '../utils/graphViews'
import Loading from '../components/Loading'
import { ConfidenceDot, ScoreBars } from '../components/RankedIssueCard'
import SkillTag from '../components/SkillTag'
import ContributionPath from '../components/contribution/ContributionPath'
import { useAsync, useProfile } from '../hooks/useProfile'
import RepositoryGate from '../components/RepositoryGate'

const pct = value => (value === null || value === undefined ? '-' : `${Math.round(value * 100)}%`)
const TABS = [['overview', 'Overview'], ['fit', 'Contribution fit'], ['files', 'File localization'], ['impact', 'Code impact'], ['history', 'Similar history'], ['guide', 'Contribution guide']]

function Distribution({ values, highlight }) {
  return <div className="mt-3 space-y-1.5">{Object.entries(values || {}).map(([name, value]) => <div key={name} className="flex items-center gap-2 text-xs">
    <span className={`w-24 shrink-0 font-semibold ${name === highlight ? 'text-ink' : 'text-slate-500'}`}>{name}</span>
    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100"><div className={`h-full rounded-full ${name === highlight ? 'bg-ink' : 'bg-slate-300'}`} style={{ width: `${value * 100}%` }} /></div>
    <span className="w-9 text-right font-bold text-slate-600">{pct(value)}</span>
  </div>)}</div>
}

// One headline number with a confidence indicator and the reason behind it.
function Metric({ label, value, sub, confidence, children }) {
  return <section className="card p-4">
    <div className="flex items-center justify-between"><p className="eyebrow">{label}</p><ConfidenceDot level={confidence} /></div>
    <div className="mt-2 text-xl font-extrabold text-ink">{value}</div>
    {sub && <p className="mt-0.5 text-xs text-slate-500">{sub}</p>}
    {children}
  </section>
}

function confidenceOf(probability) {
  if (probability === null || probability === undefined) return null
  return probability >= 0.65 ? 'high' : probability >= 0.45 ? 'medium' : 'low'
}

// Probability mass on one file out of hundreds: 20% is already a strong lead.
function fileConfidence(probability) {
  if (probability === null || probability === undefined) return null
  return probability >= 0.5 ? 'high' : probability >= 0.2 ? 'medium' : 'low'
}

function Overview({ a }) {
  const explanation = a.explanation || {}
  const top = a.files[0]
  return <div className="space-y-5">
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <Metric label="Difficulty" value={<DifficultyBadge level={a.difficulty} />} confidence={a.confidence} sub={`${pct(a.difficulty_probability)} probability · from ${a.difficulty_inputs || 'issue text'}`} />
      <Metric label="Effort" value={a.effort_bucket || '-'} confidence={confidenceOf(a.effort_probability)} sub={a.effort_range_hours ? `about ${a.effort_range_hours[0]}-${a.effort_range_hours[1]} h of focused work` : null} />
      <Metric label="Most likely file" value={<span className="mono block truncate text-sm" title={top?.path}>{top ? top.path.split('/').slice(-2).join('/') : 'none found'}</span>} confidence={top ? fileConfidence(top.relative_confidence) : null} sub={top ? `${pct(top.relative_confidence)} share of the model's score among ${a.files.length} candidates (uncalibrated) · ${top.code_read ? 'code read' : 'paths and text only'}` : null} />
      {a.actionability !== null && a.actionability !== undefined
        ? <Metric label="Actionable" value={pct(a.actionability)} confidence={confidenceOf(Math.abs(a.actionability - 0.5) * 2)} sub="chance it is resolved by a code change, not closed as a question or duplicate" />
        : <Metric label="Blast radius" value={`${a.impact.dependents_within_2_hops} files`} sub={`import the top candidates within two hops · ${a.related_tests.length} related tests`} />}
    </div>
    <section className="card p-5">
      <div className="flex flex-wrap items-center justify-between gap-2"><p className="eyebrow inline-flex items-center gap-2"><Sparkles size={14} />Summary</p><span className="text-[11px] font-bold text-slate-400">{explanation.source === 'llm' ? `written by ${explanation.model} from the model outputs` : 'template summary (no LLM configured)'}</span></div>
      <p className="mt-3 leading-7 text-slate-700">{explanation.summary}</p>
      {explanation.why_this_difficulty && <p className="mt-2 text-sm leading-6 text-slate-600"><b className="text-ink">Why this difficulty: </b>{explanation.why_this_difficulty}</p>}
      {explanation.risks?.length > 0 && <div className="mt-4 flex gap-2 rounded-xl bg-amber-50 p-3 text-xs leading-5 text-amber-800"><AlertTriangle size={14} className="mt-0.5 shrink-0" /><span>{explanation.risks.join(' ')}</span></div>}
    </section>
    <div className="grid gap-5 lg:grid-cols-2">
      <section className="card p-5">
        <p className="eyebrow">Difficulty distribution</p>
        <Distribution values={a.difficulty_distribution} highlight={a.difficulty} />
        <p className="mt-3 text-[11px] leading-4 text-slate-400">When no class clearly wins (low confidence), treat the estimate as a range rather than a label.</p>
      </section>
      <section className="card p-5">
        <p className="eyebrow">Effort distribution</p>
        <Distribution values={a.effort_distribution} highlight={a.effort_bucket} />
        {a.effort_note && <p className="mt-3 text-[11px] leading-4 text-slate-400">{a.effort_note}</p>}
      </section>
    </div>
  </div>
}

function Fit({ a }) {
  return <div className="grid gap-5 lg:grid-cols-[1.2fr_.8fr]">
    <section className="card p-5">
      <p className="eyebrow">{a.personal ? 'How well it fits you' : 'Contribution outlook'}</p>
      {a.personal ? <>
        <div className="mt-4"><ScoreBars components={a.personal.components} limit={8} /></div>
        {a.personal?.learning?.new_skills?.length > 0 && <p className="mt-5 text-sm text-slate-600"><b className="text-ink">You would learn:</b> {a.personal.learning.new_skills.map(s => s.name).join(', ')}</p>}
        {a.skill_gaps?.length > 0 && <div className="mt-4 rounded-xl bg-amber-50 p-3 text-sm text-amber-800"><b>Skill gaps:</b> {a.skill_gaps.map(s => s.name).join(', ')}<p className="mt-1 text-xs">Required by the issue but weak or missing in your profile. Fine for a learning issue; risky for a quick win.</p></div>}
      </> : <div className="mt-4 space-y-3 text-sm">
        <p><b>{pct(a.actionability)}</b> <span className="text-slate-500">likely to be resolved by a code change</span></p>
        <p><b>{pct(a.success_probability)}</b> <span className="text-slate-500">estimated merge probability for a first-time contributor</span></p>
        <Link to="/profile" className="inline-flex text-sm font-bold text-blue-700">Set up your profile to see your personal fit and skill gaps →</Link>
      </div>}
    </section>
    <section className="card p-5">
      <p className="eyebrow">Skills involved</p>
      <ul className="mt-4 space-y-3">{a.skills.map(skill => <li key={skill.id}><div className="flex items-center justify-between"><SkillTag>{skill.name}</SkillTag><span className="text-xs font-bold text-slate-400">{pct(skill.weight)}</span></div><p className="mt-1 truncate text-[11px] text-slate-400">{skill.evidence[0]}</p></li>)}</ul>
    </section>
  </div>
}

function Files({ a, history }) {
  const historical = new Map((history.data?.historical_files || []).map(item => [item.path, item]))
  return <div className="grid gap-5 xl:grid-cols-[1.15fr_.85fr]">
    <section className="card p-5">
      <p className="eyebrow">Likely files to change</p>
      <p className="mt-1 text-xs text-slate-500">Ranked over every file in the repository · {a.localization_mode}. Bars show each file's share of the model's score among these candidates (relative, not a calibrated probability); a clear gap after the first few means a confident prediction.</p>
      <ol className="mt-4 space-y-3">{a.files.map(file => <li key={file.path} className="flex gap-3">
        <span className="w-5 shrink-0 text-right text-xs font-extrabold text-slate-400">{file.rank}</span>
        <div className="min-w-0 flex-1">
          <a target="_blank" rel="noreferrer" href={`https://github.com/${a.repository}/blob/${a.sha}/${file.path}`} className="mono flex items-center gap-1.5 truncate text-sm text-blue-800 hover:underline"><FileCode2 size={13} className="shrink-0" />{file.path}</a>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {historical.has(file.path) && <span className="inline-flex items-center gap-1 rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-bold text-emerald-700" title={`Changed by the fixes of similar past issues: ${historical.get(file.path).from.map(n => `#${n}`).join(', ')}`}><GitMerge size={10} />changed by similar fixes</span>}
            {file.signals.map(signal => <span key={signal} className="rounded bg-sky px-1.5 py-0.5 text-[10px] font-bold text-ink">{signal}</span>)}
          </div>
        </div>
        <div className="w-16 shrink-0"><div className="h-1.5 overflow-hidden rounded-full bg-slate-100"><div className="h-full bg-rose-500" style={{ width: `${file.relative_confidence * 100}%` }} /></div><p className="mt-1 text-right text-[10px] text-slate-400">{pct(file.relative_confidence)}</p></div>
      </li>)}</ol>
    </section>
    <section className="card self-start p-5">
      <p className="eyebrow inline-flex items-center gap-2"><History size={14} />Changed by similar past fixes</p>
      <p className="mt-1 text-xs text-slate-500">Files the merged pull requests of similar closed issues touched. A second, independent signal: files in both lists are the strongest leads.</p>
      {history.loading && <p className="mt-4 text-xs text-slate-400">Searching closed issues and pull requests…</p>}
      {history.error && <p className="mt-4 text-xs text-amber-700">{history.error}</p>}
      {history.data && (history.data.historical_files.length ? <ul className="mt-4 space-y-2">{history.data.historical_files.slice(0, 8).map(item => <li key={item.path} className="flex items-center justify-between gap-2 text-xs">
        <span className={`mono truncate ${item.also_predicted ? 'font-bold text-emerald-700' : 'text-slate-600'}`} title={item.path}>{item.path}</span>
        <span className="shrink-0 text-[10px] text-slate-400">{item.from.map(n => `#${n}`).join(' ')}</span>
      </li>)}</ul> : <p className="mt-4 text-xs text-slate-500">No similar resolved work found in the recent history.</p>)}
      {history.data && <p className="mt-4 text-[11px] text-slate-400">{history.data.agreement} of the top history files are also predicted by the localization model.</p>}
    </section>
  </div>
}

function Impact({ a, owner, repo, history }) {
  const graph = impactView(a.graph, history.data?.historical_files)
  return <div className="space-y-5">
    <div className="grid gap-4 sm:grid-cols-3">
      <Metric label="Blast radius" value={`${a.impact.dependents_within_2_hops} files`} sub="import the top candidates within two hops" />
      <Metric label="Related tests" value={a.related_tests.length} sub={a.related_tests.length ? 'tests import the top candidates' : 'no test imports a top candidate; you may need a new one'} />
      <Metric label="Top candidate importance" value={a.files[0] ? `${(a.files[0].importance * 1000).toFixed(1)}‰` : '-'} sub="share of import-graph PageRank" />
    </div>
    <section>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        <div><p className="eyebrow">Code neighbourhood</p><p className="mt-1 text-xs text-slate-500">Predicted files with the files that import them, the files they import and their tests. Hover a file to trace its links.</p></div>
        <Link to={`/repository/${owner}/${repo}/visualizer?issue=${a.issue.number}&view=impact`} className="btn-secondary"><Network size={16} />Open in visualizer</Link>
      </div>
      {graph ? <FlowGraph graph={graph} height={480} /> : <p className="card p-6 text-sm text-slate-500">No import relationships were resolved for these files.</p>}
      <Legend items={[['target', 'likely change'], ['importer', 'imports it'], ['dependency', 'imported by it'], ['test', 'test'], ['historical', 'changed by a similar fix']]} />
    </section>
    <div className="grid gap-5 lg:grid-cols-2">
      <section className="card p-5">
        <p className="eyebrow inline-flex items-center gap-1.5"><FlaskConical size={13} />Tests to run</p>
        {a.related_tests.length ? <ul className="mt-3 space-y-1">{a.related_tests.map(test => <li key={test} className="mono text-xs text-violet-700">{test}</li>)}</ul> : <p className="mt-3 text-sm text-slate-500">None found through imports.</p>}
        {a.impact.examples?.length > 0 && <><p className="eyebrow mt-5">Dependents to check</p><ul className="mt-3 space-y-1">{a.impact.examples.map(path => <li key={path} className="mono text-xs text-slate-600">{path}</li>)}</ul></>}
      </section>
      <section className="card p-5"><p className="eyebrow">Repository tree</p><div className="mt-3"><FileTree tree={a.tree} /></div></section>
    </div>
  </div>
}

function SimilarHistory({ history }) {
  if (history.loading) return <Loading label="Searching closed issues and merged pull requests…" />
  if (history.error) return <ErrorMessage message={history.error} />
  const data = history.data
  if (!data) return null
  return <section className="card p-5">
    <p className="eyebrow">Similar resolved work</p>
    <p className="mt-1 text-xs text-slate-500">{data.method}; searched {data.searched} items. Read how these were fixed before you start.</p>
    {!data.similar.length && <p className="mt-5 text-sm text-slate-500">Nothing similar enough in the recent history.</p>}
    <ul className="mt-4 divide-y">{data.similar.map(item => <li key={`${item.kind}${item.number}`} className="py-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <a href={item.html_url} target="_blank" rel="noreferrer" className="font-bold text-ink hover:text-blue-800">{item.kind === 'issue' ? 'Issue' : 'PR'} #{item.number}: {item.title}</a>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            {item.closed_at && <span>closed {item.closed_at.slice(0, 10)}</span>}
            {item.pull_requests.map(pr => <a key={pr.number} href={pr.html_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-bold text-emerald-700 hover:underline"><GitPullRequest size={12} />#{pr.number}{pr.author ? ` by ${pr.author}` : ''}</a>)}
            {item.change_size && <span>{item.change_size.files} files, +{item.change_size.additions} -{item.change_size.deletions}</span>}
          </div>
        </div>
        <span className="shrink-0 rounded-lg bg-sky px-2 py-1 text-xs font-extrabold text-ink" title="Similarity (hybrid semantic and keyword)">{pct(item.similarity)}</span>
      </div>
      {item.changed_files.length > 0 && <div className="mt-2 flex flex-wrap gap-1.5">{item.changed_files.slice(0, 8).map(path => <span key={path} className="mono rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600">{path}</span>)}</div>}
    </li>)}</ul>
  </section>
}

function Guide({ a }) {
  const explanation = a.explanation || {}
  return <div className="grid gap-5 lg:grid-cols-[1.3fr_.7fr]">
    <ContributionPath path={a.contribution_path} storageKey={`contrimap.path.${a.repository}#${a.issue.number}`} />
    <div className="space-y-5 self-start">
      <section className="card p-5">
        <p className="eyebrow">Where to start</p>
        <ul className="mt-3 space-y-2">{(explanation.where_to_start || []).map(item => <li key={item.path} className="text-sm"><span className="mono text-blue-800">{item.path}</span><br /><span className="text-xs text-slate-500">{item.reason}</span></li>)}</ul>
        {explanation.approach?.length > 0 && <><p className="eyebrow mt-5">Approach</p><ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-slate-700">{explanation.approach.map(step => <li key={step}>{step}</li>)}</ol></>}
        {explanation.learning_value && <p className="mt-4 inline-flex items-start gap-2 text-xs text-slate-600"><Lightbulb size={13} className="mt-0.5 shrink-0" />{explanation.learning_value}</p>}
      </section>
      <p className="text-[11px] leading-4 text-slate-400">Estimates come from models evaluated on repositories they never saw; the <Link to="/model-card" className="font-bold text-blue-700">model card</Link> lists their measured accuracy.</p>
    </div>
  </div>
}

function IssueAnalysisContent() {
  const { owner, repo, issueId } = useParams()
  const { profile, isSet } = useProfile()
  const [params, setParams] = useSearchParams()
  const tab = TABS.some(([id]) => id === params.get('tab')) ? params.get('tab') : 'overview'
  const { data: a, loading, error, retry } = useAsync(() => getIssueAnalysis(owner, repo, issueId, isSet ? profile : null), [owner, repo, issueId])
  const [history, setHistory] = useState({ data: null, loading: false, error: '' })
  const [state, setState] = useState({})
  const user = feedbackUser(profile)

  // Record that the issue was opened (feeds the "like ones you engaged with" ranking signal).
  useEffect(() => {
    if (!a || !user) return
    sendFeedback(user, a.repository, { number: a.issue.number, title: a.issue.title }, 'opened').catch(() => {})
  }, [a, user])

  // History costs GitHub requests, so it loads only when a tab that shows it is opened.
  useEffect(() => {
    if (!a || !['files', 'history', 'impact'].includes(tab) || history.data || history.loading || history.error) return
    setHistory({ data: null, loading: true, error: '' })
    getSimilarHistory(owner, repo, a.issue.number).then(data => setHistory({ data, loading: false, error: '' })).catch(err => setHistory({ data: null, loading: false, error: err.message }))
  }, [a, tab]) // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) return <AppLayout><Loading label="Running difficulty, effort, localization and explanation models…" /></AppLayout>
  if (error) return <AppLayout><ErrorMessage message={error} onRetry={retry} /></AppLayout>
  const act = (action, patch) => {
    setState(previous => ({ ...previous, ...patch }))
    if (user) sendFeedback(user, a.repository, { number: a.issue.number, title: a.issue.title }, action).catch(() => {})
  }
  return <AppLayout>
    <div className="flex flex-col justify-between gap-4 md:flex-row">
      <div className="min-w-0">
        <p className="mono text-xs text-slate-500">{a.repository} · issue #{a.issue.number}{a.issue.comments ? ` · ${a.issue.comments} comments` : ''}</p>
        <h1 className="mt-2 text-2xl font-extrabold leading-tight md:text-3xl">{a.issue.title}</h1>
        <div className="mt-3 flex flex-wrap gap-2">{(a.issue.labels || []).map(label => <span key={label} className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600">{label}</span>)}</div>
      </div>
      <div className="flex shrink-0 flex-wrap gap-2 self-start">
        <button type="button" onClick={() => act(state.saved ? 'unsaved' : 'saved', { saved: !state.saved })} className="btn-secondary">{state.saved ? <BookmarkCheck size={16} /> : <Bookmark size={16} />}{state.saved ? 'Saved' : 'Save'}</button>
        <button type="button" onClick={() => act('completed', { completed: true })} disabled={state.completed} className="btn-secondary disabled:opacity-60"><CheckCircle2 size={16} />{state.completed ? 'Marked done' : 'I fixed this'}</button>
        <a target="_blank" rel="noreferrer" href={a.issue.html_url || `https://github.com/${owner}/${repo}/issues/${a.issue.number}`} className="btn-secondary">GitHub <ExternalLink size={16} /></a>
      </div>
    </div>

    <nav className="sticky top-16 z-20 -mx-1 mt-6 flex gap-1 overflow-x-auto border-b border-slate-200 bg-[#f7f9fc]/95 px-1 backdrop-blur" aria-label="Analysis sections">
      {TABS.map(([id, label]) => <button key={id} type="button" onClick={() => setParams(previous => { const next = new URLSearchParams(previous); next.set('tab', id); return next }, { replace: true })} className={`whitespace-nowrap border-b-2 px-3 py-3 text-sm font-bold transition ${tab === id ? 'border-ink text-ink' : 'border-transparent text-slate-500 hover:text-ink'}`}>
        {id === 'files' && <Target size={14} className="mr-1.5 inline" />}{label}
      </button>)}
    </nav>

    <div className="mt-6">
      {tab === 'overview' && <Overview a={a} />}
      {tab === 'fit' && <Fit a={a} />}
      {tab === 'files' && <Files a={a} history={history} />}
      {tab === 'impact' && <Impact a={a} owner={owner} repo={repo} history={history} />}
      {tab === 'history' && <SimilarHistory history={history} />}
      {tab === 'guide' && <Guide a={a} />}
    </div>
  </AppLayout>
}

// The page renders once the backend has snapshotted the repository; until then the gate shows build progress.
export default function IssueAnalysis() {
  const { owner, repo } = useParams()
  return <RepositoryGate owner={owner} repo={repo}><IssueAnalysisContent /></RepositoryGate>
}
