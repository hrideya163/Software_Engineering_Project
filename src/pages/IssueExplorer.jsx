import { Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import AppLayout from '../components/AppLayout'
import EmptyState from '../components/EmptyState'
import IssueCard from '../components/IssueCard'
import Loading from '../components/Loading'
import { useRepository } from '../hooks/useRepository'

export default function IssueExplorer() {
  const { owner, repo } = useParams()
  const { issues, loading, error } = useRepository(owner, repo)
  const [query, setQuery] = useState('')
  const [difficulty, setDifficulty] = useState('All')
  const filtered = useMemo(() => issues.filter(issue => `${issue.title} ${issue.body || ''}`.toLowerCase().includes(query.toLowerCase())), [issues, query])
  if (loading) return <AppLayout><Loading label="Fetching open GitHub issues…" /></AppLayout>
  return <AppLayout><p className="eyebrow">Issue explorer</p><h1 className="mt-2 text-3xl font-extrabold">Explore open issues.</h1>{error && <p className="mt-4 rounded-xl bg-rose-50 p-4 text-sm font-semibold text-rose-700">{error}</p>}<div className="card mt-7 flex gap-3 p-4"><label className="flex flex-1 items-center gap-2 rounded-xl border border-slate-200 px-3"><Search size={18} className="text-slate-400" /><input value={query} onChange={event => setQuery(event.target.value)} className="w-full py-3 outline-none" placeholder="Search issues" /></label></div><p className="mt-6 text-sm font-semibold text-slate-500">{filtered.length} matching issues</p><div className="mt-4 grid gap-4 xl:grid-cols-2">{filtered.map(issue => <IssueCard issue={issue} key={issue.number} />)}</div>{!filtered.length && !error && <div className="mt-4"><EmptyState message="No open issues match your search." /></div>}</AppLayout>
}
