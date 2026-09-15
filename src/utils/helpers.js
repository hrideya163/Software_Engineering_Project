export function parseGitHubUrl(value) {
  const match = value.trim().match(/(?:github\.com[/:])([^/\s]+)\/([^/#?\s]+)/i)
  return match ? { owner: match[1], repo: match[2].replace(/\.git$/, '') } : null
}
