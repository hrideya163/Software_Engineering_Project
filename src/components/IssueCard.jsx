import { ArrowUpRight, Clock, FileCode2 } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import DifficultyBadge from './DifficultyBadge'

export default function IssueCard({ issue }) {
  const { owner, repo } = useParams()
  const model = issue.model || {}
  return <article className="card p-5">
    <div className="flex items-start justify-between gap-3">
      <div><p className="mono text-xs text-slate-500">#{issue.id}</p><h3 className="mt-1 font-bold text-ink">{issue.title}</h3></div>
      <DifficultyBadge level={model.difficulty} />
    </div>
    <div className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
      <p className="flex items-center gap-2"><Clock size={15} />{model.effort_hours ?? '—'} hours</p>
      <p className="flex items-center gap-2"><FileCode2 size={15} />{model.files?.length ?? 0} localized files</p>
    </div>
    <Link to={`/repository/${owner}/${repo}/issues/${issue.id}`} className="mt-5 inline-flex items-center gap-1 border-t pt-4 text-xs font-bold text-ink hover:text-blue-700">View model outputs <ArrowUpRight size={14} /></Link>
  </article>
}
