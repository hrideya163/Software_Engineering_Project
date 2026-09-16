export function buildKnowledgeGraph(repository, issues, pullRequests = []) {
  const nodes = []
  const edges = []
  const addNode = (id, label, type) => nodes.push({ id, position: { x: 0, y: 0 }, data: { label }, type })
  const addEdge = (source, target, relation) => edges.push({ id: `${source}-${target}`, source, target, label: relation })
  const ensureFile = file => {
    const fileId = `file-${file}`
    if (!nodes.some(node => node.id === fileId)) addNode(fileId, file, 'file')
    return fileId
  }
  ;(repository.sourceFiles || []).slice(0, 100).forEach(file => ensureFile(file.path || file))
  issues.forEach(issue => {
    const issueId = `issue-${issue.id}`
    addNode(issueId, `Issue #${issue.id}`, 'issue')
    ;(issue.relevantFiles || []).forEach(file => {
      const fileId = ensureFile(file)
      addEdge(issueId, fileId, 'affects')
    })
    ;(issue.requiredSkills || []).forEach(skill => {
      const skillId = `skill-${skill}`
      if (!nodes.some(node => node.id === skillId)) addNode(skillId, skill, 'tech')
      addEdge(issueId, skillId, 'requires')
    })
  })
  pullRequests.forEach(pr => {
    const prId = `pr-${pr.id}`
    addNode(prId, `PR #${pr.id}`, 'pr')
    ;(pr.files || []).forEach(file => addEdge(prId, ensureFile(file.path || file), 'changes'))
  })
  ;(repository.modules || []).forEach(module => addNode(`module-${module.name || module}`, module.name || module, 'module'))
  ;(repository.contributors || []).forEach(contributor => addNode(`contributor-${contributor}`, contributor, 'contributor'))
  ;(repository.technologies || []).forEach(technology => addNode(`technology-${technology}`, technology, 'tech'))
  ;(repository.dependencyEdges || []).forEach(edge => addEdge(ensureFile(edge.source), ensureFile(edge.target), edge.type))
  return { nodes, edges }
}
