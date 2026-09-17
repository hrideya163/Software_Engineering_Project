import { request } from './api'
export const getIssues = (repositoryUrl) => request('/repositories/issues', {
  method: 'POST',
  body: JSON.stringify({ repositoryUrl }),
})
export const analyzeIssue = (repositoryUrl, issue) => request('/analyze', {
  method: 'POST',
  body: JSON.stringify({ repositoryUrl, issue }),
})
