// Layered ("Sugiyama-style") layout for import graphs, without extra dependencies.
// Edges point from the importing node to the imported one, so the layout reads left to right:
// files that import others sit to the left of what they import. Import cycles share a layer.

export const NODE_WIDTH = 240
export const NODE_HEIGHT = 64
const COLUMN_GAP = 120
const ROW_GAP = 22
const SUB_COLUMN_GAP = 36

// Tarjan's strongly connected components (iterative, so deep graphs cannot overflow the stack).
function components(ids, successors) {
  let index = 0
  const order = new Map()
  const low = new Map()
  const onStack = new Set()
  const stack = []
  const component = new Map()
  let count = 0
  for (const start of ids) {
    if (order.has(start)) continue
    const work = [[start, 0]]
    order.set(start, index); low.set(start, index); index += 1
    stack.push(start); onStack.add(start)
    while (work.length) {
      const frame = work[work.length - 1]
      const [node, position] = frame
      const next = successors.get(node) || []
      if (position < next.length) {
        frame[1] += 1
        const child = next[position]
        if (!order.has(child)) {
          order.set(child, index); low.set(child, index); index += 1
          stack.push(child); onStack.add(child)
          work.push([child, 0])
        } else if (onStack.has(child)) {
          low.set(node, Math.min(low.get(node), order.get(child)))
        }
      } else {
        work.pop()
        if (work.length) {
          const parent = work[work.length - 1][0]
          low.set(parent, Math.min(low.get(parent), low.get(node)))
        }
        if (low.get(node) === order.get(node)) {
          let member
          do {
            member = stack.pop()
            onStack.delete(member)
            component.set(member, count)
          } while (member !== node)
          count += 1
        }
      }
    }
  }
  return component
}

/**
 * Positions `nodes` (objects with an `id`) for the given edges.
 * Options: maxRows - tallest column before it wraps into sub-columns; isolatedColumns - grid width for
 * nodes without any edge (placed below the layered part so they do not stretch it).
 * Returns { positions: {id: {x, y}}, layers: count, width, height }.
 */
export function layeredLayout(nodes, edges, { maxRows = 7, isolatedColumns = 4, weight = () => 0 } = {}) {
  const ids = nodes.map(node => node.id)
  const known = new Set(ids)
  const successors = new Map(ids.map(id => [id, []]))
  const connected = new Set()
  for (const edge of edges) {
    if (!known.has(edge.source) || !known.has(edge.target) || edge.source === edge.target) continue
    successors.get(edge.source).push(edge.target)
    connected.add(edge.source); connected.add(edge.target)
  }
  const linked = ids.filter(id => connected.has(id))
  const isolated = ids.filter(id => !connected.has(id))

  // Longest-path layering over the condensation (cycles collapse into one component).
  const component = components(linked, successors)
  const componentEdges = new Map()
  const indegree = new Map()
  for (const id of linked) { indegree.set(component.get(id), indegree.get(component.get(id)) || 0) }
  for (const id of linked) {
    for (const target of successors.get(id)) {
      const a = component.get(id), b = component.get(target)
      if (a === b) continue
      if (!componentEdges.has(a)) componentEdges.set(a, new Set())
      if (!componentEdges.get(a).has(b)) {
        componentEdges.get(a).add(b)
        indegree.set(b, (indegree.get(b) || 0) + 1)
      }
    }
  }
  const layerOf = new Map()
  const queue = [...indegree.keys()].filter(key => !indegree.get(key))
  queue.forEach(key => layerOf.set(key, 0))
  while (queue.length) {
    const key = queue.shift()
    for (const next of componentEdges.get(key) || []) {
      layerOf.set(next, Math.max(layerOf.get(next) || 0, layerOf.get(key) + 1))
      indegree.set(next, indegree.get(next) - 1)
      if (!indegree.get(next)) queue.push(next)
    }
  }
  const layers = []
  for (const id of linked) {
    const layer = layerOf.get(component.get(id)) || 0
    ;(layers[layer] ||= []).push(id)
  }

  // Crossing reduction: order each layer by the mean position of its neighbours (barycenter), a few sweeps.
  const neighbours = new Map(linked.map(id => [id, []]))
  for (const id of linked) for (const target of successors.get(id)) { neighbours.get(id).push(target); neighbours.get(target).push(id) }
  layers.forEach(layer => layer.sort((a, b) => weight(b) - weight(a) || a.localeCompare(b)))
  for (let sweep = 0; sweep < 4; sweep += 1) {
    const position = new Map()
    layers.forEach(layer => layer.forEach((id, row) => position.set(id, row)))
    const sequence = sweep % 2 ? [...layers.keys()].reverse() : [...layers.keys()]
    for (const index of sequence) {
      const layer = layers[index]
      if (!layer) continue
      const score = id => {
        const values = neighbours.get(id).filter(other => position.has(other)).map(other => position.get(other))
        return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : position.get(id)
      }
      const scores = new Map(layer.map(id => [id, score(id)]))
      layer.sort((a, b) => scores.get(a) - scores.get(b) || weight(b) - weight(a))
      layer.forEach((id, row) => position.set(id, row))
    }
  }

  // Coordinates: tall layers wrap into sub-columns; each layer is centred vertically on the tallest one.
  const positions = {}
  const stepY = NODE_HEIGHT + ROW_GAP
  const tallest = Math.max(1, ...layers.filter(Boolean).map(layer => Math.min(layer.length, maxRows)))
  let x = 0
  for (const layer of layers) {
    if (!layer) continue
    const columns = Math.ceil(layer.length / maxRows)
    const rows = Math.min(layer.length, maxRows)
    const offset = ((tallest - rows) * stepY) / 2
    layer.forEach((id, index) => {
      positions[id] = { x: x + Math.floor(index / maxRows) * (NODE_WIDTH + SUB_COLUMN_GAP), y: offset + (index % maxRows) * stepY }
    })
    x += columns * NODE_WIDTH + (columns - 1) * SUB_COLUMN_GAP + COLUMN_GAP
  }
  let height = tallest * stepY
  // Unconnected nodes: a compact grid underneath, most important first.
  if (isolated.length) {
    const top = linked.length ? height + 70 : 0
    const perRow = Math.max(1, Math.min(isolatedColumns, isolated.length))
    isolated.sort((a, b) => weight(b) - weight(a) || a.localeCompare(b)).forEach((id, index) => {
      positions[id] = { x: (index % perRow) * (NODE_WIDTH + SUB_COLUMN_GAP), y: top + Math.floor(index / perRow) * stepY }
    })
    height = top + Math.ceil(isolated.length / perRow) * stepY
    x = Math.max(x, perRow * (NODE_WIDTH + SUB_COLUMN_GAP))
  }
  return { positions, layers: layers.filter(Boolean).length, width: x, height, isolatedTop: linked.length && isolated.length ? (tallest * stepY) + 70 : null }
}
