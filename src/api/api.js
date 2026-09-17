const BASE_URL = import.meta.env.VITE_API_URL
export async function request(path, options = {}) {
  if (!BASE_URL) throw new Error('VITE_API_URL is not configured.')
  const response = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  })
  if (!response.ok) {
    let detail = 'Unable to reach the ContriMap API.'
    try { detail = (await response.json()).detail || detail } catch {}
    throw new Error(detail)
  }
  return response.json()
}
export const usingMockData = !BASE_URL
