import { ArrowUpRight, Bookmark, BookmarkCheck, CheckCircle2, Clock, FileCode2, GraduationCap, MessageSquare, Undo2, X } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { feedbackUser, sendFeedback } from '../api/contrimapApi'
import { useProfile } from '../hooks/useProfile'
import DifficultyBadge from './DifficultyBadge'

export const LABELS = {
  actionability: 'Actionable', approachability: 'Approachable', clarity: 'Clear', focus: 'Focused', availability: 'Unassigned',
  freshness: 'Recent', community: 'Welcoming', stack_match: 'Stack match', interest: 'Interest', difficulty_fit: 'Level fit',
  learning: 'Learning', success: 'Merge odds', feedback: 'Like ones you saved',
}

export function ScoreBars({ components, weights, limit = 6 }) {
  const items = Object.entries(components || {})
    .filter(([name]) => !weights || (weights[name] || 0) > 0)
    .sort((a, b) => (weights ? (weights[b[0]] || 0) - (weights[a[0]] || 0) : b[1] - a[1]))
    .slice(0, limit)
  return <div className="grid grid-cols-2 gap-x-4 gap-y-2">{items.map(([name, value]) => <div key={name}>
    <div className="flex justify-between text-[11px] font-bold text-slate-500"><span>{LABELS[name] || name}</span><span>{Math.round(value * 100)}</span></div>
    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-mint" style={{ width: `${Math.max(2, value * 100)}%` }} /></div>
  </div>)}</div>
}

// The strongest reasons behind a score: components that are both weighted and high.
export function topReasons(components, weights, limit = 3) {
  return Object.entries(components || {})
    .filter(([name, value]) => (weights?.[name] ?? 0.1) > 0 && value >= 0.6)
    .sort((a, b) => (weights?.[b[0]] ?? 0.1) * b[1] - (weights?.[a[0]] ?? 0.1) * a[1])
    .slice(0, limit)
    .map(([name]) => LABELS[name] || name)
}

const CONFIDENCE = { high: ['bg-emerald-500', 'High confidence'], medium: ['bg-amber-400', 'Medium confidence'], low: ['bg-slate-300', 'Low confidence: the models disagree or the text is vague'] }

export function ConfidenceDot({ level }) {
  if (!level) return null
  const [color, label] = CONFIDENCE[level] || CONFIDENCE.low
  return <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-slate-500" title={label}><i className={`h-1.5 w-1.5 rounded-full ${color}`} />{level}</span>
}

function IconButton({ label, onClick, active, children }) {
  return <button type="button" onClick={onClick} title={label} aria-label={label} aria-pressed={active} className={`grid h-8 w-8 place-items-center rounded-lg border transition ${active ? 'border-ink bg-ink text-white' : 'border-slate-200 text-slate-500 hover:border-slate-300 hover:text-ink'}`}>{children}</button>
}

export default function RankedIssueCard({ item, owner, repo, weights, onDismiss }) {
  const issue = item.issue
  const repository = item.repository || `${owner}/${repo}`
  const [o, r] = repository.split('/')
  const { profile } = useProfile()
  const [state, setState] = useState(item.feedback || {})
  const user = feedbackUser(profile)
  const act = (action, patch) => {
    setState(previous => ({ ...previous, ...patch }))
    if (user) sendFeedback(user, repository, { number: issue.number, title: issue.title, summary: item.summary }, action).catch(() => {})
  }
  if (state.dismissed) {
    return <article className="flex items-center justify-between gap-3 rounded-2xl border border-dashed border-slate-200 px-4 py-3 text-xs text-slate-500">
      <span className="truncate">Hidden <b className="text-slate-600">#{issue.number}</b> {issue.title}</span>
      <button type="button" onClick={() => { act('restored', { dismissed: false }); onDismiss?.(issue.number, false) }} className="inline-flex shrink-0 items-center gap-1 font-bold text-ink hover:text-blue-700"><Undo2 size={13} />Undo</button>
    </article>
  }
  const reasons = topReasons(item.components, weights)
  return <article className={`card group flex flex-col p-4 transition hover:shadow-md ${state.completed ? 'opacity-70' : ''}`}>
    <div className="flex items-start gap-3">
      <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-sky text-center" title="Overall score (0-100) from the ranking components">
        <span className="text-base font-extrabold leading-none text-ink">{Math.round(item.score * 100)}</span>
      </div>
      <div className="min-w-0 flex-1">
        <p className="mono flex items-center gap-1.5 text-[11px] text-slate-400">{item.repository ? `${item.repository} ` : ''}#{issue.number}{issue.comments > 0 && <span className="inline-flex items-center gap-0.5"><MessageSquare size={11} />{issue.comments}</span>}{state.completed && <span className="inline-flex items-center gap-0.5 font-sans font-bold text-emerald-600"><CheckCircle2 size={12} />done</span>}</p>
        <Link to={`/repository/${o}/${r}/issues/${issue.number}`} className="mt-0.5 line-clamp-2 font-bold leading-snug text-ink hover:text-blue-800">{issue.title}</Link>
      </div>
    </div>
    <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-slate-500">
      <span className="inline-flex items-center gap-1.5"><DifficultyBadge level={item.difficulty} /><ConfidenceDot level={item.confidence} /></span>
      {item.effort_bucket && <span className="inline-flex items-center gap-1"><Clock size={12} />{item.effort_bucket}</span>}
      {item.top_files?.[0] && <span className="flex min-w-0 max-w-full items-center gap-1" title={`Most likely file to change: ${item.top_files[0]}`}><FileCode2 size={12} className="shrink-0" /><span className="mono truncate">{item.top_files[0].split('/').slice(-2).join('/')}</span></span>}
    </div>
    {(reasons.length > 0 || item.learning?.new_skills?.length > 0) && <div className="mt-3 flex flex-wrap gap-1.5">
      {reasons.map(reason => <span key={reason} className="rounded-md bg-emerald-50 px-1.5 py-0.5 text-[11px] font-bold text-emerald-700">{reason}</span>)}
      {item.learning?.new_skills?.length > 0 && <span className="inline-flex items-center gap-1 rounded-md bg-violet-50 px-1.5 py-0.5 text-[11px] font-bold text-violet-700"><GraduationCap size={11} />{item.learning.new_skills.slice(0, 2).map(s => s.name).join(', ')}</span>}
    </div>}
    <div className="mt-auto flex items-center justify-between gap-2 pt-4">
      <Link to={`/repository/${o}/${r}/issues/${issue.number}`} className="inline-flex items-center gap-1 text-xs font-bold text-ink hover:text-blue-700">Analyze <ArrowUpRight size={14} /></Link>
      <div className="flex gap-1.5">
        <IconButton label={state.saved ? 'Remove from saved' : 'Save for later'} active={state.saved} onClick={() => act(state.saved ? 'unsaved' : 'saved', { saved: !state.saved })}>{state.saved ? <BookmarkCheck size={15} /> : <Bookmark size={15} />}</IconButton>
        <IconButton label="Not for me (hide)" onClick={() => { act('dismissed', { dismissed: true }); onDismiss?.(issue.number, true) }}><X size={15} /></IconButton>
      </div>
    </div>
  </article>
}
