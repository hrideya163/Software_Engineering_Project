import { ArrowUpRight, CalendarDays } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'

export default function IssueCard({ issue }) {
  const { owner, repo } = useParams()
  return <article className="card p-5">
    <div className="flex items-start justify-between gap-3">
      <div><p className="mono text-xs text-slate-500">#{issue.number}</p><h3 className="mt-1 font-bold text-ink">{issue.title}</h3></div>
    </div>
    <p className="mt-4 line-clamp-3 text-sm leading-6 text-slate-600">{issue.body || 'No issue description provided.'}</p>
    <div className="mt-4 flex items-center gap-2 text-xs text-slate-500"><CalendarDays size={15} />Opened {new Date(issue.created_at).toLocaleDateString()}</div>
    <Link to={`/repository/${owner}/${repo}/issues/${issue.number}`} className="mt-5 inline-flex items-center gap-1 border-t pt-4 text-xs font-bold text-ink hover:text-blue-700">Analyze issue <ArrowUpRight size={14} /></Link>
  </article>
}
