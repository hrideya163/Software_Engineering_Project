import { githubGet } from '../lib/github.js'
import { cached } from '../lib/cache.js'
import { difficulty, matchScore, effort, impact, skills, summarize } from '../lib/heuristics.js'
import { getRepoMeta } from '../lib/repoMeta.js'

const TTL = 3 * 60 * 1000

export function mapIssue(issue, repoLanguage) {
  const labels = issue.labels.map((l) => (typeof l === 'string' ? l : l.name))
  const level = difficulty(issue, labels)
  return {
    id: String(issue.number),
    title: issue.title,
    labels,
    difficulty: level,
    match: matchScore(issue, level),
    effort: effort(issue, level),
    impact: impact(issue, labels),
    skills: skills(issue, labels, repoLanguage),
    summary: summarize(issue)
  }
}

export async function listIssues(owner, repo, { state = 'open', perPage = 30 } = {}) {
  return cached(`issues:${owner}/${repo}:${state}`, TTL, async () => {
    const [raw, meta] = await Promise.all([
      githubGet(`/repos/${owner}/${repo}/issues?state=${state}&per_page=${perPage}&sort=updated&direction=desc`),
      getRepoMeta(owner, repo)
    ])
    return raw.filter((i) => !i.pull_request).map((i) => mapIssue(i, meta.language))
  })
}

export async function getRawIssue(owner, repo, number) {
  return cached(`issue:${owner}/${repo}#${number}`, TTL, () =>
    githubGet(`/repos/${owner}/${repo}/issues/${number}`)
  )
}
