import { Router } from 'express'
import { randomUUID } from 'node:crypto'
import { createSession, destroySession, getSession } from '../lib/sessionStore.js'

const router = Router()
const COOKIE_NAME = 'contrimap_session'
const STATE_COOKIE = 'contrimap_oauth_state'

function isGitHubConfigured() {
  return Boolean(process.env.GITHUB_OAUTH_CLIENT_ID && process.env.GITHUB_OAUTH_CLIENT_SECRET)
}

function isGoogleConfigured() {
  return Boolean(process.env.GOOGLE_OAUTH_CLIENT_ID && process.env.GOOGLE_OAUTH_CLIENT_SECRET)
}

function frontendUrl(path = '') {
  const base = process.env.FRONTEND_URL || 'http://localhost:5173/ContriMap-website/'
  return `${base.replace(/\/$/, '')}${path}`
}

function cookieOptions(maxAgeMs) {
  return {
    httpOnly: true,
    // 'none' is required when the frontend and backend are on different sites
    // (e.g. Vercel + EC2) — browsers refuse SameSite=None without Secure, so
    // that combination only works once the backend is served over HTTPS.
    sameSite: process.env.SESSION_COOKIE_SAMESITE || 'lax',
    secure: process.env.SESSION_COOKIE_SECURE === 'true',
    maxAge: maxAgeMs
  }
}

router.get('/me', (req, res) => {
  const providers = { github: isGitHubConfigured(), google: isGoogleConfigured() }
  if (!providers.github && !providers.google) return res.json({ user: null, configured: false, providers })
  const session = getSession(req.cookies[COOKIE_NAME])
  res.json({ user: session?.user || null, configured: true, providers })
})

router.get('/github', (req, res) => {
  if (!isGitHubConfigured()) {
    return res.status(501).json({ error: 'GitHub sign-in is not configured on this server.' })
  }
  const state = randomUUID()
  res.cookie(STATE_COOKIE, state, cookieOptions(10 * 60 * 1000))

  const params = new URLSearchParams({
    client_id: process.env.GITHUB_OAUTH_CLIENT_ID,
    redirect_uri: process.env.GITHUB_OAUTH_REDIRECT_URI || 'http://localhost:8000/api/auth/github/callback',
    state
  })
  res.redirect(`https://github.com/login/oauth/authorize?${params}`)
})

router.get('/github/callback', async (req, res) => {
  if (!isGitHubConfigured()) {
    return res.status(501).json({ error: 'GitHub sign-in is not configured on this server.' })
  }

  const { code, state } = req.query
  const expectedState = req.cookies[STATE_COOKIE]
  res.clearCookie(STATE_COOKIE)

  if (!code || !state || state !== expectedState) {
    return res.redirect(frontendUrl('?login=failed'))
  }

  try {
    const tokenResponse = await fetch('https://github.com/login/oauth/access_token', {
      method: 'POST',
      headers: { 'content-type': 'application/json', accept: 'application/json' },
      body: JSON.stringify({
        client_id: process.env.GITHUB_OAUTH_CLIENT_ID,
        client_secret: process.env.GITHUB_OAUTH_CLIENT_SECRET,
        code,
        redirect_uri: process.env.GITHUB_OAUTH_REDIRECT_URI || 'http://localhost:8000/api/auth/github/callback'
      })
    })
    const tokenData = await tokenResponse.json()
    if (!tokenData.access_token) throw new Error(tokenData.error_description || 'No access token returned')

    const userResponse = await fetch('https://api.github.com/user', {
      headers: {
        Authorization: `Bearer ${tokenData.access_token}`,
        Accept: 'application/vnd.github+json'
      }
    })
    if (!userResponse.ok) throw new Error('Could not fetch GitHub profile')
    const profile = await userResponse.json()

    const sessionId = createSession({
      accessToken: tokenData.access_token,
      user: { provider: 'github', login: profile.login, name: profile.name, avatarUrl: profile.avatar_url }
    })
    res.cookie(COOKIE_NAME, sessionId, cookieOptions(12 * 60 * 60 * 1000))
    res.redirect(frontendUrl('?login=success'))
  } catch (err) {
    console.error('GitHub OAuth callback failed:', err.message)
    res.redirect(frontendUrl('?login=failed'))
  }
})

router.get('/google', (req, res) => {
  if (!isGoogleConfigured()) {
    return res.status(501).json({ error: 'Google sign-in is not configured on this server.' })
  }
  const state = randomUUID()
  res.cookie(STATE_COOKIE, state, cookieOptions(10 * 60 * 1000))

  const params = new URLSearchParams({
    client_id: process.env.GOOGLE_OAUTH_CLIENT_ID,
    redirect_uri: process.env.GOOGLE_OAUTH_REDIRECT_URI || 'http://localhost:8000/api/auth/google/callback',
    response_type: 'code',
    scope: 'openid email profile',
    access_type: 'online',
    prompt: 'select_account',
    state
  })
  res.redirect(`https://accounts.google.com/o/oauth2/v2/auth?${params}`)
})

router.get('/google/callback', async (req, res) => {
  if (!isGoogleConfigured()) {
    return res.status(501).json({ error: 'Google sign-in is not configured on this server.' })
  }

  const { code, state } = req.query
  const expectedState = req.cookies[STATE_COOKIE]
  res.clearCookie(STATE_COOKIE)

  if (!code || !state || state !== expectedState) {
    return res.redirect(frontendUrl('?login=failed'))
  }

  try {
    const tokenResponse = await fetch('https://oauth2.googleapis.com/token', {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        client_id: process.env.GOOGLE_OAUTH_CLIENT_ID,
        client_secret: process.env.GOOGLE_OAUTH_CLIENT_SECRET,
        code,
        redirect_uri: process.env.GOOGLE_OAUTH_REDIRECT_URI || 'http://localhost:8000/api/auth/google/callback',
        grant_type: 'authorization_code'
      })
    })
    const tokenData = await tokenResponse.json()
    if (!tokenData.access_token) throw new Error(tokenData.error_description || 'No access token returned')

    const userResponse = await fetch('https://www.googleapis.com/oauth2/v3/userinfo', {
      headers: { Authorization: `Bearer ${tokenData.access_token}` }
    })
    if (!userResponse.ok) throw new Error('Could not fetch Google profile')
    const profile = await userResponse.json()

    const sessionId = createSession({
      accessToken: tokenData.access_token,
      user: { provider: 'google', login: profile.email, name: profile.name, avatarUrl: profile.picture }
    })
    res.cookie(COOKIE_NAME, sessionId, cookieOptions(12 * 60 * 60 * 1000))
    res.redirect(frontendUrl('?login=success'))
  } catch (err) {
    console.error('Google OAuth callback failed:', err.message)
    res.redirect(frontendUrl('?login=failed'))
  }
})

router.post('/logout', (req, res) => {
  destroySession(req.cookies[COOKIE_NAME])
  res.clearCookie(COOKIE_NAME)
  res.json({ ok: true })
})

export default router
export { COOKIE_NAME }
