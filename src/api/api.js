const BASE_URL = import.meta.env.VITE_API_URL
export async function request(path, options = {}) { const response = await fetch(`${BASE_URL}${path}`, options); if (!response.ok) throw new Error('Unable to reach the ContriMap API.'); return response.json() }
export const usingMockData = !BASE_URL
