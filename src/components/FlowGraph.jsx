import { Background, Handle, MarkerType, MiniMap, Panel, Position, ReactFlow, ReactFlowProvider, useReactFlow, useStore } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { ChevronRight, FolderOpen, Maximize, Maximize2, Minimize2, Minus, Plus } from 'lucide-react'
import { memo, useEffect, useMemo, useState } from 'react'
import { NODE_HEIGHT, NODE_WIDTH } from '../utils/graphLayout'

// Shared palette (same hues as the repository dashboard charts).
export const MODULE_COLORS = ['#2d7ef7', '#0eaa7d', '#f59e0b', '#7c3aed', '#06b6d4', '#ec4899', '#64748b', '#ef4444']
export const ROLE_COLORS = { target: '#e11d48', historical: '#d97706', importer: '#2d7ef7', dependency: '#0eaa7d', test: '#7c3aed', directory: '#10233e', external: '#94a3b8', module_file: '#64748b' }
const ROLE_LABELS = { target: 'Likely to change', historical: 'Changed by a similar fix', importer: 'Imports it', dependency: 'Imported by it', test: 'Test', external: 'Outside this directory' }

export const moduleColor = community => (community === null || community === undefined ? '#94a3b8' : MODULE_COLORS[Number(community) % MODULE_COLORS.length])

const hidden = { opacity: 0, width: 6, height: 6, border: 0, background: 'transparent', pointerEvents: 'none' }
const splitPath = path => {
  const parts = String(path || '').split('/')
  return { name: parts.pop() || path, parent: parts.join('/') }
}

function Shell({ data, accent, dashed, children, badge }) {
  const ring = data.selected ? 'ring-2 ring-ink ring-offset-1' : data.match ? 'ring-2 ring-mint' : data.highlight > 0 || data.role === 'target' ? 'ring-2 ring-rose-200' : ''
  return <div className={`relative rounded-xl border bg-white shadow-sm transition-[opacity,box-shadow] duration-200 hover:shadow-md ${dashed ? 'border-dashed border-slate-300 bg-slate-50' : data.highlight > 0 ? 'border-rose-300' : 'border-slate-200'} ${ring}`} style={{ width: NODE_WIDTH, minHeight: NODE_HEIGHT, opacity: data.dimmed ? 0.25 : 1 }}>
    <Handle type="target" position={Position.Left} style={hidden} isConnectable={false} />
    <div className="flex h-full items-stretch" style={{ minHeight: NODE_HEIGHT }}>
      <span className="w-1.5 shrink-0 rounded-l-xl" style={{ background: accent }} />
      <div className="min-w-0 flex-1 px-3 py-2">{children}</div>
    </div>
    {badge}
    <Handle type="source" position={Position.Right} style={hidden} isConnectable={false} />
  </div>
}

const Badge = ({ tone, children, title }) => <span title={title} className={`absolute -top-2 right-2 rounded-full px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-white shadow-sm ${tone}`}>{children}</span>

const DirectoryNode = memo(function DirectoryNode({ data }) {
  const { name, parent } = splitPath(data.label)
  return <Shell data={data} accent={data.color} badge={data.highlight > 0 && <Badge tone="bg-rose-500" title="Contains files the selected issue is likely to change">likely fix</Badge>}>
    <div className="flex items-center gap-1.5">
      <FolderOpen size={13} className="shrink-0 text-slate-400" />
      <p className="mono min-w-0 flex-1 truncate text-[12.5px] font-medium text-ink" title={data.label}>{parent && <span className="text-slate-400">{parent}/</span>}{name}</p>
      <ChevronRight size={13} className="shrink-0 text-slate-300" aria-hidden="true" />
    </div>
    <p className="mt-0.5 text-[10.5px] font-semibold text-slate-500">{data.files} files{data.language ? ` · ${data.language}` : ''}</p>
    <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-slate-100" title={`Share of import-graph importance: ${Math.round((data.importanceShare || 0) * 100)}%`}>
      <div className="h-full rounded-full" style={{ width: `${Math.max(4, (data.importanceShare || 0) * 100)}%`, background: data.color }} />
    </div>
  </Shell>
})

const FileNode = memo(function FileNode({ data }) {
  const { name, parent } = splitPath(data.path || data.label)
  const isModule = data.role === 'module_file'
  const isExternal = data.role === 'external'
  const accent = isModule ? data.color : ROLE_COLORS[data.role] || '#64748b'
  const badge = data.historical && data.role !== 'historical'
    ? <Badge tone="bg-amber-500" title="Also changed by the fix of a similar past issue">history</Badge>
    : null
  return <Shell data={data} accent={accent} dashed={isExternal} badge={badge}>
    <div className="flex items-center gap-1.5">
      {data.rank && <span className="shrink-0 rounded bg-rose-100 px-1 text-[10px] font-bold text-rose-700">#{data.rank}</span>}
      <p className="mono min-w-0 flex-1 truncate text-[12.5px] font-medium text-ink" title={data.path}>{isExternal ? data.label : name}</p>
    </div>
    {isExternal
      ? <p className="mt-0.5 text-[10.5px] text-slate-500">{data.direction === 'in' ? 'imports this directory' : 'imported from here'} · {data.imports} links · open</p>
      : <p className="mono mt-0.5 truncate text-[10.5px] text-slate-400" title={parent}>{parent || '(root)'}</p>}
    {isModule
      ? <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-slate-100" title="Importance within the import graph"><div className="h-full rounded-full" style={{ width: `${Math.max(4, (data.importance_share || 0) * 100)}%`, background: accent }} /></div>
      : !isExternal && <p className="mt-1 text-[10px] font-bold uppercase tracking-wide" style={{ color: accent }}>{ROLE_LABELS[data.role] || data.role}</p>}
  </Shell>
})

// Column headings for the issue-impact view and the "not connected" group.
const LaneNode = memo(function LaneNode({ data }) {
  return <div className="pointer-events-none select-none" style={{ width: data.width || NODE_WIDTH }}>
    <p className="text-[11px] font-extrabold uppercase tracking-[.14em] text-slate-500">{data.label}</p>
    {data.hint && <p className="mt-0.5 text-[11px] text-slate-400">{data.hint}</p>}
  </div>
})

const nodeTypes = { directory: DirectoryNode, file: FileNode, lane: LaneNode }

// Centres the view on the focused nodes (search result, selection, likely fix sites) at a readable zoom.
// Computed from the payload positions, so it does not depend on nodes having been measured yet.
function FocusController({ ids, positions, minZoom = 0.3, maxZoom = 1.1, padding = 80 }) {
  const { setViewport } = useReactFlow()
  const width = useStore(state => state.width)
  const height = useStore(state => state.height)
  const key = ids.join('|')
  useEffect(() => {
    const points = ids.map(id => positions[id]).filter(Boolean)
    if (!points.length || !width || !height) return
    const left = Math.min(...points.map(p => p.x)), top = Math.min(...points.map(p => p.y))
    const right = Math.max(...points.map(p => p.x)) + NODE_WIDTH, bottom = Math.max(...points.map(p => p.y)) + NODE_HEIGHT
    const zoom = Math.min(maxZoom, Math.max(minZoom, Math.min((width - 2 * padding) / (right - left), (height - 2 * padding) / (bottom - top))))
    setViewport({ x: width / 2 - ((left + right) / 2) * zoom, y: height / 2 - ((top + bottom) / 2) * zoom, zoom }, { duration: 450 })
  }, [key, width, height]) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}

function Toolbar({ fullscreen, setFullscreen }) {
  const { zoomIn, zoomOut, fitView } = useReactFlow()
  const button = 'grid h-8 w-8 place-items-center text-slate-600 hover:bg-slate-50 hover:text-ink'
  return <Panel position="top-right">
    <div className="flex overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm" role="toolbar" aria-label="Map controls">
      <button type="button" className={button} onClick={() => zoomIn({ duration: 200 })} title="Zoom in" aria-label="Zoom in"><Plus size={15} /></button>
      <button type="button" className={`${button} border-l border-slate-100`} onClick={() => zoomOut({ duration: 200 })} title="Zoom out" aria-label="Zoom out"><Minus size={15} /></button>
      <button type="button" className={`${button} border-l border-slate-100`} onClick={() => fitView({ padding: 0.12, duration: 300 })} title="Fit everything in view" aria-label="Fit everything in view"><Maximize size={14} /></button>
      <button type="button" className={`flex h-8 items-center gap-1.5 border-l border-slate-100 px-2.5 text-xs font-bold text-ink hover:bg-slate-50`} onClick={() => setFullscreen(!fullscreen)} title={fullscreen ? 'Exit full screen (Esc)' : 'Full screen'}>
        {fullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}<span className="hidden sm:inline">{fullscreen ? 'Exit' : 'Full screen'}</span>
      </button>
    </div>
  </Panel>
}

/**
 * Renders graph payloads ({nodes, edges} with positions). Hovering or selecting a node focuses it and its
 * direct neighbours; everything else fades. `focusIds` pans/zooms to nodes; `initialIds` sets the opening view.
 */
function FlowGraphInner({ graph, height, onNodeClick, onNodeDoubleClick, onPaneClick, selectedId, matchIds, focusIds, initialIds, showMiniMap }) {
  const [hovered, setHovered] = useState(null)
  const [fullscreen, setFullscreen] = useState(false)

  useEffect(() => {
    const handle = event => {
      if (event.key !== 'Escape') return
      if (fullscreen) setFullscreen(false)
      else onPaneClick?.()
    }
    window.addEventListener('keydown', handle)
    return () => window.removeEventListener('keydown', handle)
  }, [fullscreen, onPaneClick])

  const neighbours = useMemo(() => {
    const map = {}
    for (const edge of graph?.edges || []) {
      ;(map[edge.source] ||= new Set()).add(edge.target)
      ;(map[edge.target] ||= new Set()).add(edge.source)
    }
    return map
  }, [graph])

  const focus = hovered || selectedId
  const focusSet = useMemo(() => (focus ? new Set([focus, ...(neighbours[focus] || [])]) : null), [focus, neighbours])
  const positions = useMemo(() => Object.fromEntries((graph?.nodes || []).map(node => [node.id, node.position])), [graph])
  const maxImportance = useMemo(() => Math.max(1e-9, ...(graph?.nodes || []).map(node => node.data?.importance || 0)), [graph])

  const nodes = useMemo(() => (graph?.nodes || []).map(node => {
    const data = node.data || {}
    if (node.type === 'lane') return { id: node.id, type: 'lane', position: node.position, data, draggable: false, selectable: false, focusable: false }
    const isDirectory = node.type === 'directory'
    return {
      id: node.id,
      type: isDirectory ? 'directory' : 'file',
      position: node.position,
      draggable: false,
      data: {
        ...data,
        role: isDirectory ? 'directory' : node.type,
        color: moduleColor(data.community),
        importanceShare: (data.importance || 0) / maxImportance,
        selected: node.id === selectedId,
        match: matchIds ? matchIds.has(node.id) : false,
        dimmed: (focusSet ? !focusSet.has(node.id) : false) || (matchIds ? !matchIds.has(node.id) : false),
      },
    }
  }), [graph, focusSet, matchIds, selectedId, maxImportance])

  const edges = useMemo(() => (graph?.edges || []).map(edge => {
    const active = focus && (edge.source === focus || edge.target === focus)
    const imports = edge.data?.imports || 0
    const kind = edge.data?.type
    const soft = kind === 'external' || kind === 'history'
    const color = active ? '#10233e' : kind === 'tests' ? '#a78bfa' : soft ? '#cbd5e1' : '#94a3b8'
    return {
      id: edge.id, source: edge.source, target: edge.target,
      animated: Boolean(active),
      focusable: false,
      markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color },
      style: { strokeWidth: active ? 2.2 : imports ? Math.min(4, 1 + Math.log2(imports) * 0.6) : 1.2, stroke: color, opacity: focus ? (active ? 1 : 0.12) : soft ? 0.5 : 0.55, strokeDasharray: kind === 'tests' || soft ? '5 4' : undefined },
      label: active && imports > 1 ? `${imports} imports` : undefined,
      labelStyle: { fontSize: 10, fontWeight: 700, fill: '#10233e' },
      labelBgStyle: { fill: '#ffffff' },
      labelBgPadding: [4, 2],
      zIndex: active ? 10 : 0,
    }
  }), [graph, focus])

  const frame = fullscreen ? 'fixed inset-0 z-50 rounded-none bg-[#f7f9fc]' : 'relative rounded-2xl border border-slate-200 bg-[#fbfcfe]'
  return <div className={`overflow-hidden ${frame}`} style={{ height: fullscreen ? '100vh' : height }}>
    <ReactFlow
      nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView={!initialIds.length} fitViewOptions={{ padding: 0.12 }} minZoom={0.08} maxZoom={1.8}
      nodesConnectable={false} nodesDraggable={false} elementsSelectable={false} onlyRenderVisibleElements={nodes.length > 120}
      onNodeClick={(event, node) => node.type !== 'lane' && onNodeClick?.(event, node)}
      onNodeDoubleClick={onNodeDoubleClick} onPaneClick={onPaneClick} zoomOnDoubleClick={!onNodeDoubleClick}
      onNodeMouseEnter={(_, node) => node.type !== 'lane' && setHovered(node.id)} onNodeMouseLeave={() => setHovered(null)}
      proOptions={{ hideAttribution: true }}
    >
      <Background gap={24} size={1.1} color="#dfe6ef" />
      <Toolbar fullscreen={fullscreen} setFullscreen={setFullscreen} />
      {showMiniMap && <MiniMap pannable zoomable position="bottom-right" nodeColor={node => (node.type === 'lane' ? 'transparent' : node.data?.highlight > 0 ? '#e11d48' : node.data?.role && !['directory', 'module_file'].includes(node.data.role) ? ROLE_COLORS[node.data.role] : node.data?.color || '#94a3b8')} nodeStrokeWidth={0} maskColor="rgba(16,35,62,.06)" className="!hidden !rounded-xl !border !border-slate-200 md:!block" />}
      <FocusController ids={initialIds} positions={positions} minZoom={0.5} />
      <FocusController ids={focusIds} positions={positions} />
    </ReactFlow>
  </div>
}

export default function FlowGraph({ graph, height = 560, onNodeClick, onNodeDoubleClick, onPaneClick, selectedId = null, matchIds = null, focusIds = [], initialIds = [], showMiniMap = true }) {
  // Each graph gets its own React Flow store, so several maps can live on one page.
  return <ReactFlowProvider>
    <FlowGraphInner graph={graph} height={height} onNodeClick={onNodeClick} onNodeDoubleClick={onNodeDoubleClick} onPaneClick={onPaneClick} selectedId={selectedId} matchIds={matchIds} focusIds={focusIds} initialIds={initialIds} showMiniMap={showMiniMap} />
  </ReactFlowProvider>
}

export function Legend({ items }) {
  return <div className="mt-3 flex flex-wrap gap-4 text-xs font-bold text-slate-500">{items.map(([key, label]) => <span key={key} className="flex items-center gap-2"><i className="h-2.5 w-2.5 rounded-full" style={{ background: ROLE_COLORS[key] }} />{label}</span>)}</div>
}
