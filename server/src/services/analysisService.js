import { githubGet } from '../lib/github.js'
import { cached } from '../lib/cache.js'
import { getRepoMeta } from '../lib/repoMeta.js'
import { getTree, scoreFiles, extractKeywords } from '../lib/repoTree.js'
import { titleCase } from '../lib/heuristics.js'
import { getRawIssue, mapIssue } from './issueService.js'
import { explainWithAI, explainHeuristically } from '../lib/explain.js'

const TTL = 5 * 60 * 1000
const CONFIG_FILE = /package\.json|cargo\.toml|go\.mod|pyproject\.toml|requirements\.txt|pom\.xml/i
const API_SURFACE = /\/api\/|\/public\/|\.d\.ts$/i

export async function getAnalysis(owner, repo, number) {
  return cached(`analysis:${owner}/${repo}#${number}`, TTL, async () => {
    const meta = await getRepoMeta(owner, repo)
    const rawIssue = await getRawIssue(owner, repo, number)
    const issue = mapIssue(rawIssue, meta.language)

    const { files: treeFiles } = await getTree(owner, repo, meta.default_branch)
    const keywords = extractKeywords(`${rawIssue.title} ${rawIssue.body || ''}`)
    const files = scoreFiles(treeFiles, keywords, 3)
    const modules = deriveModules(files)
    const dependency = deriveDependency(files)

    const [similarIssues, prs] = await Promise.all([
      findSimilarIssues(owner, repo, rawIssue, issue.labels),
      findRelatedPRs(owner, repo, rawIssue)
    ])

    const ai = (await explainWithAI({ issue: rawIssue, difficultyLevel: issue.difficulty, files, modules }).catch(() => null))
      || explainHeuristically({ issue: rawIssue, difficultyLevel: issue.difficulty, files, modules })

    return {
      reason: reasonFor(issue.difficulty, files),
      files,
      modules,
      dependency,
      ai,
      similarIssues,
      prs
    }
  })
}

function deriveModules(files) {
  const modules = new Set()
  for (const file of files) {
    const parts = file.split('/')
    const dir = parts.length > 1 ? parts[parts.length - 2] : parts[0]
    modules.add(titleCase(dir))
  }
  return [...modules].slice(0, 3)
}

function deriveDependency(files) {
  if (files.some((f) => CONFIG_FILE.test(f))) return 'Modifies shared dependencies — coordinate with maintainers.'
  if (files.some((f) => API_SURFACE.test(f))) return 'Touches a public API surface — verify backward compatibility.'
  return 'No public API changes.'
}

function reasonFor(level, files) {
  const scope = files.length
    ? `The change is scoped to ${files.length === 1 ? 'one identified file' : `${files.length} identified files`} (${files.join(', ')}).`
    : 'The affected files could not be determined automatically from the repository tree.'
  const tail = {
    Beginner: 'It looks approachable for a first-time contributor.',
    Intermediate: 'It requires some familiarity with the surrounding module.',
    Advanced: 'It likely touches core behaviour and deserves careful review.'
  }[level]
  return `${scope} ${tail}`
}

async function findSimilarIssues(owner, repo, rawIssue, labels) {
  const label = labels.find((l) => !/good first issue/i.test(l)) || labels[0]
  if (!label) return []
  try {
    const data = await githubGet(
      `/repos/${owner}/${repo}/issues?state=all&labels=${encodeURIComponent(label)}&per_page=6`
    )
    return data
      .filter((i) => !i.pull_request && i.number !== rawIssue.number)
      .slice(0, 3)
      .map((i) => `#${i.number}: ${i.title}`)
  } catch {
    return []
  }
}

async function findRelatedPRs(owner, repo, rawIssue) {
  try {
    const query = `repo:${owner}/${repo} type:pr ${rawIssue.number} in:body`
    const data = await githubGet(`/search/issues?q=${encodeURIComponent(query)}&per_page=5`)
    const items = (data.items || []).filter((i) => i.number !== rawIssue.number)
    if (items.length) {
      return items.slice(0, 2).map((item) => ({
        id: String(item.number),
        title: item.title,
        status: item.pull_request?.merged_at ? 'Merged' : item.state === 'closed' ? 'Closed' : 'Open',
        author: item.user?.login || 'unknown'
      }))
    }
  } catch {
    // Search API is rate-limited more aggressively; fall through to the pulls list below.
  }

  try {
    const closed = await githubGet(
      `/repos/${owner}/${repo}/pulls?state=closed&per_page=10&sort=updated&direction=desc`
    )
    return closed
      .filter((pr) => pr.merged_at)
      .slice(0, 2)
      .map((pr) => ({ id: String(pr.number), title: pr.title, status: 'Merged', author: pr.user?.login || 'unknown' }))
  } catch {
    return []
  }
}
