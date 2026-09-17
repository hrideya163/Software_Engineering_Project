import { request } from './api'
export const getRepository = (owner, repo) => Promise.resolve({ owner, name: repo, full_name: `${owner}/${repo}` })
