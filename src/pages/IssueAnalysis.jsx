import { AlertTriangle, ExternalLink, FileCode2, FlaskConical, Lightbulb, Network, Sparkles } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { getIssueAnalysis } from '../api/contrimapApi'
import AppLayout from '../components/AppLayout'
import DifficultyBadge from '../components/DifficultyBadge'
import ErrorMessage from '../components/ErrorMessage'
import FileTree from '../components/FileTree'
import FlowGraph, { Legend } from '../components/FlowGraph'
import Loading from '../components/Loading'
import { ScoreBars } from '../components/RankedIssueCard'
import SkillTag from '../components/SkillTag'
import ContributionPath from '../components/contribution/ContributionPath'
import { useAsync, useProfile } from '../hooks/useProfile'

const pct = value => (value === null || value === undefined ? '-' : `${Math.round(value * 100)}%`)

function Distribution({ values }) {
  return <div className="mt-4 space-y-2">{Object.entries(values || {}).map(([name, value]) => <div key={name} className="flex items-center gap-2 text-xs">
    <span className="w-28 shrink-0 font-semibold text-slate-500">{name}</span>
    <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100"><div className="h-full bg-ink" style={{ width: `${value * 100}%` }} /></div>
    <span className="w-9 text-right font-bold">{pct(value)}</span>
  </div>)}</div>
}

export default function IssueAnalysis() {
  const { owner, repo, issueId } = useParams()
  const { profile, isSet } = useProfile()
  const { data: a, loading, error } = useAsync(() => getIssueAnalysis(owner, repo, issueId, isSet ? profile : null), [owner, repo, issueId])
  if (loading) return <AppLayout><Loading label="Running difficulty, effort, localization and explanation models…" /></AppLayout>
  if (error) return <AppLayout><ErrorMessage message={error} /></AppLayout>
  const explanation = a.explanation || {}
  return <AppLayout>
    <div className="flex flex-col justify-between gap-4 md:flex-row">
      <div>
        <p className="mono text-xs text-slate-500">{a.repository} · ISSUE #{a.issue.number}</p>
        <h1 className="mt-2 text-3xl font-extrabold">{a.issue.title}</h1>
        <div className="mt-3 flex flex-wrap gap-2">{(a.issue.labels || []).map(label => <span key={label} className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600">{label}</span>)}</div>
      </div>
      <div className="flex shrink-0 gap-2 self-start">
        <Link to={`/repository/${owner}/${repo}/visualizer?issue=${a.issue.number}`} className="btn-secondary"><Network size={16} />On the map</Link>
        <a target="_blank" rel="noreferrer" href={a.issue.html_url || `https://github.com/${owner}/${repo}/issues/${a.issue.number}`} className="btn-secondary">GitHub <ExternalLink size={16} /></a>
      </div>
    </div>

    <div className="mt-8 grid gap-5 lg:grid-cols-3">
      <section className="card p-5">
        <p className="eyebrow">Difficulty</p>
        <div className="mt-3 flex items-center gap-3"><DifficultyBadge level={a.difficulty} /><span className="text-xs font-bold text-slate-500">{a.confidence} confidence</span></div>
        <Distribution values={a.difficulty_distribution} />
      </section>
      <section className="card p-5">
        <p className="eyebrow">Effort</p>
        <p className="mt-3 text-2xl font-extrabold">{a.effort_bucket}</p>
        <p className="text-xs text-slate-500">likely range {a.effort_range_hours?.[0]}-{a.effort_range_hours?.[1]} h of focused work</p>
        <Distribution values={a.effort_distribution} />
        <p className="mt-3 text-[11px] leading-4 text-slate-400">{a.effort_note}</p>
      </section>
      <section className="card p-5">
        <p className="eyebrow">{a.personal ? 'Fit for you' : 'Contribution outlook'}</p>
        {a.personal ? <div className="mt-4"><ScoreBars components={a.personal.components} /></div> : <div className="mt-4 space-y-3 text-sm">
          <p><b>{pct(a.actionability)}</b> <span className="text-slate-500">likely to be resolved by a code change (vs. question / duplicate)</span></p>
          <p><b>{pct(a.success_probability)}</b> <span className="text-slate-500">estimated merge probability for a first-time contributor</span></p>
          <Link to="/profile" className="text-xs font-bold text-blue-700">Set up your profile for personal fit →</Link>
        </div>}
        {a.personal?.learning?.new_skills?.length > 0 && <p className="mt-4 text-xs text-slate-600"><b>You would learn:</b> {a.personal.learning.new_skills.map(s => s.name).join(', ')}</p>}
        {a.skill_gaps?.length > 0 && <p className="mt-2 text-xs text-amber-700"><b>Gaps:</b> {a.skill_gaps.map(s => s.name).join(', ')}</p>}
      </section>
    </div>

    <section className="card mt-5 p-5">
      <div className="flex items-center justify-between"><p className="eyebrow inline-flex items-center gap-2"><Sparkles size={14} />Explanation</p><span className="text-[11px] font-bold text-slate-400">{explanation.source === 'llm' ? `generated by ${explanation.model} from the model outputs` : 'template (no LLM configured)'}</span></div>
      <p className="mt-3 leading-7 text-slate-700">{explanation.summary}</p>
      <p className="mt-2 text-sm text-slate-600">{explanation.why_this_difficulty}</p>
      <div className="mt-4 grid gap-5 md:grid-cols-2">
        <div><p className="text-xs font-bold uppercase text-slate-500">Where to start</p><ul className="mt-2 space-y-2">{(explanation.where_to_start || []).map(item => <li key={item.path} className="text-sm"><span className="mono text-blue-800">{item.path}</span><br /><span className="text-xs text-slate-500">{item.reason}</span></li>)}</ul></div>
        <div><p className="text-xs font-bold uppercase text-slate-500">Approach</p><ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-slate-700">{(explanation.approach || []).map(step => <li key={step}>{step}</li>)}</ol></div>
      </div>
      {explanation.risks?.length > 0 && <div className="mt-4 flex gap-2 rounded-xl bg-amber-50 p-3 text-xs text-amber-800"><AlertTriangle size={14} className="shrink-0" /><span>{explanation.risks.join(' ')}</span></div>}
      {explanation.learning_value && <p className="mt-3 inline-flex items-center gap-2 text-xs text-slate-600"><Lightbulb size={13} />{explanation.learning_value}</p>}
    </section>

    <div className="mt-5 grid gap-5 xl:grid-cols-[1.1fr_.9fr]">
      <section className="card p-5">
        <p className="eyebrow">Likely files to change</p>
        <p className="mt-1 text-xs text-slate-500">Learning-to-rank over every file in the repository · {a.localization_mode}</p>
        <ol className="mt-4 space-y-3">{a.files.map(file => <li key={file.path} className="flex gap-3">
          <span className="w-5 shrink-0 text-right text-xs font-extrabold text-slate-400">{file.rank}</span>
          <div className="min-w-0 flex-1">
            <a target="_blank" rel="noreferrer" href={`https://github.com/${a.repository}/blob/${a.sha}/${file.path}`} className="mono flex items-center gap-1.5 truncate text-sm text-blue-800 hover:underline"><FileCode2 size={13} className="shrink-0" />{file.path}</a>
            <div className="mt-1 flex flex-wrap gap-1.5">{file.signals.map(signal => <span key={signal} className="rounded bg-sky px-1.5 py-0.5 text-[10px] font-bold text-ink">{signal}</span>)}</div>
          </div>
          <div className="w-16 shrink-0"><div className="h-1.5 overflow-hidden rounded-full bg-slate-100"><div className="h-full bg-rose-500" style={{ width: `${file.relative_confidence * 100}%` }} /></div><p className="mt-1 text-right text-[10px] text-slate-400">{pct(file.relative_confidence)}</p></div>
        </li>)}</ol>
        {a.related_tests.length > 0 && <div className="mt-5"><p className="inline-flex items-center gap-1.5 text-xs font-bold uppercase text-slate-500"><FlaskConical size={13} />Related tests</p><ul className="mt-2 space-y-1">{a.related_tests.map(test => <li key={test} className="mono text-xs text-violet-700">{test}</li>)}</ul></div>}
        <p className="mt-4 text-xs text-slate-500">{a.impact.dependents_within_2_hops} files import the top candidates (within 2 hops) - changes there have a wider blast radius.</p>
      </section>
      <section className="card p-5">
        <p className="eyebrow">Repository tree</p>
        <div className="mt-3"><FileTree tree={a.tree} /></div>
      </section>
    </div>

    <section className="mt-5">
      <p className="eyebrow">Code neighbourhood</p>
      <p className="mb-3 mt-1 text-xs text-slate-500">Predicted files (red) with the files that import them, the files they import and their tests.</p>
      {a.graph.nodes.length ? <FlowGraph graph={a.graph} height={460} /> : <p className="card p-6 text-sm text-slate-500">No import relationships were resolved for these files.</p>}
      <Legend items={[['target', 'predicted file'], ['importer', 'imports it'], ['dependency', 'imported by it'], ['test', 'test']]} />
    </section>

    <div className="mt-5 grid gap-5 lg:grid-cols-[1.3fr_.7fr]">
      <ContributionPath path={a.contribution_path} storageKey={`contrimap.path.${a.repository}#${a.issue.number}`} />
      <section className="card self-start p-5">
        <p className="eyebrow">Skills involved</p>
        <ul className="mt-4 space-y-3">{a.skills.map(skill => <li key={skill.id}><div className="flex items-center justify-between"><SkillTag>{skill.name}</SkillTag><span className="text-xs font-bold text-slate-400">{pct(skill.weight)}</span></div><p className="mt-1 truncate text-[11px] text-slate-400">{skill.evidence[0]}</p></li>)}</ul>
        <p className="mt-6 text-[11px] leading-4 text-slate-400">Estimates come from models evaluated on repositories they never saw; see the <Link to="/model-card" className="font-bold text-blue-700">model card</Link> for their measured accuracy.</p>
      </section>
    </div>
  </AppLayout>
}
