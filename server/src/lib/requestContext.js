import { AsyncLocalStorage } from 'node:async_hooks'

export const requestContext = new AsyncLocalStorage()

export function getGithubToken() {
  const store = requestContext.getStore()
  return store?.githubToken || process.env.GITHUB_TOKEN || null
}
