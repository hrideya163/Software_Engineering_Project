# ContriMap API

An Express backend that serves the ContriMap frontend with real data pulled
from the GitHub REST API, plus heuristic scoring (difficulty, skill match,
effort, impact) layered on top since there's no real user skill profile or
ML model behind this.

## Setup

```bash
npm install
cp .env.example .env
npm run dev
```

Listens on `http://localhost:8000/api` by default (`PORT` in `.env`).

### GitHub rate limits

Unauthenticated requests to the GitHub API are capped at 60/hour **per IP**,
shared by everyone on that network — it's easy to exhaust in a shared or
sandboxed environment. Add a token to raise it to 5000/hour:

1. Create a token at https://github.com/settings/tokens (classic token, no
   scopes needed — this only reads public repositories).
2. Set `GITHUB_TOKEN=...` in `server/.env`.
3. Restart the server (`.env` is only read at startup).

If you see `"GitHub API rate limit exceeded"` responses, this is why.

### Optional: "Sign in with GitHub"

Not required — the app works fully without it, either unauthenticated
(60/hour, shared) or with the `GITHUB_TOKEN` above (5000/hour, shared by
every request the server makes). Signing in additionally lets each
logged-in user's own GitHub rate limit apply to their own requests.

1. Create an OAuth App at https://github.com/settings/developers → "New
   OAuth App". Homepage URL: `http://localhost:5173`. Authorization
   callback URL: `http://localhost:8000/api/auth/github/callback`.
2. Copy the Client ID, generate a Client Secret, and set
   `GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET` in `.env`.
3. Restart the server. A "Sign in with GitHub" button appears in the
   frontend's navbar automatically once these are set — the app hides it
   entirely when they're not configured, so there's no dead button to
   confuse anyone using mock data or the plain `GITHUB_TOKEN` setup.

No OAuth scopes are requested — a session token can read public data at
the higher rate limit, nothing more. Sessions are kept in memory (a
`contrimap_session` cookie), so they reset whenever the server restarts.

### Optional: real AI-generated explanations

The issue analysis endpoint's `ai` field is a templated heuristic by default.
Set `ANTHROPIC_API_KEY` in `.env` to have it call the Claude API instead
(model configurable via `ANTHROPIC_MODEL`, defaults to a fast Haiku model).
If the call fails or the key is unset, it silently falls back to the
template — this is optional polish, not required for the app to work.

## Endpoints

Repository routes are mounted under `/api/repositories`; auth routes under
`/api/auth`.

| Method | Path | Description |
|---|---|---|
| GET | `/repositories/:owner/:repo` | Repository summary: description, stars, forks, language breakdown, inferred structure |
| GET | `/repositories/:owner/:repo/issues` | Open issues, scored with difficulty/match/effort/impact/skills |
| GET | `/repositories/:owner/:repo/issues/:id/analysis` | Deep-dive on one issue: likely affected files (matched against the real repo tree), modules, dependency impact, an explanation, similar issues, and related PRs |
| GET | `/repositories/:owner/:repo/graph` | A knowledge graph connecting the top open issues to likely files, the repo's primary language, and recently merged PRs |
| POST | `/repositories/:owner/:repo/issues/:id/contribution-path` | Acknowledges contribution-path generation |
| GET | `/auth/me` | Current session's user, and whether OAuth is configured at all |
| GET | `/auth/github` | Redirects to GitHub's OAuth consent screen |
| GET | `/auth/github/callback` | OAuth redirect target; creates a session and redirects back to the frontend |
| POST | `/auth/logout` | Clears the current session |

## How the heuristics work

There's no real user skill profile in this app yet, so "match %" and
"skills" are derived from the issue itself rather than a comparison against
a contributor:

- **Difficulty**: labels first (`good first issue` → Beginner, etc.), then
  falls back to issue body length + comment count.
- **Match / effort**: deterministic per issue (hashed from the issue
  number), not random on every request.
- **Skills**: keyword-matched from labels (accessibility, docs, testing,
  performance, security, ...) plus the repo's primary language.
- **Affected files**: the issue title/body is tokenized into keywords and
  scored against every file path in the repo's real git tree (via the
  GitHub Trees API) — no code-search API involved, so it isn't subject to
  the tighter search rate limit.
- **Similar issues / related PRs**: fetched from GitHub directly (shared
  labels for issues; search API with a closed-PRs fallback for PRs).

This is intentionally transparent heuristics, not a trained model — it's
there so the app works end-to-end with real repositories instead of static
mock data.
