import { CheckCircle2, Circle, Loader2, RotateCcw } from 'lucide-react'
import AppLayout from './AppLayout'
import ErrorMessage from './ErrorMessage'
import { useRepositoryPreparation } from '../hooks/useRepositoryPreparation'

// Shows the real build stages (file tree, downloads, imports, graph, metrics) while the backend
// prepares a repository for the first time, instead of an unexplained 20-second spinner.
export function PreparationProgress({ owner, repo, status }) {
  const stages = status?.stages || ['Reading the file tree with git', 'Downloading source files', 'Resolving imports and the technology stack', 'Building the knowledge graph', 'Ranking core files and detecting modules', 'Ready']
  const step = status?.step || 0
  // The current stage counts as half done, so the bar moves as soon as work starts.
  const percent = Math.round((Math.max(step - 0.5, 0) / Math.max(stages.length - 1, 1)) * 100)
  return <div className="mx-auto mt-10 max-w-xl">
    <div className="card p-6" role="status" aria-live="polite">
      <p className="eyebrow">Preparing {owner}/{repo}</p>
      <h2 className="mt-2 text-xl font-extrabold">Snapshotting the repository</h2>
      <p className="mt-1 text-sm text-slate-500">First visit only: the snapshot is cached, so later pages open instantly.</p>
      <div className="mt-5 h-2 overflow-hidden rounded-full bg-slate-100" aria-hidden="true">
        <div className="h-full bg-ink transition-all duration-500" style={{ width: `${percent}%` }} />
      </div>
      <ol className="mt-5 space-y-2.5">
        {stages.slice(0, -1).map((label, index) => {
          const position = index + 1
          const done = step > position
          const current = step === position
          return <li key={label} className={`flex items-start gap-2.5 text-sm ${done ? 'text-slate-500' : current ? 'font-bold text-ink' : 'text-slate-400'}`}>
            {done ? <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-emerald-600" /> : current ? <Loader2 size={18} className="mt-0.5 shrink-0 animate-spin" /> : <Circle size={18} className="mt-0.5 shrink-0" />}
            <span>{current && status?.message ? status.message : label}</span>
          </li>
        })}
      </ol>
      {status?.elapsed_seconds > 0 && <p className="mono mt-4 text-xs text-slate-400">{Math.round(status.elapsed_seconds)} s elapsed</p>}
    </div>
  </div>
}

export default function RepositoryGate({ owner, repo, children }) {
  const { ready, status, error, retry } = useRepositoryPreparation(owner, repo)
  if (error) return <AppLayout>
    <ErrorMessage message={error} />
    <button onClick={retry} className="btn-secondary mt-4"><RotateCcw size={16} />Try again</button>
  </AppLayout>
  if (!ready) return <AppLayout><PreparationProgress owner={owner} repo={repo} status={status} /></AppLayout>
  return children
}
