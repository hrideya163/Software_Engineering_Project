import { githubGet } from './github.js'
import { cached } from './cache.js'

const TTL = 10 * 60 * 1000

export function getRepoMeta(owner, repo) {
  return cached(`meta:${owner}/${repo}`, TTL, () => githubGet(`/repos/${owner}/${repo}`))
}

export function getLanguages(owner, repo) {
  return cached(`langs:${owner}/${repo}`, TTL, () => githubGet(`/repos/${owner}/${repo}/languages`))
}
