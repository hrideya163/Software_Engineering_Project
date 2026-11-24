// Turns backend graph payloads into laid-out views for FlowGraph.
import { NODE_HEIGHT, NODE_WIDTH, layeredLayout } from './graphLayout'

const LANE_OFFSET = 64
const COLUMN = NODE_WIDTH + 130
const ROW = NODE_HEIGHT + 22
const SOURCE_FILE = /\.(py|pyi|js|jsx|ts|tsx|mjs|cjs|vue|svelte|go|rs|java|kt|scala|rb|php|c|h|cc|cpp|hpp|cs|swift)$/i

const lane = (id, label, x, y, hint) => ({ id: `lane:${id}`, type: 'lane', position: { x, y }, data: { label, hint } })

/** Directory map or one directory's files: layered left to right, outside directories in side columns. */
export function layeredView(graph) {
  if (!graph?.nodes?.length) return graph
  const inside = graph.nodes.filter(node => node.type !== 'external')
  const outside = graph.nodes.filter(node => node.type === 'external')
  const importEdges = (graph.edges || []).filter(edge => edge.data?.type !== 'external')
  const importance = Object.fromEntries(inside.map(node => [node.id, node.data?.importance || 0]))
  const layout = layeredLayout(inside, importEdges, { weight: id => importance[id] || 0 })
  const nodes = inside.map(node => ({ ...node, position: layout.positions[node.id] }))
  const extras = []
  if (layout.isolatedTop !== null && layout.isolatedTop !== undefined) {
    extras.push(lane('isolated', 'Not linked by imports', 0, layout.isolatedTop - 40, 'No resolved imports to or from the other boxes'))
  }
  // Outside directories (module view): importers on the left, dependencies on the right, no misleading anchor arrows.
  const incoming = outside.filter(node => node.data?.direction === 'in').sort((a, b) => (b.data?.imports || 0) - (a.data?.imports || 0))
  const outgoing = outside.filter(node => node.data?.direction !== 'in').sort((a, b) => (b.data?.imports || 0) - (a.data?.imports || 0))
  const placeSide = (list, x, id, label, hint) => {
    if (!list.length) return
    extras.push(lane(id, label, x, -LANE_OFFSET, hint))
    list.forEach((node, row) => nodes.push({ ...node, position: { x, y: row * ROW } }))
  }
  placeSide(incoming, -COLUMN, 'in', 'Used by', 'Other directories importing these files')
  placeSide(outgoing, layout.width + 20, 'out', 'Depends on', 'Other directories these files import')
  return { ...graph, nodes: [...nodes, ...extras], edges: importEdges, layers: layout.layers }
}

/**
 * Issue impact: who imports the likely changes, the changes themselves (with their tests), what they import,
 * and files that similar past fixes changed. `historicalFiles` are /similar votes ({path, from}).
 */
export function impactView(base, historicalFiles = []) {
  if (!base?.nodes?.length) return null
  const historical = new Map(historicalFiles.filter(item => SOURCE_FILE.test(item.path)).map(item => [item.path, item]))
  const byRole = { importer: [], target: [], test: [], dependency: [] }
  for (const node of base.nodes) (byRole[node.type] ||= []).push(node)
  byRole.target.sort((a, b) => (a.data?.rank || 99) - (b.data?.rank || 99))
  for (const role of ['importer', 'dependency', 'test']) byRole[role].sort((a, b) => (b.data?.importance || 0) - (a.data?.importance || 0))
  const extra = [...historical.values()].filter(item => !base.nodes.some(node => node.id === item.path)).slice(0, 6)

  const nodes = []
  const place = (list, column, startRow = 0) => list.forEach((node, row) => nodes.push({ ...node, position: { x: column * COLUMN, y: (startRow + row) * ROW }, data: { ...node.data, historical: historical.has(node.id) } }))
  const columns = []
  if (byRole.importer.length) columns.push(['importer', 'Import the change', 'Callers that may need updating'])
  columns.push(['target', 'Likely to change', 'Ranked by the localization model'])
  if (byRole.dependency.length) columns.push(['dependency', 'Used by the change', 'Files the likely changes import'])
  if (extra.length) columns.push(['historical', 'Changed by similar fixes', 'From merged PRs of similar issues'])
  const lanes = []
  columns.forEach(([role, label, hint], column) => {
    lanes.push(lane(role, label, column * COLUMN, -LANE_OFFSET, hint))
    if (role === 'historical') {
      extra.forEach((item, row) => nodes.push({ id: item.path, type: 'historical', position: { x: column * COLUMN, y: row * ROW }, data: { label: item.path.split('/').pop(), path: item.path, role: 'historical', historical: true } }))
    } else place(byRole[role], column)
  })
  // Tests sit under the likely changes they cover.
  if (byRole.test.length) {
    const column = columns.findIndex(([role]) => role === 'target')
    const startRow = byRole.target.length + 1
    lanes.push(lane('test', 'Tests to run', column * COLUMN, startRow * ROW - 46))
    place(byRole.test, column, startRow)
  }
  return { ...base, nodes: [...nodes, ...lanes] }
}

/** Opening view for larger graphs: strongest likely-fix sites, else the most central nodes (never more than six). */
export function initialFocus(graph, fitUpTo = 30) {
  const all = (graph?.nodes || []).filter(node => node.type !== 'lane')
  if (all.length <= fitUpTo) return []  // small maps open fully fitted
  const best = Math.max(0, ...all.map(node => node.data?.highlight || 0))
  const highlighted = all.filter(node => (best > 0 && (node.data?.highlight || 0) >= 0.5 * best) || node.type === 'target').map(node => node.id)
  if (highlighted.length) return highlighted.slice(0, 6)
  const top = Math.max(...all.map(node => node.data?.importance || 0))
  if (!top) return []
  return [...all].filter(node => (node.data?.importance || 0) >= 0.15 * top).sort((a, b) => (b.data?.importance || 0) - (a.data?.importance || 0)).slice(0, 6).map(node => node.id)
}
