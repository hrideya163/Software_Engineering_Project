import { mlRequest } from './api'
// These two endpoints are served by the Python ML service (contrimap_ml/inference_api.py,
// VITE_ML_API_URL), not the Express API — hence mlRequest and the /api prefix.
export const getIssues = (repositoryUrl) => mlRequest('/api/repositories/issues', {
  method: 'POST',
  body: JSON.stringify({ repositoryUrl }),
})
export const analyzeIssue = (repositoryUrl, issue) => mlRequest('/api/analyze', {
  method: 'POST',
  body: JSON.stringify({ repositoryUrl, issue }),
})
