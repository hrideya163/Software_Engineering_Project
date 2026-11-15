import { Background, Controls, Handle, MarkerType, MiniMap, Panel, Position, ReactFlow, useReactFlow, useStore } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Maximize2, Minimize2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

// Shared palette (same hues as the repository dashboard charts).
export const MODULE_COLORS = ['#2d7ef7', '#0eaa7d', '#f59e0b', '#7c3aed', '#06b6d4', '#ec4899', '#64748b', '#ef4444']
export const ROLE_COLORS = { target: '#e11d48', importer: '#2d7ef7', dependency: '#0eaa7d', test: '#7c3aed', directory: '#10233e' }
const ROLE_LABELS = { target: 'Likely change', importer: 'Imports it', dependency: 'Imported by it', test: 'Test' }

export const moduleColor = community => (community === null || community === undefined ? '#94a3b8' : MODULE_COLORS[Number(community) % MODULE_COLORS.length])

const hidden = { opacity: 0, width: 6, height: 6, border: 0, background: 'transparent' }

function DirectoryNode({ data }) {
  const ring = data.selected ? 'ring-2 ring-ink' : data.highlight ? 'ring-2 ring-rose-300' : data.match ? 'ring-2 ring-mint' : ''
  return <div className={`relative w-[220px] rounded-xl border bg-white shadow-sm transition-all duration-200 hover:shadow-md ${data.highlight ? 'border-rose-400' : 'border-slate-200'} ${ring}`} style={{ opacity: data.dimmed ? 0.28 : 1 }}>
    <Handle type="target" position={Position.Left} style={hidden} />
    <div className="flex items-stretch">
      <span className="w-1.5 shrink-0 rounded-l-xl" style={{ background: data.color }} />
      <div className="min-w-0 flex-1 px-3 py-2">
        <p className="mono truncate text-[12px] font-medium text-ink" title={data.label}>{data.label}</p>
        <p className="mt-0.5 text-[10px] font-semibold text-slate-500">{data.files} files{data.language ? ` · ${data.language}` : ''}</p>
        <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-slate-100" title={`Share of import-graph importance: ${Math.round(data.importanceShare * 100)}%`}>
          <div className="h-full rounded-full" style={{ width: `${Math.max(4, data.importanceShare * 100)}%`, background: data.color }} />
        </div>
      </div>
    </div>
    {data.highlight > 0 && <span className="absolute -top-2 right-2 rounded-full bg-rose-500 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-white">likely fix</span>}
    <Handle type="source" position={Position.Right} style={hidden} />
  </div>
}

function FileNode({ data }) {
  const color = ROLE_COLORS[data.role] || '#64748b'
  const ring = data.selected ? 'ring-2 ring-ink' : data.role === 'target' ? 'ring-2 ring-rose-200' : ''
  return <div className={`relative w-[230px] rounded-xl border border-slate-200 bg-white shadow-sm transition-all duration-200 hover:shadow-md ${ring}`} style={{ opacity: data.dimmed ? 0.28 : 1 }}>
    <Handle type="target" position={Position.Left} style={hidden} />
    <div className="flex items-stretch">
      <span className="w-1.5 shrink-0 rounded-l-xl" style={{ background: color }} />
      <div className="min-w-0 flex-1 px-3 py-2">
        <div className="flex items-center gap-1.5">
          {data.rank && <span className="rounded bg-rose-100 px-1 text-[10px] font-bold text-rose-700">#{data.rank}</span>}
          <p className="mono truncate text-[12px] font-medium text-ink" title={data.path}>{data.label}</p>
        </div>
        <p className="mono mt-0.5 truncate text-[10px] text-slate-400" title={data.path}>{data.path}</p>
        <p className="mt-1 text-[10px] font-bold uppercase tracking-wide" style={{ color }}>{ROLE_LABELS[data.role] || data.role}</p>
      </div>
    </div>
    <Handle type="source" position={Position.Right} style={hidden} />
  </div>
}

const nodeTypes = { directory: DirectoryNode, file: FileNode }

// Centres the view on the focused nodes (search result, selection, likely fix sites) at a readable zoom.
// Computed from the payload positions, so it does not depend on nodes having been measured yet.
const NODE_SIZE = { width: 230, height: 70 }

function FocusController({ ids, positions, minZoom = 0.3, maxZoom = 1.1, padding = 80 }) {
  const { setViewport } = useReactFlow()
  const width = useStore(state => state.width)
  const height = useStore(state => state.height)
  const key = ids.join('|')
  useEffect(() => {
    const points = ids.map(id => positions[id]).filter(Boolean)
    if (!points.length || !width || !height) return
    const left = Math.min(...points.map(p => p.x)), top = Math.min(...points.map(p => p.y))
    const right = Math.max(...points.map(p => p.x)) + NODE_SIZE.width, bottom = Math.max(...points.map(p => p.y)) + NODE_SIZE.height
    const zoom = Math.min(maxZoom, Math.max(minZoom, Math.min((width - 2 * padding) / (right - left), (height - 2 * padding) / (bottom - top))))
    setViewport({ x: width / 2 - ((left + right) / 2) * zoom, y: height / 2 - ((top + bottom) / 2) * zoom, zoom }, { duration: 450 })
  }, [key, width, height]) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}

/**
 * Renders backend graph payloads (codegraph.architecture_view / issue_view).
 * Hovering or selecting a node focuses it and its direct neighbours; everything else fades.
 */
export default function FlowGraph({ graph, height = 520, onNodeClick, onPaneClick, selectedId = null, matchIds = null, focusIds = [], showMiniMap = true }) {
  const [hovered, setHovered] = useState(null)
  const [fullscreen, setFullscreen] = useState(false)

  useEffect(() => {
    if (!fullscreen) return
    const close = event => event.key === 'Escape' && setFullscreen(false)
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [fullscreen])

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
    const isDirectory = node.type === 'directory'
    const dimmedByFocus = focusSet ? !focusSet.has(node.id) : false
    const dimmedBySearch = matchIds ? !matchIds.has(node.id) : false
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
        dimmed: dimmedByFocus || dimmedBySearch,
      },
    }
  }), [graph, focusSet, matchIds, selectedId, maxImportance])

  const edges = useMemo(() => (graph?.edges || []).map(edge => {
    const active = focus && (edge.source === focus || edge.target === focus)
    const imports = edge.data?.imports || 0
    const isTest = edge.data?.type === 'tests'
    const color = active ? '#10233e' : isTest ? '#a78bfa' : '#cbd5e1'
    return {
      id: edge.id, source: edge.source, target: edge.target,
      animated: Boolean(active),
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color },
      style: { strokeWidth: imports ? Math.min(6, 1.2 + Math.log2(imports)) : 1.5, stroke: color, opacity: focus && !active ? 0.25 : 1, strokeDasharray: isTest ? '5 4' : undefined },
      label: active && imports > 1 ? `${imports} imports` : undefined,
      labelStyle: { fontSize: 10, fontWeight: 700, fill: '#10233e' },
      labelBgStyle: { fill: '#ffffff' },
      zIndex: active ? 10 : 0,
    }
  }), [graph, focus])

  // Large graphs open on their most relevant part at a readable zoom (likely fix sites, else the most
  // central nodes); "fit view" in the controls and the minimap still give the whole picture.
  const initialIds = useMemo(() => {
    const all = graph?.nodes || []
    if (all.length <= 12) return []
    // Strongest likely fix sites (weak ones far away would zoom the view out to unreadable).
    const best = Math.max(0, ...all.map(node => node.data?.highlight || 0))
    const highlighted = all.filter(node => (best > 0 && (node.data?.highlight || 0) >= 0.5 * best) || node.type === 'target').map(node => node.id)
    if (highlighted.length) return highlighted
    // The core: nodes carrying a meaningful share of the import-graph importance (at most 6).
    const top = Math.max(...all.map(node => node.data?.importance || 0))
    return [...all].filter(node => (node.data?.importance || 0) >= 0.15 * top).sort((a, b) => (b.data?.importance || 0) - (a.data?.importance || 0)).slice(0, 6).map(node => node.id)
  }, [graph])

  const frame = fullscreen ? 'fixed inset-0 z-50 rounded-none bg-[#f7f9fc]' : 'relative rounded-2xl border border-slate-200 bg-[#fbfcfe]'
  return <div className={`overflow-hidden ${frame}`} style={{ height: fullscreen ? '100vh' : height }}>
    <ReactFlow
      nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView={!initialIds.length} fitViewOptions={{ padding: 0.15 }} minZoom={0.1} maxZoom={2}
      nodesConnectable={false} nodesDraggable={false} elementsSelectable
      onNodeClick={onNodeClick} onPaneClick={onPaneClick}
      onNodeMouseEnter={(_, node) => setHovered(node.id)} onNodeMouseLeave={() => setHovered(null)}
      proOptions={{ hideAttribution: true }}
    >
      <Background gap={22} size={1.2} color="#dbe3ee" />
      <Controls showInteractive={false} position="bottom-left" />
      {showMiniMap && <MiniMap pannable zoomable position="bottom-right" nodeColor={node => (node.data?.highlight > 0 ? '#e11d48' : node.data?.role && node.data.role !== 'directory' ? ROLE_COLORS[node.data.role] : node.data?.color || '#94a3b8')} nodeStrokeWidth={0} maskColor="rgba(16,35,62,.06)" className="!rounded-xl !border !border-slate-200" />}
      <Panel position="top-right">
        <button type="button" onClick={() => setFullscreen(!fullscreen)} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-bold text-ink shadow-sm hover:bg-slate-50" title={fullscreen ? 'Exit full screen (Esc)' : 'Full screen'}>
          {fullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}{fullscreen ? 'Exit' : 'Full screen'}
        </button>
      </Panel>
      <FocusController ids={initialIds} positions={positions} minZoom={0.55} />
      <FocusController ids={focusIds} positions={positions} />
    </ReactFlow>
  </div>
}

export function Legend({ items }) {
  return <div className="mt-3 flex flex-wrap gap-4 text-xs font-bold text-slate-500">{items.map(([key, label]) => <span key={key} className="flex items-center gap-2"><i className="h-2.5 w-2.5 rounded-full" style={{ background: ROLE_COLORS[key] }} />{label}</span>)}</div>
}
