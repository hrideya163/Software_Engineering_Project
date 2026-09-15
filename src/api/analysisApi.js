import { request, usingMockData } from './api'; import { analysis, graph } from './mockData'
export const getIssueAnalysis = (o,r,id) => usingMockData ? Promise.resolve(analysis) : request(`/repositories/${o}/${r}/issues/${id}/analysis`)
export const getKnowledgeGraph = (o,r) => usingMockData ? Promise.resolve(graph) : request(`/repositories/${o}/${r}/graph`)
export const generateContributionPath = (o,r,id) => usingMockData ? Promise.resolve({ generated: true }) : request(`/repositories/${o}/${r}/issues/${id}/contribution-path`, { method: 'POST' })
