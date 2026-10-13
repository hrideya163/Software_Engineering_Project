import { request, usingMockData } from './api'
import { repository as mockRepository, trending as mockTrending, topIssues as mockTopIssues } from './mockData'

export const getRepository = (owner, repo) => Promise.resolve({ owner, name: repo, full_name: `${owner}/${repo}` })

// Full repository details (stars, forks, languages, technologies) from the ContriMap API.
export const getRepositoryDetails = (owner, repo) => usingMockData
  ? Promise.resolve({ ...mockRepository, owner, name: repo })
  : request(`/repositories/${owner}/${repo}`)

// Trending = recently pushed to, ranked by stars (see server/src/services/trendingService.js).
export const getTrendingRepositories = ({ language, limit = 12 } = {}) => {
  if (usingMockData) return Promise.resolve(mockTrending.slice(0, limit))
  const params = new URLSearchParams({ limit })
  if (language) params.set('language', language)
  return request(`/repositories/trending?${params}`)
}

// Top issues = { mostCommented: [...], newest: [...] }.
export const getTopIssues = (owner, repo, limit = 6) => usingMockData
  ? Promise.resolve(mockTopIssues)
  : request(`/repositories/${owner}/${repo}/top-issues?limit=${limit}`)
