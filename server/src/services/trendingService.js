import { githubGet } from '../lib/github.js'
import { cached } from '../lib/cache.js'

const TTL = 15 * 60 * 1000

// GitHub has no official "trending" API. ContriMap defines trending as:
// repositories that were pushed to within the last ACTIVE_WINDOW_DAYS days
// (recent activity), ranked by star count (popularity).
const ACTIVE_WINDOW_DAYS = 30
const MIN_STARS = 1000
const LANGUAGE_PATTERN = /^[A-Za-z0-9+#.\- ]{1,30}$/

function mapRepository(item) {
  return {
    owner: item.owner.login,
    name: item.name,
    full_name: item.full_name,
    description: item.description || 'No description provided.',
    stars: item.stargazers_count,
    forks: item.forks_count,
    open_issues: item.open_issues_count,
    language: item.language,
    topics: (item.topics || []).slice(0, 4),
    pushed_at: item.pushed_at,
    html_url: item.html_url
  }
}

export async function getTrending({ language, limit = 12 } = {}) {
  const lang = language && LANGUAGE_PATTERN.test(language) ? language.trim() : ''
  return cached(`trending:${lang}:${limit}`, TTL, async () => {
    const since = new Date(Date.now() - ACTIVE_WINDOW_DAYS * 24 * 60 * 60 * 1000).toISOString().slice(0, 10)
    const qualifiers = [`pushed:>${since}`, `stars:>${MIN_STARS}`, 'archived:false']
    if (lang) qualifiers.push(`language:"${lang}"`)

    // Over-fetch a little: repositories with no open issues are useless for
    // contributors, and the search API cannot filter on that directly.
    const perPage = Math.min(limit * 2, 50)
    const result = await githubGet(
      `/search/repositories?q=${encodeURIComponent(qualifiers.join(' '))}&sort=stars&order=desc&per_page=${perPage}`
    )
    return (result.items || [])
      .filter((item) => item.open_issues_count > 0)
      .slice(0, limit)
      .map(mapRepository)
  })
}
