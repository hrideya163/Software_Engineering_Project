const LANGUAGE_COLORS = {
  JavaScript: '#f1e05a', TypeScript: '#3178c6', Python: '#3572A5', Rust: '#dea584',
  Go: '#00ADD8', Java: '#b07219', 'C++': '#f34b7d', C: '#555555', Ruby: '#701516',
  PHP: '#4F5D95', Swift: '#F05138', Kotlin: '#A97BFF', HTML: '#e34c26', CSS: '#563d7c',
  Shell: '#89e051', Vue: '#41b883', Dart: '#00B4AB', 'C#': '#178600'
}

function hashString(value) {
  let hash = 0
  for (const ch of String(value)) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0
  return hash
}

export function languageColor(name) {
  if (LANGUAGE_COLORS[name]) return LANGUAGE_COLORS[name]
  const hue = hashString(name) % 360
  return `hsl(${hue}, 55%, 55%)`
}

export function difficulty(issue, labels) {
  const lower = labels.map((l) => l.toLowerCase())
  if (lower.some((l) => /good.first.issue|beginner|starter|easy/.test(l))) return 'Beginner'
  if (lower.some((l) => /advanced|complex|architecture|breaking/.test(l))) return 'Advanced'

  const bodyLen = (issue.body || '').length
  const comments = issue.comments || 0
  const score = bodyLen / 250 + comments * 1.4
  if (score < 4) return 'Beginner'
  if (score < 11) return 'Intermediate'
  return 'Advanced'
}

export function matchScore(issue, level) {
  const base = { Beginner: 88, Intermediate: 76, Advanced: 62 }[level]
  const jitter = (hashString(`${issue.number}`) % 15) - 7
  return Math.max(45, Math.min(98, base + jitter))
}

export function effort(issue, level) {
  const options = {
    Beginner: ['1–2 hours', '2–4 hours'],
    Intermediate: ['4–8 hours', '1–2 days'],
    Advanced: ['2–3 days', '1 week+']
  }[level]
  return options[hashString(`${issue.number}effort`) % options.length]
}

export function impact(issue, labels) {
  const lower = labels.map((l) => l.toLowerCase())
  if (lower.some((l) => /security|critical|performance|breaking/.test(l))) return 'High'
  if (labels.length <= 2 && lower.some((l) => /documentation|good first issue|typo/.test(l))) return 'Low'

  const comments = issue.comments || 0
  if (comments > 8) return 'High'
  if (comments > 2) return 'Medium'
  return 'Low'
}

const SKILL_KEYWORDS = [
  [/access?ibility|a11y/, 'Accessibility'],
  [/doc(s|umentation)?/, 'Documentation'],
  [/test|coverage/, 'Testing'],
  [/perf(ormance)?/, 'Performance'],
  [/security|vuln/, 'Security'],
  [/ui|design|css|style/, 'UI/UX'],
  [/api/, 'API Design'],
  [/i18n|locale|translation/, 'Internationalization'],
  [/bug/, 'Debugging']
]

export function skills(issue, labels, repoLanguage) {
  const found = new Set()
  const haystack = labels.join(' ').toLowerCase()
  for (const [pattern, skill] of SKILL_KEYWORDS) {
    if (pattern.test(haystack)) found.add(skill)
  }
  if (repoLanguage) found.add(repoLanguage)
  if (!found.size) found.add('Open Source')
  return [...found].slice(0, 4)
}

export function summarize(issue) {
  const body = (issue.body || '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/[#*_>`~-]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  if (!body) return `Contribute to "${issue.title}".`
  return body.length > 160 ? `${body.slice(0, 157)}…` : body
}

export function titleCase(value) {
  return value
    .replace(/[-_]+/g, ' ')
    .trim()
    .split(' ')
    .filter(Boolean)
    .map((word) => word[0].toUpperCase() + word.slice(1))
    .join(' ')
}
