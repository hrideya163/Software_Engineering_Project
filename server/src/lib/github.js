import { getGithubToken } from './requestContext.js'

const GITHUB_API = 'https://api.github.com'

export class GitHubError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'GitHubError'
    this.status = status
  }
}

async function fetchWithTimeout(url, options, timeoutMs) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(url, { ...options, signal: controller.signal })
  } finally {
    clearTimeout(timer)
  }
}

export async function githubGet(path, { allow404 = false, timeoutMs = 10_000 } = {}) {
  const headers = {
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28'
  }
  const token = getGithubToken()
  if (token) headers.Authorization = `Bearer ${token}`

  let response
  try {
    response = await fetchWithTimeout(`${GITHUB_API}${path}`, { headers }, timeoutMs)
  } catch (err) {
    throw new GitHubError(`Could not reach GitHub API (${err.message}).`, 504)
  }

  if (response.status === 404 && allow404) return null

  if (!response.ok) {
    const rateLimited = response.status === 403 && response.headers.get('x-ratelimit-remaining') === '0'
    if (rateLimited) {
      throw new GitHubError(
        getGithubToken()
          ? 'GitHub API rate limit exceeded for this account. Try again later.'
          : 'GitHub API rate limit exceeded. Sign in with GitHub for a higher limit, or add a GITHUB_TOKEN to server/.env.',
        429
      )
    }
    const body = await response.text().catch(() => '')
    throw new GitHubError(
      `GitHub API error (${response.status}) for ${path}: ${body.slice(0, 200)}`,
      response.status
    )
  }

  return response.json()
}
