import { useEffect, useState } from 'react'
import { getRepositoryDetails, getTopIssues } from '../api/repositoryApi'

// Loads what the repository page needs: repo details and top issues.
// Uses allSettled so a failure in one does not hide the other.
export function useRepositoryOverview(owner, repo) {
  const [state, setState] = useState({ details: null, topIssues: null, loading: true, errors: [] })
  useEffect(() => {
    let active = true
    setState({ details: null, topIssues: null, loading: true, errors: [] })
    Promise.allSettled([getRepositoryDetails(owner, repo), getTopIssues(owner, repo)]).then(([details, topIssues]) => {
      if (!active) return
      setState({
        details: details.status === 'fulfilled' ? details.value : null,
        topIssues: topIssues.status === 'fulfilled' ? topIssues.value : null,
        loading: false,
        errors: [details, topIssues].filter(r => r.status === 'rejected').map(r => r.reason.message),
      })
    })
    return () => { active = false }
  }, [owner, repo])
  return state
}
