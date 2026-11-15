import { ArrowDownLeft, ArrowUpRight, ExternalLink, FileCode2, FolderTree, Info, Layers, Network, Search, Target, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { getArchitecture, getIssueAnalysis, getRankedIssues } from '../api/contrimapApi'
import AppLayout from '../components/AppLayout'
import ErrorMessage from '../components/ErrorMessage'
import FlowGraph, { ROLE_COLORS, moduleColor } from '../components/FlowGraph'
import Loading from '../components/Loading'
import RepositoryGate from '../components/RepositoryGate'
import { useAsync } from '../hooks/useProfile'

const pct = value => `${Math.round((value || 0) * 100)}%`

function Stat({ icon: Icon, label, value }) {
  return <div className="card flex items-center gap-3 px-4 py-3">
    <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-sky text-blue-700"><Icon size={17} /></span>
    <div><p className="text-lg font-extrabold leading-tight">{value}</p><p className="text-[11px] font-bold text-slate-500">{label}</p></div>
  </div>
}

function Segmented({ value, onChange, options }) {
  return <div className="inline-flex rounded-xl border border-slate-200 bg-white p-1">
    {options.map(([key, label, disabled]) => <button key={key} type="button" disabled={disabled} onClick={() => onChange(key)}
      className={`rounded-lg px-3 py-1.5 text-xs font-bold transition ${value === key ? 'bg-ink text-white' : 'text-slate-500 hover:text-ink disabled:cursor-not-allowed disabled:opacity-40'}`}>{label}</button>)}
  </div>
}

function DependencyList({ title, icon: Icon, items, onSelect }) {
  if (!items.length) return null
  return <div className="mt-4">
    <p className="inline-flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide text-slate-500"><Icon size={12} />{title}</p>
    <ul className="mt-1.5 space-y-1">{items.map(item => <li key={item.id}>
      <button onClick={() => onSelect(item.id)} className="flex w-full items-center gap-2 rounded-lg px-2 py-1 text-left hover:bg-slate-50">
        <i className="h-2 w-2 shrink-0 rounded-full" style={{ background: item.color }} />
        <span className="mono min-w-0 flex-1 truncate text-xs">{item.label}</span>
        <span className="text-[10px] font-bold text-slate-400">{item.imports} imp.</span>
      </button>
    </li>)}</ul>
  </div>
}

function HowToRead() {
  return <div className="space-y-3 text-xs leading-5 text-slate-600">
    <p className="inline-flex items-center gap-1.5 font-bold text-ink"><Info size={14} />How to read this map</p>
    <p><b>Boxes</b> are directories; the coloured bar marks the <b>module</b> (directories whose files import each other heavily), and the thin bar shows how central the directory is in the import graph.</p>
    <p><b>Arrows</b> point from the importing directory to the one it imports; thicker means more imports.</p>
    <p><b>Hover</b> a box to trace its connections, <b>click</b> it for details, or pick an issue above to see where its fix is likely to land.</p>
  </div>
}

function KnowledgeGraphContent() {
  const { owner, repo } = useParams()
  const [params, setParams] = useSearchParams()
  const issue = params.get('issue')
  const [view, setView] = useState(params.get('view') === 'issue' ? 'issue' : 'architecture')
  const [issueInput, setIssueInput] = useState(issue || '')
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState(null)
  const [focusIds, setFocusIds] = useState([])
  const architecture = useAsync(() => getArchitecture(owner, repo), [owner, repo])
  const analysis = useAsync(() => (issue ? getIssueAnalysis(owner, repo, issue) : Promise.resolve(null)), [owner, repo, issue])
  // Open issues for the picker; the visualizer still works (manual number) if GitHub is unavailable.
  const issues = useAsync(() => getRankedIssues(owner, repo, { limit: 30 }).catch(() => ({ issues: [] })), [owner, repo])

  const architectureGraph = useMemo(() => {
    if (!architecture.data) return null
    const highlight = analysis.data?.architecture_highlight || []
    if (!highlight.length) return architecture.data
    const depth = architecture.data.depth
    const directoryOf = path => path.split('/').slice(0, Math.min(depth, path.split('/').length - 1)).join('/') || '(root)'
    const scores = {}
    highlight.forEach(item => { const key = `dir:${directoryOf(item.path)}`; scores[key] = Math.max(scores[key] || 0, item.relative_confidence || 0.1) })
    return { ...architecture.data, nodes: architecture.data.nodes.map(node => ({ ...node, data: { ...node.data, highlight: scores[node.id] || 0 } })) }
  }, [architecture.data, analysis.data])

  const issueGraph = analysis.data?.graph?.nodes?.length ? analysis.data.graph : null
  const activeView = view === 'issue' && issueGraph ? 'issue' : 'architecture'
  const graph = activeView === 'issue' ? issueGraph : architectureGraph
  const nodesById = useMemo(() => Object.fromEntries((graph?.nodes || []).map(node => [node.id, node])), [graph])

  const matchIds = useMemo(() => {
    const term = query.trim().toLowerCase()
    if (!term || !graph) return null
    return new Set(graph.nodes.filter(node => `${node.data?.label} ${node.data?.path || ''} ${(node.data?.top_files || []).join(' ')}`.toLowerCase().includes(term)).map(node => node.id))
  }, [query, graph])

  const select = id => { setSelected(id); setFocusIds(id ? [id] : []) }
  const chooseIssue = number => {
    setIssueInput(number || '')
    setSelected(null)
    setParams(number ? { issue: number } : {})
    if (number) setView('architecture')
  }
  const switchView = next => { setView(next); setSelected(null); setFocusIds([]); setQuery('') }

  const node = selected && nodesById[selected]
  const connections = useMemo(() => {
    if (!node || !graph) return { out: [], in: [] }
    const describe = (id, imports) => { const other = nodesById[id]; return { id, label: other?.data?.label || id, imports, color: other ? moduleColor(other.data?.community) : '#94a3b8' } }
    return {
      out: graph.edges.filter(edge => edge.source === node.id).map(edge => describe(edge.target, edge.data?.imports || 1)).sort((a, b) => b.imports - a.imports),
      in: graph.edges.filter(edge => edge.target === node.id).map(edge => describe(edge.source, edge.data?.imports || 1)).sort((a, b) => b.imports - a.imports),
    }
  }, [node, graph, nodesById])

  const summary = architecture.data?.summary || {}
  const directories = architecture.data?.nodes || []
  const fileUrl = path => `https://github.com/${owner}/${repo}/blob/HEAD/${path}`
  const pickerIssues = issues.data?.issues || []

  return <AppLayout>
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div>
        <p className="eyebrow">Interactive visualizer</p>
        <h1 className="mt-2 text-3xl font-extrabold">Architecture & dependencies</h1>
        <p className="mt-2 max-w-2xl text-sm text-slate-600">How the code of {owner}/{repo} is organised and which parts depend on each other, built from the git snapshot.</p>
      </div>
      <Link to={`/repository/${owner}/${repo}/issues`} className="btn-secondary py-2.5">Browse ranked issues</Link>
    </div>

    {architecture.data && <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Stat icon={FolderTree} label="directories shown" value={directories.length} />
      <Stat icon={FileCode2} label="source files covered" value={directories.reduce((total, n) => total + (n.data?.files || 0), 0).toLocaleString()} />
      <Stat icon={Network} label="import links" value={(summary.import_edges ?? '-').toLocaleString?.() ?? summary.import_edges} />
      <Stat icon={Layers} label="modules detected" value={summary.communities ?? '-'} />
    </div>}

    <div className="card mt-5 flex flex-col gap-3 p-3 lg:flex-row lg:items-center">
      <label className="flex flex-1 items-center gap-2 rounded-xl border border-slate-200 px-3">
        <Search size={16} className="text-slate-400" />
        <input value={query} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && matchIds?.size) setFocusIds([...matchIds]) }}
          placeholder={activeView === 'issue' ? 'Find a file…' : 'Find a directory or file… (Enter to zoom)'} className="w-full py-2.5 text-sm outline-none" aria-label="Search the graph" />
        {query && <><span className="whitespace-nowrap text-[11px] font-bold text-slate-400">{matchIds?.size || 0} match{matchIds?.size === 1 ? '' : 'es'}</span><button onClick={() => setQuery('')} className="text-slate-400 hover:text-ink" aria-label="Clear search"><X size={15} /></button></>}
      </label>
      <form onSubmit={event => { event.preventDefault(); chooseIssue(issueInput) }} className="flex flex-1 gap-2">
        <select value={pickerIssues.some(item => String(item.issue.number) === issue) ? issue : ''} onChange={event => chooseIssue(event.target.value)}
          className="min-w-0 flex-1 rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm" aria-label="Highlight an open issue">
          <option value="">{issues.loading ? 'Loading open issues…' : pickerIssues.length ? 'Highlight an open issue…' : 'No issue list (enter a number)'}</option>
          {pickerIssues.map(item => <option key={item.issue.number} value={item.issue.number}>#{item.issue.number} · {item.issue.title.slice(0, 70)}</option>)}
        </select>
        <input value={issueInput} onChange={event => setIssueInput(event.target.value.replace(/\D/g, ''))} placeholder="#" className="w-20 rounded-xl border border-slate-200 px-3 text-sm outline-none" aria-label="Issue number" />
        <button className="btn-primary py-2.5" disabled={!issueInput}><Target size={15} />Show</button>
        {issue && <button type="button" onClick={() => chooseIssue('')} className="btn-secondary py-2.5" aria-label="Clear issue"><X size={15} /></button>}
      </form>
    </div>

    {architecture.error && <div className="mt-4"><ErrorMessage message={architecture.error} /></div>}
    {analysis.error && <div className="mt-4"><ErrorMessage message={`Issue #${issue}: ${analysis.error}`} /></div>}
    {architecture.loading && <Loading label="Building the architecture map…" />}

    {graph && !architecture.loading && <div className="mt-5 grid gap-5 xl:grid-cols-[1fr_340px]">
      <div className="min-w-0">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <Segmented value={activeView} onChange={switchView} options={[['architecture', 'Architecture map'], ['issue', issue ? `Issue #${issue} files` : 'Issue files', !issueGraph]]} />
          {analysis.loading && <span className="text-xs font-bold text-slate-500">Locating issue #{issue}…</span>}
          {!issue && <span className="text-xs text-slate-400">Pick an issue to see where its fix is likely to land.</span>}
        </div>
        <FlowGraph graph={graph} height={640} selectedId={selected} matchIds={matchIds} focusIds={focusIds}
          onNodeClick={(_, n) => select(n.id === selected ? null : n.id)} onPaneClick={() => select(null)} />
        {activeView === 'architecture'
          ? <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-xs font-bold text-slate-500">
            <span className="flex items-center gap-2"><span className="flex gap-0.5">{[0, 1, 2, 3].map(i => <i key={i} className="h-2.5 w-1.5 rounded-sm" style={{ background: moduleColor(i) }} />)}</span>colour = module</span>
            <span className="flex items-center gap-2"><i className="h-2.5 w-5 rounded-sm border-2 border-rose-400" />likely fix site</span>
            <span className="flex items-center gap-2"><i className="h-0.5 w-5 bg-slate-400" />arrow = imports (thicker = more)</span>
          </div>
          : <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-xs font-bold text-slate-500">
            {[['target', 'likely change'], ['importer', 'imports it'], ['dependency', 'imported by it'], ['test', 'test (dashed)']].map(([key, label]) => <span key={key} className="flex items-center gap-2"><i className="h-2.5 w-2.5 rounded-full" style={{ background: ROLE_COLORS[key] }} />{label}</span>)}
          </div>}
      </div>

      <aside className="card self-start p-5 xl:sticky xl:top-5">
        {node ? <>
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="eyebrow">{activeView === 'issue' ? 'File' : 'Directory'}</p>
              <p className="mono mt-1 break-all text-sm font-medium">{node.data.path || `${node.data.label}/`}</p>
            </div>
            <button onClick={() => select(null)} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-ink" aria-label="Close details"><X size={16} /></button>
          </div>
          {activeView === 'architecture' ? <>
            <div className="mt-3 flex flex-wrap gap-2 text-[11px] font-bold">
              <span className="rounded-full bg-slate-100 px-2 py-1">{node.data.files} files</span>
              {node.data.language && <span className="rounded-full bg-slate-100 px-2 py-1">{node.data.language}</span>}
              <span className="rounded-full px-2 py-1 text-white" style={{ background: moduleColor(node.data.community) }}>module {node.data.community ?? '-'}</span>
              {node.data.highlight > 0 && <span className="rounded-full bg-rose-100 px-2 py-1 text-rose-700">likely fix site</span>}
            </div>
            <DependencyList title={`Depends on (${connections.out.length})`} icon={ArrowUpRight} items={connections.out} onSelect={select} />
            <DependencyList title={`Used by (${connections.in.length})`} icon={ArrowDownLeft} items={connections.in} onSelect={select} />
            {!connections.out.length && !connections.in.length && <p className="mt-4 text-xs text-slate-400">No resolved imports to or from other directories shown here.</p>}
            <p className="mt-5 text-[11px] font-bold uppercase tracking-wide text-slate-500">Most central files</p>
            <ul className="mt-1.5 space-y-1">{(node.data.top_files || []).map(path => <li key={path}>
              <a href={fileUrl(path)} target="_blank" rel="noreferrer" className="group flex items-center gap-1.5 rounded-lg px-2 py-1 hover:bg-slate-50"><FileCode2 size={12} className="shrink-0 text-slate-400" /><span className="mono min-w-0 flex-1 truncate text-xs">{path}</span><ExternalLink size={11} className="shrink-0 text-slate-300 group-hover:text-blue-700" /></a>
            </li>)}</ul>
          </> : <>
            <p className="mt-3 text-xs font-bold" style={{ color: ROLE_COLORS[node.data.role] }}>{{ target: `Likely change${node.data.rank ? ` · rank #${node.data.rank}` : ''}`, importer: 'Imports a likely-changed file', dependency: 'Imported by a likely-changed file', test: 'Tests a likely-changed file' }[node.data.role]}</p>
            <a href={fileUrl(node.data.path)} target="_blank" rel="noreferrer" className="btn-secondary mt-4 w-full py-2"><ExternalLink size={14} />Open on GitHub</a>
          </>}
        </> : analysis.data ? <>
          <p className="eyebrow">Issue #{analysis.data.issue.number}</p>
          <p className="mt-2 text-sm font-bold leading-5">{analysis.data.issue.title}</p>
          <p className="mt-4 text-[11px] font-bold uppercase tracking-wide text-slate-500">Most likely files to change</p>
          <ol className="mt-2 space-y-2">{analysis.data.files.slice(0, 6).map(file => <li key={file.path}>
            <a href={fileUrl(file.path)} target="_blank" rel="noreferrer" className="group block rounded-lg px-2 py-1 hover:bg-slate-50">
              <div className="flex items-center gap-2"><span className="w-5 text-[11px] font-bold text-rose-600">#{file.rank}</span><span className="mono min-w-0 flex-1 truncate text-xs">{file.path}</span><span className="text-[10px] font-bold text-slate-400">{pct(file.relative_confidence)}</span></div>
              <div className="ml-7 mt-1 h-1 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-rose-500" style={{ width: pct(file.relative_confidence) }} /></div>
            </a>
          </li>)}</ol>
          <Link to={`/repository/${owner}/${repo}/issues/${analysis.data.issue.number}`} className="btn-primary mt-5 w-full py-2.5">Open full analysis</Link>
          <p className="mt-4 text-[11px] text-slate-400">Click a box for its details.</p>
        </> : <HowToRead />}
      </aside>
    </div>}
  </AppLayout>
}

// The page renders once the backend has snapshotted the repository; until then the gate shows build progress.
export default function KnowledgeGraph() {
  const { owner, repo } = useParams()
  return <RepositoryGate owner={owner} repo={repo}><KnowledgeGraphContent /></RepositoryGate>
}
