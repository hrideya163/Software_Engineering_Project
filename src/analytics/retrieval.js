import { cosineSimilarity, overlapScore, termSet } from './text.js'

function searchable(value) {
  return `${value.title || ''} ${value.body || ''} ${value.summary || ''} ${(value.labels || []).join(' ')} ${(value.files || []).join(' ')}`
}

export function retrieveSimilar(query, candidates = [], limit = 5) {
  const queryTerms = termSet(searchable(query))
  return candidates
    .filter(candidate => candidate.id !== query.id)
    .map(candidate => ({
      ...candidate,
      similarity: Math.round((0.65 * cosineSimilarity(searchable(query), searchable(candidate)) + 0.35 * overlapScore(queryTerms, termSet(searchable(candidate)))) * 100),
    }))
    .filter(candidate => candidate.similarity > 0)
    .sort((a, b) => b.similarity - a.similarity)
    .slice(0, limit)
}
