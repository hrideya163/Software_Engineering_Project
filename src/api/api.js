const BASE_URL = import.meta.env.VITE_API_URL
// The FastAPI backend (contrimap_ml/api.py). Defaults to the local dev server.
// Production builds without VITE_ML_API_URL assume the API is served from the same origin (Docker image).
const ML_BASE_URL = import.meta.env.VITE_ML_API_URL || (import.meta.env.DEV ? 'http://localhost:8001' : window.location.origin)

async function send(baseUrl, path, options = {}) {
  let response
  try {
    response = await fetch(`${baseUrl}${path}`, {
      credentials: 'include',
      ...options,
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    })
  } catch {
    // fetch only rejects on network failures: the server is down, starting up or blocked by CORS.
    throw new Error(`Can't reach the ContriMap server at ${baseUrl}. It may still be starting - try again in a few seconds.`)
  }
  if (!response.ok) {
    let detail = 'Unable to reach the ContriMap API.'
    try { const body = await response.json(); detail = body.detail || body.error || detail } catch {}
    throw new Error(detail)
  }
  return response.json()
}

export async function request(path, options = {}) {
  if (!BASE_URL) throw new Error('VITE_API_URL is not configured.')
  return send(BASE_URL, path, options)
}

export async function mlRequest(path, options = {}) {
  if (!ML_BASE_URL) throw new Error('VITE_ML_API_URL is not configured.')
  return send(ML_BASE_URL, path, options)
}

export const usingMockData = !BASE_URL
export const usingMockModel = !ML_BASE_URL
