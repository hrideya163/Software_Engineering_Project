import { ExternalLink, FileCode2 } from 'lucide-react'
import { useParams } from 'react-router-dom'
import AppLayout from '../components/AppLayout'
import DifficultyBadge from '../components/DifficultyBadge'
import Loading from '../components/Loading'
import { useRepository } from '../hooks/useRepository'
import { analyzeIssue } from '../api/issueApi'
import { useEffect, useState } from 'react'

export default function IssueAnalysis() {
  const { owner, repo, issueId } = useParams()
  const { issues, loading: issuesLoading, error: repositoryError, repositoryUrl } = useRepository(owner, repo)
  const issue = issues.find(item => String(item.number) === issueId)
  const [model, setModel] = useState(null)
  const [analysisLoading, setAnalysisLoading] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!issue) return
    let active = true
    setAnalysisLoading(true)
    analyzeIssue(repositoryUrl, issue)
      .then(result => active && setModel(result))
      .catch(nextError => active && setError(nextError.message))
      .finally(() => active && setAnalysisLoading(false))
    return () => { active = false }
  }, [issue, repositoryUrl])
  if (issuesLoading || analysisLoading || !issue) return <AppLayout><Loading label={issue ? 'Analyzing issue with trained models…' : 'Fetching issue…'} /></AppLayout>
  if (repositoryError || error) return <AppLayout><p className="rounded-xl bg-rose-50 p-4 text-sm font-semibold text-rose-700">{repositoryError || error}</p></AppLayout>
  if (!model) return null
  return <AppLayout>
    <div className="flex flex-col justify-between gap-4 md:flex-row">
      <div><p className="mono text-xs text-slate-500">ISSUE #{issue.number}</p><h1 className="mt-2 text-3xl font-extrabold">{issue.title}</h1><p className="mt-3 max-w-3xl text-slate-600">{issue.body || 'No issue description provided.'}</p></div>
      <a target="_blank" rel="noreferrer" href={`https://github.com/${owner}/${repo}/issues/${issue.number}`} className="btn-secondary self-start">GitHub issue <ExternalLink size={16} /></a>
    </div>
    <div className="mt-8 grid gap-5 lg:grid-cols-3">
      <div className="card p-5"><p className="eyebrow">Difficulty classification</p><div className="mt-4"><DifficultyBadge level={model.difficulty} /></div><p className="mt-4 text-sm text-slate-600">{Math.round((model.difficulty_probability || 0) * 100)}% model probability</p></div>
      <div className="card p-5"><p className="eyebrow">Effort prediction</p><p className="mt-4 text-3xl font-extrabold">{model.effort_hours ?? '—'} hours</p><p className="mt-3 text-sm text-slate-600">Predicted by the trained regression model.</p></div>
      <div className="card p-5"><p className="eyebrow">Analysis status</p><p className="mt-4 text-lg font-extrabold">Complete</p><p className="mt-3 text-sm text-slate-600">Computed from the cached trained artifacts.</p></div>
    </div>
    <section className="card mt-6 p-6"><p className="eyebrow">Top-K localized files</p><div className="mt-5 space-y-3">{(model.affected_files || []).map((file, index) => <div key={file.path} className="flex items-center gap-3"><span className="grid h-8 w-8 place-items-center rounded-lg bg-sky text-xs font-bold">{index + 1}</span><FileCode2 size={17} className="text-slate-400" /><span className="mono text-sm">{file.path}</span><span className="ml-auto text-xs text-slate-500">{file.similarity.toFixed(3)}</span></div>)}{!model.affected_files?.length && <p className="text-sm text-slate-500">No localized files returned.</p>}</div></section>
  </AppLayout>
}
