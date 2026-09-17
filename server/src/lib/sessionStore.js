import { randomUUID } from 'node:crypto'

const TTL = 12 * 60 * 60 * 1000
const sessions = new Map()

export function createSession({ accessToken, user }) {
  const id = randomUUID()
  sessions.set(id, { accessToken, user, expires: Date.now() + TTL })
  return id
}

export function getSession(id) {
  if (!id) return null
  const session = sessions.get(id)
  if (!session) return null
  if (Date.now() > session.expires) {
    sessions.delete(id)
    return null
  }
  return session
}

export function destroySession(id) {
  sessions.delete(id)
}
