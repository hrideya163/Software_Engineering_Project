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
export const prepareRepository = (owner, repo) => mlRequest(`/api/repos/${owner}/${repo}/prepare`, { method: 'POST' })
export const getPreparationStatus = (owner, repo) => mlRequest(`/api/repos/${owner}/${repo}/status`)
export const getRepositoryOverview = (owner, repo) => mlRequest(`/api/repos/${owner}/${repo}`)
// Feedback (saved / dismissed / completed issues) is keyed by the GitHub login when set, else by a random id kept in this browser.
export function feedbackUser(profile) {
  if (profile?.login && /^[A-Za-z0-9_.-]{1,64}$/.test(profile.login)) return profile.login
  try {
    let id = window.localStorage.getItem('contrimap.user')
    if (!id) {
      id = `browser-${Math.random().toString(36).slice(2, 12)}`
      window.localStorage.setItem('contrimap.user', id)
    }
    return id
  } catch {
    return null
  }
}
export const getRankedIssues = (owner, repo, { profile, mode = 'balanced', limit = 30, user = feedbackUser(profile) } = {}) => hasProfile(profile)
  ? post(`/api/repos/${owner}/${repo}/issues/ranked`, { profile, mode, limit, user })
  : mlRequest(`/api/repos/${owner}/${repo}/issues?limit=${limit}${user ? `&user=${encodeURIComponent(user)}` : ''}`)
export const sendFeedback = (user, repository, item, action) => post('/api/feedback', {
  user, repository, number: item.number, action, title: item.title || '', text: [item.title || '', item.body || item.summary || ''].join('\n').slice(0, 4000),
})
export const getFeedback = user => mlRequest(`/api/feedback/${encodeURIComponent(user)}`)
export const getActivity = (owner, repo) => mlRequest(`/api/repos/${owner}/${repo}/activity`)
export const getSimilarHistory = (owner, repo, number) => mlRequest(`/api/repos/${owner}/${repo}/issues/${number}/similar`)
export const getModuleGraph = (owner, repo, directory, { tests = false, issue = null } = {}) => {
  const params = new URLSearchParams({ directory, tests })
  if (issue) params.set('issue', issue)
  return mlRequest(`/api/repos/${owner}/${repo}/module?${params}`)
}
export const getFileDetails = (owner, repo, path) => mlRequest(`/api/repos/${owner}/${repo}/file?path=${encodeURIComponent(path)}`)
export const getIssueAnalysis = (owner, repo, number, profile) => hasProfile(profile)
  ? post(`/api/repos/${owner}/${repo}/issues/${number}/analysis`, { profile })
  : mlRequest(`/api/repos/${owner}/${repo}/issues/${number}/analysis`)
export const analyzeDraftIssue = (owner, repo, issue, profile) => post(`/api/repos/${owner}/${repo}/analyze`, { issue, profile: hasProfile(profile) ? profile : null })
export const getArchitecture = (owner, repo) => mlRequest(`/api/repos/${owner}/${repo}/architecture`)
export const getLearningOpportunities = (owner, repo, profile) => post(`/api/repos/${owner}/${repo}/learning`, { profile })
export const getContributor = login => mlRequest(`/api/contributors/${login}`)
export const getRecommendations = (profile, repositories, mode = 'balanced') => post('/api/recommendations', { profile, repositories, mode, user: feedbackUser(profile) })
