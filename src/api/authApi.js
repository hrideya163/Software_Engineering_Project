import { API_BASE_URL, mlRequest } from './api'

// Sign-in is handled by the FastAPI backend (contrimap_ml/auth.py) with a signed, HTTP-only session cookie.
export const getSession = () => mlRequest('/api/auth/me')

// Full-page redirect to the provider; `next` is the in-app path to return to afterwards.
export const signIn = (provider, next = '/') => {
  window.location.href = `${API_BASE_URL}/api/auth/${provider}?next=${encodeURIComponent(next)}`
}

export const signOut = () => mlRequest('/api/auth/logout', { method: 'POST' })
