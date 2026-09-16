import { clamp, slug } from './text.js'

const TECHNOLOGY_SIGNATURES = [
  ['TypeScript', ['.ts', '.tsx', 'typescript']],
  ['JavaScript', ['.js', '.jsx', 'javascript']],
  ['Python', ['.py', 'python', 'pyproject.toml']],
  ['Rust', ['.rs', 'cargo.toml', 'rust']],
  ['React', ['react', '.jsx', '.tsx']],
  ['Jest', ['jest', 'vitest', 'test.']],
  ['Webpack', ['webpack']],
  ['Docker', ['dockerfile', 'docker-compose']],
]

function pathMatches(path, signature) {
  const normalized = path.toLowerCase()
  return signature.some(term => normalized.includes(term))
}

function contentMatches(file, signature) {
  return signature.some(term => file.content.toLowerCase().includes(term))
}

function moduleFor(path) {
  const parts = String(path).split('/')
  return parts.length > 1 ? parts.slice(0, Math.min(2, parts.length - 1)).join('/') : parts[0]
}

export function analyzeRepository(repository, files = []) {
  const normalizedFiles = files.map(file => typeof file === 'string' ? { path: file, content: '' } : file)
  const paths = normalizedFiles.length ? normalizedFiles.map(file => file.path) : (repository.structure || [])
  const technologies = TECHNOLOGY_SIGNATURES
    .map(([name, signature]) => ({
      name,
      evidence: normalizedFiles.filter(file => pathMatches(file.path, signature) || contentMatches(file, signature)).map(file => file.path),
    }))
    .filter(item => item.evidence.length)
    .map(item => item.name)
  const modules = [...new Set(paths.map(moduleFor))]
  const structure = modules.slice(0, 12)
  const importantModules = modules
    .map((name, index) => ({ name, score: clamp(1 - index / Math.max(modules.length, 1)) }))
    .sort((a, b) => b.score - a.score)

  return {
    id: `${repository.owner}/${repository.name}`,
    technologies: technologies.length ? technologies : (repository.technologies || []),
    structure,
    modules: importantModules,
    fileCount: paths.length,
    evidence: paths.slice(0, 20),
    sourceFiles: normalizedFiles.filter(file => !/^(docs?|test|examples?)\//i.test(file.path)),
    slug: slug(`${repository.owner}-${repository.name}`),
  }
}
