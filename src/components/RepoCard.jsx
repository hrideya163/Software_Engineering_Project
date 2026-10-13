import { CircleDot, GitFork, Star } from 'lucide-react'
import { Link } from 'react-router-dom'
import { compact, timeAgo } from '../utils/formatters'

export default function RepoCard({ repository }) {
  return <Link to={`/repository/${repository.owner}/${repository.name}`} className="card flex flex-col p-5 text-left transition hover:-translate-y-0.5 hover:border-blue-300">
    <p className="mono text-xs text-slate-500">{repository.owner} /</p>
    <h3 className="mt-1 font-extrabold text-ink">{repository.name}</h3>
    <p className="mt-3 line-clamp-2 flex-1 text-sm leading-6 text-slate-600">{repository.description}</p>
    <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs font-semibold text-slate-500">
      <span className="inline-flex items-center gap-1"><Star size={14} />{compact(repository.stars)}</span>
      <span className="inline-flex items-center gap-1"><GitFork size={14} />{compact(repository.forks)}</span>
      <span className="inline-flex items-center gap-1"><CircleDot size={14} />{compact(repository.open_issues)} open</span>
      {repository.language && <span className="rounded-full bg-sky px-2 py-0.5 text-ink">{repository.language}</span>}
    </div>
    <p className="mt-3 text-xs text-slate-400">Active {timeAgo(repository.pushed_at)}</p>
  </Link>
}
