import { Background, Controls, MarkerType, ReactFlow } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useMemo } from 'react'

const ROLE_COLORS = { target: '#e11d48', importer: '#2d7ef7', dependency: '#0eaa7d', test: '#7c3aed', directory: '#10233e' }

// Renders backend graph payloads (codegraph.issue_view / architecture_view) with @xyflow/react.
export default function FlowGraph({ graph, height = 520, onNodeClick }) {
  const nodes = useMemo(() => (graph?.nodes || []).map(node => {
    const data = node.data || {}
    const highlight = data.highlight || 0
    const isDirectory = node.type === 'directory'
    const background = isDirectory ? (highlight > 0 ? '#e11d48' : ROLE_COLORS.directory) : ROLE_COLORS[node.type] || '#64748b'
    const size = isDirectory ? Math.min(1.6, 0.85 + Math.sqrt(data.files || 1) / 12) : 1
    return {
      id: node.id,
      position: node.position,
      data: { label: isDirectory ? `${data.label} · ${data.files}` : `${data.rank ? `#${data.rank} ` : ''}${data.label}` },
      title: data.path || data.label,
      style: {
        background, color: '#fff', border: highlight > 0 ? '3px solid #fecdd3' : '0', borderRadius: 12,
        padding: `${8 * size}px ${12 * size}px`, fontWeight: 700, fontSize: 12 * Math.min(size, 1.2), maxWidth: 260,
        opacity: isDirectory && graph.nodes.some(n => (n.data?.highlight || 0) > 0) && highlight === 0 ? 0.55 : 1,
      },
    }
  }), [graph])
  const edges = useMemo(() => (graph?.edges || []).map(edge => ({
    id: edge.id, source: edge.source, target: edge.target,
    markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
    style: { strokeWidth: edge.data?.imports ? Math.min(6, 1 + Math.log2(edge.data.imports)) : 1.4, stroke: edge.data?.type === 'tests' ? '#7c3aed' : '#94a3b8' },
    label: edge.data?.imports > 2 ? String(edge.data.imports) : undefined,
  })), [graph])
  return <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white" style={{ height }}>
    <ReactFlow nodes={nodes} edges={edges} fitView minZoom={0.1} onNodeClick={onNodeClick} nodesConnectable={false}><Background gap={20} /><Controls /></ReactFlow>
  </div>
}

export function Legend({ items }) {
  return <div className="mt-3 flex flex-wrap gap-4 text-xs font-bold text-slate-500">{items.map(([key, label]) => <span key={key} className="flex items-center gap-2"><i className="h-2.5 w-2.5 rounded-full" style={{ background: ROLE_COLORS[key] }} />{label}</span>)}</div>
}
