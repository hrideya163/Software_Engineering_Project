import { ArrowDownLeft, ArrowUpRight, ChevronRight, FileCode2, FolderOpen, FolderTree, Info, Layers, Network, Search, Target, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { getArchitecture, getIssueAnalysis, getModuleGraph, getRankedIssues, getSimilarHistory } from '../api/contrimapApi'
import AppLayout from '../components/AppLayout'
import ErrorMessage from '../components/ErrorMessage'
import FileInspector from '../components/FileInspector'
import FlowGraph, { ROLE_COLORS, moduleColor } from '../components/FlowGraph'
import Loading from '../components/Loading'
import RepositoryGate from '../components/RepositoryGate'
import { useAsync } from '../hooks/useProfile'

const pct = value => `${Math.round((value || 0) * 100)}%`
const SOURCE_FILE = /\.(py|pyi|js|jsx|ts|tsx|mjs|cjs|vue|svelte|go|rs|java|kt|scala|rb|php|c|h|cc|cpp|hpp|cs|swift)$/i

function Stat({ icon: Icon, label, value }) {
  return <div className="card flex items-center gap-3 px-4 py-3">
    <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-sky text-blue-700"><Icon size={17} /></span>
    <div><p className="text-lg font-extrabold leading-tight">{value}</p><p className="text-[11px] font-bold text-slate-500">{label}</p></div>
  </div>
}

function DependencyList({ title, icon: Icon, items, onSelect }) {
  if (!items.length) return null
  return <div className="mt-4">
    <p className="inline-flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide text-slate-500"><Icon size={12} />{title}</p>
    <ul className="mt-1.5 space-y-1">{items.map(item => <li key={item.id}>
      <button type="button" onClick={() => onSelect(item.id)} className="flex w-full items-center gap-2 rounded-lg px-2 py-1 text-left hover:bg-slate-50">
        <i className="h-2 w-2 shrink-0 rounded-full" style={{ background: item.color }} />
        <span className="mono min-w-0 flex-1 truncate text-xs">{item.label}</span>
        <span className="text-[10px] font-bold text-slate-400">{item.imports} imp.</span>
      </button>
    </li>)}</ul>
  </div>
}

function LegendItem({ swatch, children }) {
  return <span className="flex items-center gap-2">{swatch}{children}</span>
}
const dot = color => <i className="h-2.5 w-2.5 rounded-full" style={{ background: color }} />

function HowToRead({ level }) {
  return <div className="space-y-3 text-xs leading-5 text-slate-600">
    <p className="inline-flex items-center gap-1.5 font-bold text-ink"><Info size={14} />How to use the map</p>
    {level === 'module'
      ? <p>Files are laid out in <b>layers</b>: files on the left import the ones to their right. Dashed boxes at the edges are other directories that import, or are imported by, this one.</p>
      : <p><b>Boxes</b> are directories; the coloured bar marks the <b>module</b> (code that imports itself heavily) and the thin bar shows how central it is.</p>}
    <p><b>Hover</b> to trace connections, <b>click</b> for details, <b>double-click</b> a directory to open its files, and click a file to inspect its code, symbols and history.</p>
    <p>Switch to <b>Issue impact</b> to see where a fix is likely to land and what it could affect.</p>
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

  const architecture = useAsync(() => getArchitecture(owner, repo), [owner, repo])
  const moduleGraph = useAsync(() => (directory && view === 'architecture' ? getModuleGraph(owner, repo, directory, { tests: showTests, issue }) : Promise.resolve(null)), [owner, repo, directory, showTests, issue, view])
  const analysis = useAsync(() => (issue ? getIssueAnalysis(owner, repo, issue) : Promise.resolve(null)), [owner, repo, issue])
  const history = useAsync(() => (issue && view === 'impact' ? getSimilarHistory(owner, repo, issue).catch(() => null) : Promise.resolve(null)), [owner, repo, issue, view])
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

  // Issue impact: predicted files and their neighbourhood, plus files changed by the fixes of similar past issues.
  const impactGraph = useMemo(() => {
    const base = analysis.data?.graph
    if (!base?.nodes?.length) return null
    const historical = new Map((history.data?.historical_files || []).filter(item => SOURCE_FILE.test(item.path)).map(item => [item.path, item]))
    const nodes = base.nodes.map(node => ({ ...node, data: { ...node.data, historical: historical.has(node.id) } }))
    const present = new Set(nodes.map(node => node.id))
    const maxX = Math.max(...nodes.map(node => node.position.x)) + 360
    const extra = [...historical.values()].filter(item => !present.has(item.path)).slice(0, 6)
    extra.forEach((item, row) => nodes.push({ id: item.path, type: 'historical', position: { x: maxX, y: row * 90 }, data: { label: item.path.split('/').pop(), path: item.path, role: 'historical', historical: true } }))
    return { ...base, nodes }
  }, [analysis.data, history.data])

  const graph = view === 'impact' ? impactGraph : directory ? moduleGraph.data : architectureGraph
  const level = view === 'impact' ? 'impact' : directory ? 'module' : 'overview'
  const nodesById = useMemo(() => Object.fromEntries((graph?.nodes || []).map(node => [node.id, node])), [graph])
  const modules = useMemo(() => [...new Set((graph?.nodes || []).map(node => node.data?.community).filter(value => value !== null && value !== undefined))].sort((a, b) => a - b), [graph])

  const matchIds = useMemo(() => {
    const term = query.trim().toLowerCase()
    if ((!term && moduleFilter === null) || !graph) return null
    return new Set(graph.nodes.filter(node => (!term || `${node.data?.label} ${node.data?.path || ''} ${(node.data?.top_files || []).join(' ')}`.toLowerCase().includes(term)) && (moduleFilter === null || node.data?.community === moduleFilter)).map(node => node.id))
  }, [query, moduleFilter, graph])

  const reset = () => { setSelected(null); setFocusIds([]); setQuery(''); setModuleFilter(null) }
  const select = id => { setSelected(id); setFocusIds(id ? [id] : []) }
  const openModule = dir => { reset(); update({ dir, file: null }) }
  const inspect = path => update({ file: path })
  const chooseIssue = number => { setIssueInput(number || ''); reset(); update({ issue: number || null, view: number ? 'impact' : null }) }
  const switchView = next => { reset(); update({ view: next === 'impact' ? 'impact' : null }) }

  const onNodeClick = (_, node) => {
    if (node.data?.role === 'external') return openModule(node.data.path.replace(/\/$/, ''))
    if (node.type === 'directory') return select(node.id === selected ? null : node.id)
    select(node.id)
    inspect(node.data?.path || node.id)
  }
  const onNodeDoubleClick = (_, node) => { if (node.type === 'directory') openModule(node.data.label) }

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
  const historicalNode = inspected && nodesById[inspected]?.data
  const inspectorBadge = historicalNode && (historicalNode.role === 'target' || historicalNode.historical) && <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] font-bold">
    {historicalNode.role === 'target' && <span className="rounded-full bg-rose-100 px-2 py-0.5 text-rose-700">predicted #{historicalNode.rank}</span>}
    {historicalNode.historical && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-amber-700">changed by a similar past fix</span>}
  </div>

  return <AppLayout>
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div>
        <p className="eyebrow">Interactive visualizer</p>
        <h1 className="mt-2 text-3xl font-extrabold">{view === 'impact' ? 'Issue impact' : 'Repository architecture'}</h1>
        <p className="mt-2 max-w-2xl text-sm text-slate-600">{view === 'impact' ? 'Where an issue\'s fix is likely to land, what imports it, what it imports, which tests cover it and what similar past fixes changed.' : `How the code of ${owner}/${repo} is organised and which parts depend on each other, built from the git snapshot.`}</p>
      </div>
      <div className="inline-flex rounded-xl border border-slate-200 bg-white p-1" role="tablist">
        {[['architecture', 'Repository architecture', Network], ['impact', 'Issue impact', Target]].map(([key, label, Icon]) => <button key={key} type="button" role="tab" aria-selected={view === key} onClick={() => switchView(key)}
          className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-bold transition ${view === key ? 'bg-ink text-white' : 'text-slate-500 hover:text-ink'}`}><Icon size={14} />{label}</button>)}
      </div>
    </div>

    {architecture.data && view === 'architecture' && <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Stat icon={FolderTree} label="directories on the map" value={directories.length} />
      <Stat icon={FileCode2} label="source files covered" value={directories.reduce((total, n) => total + (n.data?.files || 0), 0).toLocaleString()} />
      <Stat icon={Network} label="import links" value={(summary.import_edges ?? '-').toLocaleString?.() ?? summary.import_edges} />
      <Stat icon={Layers} label="modules detected" value={summary.communities ?? '-'} />
    </div>}

    <div className="card mt-5 flex flex-col gap-3 p-3 lg:flex-row lg:items-center">
      <label className="flex flex-1 items-center gap-2 rounded-xl border border-slate-200 px-3">
        <Search size={16} className="text-slate-400" />
        <input value={query} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && matchIds?.size) setFocusIds([...matchIds]) }}
          placeholder={level === 'overview' ? 'Find a directory or file… (Enter to zoom)' : 'Find a file… (Enter to zoom)'} className="w-full py-2.5 text-sm outline-none" aria-label="Search the graph" />
        {query && <><span className="whitespace-nowrap text-[11px] font-bold text-slate-400">{matchIds?.size || 0} match{matchIds?.size === 1 ? '' : 'es'}</span><button type="button" onClick={() => setQuery('')} className="text-slate-400 hover:text-ink" aria-label="Clear search"><X size={15} /></button></>}
      </label>
      <form onSubmit={event => { event.preventDefault(); chooseIssue(issueInput) }} className="flex flex-1 gap-2">
        <select value={pickerIssues.some(item => String(item.issue.number) === issue) ? issue : ''} onChange={event => chooseIssue(event.target.value)}
          className="min-w-0 flex-1 rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm" aria-label="Pick an open issue">
          <option value="">{issues.loading ? 'Loading open issues…' : pickerIssues.length ? 'Pick an open issue…' : 'No issue list (enter a number)'}</option>
          {pickerIssues.map(item => <option key={item.issue.number} value={item.issue.number}>#{item.issue.number} · {item.issue.title.slice(0, 70)}</option>)}
        </select>
        <input value={issueInput} onChange={event => setIssueInput(event.target.value.replace(/\D/g, ''))} placeholder="#" className="w-20 rounded-xl border border-slate-200 px-3 text-sm outline-none" aria-label="Issue number" />
        <button className="btn-primary py-2.5" disabled={!issueInput}><Target size={15} />Show</button>
        {issue && <button type="button" onClick={() => chooseIssue('')} className="btn-secondary py-2.5" aria-label="Clear issue"><X size={15} /></button>}
      </form>
    </div>

    {architecture.error && <div className="mt-4"><ErrorMessage message={architecture.error} /></div>}
    {moduleGraph.error && level === 'module' && <div className="mt-4"><ErrorMessage message={moduleGraph.error} /></div>}
    {analysis.error && <div className="mt-4"><ErrorMessage message={`Issue #${issue}: ${analysis.error}`} /></div>}

    <div className="mt-5 grid gap-5 xl:grid-cols-[1fr_380px]">
      <div className="min-w-0">
        <div className="mb-3 flex min-h-[34px] flex-wrap items-center justify-between gap-3">
          {view === 'architecture' ? <nav className="flex flex-wrap items-center gap-1 text-sm font-bold" aria-label="Breadcrumb">
            <button type="button" onClick={() => openModule(null)} className={directory ? 'text-blue-700 hover:underline' : 'text-ink'}>All directories</button>
            {directory && directory.split('/').map((part, index, parts) => <span key={index} className="inline-flex items-center gap-1"><ChevronRight size={14} className="text-slate-400" />
              <button type="button" onClick={() => openModule(parts.slice(0, index + 1).join('/'))} className={`mono ${index === parts.length - 1 ? 'text-ink' : 'text-blue-700 hover:underline'}`}>{part}</button></span>)}
            {level === 'module' && moduleGraph.data && <span className="ml-2 text-xs font-semibold text-slate-400">{moduleGraph.data.files_shown} of {moduleGraph.data.files_total} files · {moduleGraph.data.layers} layers</span>}
          </nav> : <span className="text-sm font-bold text-ink">{issue ? `Issue #${issue}` : 'No issue selected'}{history.loading && issue ? <span className="ml-2 text-xs font-semibold text-slate-400">checking similar past fixes…</span> : null}</span>}
          <div className="flex flex-wrap items-center gap-2">
            {level === 'module' && <label className="inline-flex items-center gap-1.5 text-xs font-bold text-slate-600"><input type="checkbox" checked={showTests} onChange={event => setShowTests(event.target.checked)} />Show tests</label>}
            {level !== 'impact' && modules.length > 1 && <div className="flex flex-wrap items-center gap-1" aria-label="Filter by module">
              {modules.slice(0, 8).map(community => <button key={community} type="button" onClick={() => setModuleFilter(moduleFilter === community ? null : community)} title={`Show only module ${community}`}
                className={`h-5 w-5 rounded-md border-2 transition ${moduleFilter === community ? 'border-ink' : 'border-transparent opacity-70 hover:opacity-100'}`} style={{ background: moduleColor(community) }} />)}
              {moduleFilter !== null && <button type="button" onClick={() => setModuleFilter(null)} className="text-[11px] font-bold text-slate-500 hover:text-ink">all modules</button>}
            </div>}
          </div>
        </div>

        {view === 'impact' && !issue ? <div className="card p-6">
          <p className="font-bold text-ink">Pick an issue to see its impact</p>
          <p className="mt-1 text-sm text-slate-500">The map shows the files its fix is likely to change, what depends on them and what similar past fixes touched.</p>
          <ul className="mt-4 grid gap-2 md:grid-cols-2">{pickerIssues.slice(0, 8).map(item => <li key={item.issue.number}><button type="button" onClick={() => chooseIssue(String(item.issue.number))} className="w-full truncate rounded-xl border border-slate-200 px-3 py-2 text-left text-sm hover:border-ink"><span className="mono text-xs text-slate-400">#{item.issue.number}</span> {item.issue.title}</button></li>)}</ul>
        </div>
          : loadingGraph ? <Loading label={level === 'impact' ? `Locating issue #${issue}…` : level === 'module' ? 'Opening the module…' : 'Building the architecture map…'} />
          : graph?.nodes?.length ? <FlowGraph key={`${level}:${directory || ''}:${issue || ''}`} graph={graph} height={640} selectedId={selected || inspected} matchIds={matchIds} focusIds={focusIds}
              onNodeClick={onNodeClick} onNodeDoubleClick={level === 'overview' ? onNodeDoubleClick : undefined} onPaneClick={() => select(null)} />
          : <p className="card p-6 text-sm text-slate-500">{level === 'impact' ? 'No import relationships were resolved for the predicted files.' : 'Nothing to show here.'}</p>}

        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-xs font-bold text-slate-500">
          {level === 'overview' && <>
            <LegendItem swatch={<span className="flex gap-0.5">{[0, 1, 2, 3].map(i => <i key={i} className="h-2.5 w-1.5 rounded-sm" style={{ background: moduleColor(i) }} />)}</span>}>colour = module</LegendItem>
            <LegendItem swatch={<i className="h-2.5 w-5 rounded-sm border-2 border-rose-400" />}>likely fix site</LegendItem>
            <LegendItem swatch={<i className="h-0.5 w-5 bg-slate-400" />}>arrow = imports (thicker = more)</LegendItem>
            <span className="text-slate-400">double-click a directory to open it</span>
          </>}
          {level === 'module' && <>
            <LegendItem swatch={dot(ROLE_COLORS.target)}>likely change</LegendItem>
            <LegendItem swatch={dot(ROLE_COLORS.test)}>test</LegendItem>
            <LegendItem swatch={<i className="h-3 w-5 rounded border border-dashed border-slate-400" />}>other directory (click to open)</LegendItem>
          </>}
          {level === 'impact' && <>
            <LegendItem swatch={dot(ROLE_COLORS.target)}>predicted change</LegendItem>
            <LegendItem swatch={<span className="rounded-full bg-amber-500 px-1 text-[8px] text-white">HISTORY</span>}>also changed by a similar past fix</LegendItem>
            <LegendItem swatch={dot(ROLE_COLORS.historical)}>changed by a similar fix only</LegendItem>
            <LegendItem swatch={dot(ROLE_COLORS.importer)}>imports it</LegendItem>
            <LegendItem swatch={dot(ROLE_COLORS.dependency)}>imported by it</LegendItem>
            <LegendItem swatch={dot(ROLE_COLORS.test)}>test (dashed)</LegendItem>
          </>}
        </div>
      </div>

      <aside className="card self-start p-5 xl:sticky xl:top-5">
        {inspected ? <FileInspector owner={owner} repo={repo} path={inspected} badge={inspectorBadge} onNavigate={path => { select(nodesById[path] ? path : null); inspect(path) }} onClose={() => { update({ file: null }); select(null) }} />
          : node && node.type === 'directory' ? <>
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0"><p className="eyebrow">Directory</p><p className="mono mt-1 break-all text-sm font-medium">{node.data.label}/</p></div>
              <button type="button" onClick={() => select(null)} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-ink" aria-label="Close details"><X size={16} /></button>
            </div>
            <div className="mt-3 flex flex-wrap gap-2 text-[11px] font-bold">
              <span className="rounded-full bg-slate-100 px-2 py-1">{node.data.files} files</span>
              {node.data.language && <span className="rounded-full bg-slate-100 px-2 py-1">{node.data.language}</span>}
              <span className="rounded-full px-2 py-1 text-white" style={{ background: moduleColor(node.data.community) }}>module {node.data.community ?? '-'}</span>
              {node.data.highlight > 0 && <span className="rounded-full bg-rose-100 px-2 py-1 text-rose-700">likely fix site</span>}
            </div>
            <button type="button" onClick={() => openModule(node.data.label)} className="btn-primary mt-4 w-full py-2.5"><FolderOpen size={15} />Open this directory</button>
            <DependencyList title={`Depends on (${connections.out.length})`} icon={ArrowUpRight} items={connections.out} onSelect={select} />
            <DependencyList title={`Used by (${connections.in.length})`} icon={ArrowDownLeft} items={connections.in} onSelect={select} />
            <p className="mt-5 text-[11px] font-bold uppercase tracking-wide text-slate-500">Most central files</p>
            <ul className="mt-1.5 space-y-1">{(node.data.top_files || []).map(path => <li key={path}>
              <button type="button" onClick={() => inspect(path)} className="flex w-full items-center gap-1.5 rounded-lg px-2 py-1 text-left hover:bg-slate-50"><FileCode2 size={12} className="shrink-0 text-slate-400" /><span className="mono min-w-0 flex-1 truncate text-xs">{path}</span></button>
            </li>)}</ul>
          </> : analysis.data ? <>
            <p className="eyebrow">Issue #{analysis.data.issue.number}</p>
            <p className="mt-2 text-sm font-bold leading-5">{analysis.data.issue.title}</p>
            <p className="mt-4 text-[11px] font-bold uppercase tracking-wide text-slate-500">Most likely files to change</p>
            <ol className="mt-2 space-y-2">{analysis.data.files.slice(0, 6).map(file => <li key={file.path}>
              <button type="button" onClick={() => { select(nodesById[file.path] ? file.path : null); inspect(file.path) }} className="block w-full rounded-lg px-2 py-1 text-left hover:bg-slate-50">
                <div className="flex items-center gap-2"><span className="w-5 text-[11px] font-bold text-rose-600">#{file.rank}</span><span className="mono min-w-0 flex-1 truncate text-xs">{file.path}</span><span className="text-[10px] font-bold text-slate-400">{pct(file.relative_confidence)}</span></div>
                <div className="ml-7 mt-1 h-1 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-rose-500" style={{ width: pct(file.relative_confidence) }} /></div>
              </button>
            </li>)}</ol>
            {history.data?.similar?.length > 0 && <>
              <p className="mt-5 text-[11px] font-bold uppercase tracking-wide text-slate-500">Similar past work</p>
              <ul className="mt-1.5 space-y-1">{history.data.similar.slice(0, 3).map(item => <li key={`${item.kind}${item.number}`}><a href={item.html_url} target="_blank" rel="noreferrer" className="line-clamp-1 text-xs text-blue-800 hover:underline">#{item.number} {item.title}</a></li>)}</ul>
            </>}
            <Link to={`/repository/${owner}/${repo}/issues/${analysis.data.issue.number}`} className="btn-primary mt-5 w-full py-2.5">Open full analysis</Link>
          </> : <HowToRead level={level} />}
      </aside>
    </div>
  </AppLayout>
}

// The page renders once the backend has snapshotted the repository; until then the gate shows build progress.
export default function KnowledgeGraph() {
  const { owner, repo } = useParams()
  return <RepositoryGate owner={owner} repo={repo}><KnowledgeGraphContent /></RepositoryGate>
}
