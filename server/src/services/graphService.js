import { githubGet } from '../lib/github.js'
import { cached } from '../lib/cache.js'
import { getRepoMeta } from '../lib/repoMeta.js'
import { getTree, scoreFiles, extractKeywords } from '../lib/repoTree.js'
import { listIssues } from './issueService.js'

const TTL = 5 * 60 * 1000

export async function getGraph(owner, repo) {
  return cached(`graph:${owner}/${repo}`, TTL, async () => {
    const meta = await getRepoMeta(owner, repo)
    const [{ files }, issues, prs] = await Promise.all([
      getTree(owner, repo, meta.default_branch),
      listIssues(owner, repo).then((list) => list.slice(0, 3)),
      topMergedPRs(owner, repo)
    ])

    const nodes = []
    const edges = []
    const fileNodeIds = new Map()
    let edgeCount = 0

    issues.forEach((issue, i) => {
      const issueNodeId = `issue-${issue.id}`
      nodes.push({
        id: issueNodeId,
        type: 'issue',
        position: { x: 20, y: 60 + i * 160 },
        data: { label: `Issue #${issue.id}` }
      })

      const keywords = extractKeywords(`${issue.title} ${issue.summary}`)
      const picked = scoreFiles(files, keywords, 2)
      picked.forEach((path) => {
        if (!fileNodeIds.has(path)) {
          const index = fileNodeIds.size
          const fileNodeId = `file-${index}`
          fileNodeIds.set(path, fileNodeId)
          nodes.push({
            id: fileNodeId,
            type: 'file',
            position: { x: 280, y: 40 + index * 130 },
            data: { label: path.split('/').pop() }
          })
        }
        edges.push({ id: `e${edgeCount++}`, source: issueNodeId, target: fileNodeIds.get(path) })
      })
    })

    const techNodeId = 'tech'
    nodes.push({
      id: techNodeId,
      type: 'tech',
      position: { x: 540, y: 140 },
      data: { label: meta.language || 'Core' }
    })
    for (const fileNodeId of fileNodeIds.values()) {
      edges.push({ id: `e${edgeCount++}`, source: fileNodeId, target: techNodeId })
    }

    prs.slice(0, 2).forEach((pr, i) => {
      const prNodeId = `pr-${pr.id}`
      nodes.push({
        id: prNodeId,
        type: 'pr',
        position: { x: 780, y: 80 + i * 140 },
        data: { label: `PR #${pr.id}` }
      })
      edges.push({ id: `e${edgeCount++}`, source: techNodeId, target: prNodeId })
    })

    return { nodes, edges }
  })
}

async function topMergedPRs(owner, repo) {
  try {
    const closed = await githubGet(
      `/repos/${owner}/${repo}/pulls?state=closed&per_page=10&sort=updated&direction=desc`
    )
    return closed.filter((pr) => pr.merged_at).map((pr) => ({ id: String(pr.number), title: pr.title }))
  } catch {
    return []
  }
}
