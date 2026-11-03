import { useCallback, useEffect, useState } from 'react'

const KEY = 'contrimap.profile.v1'
export const EMPTY_PROFILE = { level: 'intermediate', tech_stack: [], interests: [], learning_goals: [], time_budget_hours: null, login: null }

function read() {
  try {
    const stored = JSON.parse(window.localStorage.getItem(KEY) || 'null')
    return stored ? { ...EMPTY_PROFILE, ...stored } : EMPTY_PROFILE
  } catch {
    return EMPTY_PROFILE
  }
}

// The contributor profile lives in this browser only; it is sent with ranking requests.
export function useProfile() {
  const [profile, setProfile] = useState(read)
  useEffect(() => {
    const sync = event => event.key === KEY && setProfile(read())
    window.addEventListener('storage', sync)
    return () => window.removeEventListener('storage', sync)
  }, [])
  const save = useCallback(next => {
    setProfile(next)
    try { window.localStorage.setItem(KEY, JSON.stringify(next)) } catch { /* storage unavailable: keep in memory */ }
  }, [])
  const isSet = Boolean(profile.tech_stack.length || profile.interests.length || profile.learning_goals.length || profile.login)
  return { profile, save, isSet }
}

export function useAsync(factory, deps) {
  const [state, setState] = useState({ data: null, loading: true, error: '' })
  useEffect(() => {
    let active = true
    setState(previous => ({ ...previous, loading: true, error: '' }))
    factory()
      .then(data => active && setState({ data, loading: false, error: '' }))
      .catch(error => active && setState({ data: null, loading: false, error: error.message }))
    return () => { active = false }
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps
  return state
}
