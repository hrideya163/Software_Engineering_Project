import { useMemo, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { getArchitecture, getIssueAnalysis } from '../api/contrimapApi'
import AppLayout from '../components/AppLayout'
import ErrorMessage from '../components/ErrorMessage'
import FlowGraph, { Legend } from '../components/FlowGraph'
import Loading from '../components/Loading'
import { useAsync } from '../hooks/useProfile'

// Architecture map: directories sized by file count, edges = aggregated imports,
// optionally highlighting where a given issue's predicted files live.
export default function KnowledgeGraph() {
  const { owner, repo } = useParams()
  const [params, setParams] = useSearchParams()
  const issue = params.get('issue')
  const [issueInput, setIssueInput] = useState(issue || '')
  const [selected, setSelected] = useState(null)
  const architecture = useAsync(() => getArchitecture(owner, repo), [owner, repo])
  const analysis = useAsync(() => (issue ? getIssueAnalysis(owner, repo, issue) : Promise.resolve(null)), [owner, repo, issue])
  const graph = useMemo(() => {
    if (!architecture.data) return null
    const highlight = analysis.data?.architecture_highlight || []
    if (!highlight.length) return architecture.data
    const depth = architecture.data.depth
    const directoryOf = path => path.split('/').slice(0, Math.min(depth, path.split('/').length - 1)).join('/') || '(root)'
    const scores = {}
    highlight.forEach(item => { const key = `dir:${directoryOf(item.path)}`; scores[key] = Math.max(scores[key] || 0, item.relative_confidence || 0.1) })
    return { ...architecture.data, nodes: architecture.data.nodes.map(node => ({ ...node, data: { ...node.data, highlight: scores[node.id] || 0 } })) }
  }, [architecture.data, analysis.data])
  const node = selected && graph?.nodes.find(n => n.id === selected)
  return <AppLayout>
    <p className="eyebrow">Interactive visualizer</p>
    <h1 className="mt-2 text-3xl font-extrabold">Architecture & dependencies</h1>
    <p className="mt-2 max-w-3xl text-sm text-slate-600">Directories of {owner}/{repo} grouped from the git snapshot; arrows are resolved imports between them (thicker = more imports). Enter an issue number to highlight where its fix is likely to land.</p>
    <form onSubmit={event => { event.preventDefault(); setParams(issueInput ? { issue: issueInput } : {}) }} className="card mt-5 flex gap-3 p-3">
      <input value={issueInput} onChange={event => setIssueInput(event.target.value.replace(/\D/g, ''))} placeholder="Issue number, e.g. 1234" className="flex-1 px-3 outline-none" />
      <button className="btn-primary py-2.5">Highlight issue</button>
      {issue && <button type="button" onClick={() => { setIssueInput(''); setParams({}) }} className="btn-secondary py-2.5">Clear</button>}
    </form>
    {(architecture.loading || analysis.loading) && <Loading label="Building the architecture map…" />}
    {architecture.error && <div className="mt-4"><ErrorMessage message={architecture.error} /></div>}
    {analysis.error && <div className="mt-4"><ErrorMessage message={analysis.error} /></div>}
    {graph && !architecture.loading && <div className="mt-5 grid gap-5 xl:grid-cols-[1fr_320px]">
      <div>
        <FlowGraph graph={graph} height={600} onNodeClick={(_, n) => setSelected(n.id)} />
        <Legend items={[['directory', 'directory (size = files)'], ['target', 'contains predicted files']]} />
      </div>
      <aside className="card self-start p-5">
        <p className="eyebrow">Summary</p>
        <p className="mt-3 text-sm text-slate-600">{graph.summary.import_edges} import edges · {graph.summary.communities} modules · modularity {graph.summary.modularity?.toFixed?.(2)}</p>
        {analysis.data && <><p className="eyebrow mt-5">Issue #{analysis.data.issue.number}</p><p className="mt-2 text-sm font-bold">{analysis.data.issue.title}</p><ol className="mt-2 space-y-1">{analysis.data.files.slice(0, 5).map(f => <li key={f.path} className="mono truncate text-xs text-rose-700">{f.rank}. {f.path}</li>)}</ol></>}
        {node && <><p className="eyebrow mt-5">{node.data.label}/</p><p className="mt-2 text-xs text-slate-500">{node.data.files} files · {node.data.language || 'mixed'}</p><p className="mt-3 text-xs font-bold text-slate-500">Most central files</p><ul className="mt-1 space-y-1">{node.data.top_files.map(path => <li key={path} className="mono truncate text-xs">{path}</li>)}</ul></>}
        {!node && <p className="mt-5 text-xs text-slate-400">Click a directory to inspect it.</p>}
      </aside>
    </div>}
  </AppLayout>
}
