import { ExternalLink, FileCode2 } from 'lucide-react'
import { useParams } from 'react-router-dom'
import AppLayout from '../components/AppLayout'
import DifficultyBadge from '../components/DifficultyBadge'
import Loading from '../components/Loading'
import { useRepository } from '../hooks/useRepository'

export default function IssueAnalysis() {
  const { owner, repo, issueId } = useParams()
  const { issues, loading } = useRepository(owner, repo)
  const issue = issues.find(item => item.id === issueId)
  if (loading || !issue) return <AppLayout><Loading /></AppLayout>
  const model = issue.model || {}
  return <AppLayout>
    <div className="flex flex-col justify-between gap-4 md:flex-row">
      <div><p className="mono text-xs text-slate-500">ISSUE #{issue.id}</p><h1 className="mt-2 text-3xl font-extrabold">{issue.title}</h1><p className="mt-3 max-w-3xl text-slate-600">{issue.body || issue.summary}</p></div>
      <a target="_blank" rel="noreferrer" href={`https://github.com/${owner}/${repo}/issues/${issueId}`} className="btn-secondary self-start">GitHub issue <ExternalLink size={16} /></a>
    </div>
    <div className="mt-8 grid gap-5 lg:grid-cols-3">
      <div className="card p-5"><p className="eyebrow">Difficulty classification</p><div className="mt-4"><DifficultyBadge level={model.difficulty} /></div><p className="mt-4 text-sm text-slate-600">{Math.round((model.difficulty_probability || 0) * 100)}% model probability</p></div>
      <div className="card p-5"><p className="eyebrow">Effort prediction</p><p className="mt-4 text-3xl font-extrabold">{model.effort_hours ?? '—'} hours</p><p className="mt-3 text-sm text-slate-600">Predicted by the trained regression model.</p></div>
      <div className="card p-5"><p className="eyebrow">Model version</p><p className="mt-4 text-lg font-extrabold">{model.model_version || '—'}</p><p className="mt-3 text-sm text-slate-600">Artifacts used for this prediction.</p></div>
    </div>
    <section className="card mt-6 p-6"><p className="eyebrow">Top-K localized files</p><div className="mt-5 space-y-3">{(model.files || []).map((file, index) => <div key={file.path} className="flex items-center gap-3"><span className="grid h-8 w-8 place-items-center rounded-lg bg-sky text-xs font-bold">{index + 1}</span><FileCode2 size={17} className="text-slate-400" /><span className="mono text-sm">{file.path}</span><span className="ml-auto text-xs text-slate-500">{file.similarity.toFixed(3)}</span></div>)}{!model.files?.length && <p className="text-sm text-slate-500">No localized files returned.</p>}</div></section>
  </AppLayout>
}
