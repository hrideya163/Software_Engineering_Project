import { useEffect, useState } from 'react'
import { EMPTY_PROFILE, useApp } from '../context/AppContext'

export { EMPTY_PROFILE }

export const isProfileSet = profile => Boolean(profile.tech_stack.length || profile.interests.length || profile.learning_goals.length || profile.login)

// The contributor profile lives in this browser only (shared through AppContext); it is sent with ranking requests.
export function useProfile() {
  const { profile, saveProfile } = useApp()
  return { profile, save: saveProfile, isSet: isProfileSet(profile) }
}

export function useAsync(factory, deps) {
  const [state, setState] = useState({ data: null, loading: true, error: '' })
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true
    setState(previous => ({ ...previous, loading: true, error: '' }))
    factory()
      .then(data => active && setState({ data, loading: false, error: '' }))
      .catch(error => active && setState({ data: null, loading: false, error: error.message }))
    return () => { active = false }
  }, [...deps, attempt]) // eslint-disable-line react-hooks/exhaustive-deps
  return { ...state, retry: () => setAttempt(value => value + 1) }
}
