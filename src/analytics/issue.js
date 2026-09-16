import { clamp, overlapScore, termSet } from './text.js'
import { calculateSkillMatch, inferRequiredSkills } from './skills.js'
import { retrieveSimilar } from './retrieval.js'

const TYPE_WEIGHTS = { bug: 0.55, feature: 0.65, documentation: 0.25, refactor: 0.6, performance: 0.75 }

function classifyIssue(issue) {
  const text = `${issue.title || ''} ${issue.summary || ''} ${(issue.labels || []).join(' ')}`.toLowerCase()
  if (/document|docs|readme/.test(text)) return 'documentation'
  if (/bug|fix|error|crash|failure|broken/.test(text)) return 'bug'
  if (/performance|optimi|cache/.test(text)) return 'performance'
  if (/refactor|cleanup|rename/.test(text)) return 'refactor'
  return 'feature'
}

function difficultyLabel(score) {
  if (score < 3.5) return 'Beginner'
  if (score < 6.5) return 'Intermediate'
  return 'Advanced'
}

function relatedFiles(issue, repository) {
  const tokens = termSet(`${issue.title} ${issue.summary || ''} ${(issue.skills || []).join(' ')}`)
  return (repository.sourceFiles || repository.structure || [])
    .map(file => {
      const path = file.path || file
      const content = file.content || ''
      return { path, score: overlapScore(tokens, termSet(`${path} ${content.slice(0, 4000)}`)) }
    })
    .filter(item => item.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 5)
    .map(item => item.path)
}

function featureVector(issue, repository, files, pullRequests) {
  const text = `${issue.title || ''} ${issue.body || ''} ${issue.summary || ''}`
  const historical = pullRequests.filter(pr => retrieveSimilar(issue, [pr], 1).length).length
  return {
    dependencyDepth: clamp((repository.dependencyEdges || []).filter(edge => files.includes(edge.source)).length / 5),
    filesModified: clamp(files.length / 8),
    historicalResolutionDays: clamp(Number(issue.resolutionDays || issue.timeToCloseDays || 7) / 30),
    reviewCycles: clamp(Number(issue.reviewCycles || 1) / 5),
    commitCount: clamp(Number(issue.commitCount || Math.max(1, historical)) / 8),
    contributorCount: clamp(Number(issue.contributorCount || 1) / 5),
    ambiguity: clamp(0.6 - Math.min(text.length / 500, 0.5)),
    validationGap: /test|verify|regression/.test(text.toLowerCase()) ? 0.2 : 0.65,
  }
}

function buildPath(files, repository, issue) {
  const tests = (repository.tests || []).filter(test => files.some(file => String(test).split('/')[0] === String(file).split('/')[0])).slice(0, 3)
  const docs = (repository.documentation || []).slice(0, 3)
  const primary = files[0] || repository.structure?.[0] || 'the repository'
  return [
    { step: 'Read', title: 'Read the issue and project conventions', detail: `Start with ${docs[0] || 'the repository README'} and confirm the acceptance criteria.`, evidence: docs },
    { step: 'Explore', title: 'Trace the affected area', detail: `Inspect ${files.slice(0, 3).join(', ') || primary} and its callers.`, evidence: files },
    { step: 'Learn', title: 'Close the skill gaps', detail: `Review the repository technologies and one historical contribution before coding.`, evidence: repository.technologies || [] },
    { step: 'Implement', title: 'Make a scoped change', detail: `Keep the change focused on ${primary} and avoid unrelated refactors.`, evidence: [primary] },
    { step: 'Test', title: 'Validate the behavior', detail: tests.length ? `Run focused tests: ${tests.join(', ')}.` : 'Add a focused regression test, then run the nearest test suite.', evidence: tests },
    { step: 'Submit', title: 'Prepare the contribution', detail: 'Describe the evidence, tests, and remaining risks in the pull request.', evidence: [] },
  ]
}

export function analyzeIssue(issue, repository, allIssues = [], pullRequests = [], contributorProfile = {}) {
  const type = classifyIssue(issue)
  const files = relatedFiles(issue, repository)
  const features = featureVector(issue, repository, files, pullRequests)
  const weighted = (TYPE_WEIGHTS[type] || 0.5) * 0.25 + features.filesModified * 0.2 +
    features.dependencyDepth * 0.15 + features.historicalResolutionDays * 0.12 +
    features.reviewCycles * 0.1 + features.commitCount * 0.08 +
    features.contributorCount * 0.05 + features.ambiguity * 0.05
  const score = Math.round((1 + 9 * clamp(weighted)) * 10) / 10
  const requiredSkillObjects = inferRequiredSkills(issue, repository)
  const requiredSkills = requiredSkillObjects.map(skill => skill.name)
  const skillMatch = calculateSkillMatch(requiredSkillObjects, contributorProfile)
  const effortHours = Math.max(1, Math.round(2 + score * 0.9 + files.length * 0.75 + features.dependencyDepth * 8))
  const confidence = Math.round((0.45 + Math.min(0.5, (files.length + (issue.summary ? 1 : 0)) / 10)) * 100)
  const modules = [...new Set(files.map(file => String(file).split('/').slice(0, 2).join('/')))]
  return {
    ...issue,
    type,
    difficulty: difficultyLabel(score),
    difficultyScore: score,
    difficultyConfidence: confidence,
    difficultyFeatures: features,
    match: issue.match ?? skillMatch.score,
    skillMatch,
    effort: effortHours < 8 ? `${Math.max(1, effortHours - 2)}–${effortHours} hours` : '1–2 days',
    effortHours,
    explorationHours: Math.max(0.5, Math.round((1 + files.length * 0.75 + modules.length * 0.5) * 10) / 10),
    impact: score < 4 ? 'Low' : score < 7 ? 'Medium' : 'High',
    requiredSkills,
    relevantFiles: files,
    modules,
    dependencyImpact: features.dependencyDepth > 0.4 ? 'Review direct dependents and integration tests' : 'No broad dependency impact detected',
    similarIssues: retrieveSimilar(issue, allIssues, 3),
    similarPRs: retrieveSimilar(issue, pullRequests, 3),
    explanation: `Estimated ${difficultyLabel(score).toLowerCase()} from ${files.length} evidence-backed files, ${modules.length} modules, historical complexity signals, and validation requirements.`,
    contributionPath: buildPath(files, repository, issue),
  }
}
