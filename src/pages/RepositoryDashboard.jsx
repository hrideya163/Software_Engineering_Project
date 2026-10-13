import { CircleDot, ExternalLink, GitFork, Star } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import AppLayout from '../components/AppLayout'
import EmptyState from '../components/EmptyState'
import ErrorMessage from '../components/ErrorMessage'
import IssueCard from '../components/IssueCard'
import Loading from '../components/Loading'
import { useRepositoryOverview } from '../hooks/useRepositoryOverview'
import { compact } from '../utils/formatters'

const tabs = [['mostCommented', 'Most commented'], ['newest', 'Newest']]

export default function RepositoryDashboard() {
  const { owner, repo } = useParams()
  const { details, topIssues, loading, errors } = useRepositoryOverview(owner, repo)
  const [tab, setTab] = useState('mostCommented')
  if (loading) return <AppLayout><Loading label="Loading repository…" /></AppLayout>
  const issues = topIssues?.[tab] || []
  return <AppLayout>
    <p className="eyebrow">Repository</p>
    <h1 className="mt-2 text-3xl font-extrabold">{owner} <span className="text-slate-400">/</span> {repo}</h1>
    {details && <>
      <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">{details.description}</p>
      <div className="mt-4 flex flex-wrap items-center gap-5 text-sm font-semibold text-slate-600">
        <span className="inline-flex items-center gap-1.5"><Star size={16} />{compact(details.stars)} stars</span>
        <span className="inline-flex items-center gap-1.5"><GitFork size={16} />{compact(details.forks)} forks</span>
        <a target="_blank" rel="noreferrer" href={`https://github.com/${owner}/${repo}`} className="inline-flex items-center gap-1.5 text-blue-700 hover:underline">GitHub <ExternalLink size={14} /></a>
      </div>
      {details.languages?.length > 0 && <div className="mt-5 max-w-xl">
        <div className="flex h-2 overflow-hidden rounded-full bg-slate-100">{details.languages.map(l => <div key={l.name} style={{ width: `${l.value}%`, background: l.color }} title={`${l.name} ${l.value}%`} />)}</div>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">{details.languages.map(l => <span key={l.name} className="inline-flex items-center gap-1.5"><i className="inline-block h-2 w-2 rounded-full" style={{ background: l.color }} />{l.name} {l.value}%</span>)}</div>
      </div>}
      {details.technologies?.length > 0 && <div className="mt-4 flex flex-wrap gap-2">{details.technologies.map(t => <span key={t} className="rounded-full bg-sky px-3 py-1 text-xs font-bold text-ink">{t}</span>)}</div>}
    </>}
    {errors.map(message => <div className="mt-4" key={message}><ErrorMessage message={message} /></div>)}
    <section className="mt-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="inline-flex items-center gap-2 text-lg font-extrabold"><CircleDot size={18} />Top issues</h2>
        <Link to={`/repository/${owner}/${repo}/issues`} className="btn-secondary">View all issues</Link>
      </div>
      <div className="mt-4 inline-flex rounded-xl bg-slate-100 p-1" role="tablist">{tabs.map(([key, label]) => <button key={key} role="tab" aria-selected={tab === key} onClick={() => setTab(key)} className={`rounded-lg px-4 py-2 text-sm font-bold ${tab === key ? 'bg-white text-ink shadow-soft' : 'text-slate-500'}`}>{label}</button>)}</div>
      {topIssues && !issues.length && <div className="mt-4"><EmptyState message="No open issues found for this repository." /></div>}
      <div className="mt-4 grid gap-4 xl:grid-cols-2">{issues.map(issue => <IssueCard issue={issue} key={issue.number} />)}</div>
    </section>
  </AppLayout>
}
