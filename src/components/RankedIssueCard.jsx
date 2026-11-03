import { ArrowUpRight, Clock, FileCode2, GraduationCap } from 'lucide-react'
import { Link } from 'react-router-dom'
import DifficultyBadge from './DifficultyBadge'
import SkillTag from './SkillTag'

const LABELS = {
  actionability: 'Actionable', approachability: 'Approachable', clarity: 'Clear', focus: 'Focused', availability: 'Available',
  freshness: 'Fresh', community: 'Welcoming', stack_match: 'Stack match', interest: 'Interest', difficulty_fit: 'Level fit',
  learning: 'Learning', success: 'Merge odds',
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

export default function RankedIssueCard({ item, owner, repo, weights }) {
  const issue = item.issue
  const repository = item.repository || `${owner}/${repo}`
  const [o, r] = repository.split('/')
  return <article className="card flex flex-col p-5">
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <p className="mono text-xs text-slate-500">{item.repository ? `${item.repository} ` : ''}#{issue.number} · rank {item.rank}</p>
        <h3 className="mt-1 font-bold text-ink">{issue.title}</h3>
      </div>
      <div className="shrink-0 text-right"><DifficultyBadge level={item.difficulty} /><p className="mt-2 text-xl font-extrabold text-ink">{Math.round(item.score * 100)}</p><p className="text-[10px] font-bold uppercase text-slate-400">score</p></div>
    </div>
    {item.summary && <p className="mt-3 line-clamp-2 text-sm leading-6 text-slate-600">{item.summary}</p>}
    <div className="mt-4"><ScoreBars components={item.components} weights={weights} /></div>
    <div className="mt-4 flex flex-wrap gap-2">{(item.skills || []).slice(0, 4).map(skill => <SkillTag key={skill.id}>{skill.name}</SkillTag>)}</div>
    <div className="mt-4 space-y-1 text-xs text-slate-500">
      {item.effort_bucket && <p className="inline-flex items-center gap-1.5"><Clock size={13} />Estimated effort: {item.effort_bucket}</p>}
      {item.top_files?.[0] && <p className="flex items-center gap-1.5 truncate"><FileCode2 size={13} className="shrink-0" /><span className="mono truncate">{item.top_files[0]}</span></p>}
      {item.learning?.new_skills?.length > 0 && <p className="inline-flex items-center gap-1.5"><GraduationCap size={13} />Learn: {item.learning.new_skills.map(s => s.name).join(', ')}</p>}
    </div>
    <Link to={`/repository/${o}/${r}/issues/${issue.number}`} className="mt-auto inline-flex items-center gap-1 border-t pt-4 text-xs font-bold text-ink hover:text-blue-700">Analyze issue <ArrowUpRight size={14} /></Link>
  </article>
}
