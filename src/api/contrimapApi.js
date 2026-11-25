import { mlRequest } from './api'

// Every model-backed endpoint is served by the FastAPI backend (contrimap_ml/api.py).
const post = (path, body) => mlRequest(path, { method: 'POST', body: JSON.stringify(body) })
const hasProfile = profile => profile && (profile.tech_stack?.length || profile.interests?.length || profile.learning_goals?.length || profile.login)

// Read requests are shared: identical calls made while one is in flight (several components mounting at once)
// or within `ttl` seconds (moving between pages) reuse the same response instead of asking the server again.
const shared = new Map()
function reuse(key, ttl, run) {
  const now = Date.now()
  const hit = shared.get(key)
  if (hit && hit.expires > now) return hit.promise
  const promise = run().catch(error => { shared.delete(key); throw error })
  shared.set(key, { promise, expires: now + ttl * 1000 })
  if (shared.size > 300) shared.delete(shared.keys().next().value)
  return promise
}
const cachedGet = (path, ttl = 60) => reuse(`GET ${path}`, ttl, () => mlRequest(path))
const cachedPost = (path, body, ttl = 60) => reuse(`POST ${path} ${JSON.stringify(body)}`, ttl, () => post(path, body))
// Feedback changes rankings, saved lists and analyses: drop what it affects.
const forget = test => { for (const key of [...shared.keys()]) if (test(key)) shared.delete(key) }

export const getHealth = () => mlRequest('/api/health')
export const getTrending = ({ language = '', limit = 12 } = {}) => {
  const params = new URLSearchParams({ limit })
  if (language) params.set('language', language)
  return cachedGet(`/api/trending?${params}`, 600)
}
export const prepareRepository = (owner, repo) => mlRequest(`/api/repos/${owner}/${repo}/prepare`, { method: 'POST' })
export const getPreparationStatus = (owner, repo) => mlRequest(`/api/repos/${owner}/${repo}/status`)
export const getRepositoryOverview = (owner, repo) => cachedGet(`/api/repos/${owner}/${repo}`, 120)
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
export const getRankedIssues = (owner, repo, { profile, mode = 'balanced', limit = 30, user = feedbackUser(profile), fresh = false } = {}) => (fresh ? forget(key => key.includes(`/api/repos/${owner}/${repo}/issues`)) : null, hasProfile(profile))
  ? cachedPost(`/api/repos/${owner}/${repo}/issues/ranked`, { profile, mode, limit, user }, 30)
  : cachedGet(`/api/repos/${owner}/${repo}/issues?limit=${limit}${user ? `&user=${encodeURIComponent(user)}` : ''}`, 30)
export const sendFeedback = (user, repository, item, action) => post('/api/feedback', {
  user, repository, number: item.number, action, title: item.title || '', text: [item.title || '', item.body || item.summary || ''].join('\n').slice(0, 4000),
}).then(result => {
  if (action !== 'opened') forget(key => key.includes('/issues') || key.includes('/recommendations') || key.includes('/feedback/'))
  return result
})
export const getFeedback = user => cachedGet(`/api/feedback/${encodeURIComponent(user)}`, 10)
export const getActivity = (owner, repo) => cachedGet(`/api/repos/${owner}/${repo}/activity`, 300)
export const getSimilarHistory = (owner, repo, number) => cachedGet(`/api/repos/${owner}/${repo}/issues/${number}/similar`, 600)
export const getModuleGraph = (owner, repo, directory, { tests = false, issue = null } = {}) => {
  const params = new URLSearchParams({ directory, tests })
  if (issue) params.set('issue', issue)
  return cachedGet(`/api/repos/${owner}/${repo}/module?${params}`, 300)
}
export const getFileDetails = (owner, repo, path) => cachedGet(`/api/repos/${owner}/${repo}/file?path=${encodeURIComponent(path)}`, 300)
// Just the issue (title, labels): lets the page show its header before the analysis is ready.
export const getIssueDetails = (owner, repo, number) => cachedGet(`/api/repos/${owner}/${repo}/issues/${number}`, 300)
export const getIssueAnalysis = (owner, repo, number, profile) => hasProfile(profile)
  ? cachedPost(`/api/repos/${owner}/${repo}/issues/${number}/analysis`, { profile }, 300)
  : cachedGet(`/api/repos/${owner}/${repo}/issues/${number}/analysis`, 300)
// Claude writes an explanation only here, when the user asks for it; the server stores the result.
export const generateExplanation = (owner, repo, number, profile) => post(`/api/repos/${owner}/${repo}/issues/${number}/explanation`, { profile: hasProfile(profile) ? profile : null, generate: true })
  .then(result => { forget(key => key.includes(`/issues/${number}/analysis`)); return result })
export const analyzeDraftIssue = (owner, repo, issue, profile) => post(`/api/repos/${owner}/${repo}/analyze`, { issue, profile: hasProfile(profile) ? profile : null })
export const getArchitecture = (owner, repo) => cachedGet(`/api/repos/${owner}/${repo}/architecture`, 300)
export const getLearningOpportunities = (owner, repo, profile) => post(`/api/repos/${owner}/${repo}/learning`, { profile })
export const getContributor = login => cachedGet(`/api/contributors/${login}`, 600)
export const getRecommendations = (profile, repositories, mode = 'balanced') => cachedPost('/api/recommendations', { profile, repositories, mode, user: feedbackUser(profile) }, 30)
export const getStoredProfile = user => mlRequest(`/api/profiles/${encodeURIComponent(user)}`)
export const storeProfile = (user, profile) => post(`/api/profiles/${encodeURIComponent(user)}`, { profile })
