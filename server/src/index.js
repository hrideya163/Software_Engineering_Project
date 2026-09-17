try {
  process.loadEnvFile()
} catch {
  // No .env file present — fall back to whatever is already in the environment.
}

import express from 'express'
import cors from 'cors'
import cookieParser from 'cookie-parser'
import repositoriesRouter from './routes/repositories.js'
import authRouter, { COOKIE_NAME } from './routes/auth.js'
import { GitHubError } from './lib/github.js'
import { requestContext } from './lib/requestContext.js'
import { getSession } from './lib/sessionStore.js'

const app = express()

app.use(cors({ origin: process.env.CORS_ORIGIN || true, credentials: true }))
app.use(express.json())
app.use(cookieParser())

app.use((req, res, next) => {
  const session = getSession(req.cookies[COOKIE_NAME])
  requestContext.run({ githubToken: session?.accessToken, user: session?.user }, next)
})

app.get('/api/health', (req, res) => res.json({ ok: true }))
app.use('/api/auth', authRouter)
app.use('/api/repositories', repositoriesRouter)

app.use((req, res) => res.status(404).json({ error: 'Not found' }))

app.use((err, req, res, next) => {
  console.error(err)
  const status = err instanceof GitHubError ? (err.status === 404 ? 404 : err.status === 429 ? 429 : 502) : 500
  res.status(status).json({ error: err.message || 'Internal server error' })
})

const port = process.env.PORT || 8000
app.listen(port, () => console.log(`ContriMap API listening on http://localhost:${port}/api`))
