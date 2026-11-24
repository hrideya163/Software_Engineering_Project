// The FastAPI backend (contrimap_ml/api.py) serves analysis, recommendations and sign-in.
// Production builds without VITE_ML_API_URL assume the API is served from the same origin (Docker image).
export const API_BASE_URL = import.meta.env.VITE_ML_API_URL || (import.meta.env.DEV ? 'http://localhost:8001' : window.location.origin)

export async function mlRequest(path, options = {}) {
  let response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      credentials: 'include',
      ...options,
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    })
  } catch {
    // fetch only rejects on network failures: the server is down, starting up or blocked by CORS.
    throw new Error(`Can't reach the ContriMap server at ${API_BASE_URL}. It may still be starting - try again in a few seconds.`)
  }
  if (!response.ok) {
    let detail = `The server answered with an error (${response.status}).`
    try {
      const body = await response.json()
      detail = typeof body.detail === 'string' ? body.detail : Array.isArray(body.detail) ? body.detail.map(item => item.msg).join('; ') : body.error || detail
    } catch { /* not JSON */ }
    const error = new Error(detail)
    error.status = response.status
    throw error
  }
  return response.json()
}
