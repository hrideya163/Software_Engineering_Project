import { useParams } from 'react-router-dom'
import AppLayout from '../components/AppLayout'
import IssueCard from '../components/IssueCard'
import Loading from '../components/Loading'
import { useRepository } from '../hooks/useRepository'

export default function RepositoryDashboard() {
  const { owner, repo } = useParams()
  const { currentRepository: repository, issues, loading } = useRepository(owner, repo)
  if (loading || !repository) return <AppLayout><Loading label="Running trained models…" /></AppLayout>
  return <AppLayout>
    <p className="eyebrow">Model predictions</p>
    <h1 className="mt-2 text-3xl font-extrabold">{owner} <span className="text-slate-400">/</span> {repo}</h1>
    <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">Difficulty classification, effort regression, and top-K issue localization from the deployed model artifacts.</p>
    <section className="mt-8"><h2 className="text-lg font-extrabold">Issues</h2><div className="mt-4 grid gap-4 xl:grid-cols-2">{issues.slice(0, 6).map(issue => <IssueCard issue={issue} key={issue.id} />)}</div></section>
  </AppLayout>
}
