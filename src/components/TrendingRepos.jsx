import { useEffect, useState } from 'react'
import { getTrendingRepositories } from '../api/repositoryApi'
import EmptyState from './EmptyState'
import ErrorMessage from './ErrorMessage'
import Loading from './Loading'
import RepoCard from './RepoCard'

export default function TrendingRepos() {
  const [repositories, setRepositories] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    getTrendingRepositories({ limit: 12 })
      .then(data => active && setRepositories(data))
      .catch(err => active && setError(err.message))
      .finally(() => active && setLoading(false))
    return () => { active = false }
  }, [])
  return <section id="trending" className="mx-auto max-w-6xl px-5 py-16">
    <p className="eyebrow">Trending now</p>
    <h2 className="mt-3 text-3xl font-extrabold">Popular repositories with open issues.</h2>
    <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">Ranked by stars among repositories pushed to in the last 30 days. Pick one to see its top issues.</p>
    <div className="mt-8">
      {loading && <Loading label="Fetching trending repositories…" />}
      {error && <ErrorMessage message={error} />}
      {!loading && !error && !repositories.length && <EmptyState message="No trending repositories found right now." />}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{repositories.map(repository => <RepoCard repository={repository} key={repository.full_name} />)}</div>
    </div>
  </section>
}
