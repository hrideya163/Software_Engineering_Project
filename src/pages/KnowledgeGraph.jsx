import { ArrowDownLeft, ArrowLeft, ArrowUpRight, ChevronRight, FileCode2, FolderOpen, Info, Network, Search, Target, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { getArchitecture, getIssueAnalysis, getModuleGraph, getRankedIssues, getSimilarHistory } from '../api/contrimapApi'
import AppLayout from '../components/AppLayout'
import ErrorMessage from '../components/ErrorMessage'
import FileInspector from '../components/FileInspector'
import FlowGraph, { ROLE_COLORS, moduleColor } from '../components/FlowGraph'
import Loading from '../components/Loading'
import RepositoryGate from '../components/RepositoryGate'
import { useAsync } from '../hooks/useProfile'
import { impactView, initialFocus, layeredView } from '../utils/graphViews'

const pct = value => `${Math.round((value || 0) * 100)}%`
const GRAPH_HEIGHT = 'max(520px, calc(100vh - 300px))'

function DependencyList({ title, icon: Icon, items, onSelect }) {
  if (!items.length) return null
  return <div className="mt-4">
    <p className="inline-flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide text-slate-500"><Icon size={12} />{title}</p>
    <ul className="mt-1.5 space-y-0.5">{items.map(item => <li key={item.id}>
      <button type="button" onClick={() => onSelect(item.id)} className="flex w-full items-center gap-2 rounded-lg px-2 py-1 text-left hover:bg-slate-50">
        <i className="h-2 w-2 shrink-0 rounded-full" style={{ background: item.color }} />
        <span className="mono min-w-0 flex-1 truncate text-xs">{item.label}</span>
        <span className="text-[10px] font-bold text-slate-400">{item.imports}</span>
      </button>
    </li>)}</ul>
  </div>
}

const Swatch = ({ color, dashed, children }) => <span className="flex items-center gap-2"><i className={`h-2.5 w-2.5 rounded-sm ${dashed ? 'border border-dashed border-slate-400' : ''}`} style={dashed ? undefined : { background: color }} />{children}</span>

function Help({ view }) {
  return <div className="space-y-3 text-xs leading-5 text-slate-600">
    <p className="inline-flex items-center gap-1.5 text-sm font-bold text-ink"><Info size={15} />Reading the map</p>
    {view === 'impact' ? <>
      <p>Columns read left to right: files that <b>import</b> the likely changes, the <b>likely changes</b> themselves with their <b>tests</b>, and what they <b>import</b>.</p>
      <p>An amber <b>history</b> tag marks files that the fix of a similar past issue also changed.</p>
    </> : <>
      <p>Boxes read left to right: a box <b>imports</b> the boxes its arrows point to. Boxes in the same column import each other in a cycle or sit at the same depth.</p>
      <p>The coloured strip marks the <b>module</b>, code that mostly imports itself; the thin bar shows how central a box is.</p>
    </>}
    <p><b>Hover</b> to trace connections, <b>click</b> for details, <b>double-click</b> a directory to open it, and press <b>Esc</b> to clear the selection.</p>
  </div>
}

function KnowledgeGraphContent() {
  const { owner, repo } = useParams()
  const [params, setParams] = useSearchParams()
  const issue = params.get('issue')
  const directory = params.get('dir')
  const inspected = params.get('file')
  const view = params.get('view') === 'impact' ? 'impact' : 'architecture'
  const [issueInput, setIssueInput] = useState(issue || '')
  const [query, setQuery] = useState('')
  const [moduleFilter, setModuleFilter] = useState(null)
  const [showTests, setShowTests] = useState(false)
  const [selected, setSelected] = useState(null)
  const [focusIds, setFocusIds] = useState([])

  const update = changes => setParams(previous => {
    const next = new URLSearchParams(previous)
    Object.entries(changes).forEach(([key, value]) => (value === null || value === undefined || value === '' ? next.delete(key) : next.set(key, value)))
    return next
  })
  useEffect(() => setIssueInput(issue || ''), [issue])

  const architecture = useAsync(() => getArchitecture(owner, repo), [owner, repo])
  const moduleGraph = useAsync(() => (directory && view === 'architecture' ? getModuleGraph(owner, repo, directory, { tests: showTests, issue }) : Promise.resolve(null)), [owner, repo, directory, showTests, issue, view])
  const analysis = useAsync(() => (issue ? getIssueAnalysis(owner, repo, issue) : Promise.resolve(null)), [owner, repo, issue])
  const history = useAsync(() => (issue && view === 'impact' ? getSimilarHistory(owner, repo, issue).catch(() => null) : Promise.resolve(null)), [owner, repo, issue, view])
  // Open issues for the picker; the visualizer still works (manual number) if GitHub is unavailable.
  const issues = useAsync(() => getRankedIssues(owner, repo, { limit: 30 }).catch(() => ({ issues: [] })), [owner, repo])

  const overviewGraph = useMemo(() => {
    if (!architecture.data) return null
    const highlight = analysis.data?.architecture_highlight || []
    let base = architecture.data
    if (highlight.length) {
      const depth = base.depth
      const directoryOf = path => path.split('/').slice(0, Math.min(depth, path.split('/').length - 1)).join('/') || '(root)'
      const scores = {}
      highlight.forEach(item => { const key = `dir:${directoryOf(item.path)}`; scores[key] = Math.max(scores[key] || 0, item.relative_confidence || 0.1) })
      base = { ...base, nodes: base.nodes.map(node => ({ ...node, data: { ...node.data, highlight: scores[node.id] || 0 } })) }
    }
    return layeredView(base)
  }, [architecture.data, analysis.data])
  const directoryGraph = useMemo(() => layeredView(moduleGraph.data), [moduleGraph.data])
  const issueGraph = useMemo(() => impactView(analysis.data?.graph, history.data?.historical_files), [analysis.data, history.data])

  const level = view === 'impact' ? 'impact' : directory ? 'module' : 'overview'
  const graph = level === 'impact' ? issueGraph : level === 'module' ? directoryGraph : overviewGraph
  const nodesById = useMemo(() => Object.fromEntries((graph?.nodes || []).map(node => [node.id, node])), [graph])
  const opening = useMemo(() => initialFocus(graph, level === 'overview' ? 30 : 10), [graph, level])
  const modules = useMemo(() => [...new Set((graph?.nodes || []).map(node => node.data?.community).filter(value => value !== null && value !== undefined))].sort((a, b) => a - b), [graph])

  const matchIds = useMemo(() => {
    const term = query.trim().toLowerCase()
    if ((!term && moduleFilter === null) || !graph) return null
    return new Set(graph.nodes.filter(node => node.type !== 'lane' && (!term || `${node.data?.label} ${node.data?.path || ''} ${(node.data?.top_files || []).join(' ')}`.toLowerCase().includes(term)) && (moduleFilter === null || node.data?.community === moduleFilter)).map(node => node.id))
  }, [query, moduleFilter, graph])

  const reset = () => { setSelected(null); setFocusIds([]); setQuery(''); setModuleFilter(null) }
  const select = id => { setSelected(id); setFocusIds(id ? [id] : []) }
  const openDirectory = dir => { reset(); update({ dir: dir || null, file: null, view: null }) }
  const parentOf = dir => (dir && dir.includes('/') ? dir.slice(0, dir.lastIndexOf('/')) : null)
  const inspect = path => update({ file: path })
  const chooseIssue = number => { reset(); update({ issue: number || null, view: number ? 'impact' : null, file: null }) }
  const switchView = next => { reset(); update({ view: next === 'impact' ? 'impact' : null, file: null }) }
  const clear = () => { select(null); if (inspected) update({ file: null }) }

  const onNodeClick = (_, node) => {
    if (node.data?.role === 'external') return openDirectory(node.data.path.replace(/\/$/, '').replace('(root)', ''))
    if (node.type === 'directory') { update({ file: null }); return select(node.id === selected ? null : node.id) }
    select(node.id)
    inspect(node.data?.path || node.id)
  }
  const onNodeDoubleClick = (_, node) => { if (node.type === 'directory') openDirectory(node.data.label) }

  const node = selected && nodesById[selected]
  const connections = useMemo(() => {
    if (!node || !graph || node.type !== 'directory') return { out: [], in: [] }
    const describe = (id, imports) => { const other = nodesById[id]; return { id, label: other?.data?.label || id, imports, color: other ? moduleColor(other.data?.community) : '#94a3b8' } }
    return {
      out: graph.edges.filter(edge => edge.source === node.id).map(edge => describe(edge.target, edge.data?.imports || 1)).sort((a, b) => b.imports - a.imports),
      in: graph.edges.filter(edge => edge.target === node.id).map(edge => describe(edge.source, edge.data?.imports || 1)).sort((a, b) => b.imports - a.imports),
    }
  }, [node, graph, nodesById])

  const summary = architecture.data?.summary || {}
  const directories = architecture.data?.nodes || []
  const pickerIssues = issues.data?.issues || []
  const loadingGraph = level === 'overview' ? architecture.loading : level === 'module' ? moduleGraph.loading : analysis.loading
  const graphError = level === 'overview' ? architecture.error : level === 'module' ? moduleGraph.error : analysis.error
  const retryGraph = level === 'overview' ? architecture.retry : level === 'module' ? moduleGraph.retry : analysis.retry
  const inspectedNode = inspected && nodesById[inspected]?.data
  const inspectorBadge = inspectedNode && (inspectedNode.role === 'target' || inspectedNode.historical) && <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] font-bold">
    {inspectedNode.role === 'target' && <span className="rounded-full bg-rose-100 px-2 py-0.5 text-rose-700">likely change #{inspectedNode.rank}</span>}
    {inspectedNode.historical && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-amber-700">changed by a similar past fix</span>}
  </div>
  const searchable = graph?.nodes?.some(item => item.type !== 'lane')

  return <AppLayout>
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <p className="eyebrow">Visualizer</p>
        <h1 className="mt-2 text-2xl font-extrabold md:text-3xl">{view === 'impact' ? 'Issue impact' : 'Repository architecture'}</h1>
        <p className="mt-1 text-sm text-slate-500">{view === 'impact' ? 'Where a fix is likely to land and what it touches.' : `${directories.length} directories · ${directories.reduce((total, item) => total + (item.data?.files || 0), 0).toLocaleString()} source files · ${(summary.import_edges ?? 0).toLocaleString()} import links · ${summary.communities ?? 0} modules`}</p>
      </div>
      <div className="inline-flex rounded-xl border border-slate-200 bg-white p-1" role="tablist" aria-label="Visualizer view">
        {[['architecture', 'Architecture', Network], ['impact', 'Issue impact', Target]].map(([key, label, Icon]) => <button key={key} type="button" role="tab" aria-selected={view === key} onClick={() => switchView(key)}
          className={`inline-flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-bold transition ${view === key ? 'bg-ink text-white' : 'text-slate-500 hover:text-ink'}`}><Icon size={15} />{label}</button>)}
      </div>
    </div>

    {/* One toolbar: where you are, what to find, and which issue to show. */}
    <div className="card mt-5 space-y-3 p-3">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
        {view === 'architecture'
          ? <nav className="flex min-w-0 flex-1 flex-wrap items-center gap-1 text-sm font-bold" aria-label="Directory path">
            {directory && <button type="button" onClick={() => openDirectory(parentOf(directory))} className="mr-1 grid h-8 w-8 place-items-center rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50" title="Up one level" aria-label="Up one level"><ArrowLeft size={15} /></button>}
            <button type="button" onClick={() => openDirectory(null)} className={`rounded-md px-1.5 py-1 ${directory ? 'text-blue-700 hover:bg-sky' : 'text-ink'}`}>All directories</button>
            {directory && directory.split('/').map((part, index, parts) => <span key={index} className="inline-flex items-center gap-1"><ChevronRight size={14} className="text-slate-300" />
              <button type="button" onClick={() => openDirectory(parts.slice(0, index + 1).join('/'))} className={`mono rounded-md px-1.5 py-1 ${index === parts.length - 1 ? 'text-ink' : 'text-blue-700 hover:bg-sky'}`}>{part}</button></span>)}
            {level === 'module' && directoryGraph && <span className="ml-1 text-xs font-semibold text-slate-400">{moduleGraph.data.files_shown} of {moduleGraph.data.files_total} files</span>}
          </nav>
          : <form onSubmit={event => { event.preventDefault(); chooseIssue(issueInput) }} className="flex min-w-0 flex-1 gap-2">
            <select value={pickerIssues.some(item => String(item.issue.number) === issue) ? issue : ''} onChange={event => chooseIssue(event.target.value)} className="min-w-0 flex-1 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm" aria-label="Pick an open issue">
              <option value="">{issues.loading ? 'Loading open issues…' : pickerIssues.length ? 'Pick an open issue…' : 'Enter an issue number'}</option>
              {pickerIssues.map(item => <option key={item.issue.number} value={item.issue.number}>#{item.issue.number} · {item.issue.title.slice(0, 80)}</option>)}
            </select>
            <input value={issueInput} onChange={event => setIssueInput(event.target.value.replace(/\D/g, ''))} placeholder="#" inputMode="numeric" className="w-20 rounded-xl border border-slate-200 px-3 text-sm outline-none focus:border-blue-400" aria-label="Issue number" />
            <button className="btn-primary py-2 disabled:opacity-50" disabled={!issueInput || issueInput === issue}>Show</button>
          </form>}
        <label className="flex items-center gap-2 rounded-xl border border-slate-200 px-3 lg:w-72">
          <Search size={15} className="shrink-0 text-slate-400" />
          <input value={query} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && matchIds?.size) setFocusIds([...matchIds]) }} disabled={!searchable}
            placeholder={level === 'overview' ? 'Find a directory or file' : 'Find a file'} className="w-full py-2 text-sm outline-none disabled:bg-transparent" aria-label="Search the map" />
          {query && <><span className="whitespace-nowrap text-[11px] font-bold text-slate-400">{matchIds?.size || 0}</span><button type="button" onClick={() => setQuery('')} className="text-slate-400 hover:text-ink" aria-label="Clear search"><X size={14} /></button></>}
        </label>
      </div>
      {(level !== 'impact' && (modules.length > 1 || level === 'module')) && <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-slate-100 pt-3 text-xs font-bold text-slate-500">
        {modules.length > 1 && <div className="flex flex-wrap items-center gap-1.5" aria-label="Filter by module">
          <span>Modules</span>
          {modules.slice(0, 8).map(community => <button key={community} type="button" onClick={() => setModuleFilter(moduleFilter === community ? null : community)} aria-pressed={moduleFilter === community} title={`Show only module ${community}`}
            className={`h-5 w-5 rounded-md border-2 transition ${moduleFilter === community ? 'border-ink' : 'border-white opacity-70 hover:opacity-100'}`} style={{ background: moduleColor(community) }} />)}
          {moduleFilter !== null && <button type="button" onClick={() => setModuleFilter(null)} className="text-blue-700 hover:underline">show all</button>}
        </div>}
        {level === 'module' && <label className="inline-flex items-center gap-1.5"><input type="checkbox" checked={showTests} onChange={event => setShowTests(event.target.checked)} />Include tests</label>}
        {issue && view === 'architecture' && <span className="inline-flex items-center gap-1.5 text-rose-700"><i className="h-2.5 w-4 rounded-sm border-2 border-rose-400" />Issue #{issue} highlighted<button type="button" onClick={() => chooseIssue('')} className="text-slate-400 hover:text-ink" aria-label="Clear issue"><X size={13} /></button></span>}
      </div>}
    </div>

    <div className="mt-4 grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="min-w-0">
        {view === 'impact' && !issue ? <div className="card p-6">
          <p className="font-extrabold">Pick an issue to see its impact</p>
          <p className="mt-1 text-sm text-slate-500">The map shows the files its fix is likely to change, what imports them, what they import, their tests and what similar past fixes touched.</p>
          {issues.loading ? <Loading compact label="Loading open issues…" /> : <ul className="mt-4 grid gap-2 md:grid-cols-2">{pickerIssues.slice(0, 10).map(item => <li key={item.issue.number}><button type="button" onClick={() => chooseIssue(String(item.issue.number))} className="flex w-full items-center gap-2 rounded-xl border border-slate-200 px-3 py-2.5 text-left text-sm hover:border-ink"><span className="mono shrink-0 text-xs text-slate-400">#{item.issue.number}</span><span className="truncate">{item.issue.title}</span></button></li>)}</ul>}
        </div>
          : graphError ? <ErrorMessage message={graphError} onRetry={retryGraph} />
          : loadingGraph ? <div className="card" style={{ height: GRAPH_HEIGHT }}><Loading label={level === 'impact' ? `Locating issue #${issue}…` : level === 'module' ? 'Opening the directory…' : 'Building the architecture map…'} /></div>
          : graph?.nodes?.length ? <FlowGraph key={`${level}:${directory || ''}:${issue || ''}:${showTests}`} graph={graph} height={GRAPH_HEIGHT} selectedId={selected || inspected} matchIds={matchIds} focusIds={focusIds} initialIds={opening}
              onNodeClick={onNodeClick} onNodeDoubleClick={level === 'overview' ? onNodeDoubleClick : undefined} onPaneClick={clear} showMiniMap={graph.nodes.filter(item => item.type !== 'lane').length > 30} />
          : <div className="card p-6 text-sm text-slate-500">{level === 'impact' ? 'No import relationships were resolved for the predicted files.' : 'No source files with resolvable imports here.'}</div>}

        {graph?.nodes?.length > 0 && <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-xs font-semibold text-slate-500">
          {level === 'overview' && <>
            <span className="flex items-center gap-2"><span className="flex gap-0.5">{[0, 1, 2, 3].map(i => <i key={i} className="h-2.5 w-1.5 rounded-sm" style={{ background: moduleColor(i) }} />)}</span>module</span>
            <span className="flex items-center gap-2"><i className="h-0.5 w-6 bg-slate-400" />imports (left to right)</span>
            {issue && <span className="flex items-center gap-2"><i className="h-2.5 w-5 rounded-sm border-2 border-rose-400" />likely fix site</span>}
          </>}
          {level === 'module' && <>
            <span className="flex items-center gap-2"><i className="h-0.5 w-6 bg-slate-400" />imports (left to right)</span>
            {issue && <Swatch color={ROLE_COLORS.target}>likely change</Swatch>}
            {showTests && <Swatch color={ROLE_COLORS.test}>test</Swatch>}
            <Swatch dashed>other directory (click to open)</Swatch>
          </>}
          {level === 'impact' && <>
            <Swatch color={ROLE_COLORS.target}>likely change</Swatch>
            <Swatch color={ROLE_COLORS.importer}>imports it</Swatch>
            <Swatch color={ROLE_COLORS.dependency}>imported by it</Swatch>
            <Swatch color={ROLE_COLORS.test}>test</Swatch>
            <Swatch color={ROLE_COLORS.historical}>changed by a similar fix</Swatch>
            {history.loading && <span className="text-slate-400">checking similar past fixes…</span>}
          </>}
        </div>}
      </div>

      <aside className="card self-start p-5 xl:sticky xl:top-20 xl:max-h-[calc(100vh-6rem)] xl:overflow-y-auto">
        {inspected ? <FileInspector owner={owner} repo={repo} path={inspected} badge={inspectorBadge} onNavigate={path => { select(nodesById[path] ? path : null); inspect(path) }} onClose={clear} />
          : node && node.type === 'directory' ? <>
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0"><p className="eyebrow">Directory</p><p className="mono mt-1 break-all text-sm font-medium">{node.data.label}/</p></div>
              <button type="button" onClick={() => select(null)} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-ink" aria-label="Close details"><X size={16} /></button>
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5 text-[11px] font-bold">
              <span className="rounded-full bg-slate-100 px-2 py-0.5">{node.data.files} files</span>
              {node.data.language && <span className="rounded-full bg-slate-100 px-2 py-0.5">{node.data.language}</span>}
              <span className="rounded-full px-2 py-0.5 text-white" style={{ background: moduleColor(node.data.community) }}>module {node.data.community ?? '-'}</span>
              {node.data.highlight > 0 && <span className="rounded-full bg-rose-100 px-2 py-0.5 text-rose-700">likely fix site</span>}
            </div>
            <button type="button" onClick={() => openDirectory(node.data.label)} className="btn-primary mt-4 w-full py-2.5"><FolderOpen size={15} />Open directory</button>
            <DependencyList title={`Imports from (${connections.out.length})`} icon={ArrowUpRight} items={connections.out} onSelect={select} />
            <DependencyList title={`Imported by (${connections.in.length})`} icon={ArrowDownLeft} items={connections.in} onSelect={select} />
            <p className="mt-5 text-[11px] font-bold uppercase tracking-wide text-slate-500">Most central files</p>
            <ul className="mt-1.5 space-y-0.5">{(node.data.top_files || []).map(path => <li key={path}>
              <button type="button" onClick={() => inspect(path)} className="flex w-full items-center gap-1.5 rounded-lg px-2 py-1 text-left hover:bg-slate-50"><FileCode2 size={12} className="shrink-0 text-slate-400" /><span className="mono min-w-0 flex-1 truncate text-xs">{path}</span></button>
            </li>)}</ul>
          </> : analysis.data ? <>
            <p className="eyebrow">Issue #{analysis.data.issue.number}</p>
            <p className="mt-2 text-sm font-bold leading-5">{analysis.data.issue.title}</p>
            <p className="mt-4 text-[11px] font-bold uppercase tracking-wide text-slate-500">Most likely files to change</p>
            <ol className="mt-2 space-y-1.5">{analysis.data.files.slice(0, 6).map(file => <li key={file.path}>
              <button type="button" onClick={() => { select(nodesById[file.path] ? file.path : null); inspect(file.path) }} className="block w-full rounded-lg px-2 py-1 text-left hover:bg-slate-50">
                <div className="flex items-center gap-2"><span className="w-5 text-[11px] font-bold text-rose-600">#{file.rank}</span><span className="mono min-w-0 flex-1 truncate text-xs">{file.path}</span><span className="text-[10px] font-bold text-slate-400">{pct(file.relative_confidence)}</span></div>
                <div className="ml-7 mt-1 h-1 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-rose-500" style={{ width: pct(file.relative_confidence) }} /></div>
              </button>
            </li>)}</ol>
            {history.data?.similar?.length > 0 && <>
              <p className="mt-5 text-[11px] font-bold uppercase tracking-wide text-slate-500">Similar past work</p>
              <ul className="mt-1.5 space-y-1">{history.data.similar.slice(0, 3).map(item => <li key={`${item.kind}${item.number}`}><a href={item.html_url} target="_blank" rel="noreferrer" className="line-clamp-1 text-xs text-blue-800 hover:underline">#{item.number} {item.title}</a></li>)}</ul>
            </>}
            <div className="mt-5 grid gap-2">
              {view === 'architecture' && <button type="button" onClick={() => switchView('impact')} className="btn-secondary w-full py-2.5"><Target size={15} />Show issue impact</button>}
              <Link to={`/repository/${owner}/${repo}/issues/${analysis.data.issue.number}`} className="btn-primary w-full py-2.5">Open full analysis</Link>
            </div>
          </> : <Help view={view} />}
      </aside>
    </div>
  </AppLayout>
}

// The page renders once the backend has snapshotted the repository; until then the gate shows build progress.
export default function KnowledgeGraph() {
  const { owner, repo } = useParams()
  return <RepositoryGate owner={owner} repo={repo}><KnowledgeGraphContent /></RepositoryGate>
}
