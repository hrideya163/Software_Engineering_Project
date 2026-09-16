import { analyzeIssue } from './issue.js'
import { analyzeRepository } from './repository.js'
import { buildKnowledgeGraph } from './graph.js'
import { extractRepositorySnapshot } from './extract.js'
import { buildContributionGuidance } from './guidance.js'

function rankRecommendations(issues) {
  const normalize = (value, max) => Math.min(1, Number(value || 0) / max)
  return issues.map(issue => {
    const beginner = issue.difficulty === 'Beginner' ? 1 : issue.difficulty === 'Intermediate' ? 0.55 : 0.15
    const lowEffort = 1 - normalize(issue.effortHours, 24)
    const impact = issue.impact === 'High' ? 1 : issue.impact === 'Medium' ? 0.65 : 0.3
    const learning = Math.min(1, (issue.requiredSkills || []).length / 4)
    return {
      ...issue,
      recommendationScores: {
        beginner: Math.round((0.7 * beginner + 0.3 * (issue.match || 0) / 100) * 100),
        learning: Math.round((0.55 * learning + 0.45 * impact) * 100),
        lowEffort: Math.round((0.7 * lowEffort + 0.3 * beginner) * 100),
        highImpact: Math.round((0.7 * impact + 0.3 * (issue.match || 0) / 100) * 100),
      },
    }
  }).sort((a, b) => b.recommendationScores.beginner - a.recommendationScores.beginner)
}

export function buildAnalytics(input) {
  const snapshot = extractRepositorySnapshot(input)
  const repositoryAnalysis = analyzeRepository(snapshot.repository, snapshot.files)
  const analyzedIssues = snapshot.issues.map(issue => {
    const analysis = analyzeIssue(issue, { ...snapshot.repository, ...repositoryAnalysis, ...snapshot }, snapshot.issues, snapshot.pullRequests)
    return { ...analysis, guidance: buildContributionGuidance(issue, analysis, snapshot) }
  })
  const rankedIssues = rankRecommendations(analyzedIssues)
  const graph = buildKnowledgeGraph({ ...snapshot.repository, ...repositoryAnalysis, contributors: snapshot.contributors, dependencyEdges: snapshot.dependencyEdges }, rankedIssues, snapshot.pullRequests)
  return {
    repository: { ...snapshot.repository, ...repositoryAnalysis },
    issues: rankedIssues,
    recommendations: {
      beginner: rankedIssues.slice().sort((a, b) => b.recommendationScores.beginner - a.recommendationScores.beginner).slice(0, 10),
      learning: rankedIssues.slice().sort((a, b) => b.recommendationScores.learning - a.recommendationScores.learning).slice(0, 10),
      lowEffort: rankedIssues.slice().sort((a, b) => b.recommendationScores.lowEffort - a.recommendationScores.lowEffort).slice(0, 10),
      highImpact: rankedIssues.slice().sort((a, b) => b.recommendationScores.highImpact - a.recommendationScores.highImpact).slice(0, 10),
    },
    graph,
    contributors: snapshot.contributors,
    metadata: { snapshotId: snapshot.snapshotId, files: snapshot.files.length, sourceFiles: snapshot.sourceFiles.length, tests: snapshot.tests.length, documentation: snapshot.documentation.length, dependencyEdges: snapshot.dependencyEdges.length },
    generatedAt: new Date().toISOString(),
  }
}
