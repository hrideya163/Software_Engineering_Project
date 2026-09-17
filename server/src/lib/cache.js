const store = new Map()

export async function cached(key, ttlMs, fn) {
  const hit = store.get(key)
  if (hit && Date.now() < hit.expires) return hit.value
  const value = await fn()
  store.set(key, { value, expires: Date.now() + ttlMs })
  return value
}
