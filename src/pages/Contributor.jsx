import { ExternalLink, GitMerge } from 'lucide-react'
import { useParams } from 'react-router-dom'
import { getContributor } from '../api/contrimapApi'
import ErrorMessage from '../components/ErrorMessage'
import Loading from '../components/Loading'
import Navbar from '../components/Navbar'
import { useAsync } from '../hooks/useProfile'
import { timeAgo } from '../utils/formatters'

export default function Contributor() {
  const { login } = useParams()
  const { data, loading, error } = useAsync(() => getContributor(login), [login])
  return <><Navbar /><main className="mx-auto max-w-5xl px-5 py-12">
    {loading && <Loading label="Reading public GitHub activity…" />}
    {error && <ErrorMessage message={error} />}
    {data && <>
      <div className="flex flex-wrap items-center gap-5">
        {data.avatar_url && <img src={data.avatar_url} alt={data.login} className="h-20 w-20 rounded-2xl" />}
        <div className="flex-1">
          <p className="eyebrow">Contributor profile</p>
          <h1 className="mt-1 text-3xl font-extrabold">{data.name || data.login}</h1>
          <p className="text-sm text-slate-500">@{data.login} · {data.level} · {data.merged_pull_requests} merged PRs · {data.public_repos} public repos</p>
          {data.bio && <p className="mt-2 text-sm text-slate-600">{data.bio}</p>}
        </div>
        <a href={data.html_url} target="_blank" rel="noreferrer" className="btn-secondary">GitHub <ExternalLink size={14} /></a>
      </div>
      <div className="mt-8 grid gap-5 md:grid-cols-2">
        <section className="card p-5">
          <p className="eyebrow">Extracted skills</p>
          <ul className="mt-4 space-y-3">{data.skills.map(skill => <li key={skill.id}>
            <div className="flex justify-between text-sm"><span className="font-bold">{skill.name}</span><span className="text-xs text-slate-500">{skill.category}</span></div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100"><div className="h-full bg-mint" style={{ width: `${skill.weight * 100}%` }} /></div>
            <p className="mt-1 truncate text-[11px] text-slate-400">{skill.evidence.join(' · ')}</p>
          </li>)}</ul>
        </section>
        <section className="card p-5">
          <p className="eyebrow">Recent merged contributions</p>
          <ul className="mt-4 space-y-3">{data.recent_contributions.map(item => <li key={`${item.repository}${item.title}`} className="flex gap-2 text-sm"><GitMerge size={15} className="mt-0.5 shrink-0 text-violet-600" /><div><p className="font-semibold">{item.title}</p><p className="text-xs text-slate-500">{item.repository} · {timeAgo(item.created_at)}</p></div></li>)}</ul>
          {!data.recent_contributions.length && <p className="mt-4 text-sm text-slate-500">No public merged pull requests found.</p>}
          <p className="eyebrow mt-6">Top languages</p>
          <p className="mt-2 text-sm text-slate-600">{data.top_languages.map(l => `${l.name} (${l.repositories})`).join(' · ') || '-'}</p>
        </section>
      </div>
    </>}
  </main></>
}
