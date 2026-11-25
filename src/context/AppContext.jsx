import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { getSession, signOut as requestSignOut } from '../api/authApi'
import { feedbackUser, getStoredProfile, storeProfile } from '../api/contrimapApi'

const PROFILE_KEY = 'contrimap.profile.v1'
export const EMPTY_PROFILE = { level: 'intermediate', tech_stack: [], interests: [], learning_goals: [], time_budget_hours: null, login: null }

function readProfile() {
  try {
    const stored = JSON.parse(window.localStorage.getItem(PROFILE_KEY) || 'null')
    return stored ? { ...EMPTY_PROFILE, ...stored } : EMPTY_PROFILE
  } catch {
    return EMPTY_PROFILE
  }
}

const LOGIN_NOTICES = {
  success: ['success', 'You are signed in.'],
  failed: ['error', 'Sign-in did not complete. Please try again.'],
  cancelled: ['info', 'Sign-in was cancelled.'],
}

const AppContext = createContext(null)

// One place for the signed-in account and the contributor profile, so every page sees the same state.
export function AppProvider({ children }) {
  const [auth, setAuth] = useState({ status: 'loading', user: null, providers: { github: false, google: false }, configured: false })
  const [profile, setProfile] = useState(readProfile)
  const [notice, setNotice] = useState(null)

  const saveProfile = useCallback((next, { sync = true } = {}) => {
    setProfile(next)
    try { window.localStorage.setItem(PROFILE_KEY, JSON.stringify(next)) } catch { /* storage unavailable: keep in memory */ }
    // Also kept on the server (Supabase), so a signed-in user finds it in another browser. Best effort.
    // An empty profile is only sent when the user clears it on purpose (sync: 'force'), so filling in just the
    // GitHub username after sign-in never overwrites a profile saved from another browser.
    const user = feedbackUser(next)
    const content = next.tech_stack.length || next.interests.length || next.learning_goals.length
    if (user && ((sync && content) || sync === 'force')) storeProfile(user, next).catch(() => {})
  }, [])

  // An empty profile in this browser is filled from the server copy for the same user (e.g. after signing in elsewhere).
  const hasContent = profile.tech_stack.length || profile.interests.length || profile.learning_goals.length
  useEffect(() => {
    const user = feedbackUser(profile)
    if (hasContent || !user) return
    let active = true
    getStoredProfile(user).then(({ profile: stored }) => {
      if (active && stored && (stored.tech_stack?.length || stored.interests?.length || stored.learning_goals?.length)) {
        const { updated_at: _ignored, history: _history, ...fields } = stored
        saveProfile({ ...EMPTY_PROFILE, ...fields, login: profile.login || fields.login || null }, { sync: false })
      }
    }).catch(() => {})
    return () => { active = false }
  }, [profile.login, hasContent]) // eslint-disable-line react-hooks/exhaustive-deps

  const refreshSession = useCallback(() => getSession()
    .then(({ user, providers, configured }) => setAuth({ status: user ? 'signed-in' : 'signed-out', user, providers: providers || {}, configured: Boolean(configured) }))
    .catch(() => setAuth(previous => ({ ...previous, status: 'unavailable' }))), [])

  useEffect(() => {
    refreshSession()
    // The backend redirects back with ?login=success|failed|cancelled; show it once and clean the URL.
    const params = new URLSearchParams(window.location.search)
    const result = params.get('login')
    if (result) {
      if (LOGIN_NOTICES[result]) setNotice(LOGIN_NOTICES[result])
      params.delete('login')
      const query = params.toString()
      window.history.replaceState({}, '', `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`)
    }
  }, [refreshSession])

  // Profiles edited in another tab stay in sync.
  useEffect(() => {
    const sync = event => event.key === PROFILE_KEY && setProfile(readProfile())
    window.addEventListener('storage', sync)
    return () => window.removeEventListener('storage', sync)
  }, [])

  // A GitHub sign-in fills in the profile's GitHub username when it is empty.
  useEffect(() => {
    const github = auth.user?.github
    if (github && !profile.login) saveProfile({ ...profile, login: github })
  }, [auth.user, profile, saveProfile])

  const signOut = useCallback(() => requestSignOut()
    .catch(() => null)
    .then(() => {
      setAuth(previous => ({ ...previous, status: 'signed-out', user: null }))
      setNotice(['info', 'You are signed out. Your profile stays saved in this browser.'])
    }), [])

  const value = useMemo(() => ({ auth, refreshSession, signOut, profile, saveProfile, notice, setNotice }), [auth, refreshSession, signOut, profile, saveProfile, notice])
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export const useApp = () => useContext(AppContext)
