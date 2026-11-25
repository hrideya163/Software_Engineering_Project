import { useState } from 'react'
import { getTrending } from '../api/contrimapApi'
import { useAsync } from '../hooks/useProfile'
import EmptyState from './EmptyState'
import ErrorMessage from './ErrorMessage'
import Loading from './Loading'
import RepoCard from './RepoCard'

const LANGUAGES = ['', 'Python', 'TypeScript', 'JavaScript', 'Go', 'Rust', 'Java', 'C++', 'Ruby']

export default function TrendingRepos() {
  const [language, setLanguage] = useState('')
  const { data, loading, error } = useAsync(() => getTrending({ language, limit: 12 }), [language])
  const repositories = data?.repositories || []
  return <section id="trending" className="mx-auto max-w-6xl px-5 py-16">
    <p className="eyebrow">Trending now</p>
    <h2 className="mt-3 text-3xl font-extrabold">Popular repositories with beginner-friendly issues.</h2>
    <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">Repositories with 1k+ stars, pushed to in the last 30 days and with open “good first issue” issues, ordered by momentum (stars weighted by how recently they were active).</p>
    <div className="mt-6 flex flex-wrap gap-2">{LANGUAGES.map(name => <button key={name || 'all'} onClick={() => setLanguage(name)} className={`rounded-full px-3 py-1.5 text-xs font-bold ${language === name ? 'bg-ink text-white' : 'bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50'}`}>{name || 'All languages'}</button>)}</div>
    {data?.source === 'curated' && <p className="mt-4 rounded-xl bg-amber-50 p-3 text-xs font-semibold text-amber-800">{data.note} Showing a curated list instead.</p>}
    <div className="mt-6">
      {loading && <Loading label="Fetching trending repositories…" />}
      {error && <ErrorMessage message={error} />}
      {!loading && !error && !repositories.length && <EmptyState message="No trending repositories found right now." />}
      {!loading && <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{repositories.map(repository => <RepoCard repository={repository} key={repository.full_name} />)}</div>}
    </div>
  </section>
}
