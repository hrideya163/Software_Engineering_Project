import { useCallback, useEffect, useState } from 'react'
import { getPreparationStatus, prepareRepository } from '../api/contrimapApi'

// Starts the backend's background snapshot + graph build for a repository and polls its progress.
// Pages render their content only once the repository is ready, so their own requests hit a warm cache.
export function useRepositoryPreparation(owner, repo) {
  const [state, setState] = useState({ status: null, ready: false, error: '' })
  const [attempt, setAttempt] = useState(0)
  const retry = useCallback(() => setAttempt(value => value + 1), [])

  useEffect(() => {
    let active = true
    let timer = null
    const apply = status => {
      if (!active) return
      if (status.state === 'error') return setState({ status, ready: false, error: status.error || status.message || 'Preparation failed.' })
      setState({ status, ready: status.state === 'ready', error: '' })
      // Poll quickly at first, then back off for very large repositories.
      if (status.state !== 'ready') timer = setTimeout(poll, (status.elapsed_seconds || 0) > 30 ? 2000 : 700)
    }
    const fail = error => active && setState({ status: null, ready: false, error: error.message })
    const poll = () => getPreparationStatus(owner, repo).then(apply).catch(fail)
    setState({ status: null, ready: false, error: '' })
    prepareRepository(owner, repo).then(apply).catch(fail)
    return () => { active = false; clearTimeout(timer) }
  }, [owner, repo, attempt])

  return { ...state, retry }
}
