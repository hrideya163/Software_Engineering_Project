import { Router } from 'express'
import { getRepository } from '../services/repositoryService.js'
import { listIssues } from '../services/issueService.js'
import { getAnalysis } from '../services/analysisService.js'
import { getGraph } from '../services/graphService.js'

const router = Router()

router.get('/:owner/:repo', async (req, res, next) => {
  try {
    res.json(await getRepository(req.params.owner, req.params.repo))
  } catch (err) {
    next(err)
  }
})

router.get('/:owner/:repo/issues', async (req, res, next) => {
  try {
    res.json(await listIssues(req.params.owner, req.params.repo))
  } catch (err) {
    next(err)
  }
})

router.get('/:owner/:repo/issues/:id/analysis', async (req, res, next) => {
  try {
    res.json(await getAnalysis(req.params.owner, req.params.repo, req.params.id))
  } catch (err) {
    next(err)
  }
})

router.post('/:owner/:repo/issues/:id/contribution-path', (req, res) => {
  res.json({ generated: true })
})

router.get('/:owner/:repo/graph', async (req, res, next) => {
  try {
    res.json(await getGraph(req.params.owner, req.params.repo))
  } catch (err) {
    next(err)
  }
})

export default router
