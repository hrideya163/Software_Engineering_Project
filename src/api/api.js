const BASE_URL = import.meta.env.VITE_API_URL
export async function request(path, options = {}) {
  const response = await fetch(`${BASE_URL}${path}`, { credentials: 'include', ...options })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.error || 'Unable to reach the ContriMap API.')
  }
  return response.json()
}
export const usingMockData = !BASE_URL
