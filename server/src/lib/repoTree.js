import { githubGet } from './github.js'
import { cached } from './cache.js'

const TTL = 10 * 60 * 1000
const MAX_FILES = 6000

const STOPWORDS = new Set([
  'the', 'and', 'for', 'with', 'that', 'this', 'from', 'into', 'when', 'have',
  'has', 'are', 'was', 'were', 'will', 'should', 'could', 'their', 'there',
  'about', 'issue', 'please', 'error', 'bug', 'like', 'also', 'they', 'them'
])

export async function getTree(owner, repo, branch) {
  return cached(`tree:${owner}/${repo}@${branch}`, TTL, async () => {
    const data = await githubGet(
      `/repos/${owner}/${repo}/git/trees/${encodeURIComponent(branch)}?recursive=1`
    )
    const files = (data.tree || []).filter((item) => item.type === 'blob').slice(0, MAX_FILES)
    return { files, truncated: Boolean(data.truncated) }
  })
}

export function inferStructure(files) {
  const counts = new Map()
  for (const file of files) {
    const parts = file.path.split('/')
    const key = parts.length > 1 ? parts.slice(0, Math.min(2, parts.length - 1)).join('/') : parts[0]
    counts.set(key, (counts.get(key) || 0) + 1)
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)
    .map(([path]) => path)
}

export function extractKeywords(text) {
  const words = (text || '').toLowerCase().match(/[a-z][a-z0-9]{2,}/g) || []
  return [...new Set(words)].filter((w) => !STOPWORDS.has(w)).slice(0, 8)
}

export function scoreFiles(files, keywords, limit = 3) {
  if (!keywords.length) return files.slice(0, limit).map((f) => f.path)

  const scored = files
    .map((file) => {
      const lower = file.path.toLowerCase()
      const basename = lower.split('/').pop()
      const score = keywords.reduce((sum, word) => {
        if (basename.includes(word)) return sum + 2
        if (lower.includes(word)) return sum + 1
        return sum
      }, 0)
      return { path: file.path, score }
    })
    .filter((f) => f.score > 0)

  scored.sort((a, b) => b.score - a.score || a.path.length - b.path.length)
  if (scored.length) return scored.slice(0, limit).map((f) => f.path)
  return files.slice(0, limit).map((f) => f.path)
}
