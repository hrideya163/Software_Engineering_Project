import { request, usingMockData } from './api'

const BASE_URL = import.meta.env.VITE_API_URL

export const getCurrentUser = () =>
  usingMockData ? Promise.resolve({ user: null, configured: false, providers: { github: false, google: false } }) : request('/auth/me')

export const loginWithGitHub = () => {
  window.location.href = `${BASE_URL}/auth/github`
}

export const loginWithGoogle = () => {
  window.location.href = `${BASE_URL}/auth/google`
}

export const logout = () =>
  usingMockData ? Promise.resolve({ ok: true }) : request('/auth/logout', { method: 'POST' })
