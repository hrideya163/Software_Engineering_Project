const STOP_WORDS = new Set(['the', 'and', 'for', 'with', 'this', 'that', 'from', 'into', 'issue', 'add', 'use', 'should', 'would', 'could', 'make'])

export function tokenize(value = '') {
  return String(value)
    .toLowerCase()
    .replace(/[`"'()[\]{}.,:;!?/\\#]/g, ' ')
    .split(/\s+/)
    .map(token => token.trim())
    .filter(token => token.length > 2 && !STOP_WORDS.has(token))
}

export function termSet(value) {
  return new Set(tokenize(value))
}

export function overlapScore(left, right) {
  const a = left instanceof Set ? left : termSet(left)
  const b = right instanceof Set ? right : termSet(right)
  if (!a.size || !b.size) return 0
  let shared = 0
  a.forEach(token => { if (b.has(token)) shared += 1 })
  return shared / Math.max(a.size, b.size)
}

export function cosineSimilarity(left, right) {
  const a = left instanceof Map ? left : termFrequency(left)
  const b = right instanceof Map ? right : termFrequency(right)
  const vocabulary = new Set([...a.keys(), ...b.keys()])
  let dot = 0
  let leftNorm = 0
  let rightNorm = 0
  vocabulary.forEach(token => {
    const av = a.get(token) || 0
    const bv = b.get(token) || 0
    dot += av * bv
    leftNorm += av * av
    rightNorm += bv * bv
  })
  return leftNorm && rightNorm ? dot / (Math.sqrt(leftNorm) * Math.sqrt(rightNorm)) : 0
}

export function termFrequency(value) {
  const counts = new Map()
  tokenize(value).forEach(token => counts.set(token, (counts.get(token) || 0) + 1))
  return counts
}

export function clamp(value, min = 0, max = 1) {
  return Math.min(max, Math.max(min, value))
}

export function slug(value) {
  return String(value).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
}
