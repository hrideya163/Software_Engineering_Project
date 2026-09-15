import { request, usingMockData } from './api'; import { repository } from './mockData'
export const getRepository = (owner, repo) => usingMockData ? Promise.resolve({ ...repository, owner, name: repo }) : request(`/repositories/${owner}/${repo}`)
