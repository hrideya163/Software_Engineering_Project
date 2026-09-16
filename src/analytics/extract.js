import { slug } from './text.js'

const DEPENDENCY_FILES = ['package.json', 'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'pyproject.toml', 'requirements.txt', 'Cargo.toml', 'go.mod']
const TEST_PATTERN = /(^|\/)(__tests__|test|tests|spec)(\/|$)|\.(test|spec)\.[^.]+$/
const DOC_PATTERN = /(^|\/)(readme|docs?|documentation|contributing)(\/|\.|$)/i
const SOURCE_PATTERN = /\.(c|cc|cpp|cs|go|java|js|jsx|kt|py|rb|rs|swift|ts|tsx|vue)$/i

function normalizeFile(file) {
  const path = String(file.path || file.name || file).replace(/\\/g, '/').replace(/^\.\/+/, '')
  return { path, content: typeof file.content === 'string' ? file.content : '', language: file.language || path.split('.').pop() || null }
}

function normalizeItem(item = {}) {
  return { ...item, id: String(item.id || item.number || item.sha || ''), labels: item.labels || [], files: item.files || [] }
}

function extractDependencies(files) {
  const manifests = files.filter(file => DEPENDENCY_FILES.some(name => file.path.toLowerCase().endsWith(name.toLowerCase())))
  return manifests.map(file => ({ path: file.path, content: file.content }))
}

function dependencyPackages(manifests) {
  return [...new Set(manifests.flatMap(manifest => {
    try {
      const parsed = JSON.parse(manifest.content)
      return Object.keys({ ...(parsed.dependencies || {}), ...(parsed.devDependencies || {}) })
    } catch {
      return manifest.content
        .split(/\r?\n/)
        .map(line => line.trim().match(/^([A-Za-z0-9_.-]+)(?:[<>=!~].*)?$/)?.[1])
        .filter(Boolean)
    }
  }))]
}

function buildDependencyEdges(files) {
  const sourcePaths = files.filter(file => SOURCE_PATTERN.test(file.path)).map(file => file.path)
  return files.flatMap(file => {
    if (!SOURCE_PATTERN.test(file.path)) return []
    const imports = [...file.content.matchAll(/(?:from|import|require\()\s*['"`]([^'"`]+)['"`]/g)].map(match => match[1])
    return imports.map(importPath => {
      const match = sourcePaths.find(path => path.includes(importPath.replace(/^@\//, '')) || path.endsWith(`${importPath}.js`) || path.endsWith(`${importPath}.ts`))
      return match && match !== file.path ? { source: file.path, target: match, type: 'imports' } : null
    }).filter(Boolean)
  })
}

export function extractRepositorySnapshot(input = {}) {
  const files = (input.files || []).map(normalizeFile)
  const dependencyManifests = extractDependencies(files)
  const dependencies = dependencyManifests.map(file => file.path)
  const tests = files.filter(file => TEST_PATTERN.test(file.path)).map(file => file.path)
  const documentation = files.filter(file => DOC_PATTERN.test(file.path)).map(file => file.path)
  const commits = (input.commits || []).map(normalizeItem)
  const pullRequests = (input.pullRequests || []).map(normalizeItem)
  const issues = (input.issues || []).map(normalizeItem)
  const contributors = [...new Set([
    ...commits.map(commit => commit.author).filter(Boolean),
    ...pullRequests.map(pr => pr.author).filter(Boolean),
  ])]

  return {
    repository: input.repository || {},
    files,
    dependencies,
    dependencyManifests,
    dependencyPackages: dependencyPackages(dependencyManifests),
    sourceFiles: files.filter(file => SOURCE_PATTERN.test(file.path)),
    dependencyEdges: buildDependencyEdges(files),
    tests,
    documentation,
    commits,
    pullRequests,
    issues,
    contributors,
    snapshotId: slug(`${input.repository?.owner || 'repository'}-${input.repository?.name || 'unknown'}`),
  }
}
