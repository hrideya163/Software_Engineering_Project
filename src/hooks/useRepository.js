import { useEffect } from 'react'
import { getRepository } from '../api/repositoryApi'
import { getIssues } from '../api/issueApi'
import { useApp } from '../context/AppContext'

export function useRepository(owner, repo) {
  const app = useApp()
  const repositoryUrl = `https://github.com/${owner}/${repo}`
  useEffect(() => {
    let active = true
    app.setLoading(true)
    app.setError('')
    Promise.all([getRepository(owner, repo), getIssues(repositoryUrl)])
      .then(([repository, issues]) => {
        if (active) {
          app.setCurrentRepository(repository)
          app.setIssues(issues)
        }
      })
      .catch(error => active && app.setError(error.message))
      .finally(() => active && app.setLoading(false))
    return () => { active = false }
  }, [owner, repo])
  return { ...app, repositoryUrl }
}
