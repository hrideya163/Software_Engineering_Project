import { request, usingMockData } from './api'; import { issues } from './mockData'
export const getIssues = (owner, repo, filters) => usingMockData ? Promise.resolve(issues) : request(`/repositories/${owner}/${repo}/issues?${new URLSearchParams(filters)}`)
export const getIssue = async (owner, repo, id) => (await getIssues(owner, repo)).find(issue => issue.id === id)
