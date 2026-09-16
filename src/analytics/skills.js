const SKILL_RULES = [
  [/typescript|javascript|\.tsx?|\.jsx/i, 'JavaScript/TypeScript'],
  [/react|component|hook/i, 'React'],
  [/test|regression|jest|vitest|pytest/i, 'Testing'],
  [/document|docs|readme|mdx/i, 'Documentation'],
  [/cache|latency|performance|optimi/i, 'Performance engineering'],
  [/api|endpoint|request|route/i, 'API design'],
  [/database|migration|sql|query/i, 'Database engineering'],
  [/rust|cargo|\.rs/i, 'Rust'],
  [/accessib|a11y|keyboard|screen reader/i, 'Accessibility'],
  [/graphql|rest|http|api/i, 'API design'],
  [/webpack|bundler|vite|turbopack/i, 'Build tooling'],
  [/security|auth|permission|oauth/i, 'Security engineering'],
]

export function inferRequiredSkills(issue, repository = {}) {
  const text = `${issue.title || ''} ${issue.body || ''} ${issue.summary || ''} ${(issue.labels || []).join(' ')} ${(repository.technologies || []).join(' ')}`
  return [...new Map(SKILL_RULES
    .filter(([pattern]) => pattern.test(text))
    .map(([, skill]) => [skill, { name: skill, importance: 'required', confidence: 0.78, evidence: text.match(SKILL_RULES.find(([pattern, name]) => name === skill)[0])?.[0] || null }])).values()]
}

export function buildContributorProfile(contributor, snapshot) {
  const contributions = [
    ...(snapshot.commits || []).filter(item => item.author === contributor),
    ...(snapshot.pullRequests || []).filter(item => item.author === contributor),
  ]
  const skills = inferRequiredSkills({ title: contributions.map(item => item.title).join(' ') }, snapshot.repository)
  return { contributor, contributionCount: contributions.length, skills: skills.map(skill => skill.name) }
}

export function calculateSkillMatch(requiredSkills, profile = {}) {
  const known = new Set(profile.skills || [])
  const required = requiredSkills.map(skill => skill.name || skill)
  if (!required.length) return { score: 0, matched: [], gaps: [] }
  const matched = required.filter(skill => known.has(skill))
  return { score: Math.round((matched.length / required.length) * 100), matched, gaps: required.filter(skill => !known.has(skill)) }
}
