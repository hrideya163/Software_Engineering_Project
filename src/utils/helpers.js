// Accepts "owner/name", "github.com/owner/name", full URLs and git remotes.
export function parseRepository(value) {
  const text = (value || '').trim()
  const url = text.match(/(?:github\.com[/:])([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+?)(?:\.git)?(?:[/#?].*)?$/i)
  if (url) return { owner: url[1], repo: url[2] }
  const short = text.match(/^([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+?)(?:\.git)?$/)
  return short ? { owner: short[1], repo: short[2] } : null
}

// Kept for older imports.
export const parseGitHubUrl = parseRepository
