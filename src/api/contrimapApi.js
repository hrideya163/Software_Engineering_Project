import { mlRequest } from './api'

// Every model-backed endpoint is served by the FastAPI backend (contrimap_ml/api.py).
const post = (path, body) => mlRequest(path, { method: 'POST', body: JSON.stringify(body) })
const hasProfile = profile => profile && (profile.tech_stack?.length || profile.interests?.length || profile.learning_goals?.length || profile.login)

export const getHealth = () => mlRequest('/api/health')
export const getModelCard = () => mlRequest('/api/model-card')
export const getTrending = ({ language = '', limit = 12 } = {}) => {
  const params = new URLSearchParams({ limit })
  if (language) params.set('language', language)
  return mlRequest(`/api/trending?${params}`)
}
export const getRepositoryOverview = (owner, repo) => mlRequest(`/api/repos/${owner}/${repo}`)
export const getRankedIssues = (owner, repo, { profile, mode = 'balanced', limit = 30 } = {}) => hasProfile(profile)
  ? post(`/api/repos/${owner}/${repo}/issues/ranked`, { profile, mode, limit })
  : mlRequest(`/api/repos/${owner}/${repo}/issues?limit=${limit}`)
export const getIssueAnalysis = (owner, repo, number, profile) => hasProfile(profile)
  ? post(`/api/repos/${owner}/${repo}/issues/${number}/analysis`, { profile })
  : mlRequest(`/api/repos/${owner}/${repo}/issues/${number}/analysis`)
export const analyzeDraftIssue = (owner, repo, issue, profile) => post(`/api/repos/${owner}/${repo}/analyze`, { issue, profile: hasProfile(profile) ? profile : null })
export const getArchitecture = (owner, repo) => mlRequest(`/api/repos/${owner}/${repo}/architecture`)
export const getLearningOpportunities = (owner, repo, profile) => post(`/api/repos/${owner}/${repo}/learning`, { profile })
export const getContributor = login => mlRequest(`/api/contributors/${login}`)
export const getRecommendations = (profile, repositories, mode = 'balanced') => post('/api/recommendations', { profile, repositories, mode })
