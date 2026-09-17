import { useParams } from 'react-router-dom'
import AppLayout from '../components/AppLayout'
import IssueCard from '../components/IssueCard'
import Loading from '../components/Loading'
import { useRepository } from '../hooks/useRepository'

export default function RepositoryDashboard() {
  const { owner, repo } = useParams()
  const { currentRepository: repository, issues, loading, error } = useRepository(owner, repo)
  if (loading || !repository) return <AppLayout><Loading label="Fetching open GitHub issues…" /></AppLayout>
  return <AppLayout>
    <p className="eyebrow">Model predictions</p>
    <h1 className="mt-2 text-3xl font-extrabold">{owner} <span className="text-slate-400">/</span> {repo}</h1>
    <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">Open issues from GitHub. Select an issue to run the trained difficulty, effort, and file localization models.</p>{error && <p className="mt-4 rounded-xl bg-rose-50 p-4 text-sm font-semibold text-rose-700">{error}</p>}
    <section className="mt-8"><h2 className="text-lg font-extrabold">Open issues</h2><div className="mt-4 grid gap-4 xl:grid-cols-2">{issues.slice(0, 6).map(issue => <IssueCard issue={issue} key={issue.number} />)}</div></section>
  </AppLayout>
}
