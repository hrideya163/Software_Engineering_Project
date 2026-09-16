import { request, usingMockData } from './api'; import { analysis, graph } from './mockData'
export const predictIssue = (issue) => usingMockData
  ? Promise.resolve({
      model_version: 'mock',
      difficulty: ({ Beginner: 'Easy', Intermediate: 'Medium', Advanced: 'Hard' })[issue.difficulty] || issue.difficulty || 'Medium',
      difficulty_probability: 0.5,
      effort_hours: Number.parseFloat(issue.effort) || 0,
      files: [],
    })
  : request('/predict', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: issue.title, body: issue.body || issue.summary || '', labels: issue.labels || [], top_k: 10 }),
    })
export const getIssueAnalysis = (o,r,id) => usingMockData ? Promise.resolve(analysis) : request(`/repositories/${o}/${r}/issues/${id}/analysis`)
export const getKnowledgeGraph = (o,r) => usingMockData ? Promise.resolve(graph) : request(`/repositories/${o}/${r}/graph`)
export const generateContributionPath = (o,r,id) => usingMockData ? Promise.resolve({ generated: true }) : request(`/repositories/${o}/${r}/issues/${id}/contribution-path`, { method: 'POST' })
