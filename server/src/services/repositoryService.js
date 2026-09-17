import { getRepoMeta, getLanguages } from '../lib/repoMeta.js'
import { getTree, inferStructure } from '../lib/repoTree.js'
import { languageColor, titleCase } from '../lib/heuristics.js'
import { cached } from '../lib/cache.js'

const TTL = 5 * 60 * 1000

export async function getRepository(owner, repo) {
  return cached(`repository:${owner}/${repo}`, TTL, async () => {
    const [meta, languages] = await Promise.all([
      getRepoMeta(owner, repo),
      getLanguages(owner, repo)
    ])

    const totalBytes = Object.values(languages).reduce((a, b) => a + b, 0) || 1
    const languageList = Object.entries(languages)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5)
      .map(([name, bytes]) => ({
        name,
        value: Math.round((bytes / totalBytes) * 100),
        color: languageColor(name)
      }))

    const { files } = await getTree(owner, repo, meta.default_branch)
    const structure = inferStructure(files)

    const technologies = [
      ...(meta.topics || []).slice(0, 4).map(titleCase),
      ...languageList.slice(0, 3).map((l) => l.name)
    ]

    return {
      owner: meta.owner.login,
      name: meta.name,
      description: meta.description || 'No description provided.',
      stars: meta.stargazers_count,
      forks: meta.forks_count,
      languages: languageList,
      technologies: [...new Set(technologies)].slice(0, 6),
      structure
    }
  })
}
