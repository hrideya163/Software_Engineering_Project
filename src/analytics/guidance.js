export function buildContributionGuidance(issue, analysis, snapshot) {
  const files = analysis.relevantFiles || []
  const docs = (snapshot.documentation || []).filter(path => files.some(file => path.toLowerCase().includes(String(file).split('/')[0].toLowerCase()))).slice(0, 3)
  const tests = (snapshot.tests || []).filter(path => files.some(file => String(path).split('/')[0] === String(file).split('/')[0])).slice(0, 3)
  return {
    readingOrder: [...docs, ...files, ...tests],
    documentation: docs,
    similarPullRequests: analysis.similarPRs || [],
    path: analysis.contributionPath || [],
    validation: tests.length ? `Run the focused tests covering ${tests.join(', ')}` : 'Add a focused regression test for the changed behavior.',
    issueId: issue.id,
    analyticsContext: {
      whyBeyondLlm: 'Ranks historical evidence, repository dependencies, and contributor-fit signals before language generation.',
      evidence: {
        difficulty: analysis.difficultyFeatures,
        affectedFiles: files,
        similarIssues: (analysis.similarIssues || []).map(item => item.id),
        similarPullRequests: (analysis.similarPRs || []).map(item => item.id),
      },
      llmInstruction: 'Explain the supplied evidence and uncertainty. Do not invent files, dependencies, metrics, or historical outcomes.',
    },
  }
}
