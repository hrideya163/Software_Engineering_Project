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

function mapTopIssue(issue) {
  return {
    number: issue.number,
    title: issue.title,
    body: (issue.body || '').slice(0, 4000),
    comments: issue.comments,
    labels: issue.labels.map((l) => (typeof l === 'string' ? l : l.name)),
    created_at: issue.created_at,
    updated_at: issue.updated_at,
    html_url: issue.html_url,
    author: issue.user?.login || null
  }
}

// "Top issues" are defined two ways for now: most commented, and newest.
export async function listTopIssues(owner, repo, { limit = 6 } = {}) {
  return cached(`top-issues:${owner}/${repo}:${limit}`, TTL, async () => {
    const base = `/repos/${owner}/${repo}/issues?state=open&per_page=50&direction=desc`
    const [byComments, byCreated] = await Promise.all([
      githubGet(`${base}&sort=comments`),
      githubGet(`${base}&sort=created`)
    ])
    // The issues endpoint also returns pull requests; drop them.
    const pick = (raw) => raw.filter((i) => !i.pull_request).slice(0, limit).map(mapTopIssue)
    return { mostCommented: pick(byComments), newest: pick(byCreated) }
  })
}
