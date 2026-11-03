import { BookOpen, ExternalLink, FileCode2, FlaskConical, GitFork, Network, Star } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { getRankedIssues, getRepositoryOverview } from '../api/contrimapApi'
import AppLayout from '../components/AppLayout'
import EmptyState from '../components/EmptyState'
import ErrorMessage from '../components/ErrorMessage'
import Loading from '../components/Loading'
import RankedIssueCard from '../components/RankedIssueCard'
import SkillTag from '../components/SkillTag'
import { useAsync, useProfile } from '../hooks/useProfile'
import { compact } from '../utils/formatters'

const PALETTE = ['#2d7ef7', '#0eaa7d', '#f59e0b', '#7c3aed', '#ef4444', '#06b6d4', '#64748b', '#ec4899']

function Stat({ icon: Icon, label, value }) {
  return <div className="card p-4"><Icon size={18} className="text-blue-700" /><p className="mt-3 text-2xl font-extrabold">{value}</p><p className="text-xs font-bold text-slate-500">{label}</p></div>
}

export default function RepositoryDashboard() {
  const { owner, repo } = useParams()
  const { profile } = useProfile()
  const overview = useAsync(() => getRepositoryOverview(owner, repo), [owner, repo])
  const ranked = useAsync(() => getRankedIssues(owner, repo, { profile, limit: 20 }), [owner, repo])
  if (overview.loading) return <AppLayout><Loading label="Snapshotting the repository and building its code graph…" /></AppLayout>
  if (overview.error) return <AppLayout><ErrorMessage message={overview.error} /></AppLayout>
  const details = overview.data
  return <AppLayout>
    <p className="eyebrow">Repository</p>
    <div className="mt-2 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="text-3xl font-extrabold">{owner} <span className="text-slate-400">/</span> {repo}</h1>
        {details.description && <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">{details.description}</p>}
        <p className="mono mt-2 text-xs text-slate-400">snapshot {details.sha?.slice(0, 10)}</p>
      </div>
      <div className="flex gap-2">
        <Link to={`/repository/${owner}/${repo}/visualizer`} className="btn-secondary"><Network size={16} />Visualizer</Link>
        <a target="_blank" rel="noreferrer" href={`https://github.com/${owner}/${repo}`} className="btn-secondary">GitHub <ExternalLink size={14} /></a>
      </div>
    </div>
    {details.available === false && <div className="mt-4"><ErrorMessage message={`GitHub metadata unavailable (${details.reason}). Structure and models still work from the git snapshot.`} /></div>}
    <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
      {details.stars !== undefined && <Stat icon={Star} label="stars" value={compact(details.stars)} />}
      {details.forks !== undefined && <Stat icon={GitFork} label="forks" value={compact(details.forks)} />}
      <Stat icon={FileCode2} label="files in snapshot" value={compact(details.file_count)} />
      <Stat icon={FlaskConical} label="test files" value={compact(details.tests)} />
    </div>
    <div className="mt-6 grid gap-5 lg:grid-cols-3">
      <section className="card p-5">
        <p className="eyebrow">Languages</p>
        <div className="mt-4 flex h-2 overflow-hidden rounded-full bg-slate-100">{details.languages_breakdown.map((l, i) => <div key={l.name} style={{ width: `${l.share * 100}%`, background: PALETTE[i % PALETTE.length] }} title={`${l.name} ${(l.share * 100).toFixed(1)}%`} />)}</div>
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">{details.languages_breakdown.map((l, i) => <span key={l.name} className="inline-flex items-center gap-1.5"><i className="inline-block h-2 w-2 rounded-full" style={{ background: PALETTE[i % PALETTE.length] }} />{l.name} {(l.share * 100).toFixed(1)}%</span>)}</div>
        <p className="eyebrow mt-6">Skills this project uses</p>
        <div className="mt-3 flex flex-wrap gap-2">{details.skills.slice(0, 12).map(skill => <span key={skill.id} title={skill.evidence.join('; ')}><SkillTag>{skill.name}</SkillTag></span>)}</div>
        {(details.contributing || details.readme) && <div className="mt-6 space-y-1 text-xs">{[details.contributing, details.readme].filter(Boolean).map(path => <a key={path} target="_blank" rel="noreferrer" href={`https://github.com/${owner}/${repo}/blob/${details.sha}/${path}`} className="flex items-center gap-1.5 font-bold text-blue-700"><BookOpen size={13} />{path}</a>)}</div>}
      </section>
      <section className="card p-5">
        <p className="eyebrow">Core files (import-graph PageRank)</p>
        {details.core_files.length ? <ol className="mt-4 space-y-2">{details.core_files.slice(0, 8).map((file, i) => <li key={file.path} className="flex items-center gap-2 text-xs"><span className="w-4 font-bold text-slate-400">{i + 1}</span><span className="mono truncate text-ink" title={file.path}>{file.path}</span></li>)}</ol> : <p className="mt-4 text-sm text-slate-500">No resolvable imports found for this language.</p>}
        <p className="mt-5 text-xs text-slate-500">{details.graph_summary.import_edges} import edges · {details.graph_summary.communities} modules (Louvain)</p>
      </section>
      <section className="card p-5">
        <p className="eyebrow">Structure</p>
        <ul className="mt-4 space-y-2">{details.structure.slice(0, 10).map(dir => <li key={dir.name} className="flex justify-between text-xs"><span className="mono text-ink">{dir.name}/</span><span className="text-slate-500">{dir.files} files</span></li>)}</ul>
        {details.packages.length > 0 && <><p className="eyebrow mt-6">Dependencies</p><p className="mt-2 line-clamp-3 text-xs leading-5 text-slate-500">{details.packages.slice(0, 20).join(' · ')}</p></>}
      </section>
    </div>
    <section className="mt-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h2 className="text-lg font-extrabold">Best issues to work on</h2><p className="text-xs text-slate-500">{ranked.data?.personalized ? 'Personalised with your profile.' : 'General ranking - set up your profile for personalised results.'}</p></div>
        <Link to={`/repository/${owner}/${repo}/issues`} className="btn-secondary">All ranked issues</Link>
      </div>
      {ranked.loading && <Loading label="Scoring open issues with the models…" />}
      {ranked.error && <div className="mt-4"><ErrorMessage message={ranked.error} /></div>}
      {ranked.data && !ranked.data.issues.length && <div className="mt-4"><EmptyState message="No open issues found for this repository." /></div>}
      <div className="mt-4 grid gap-4 xl:grid-cols-2">{ranked.data?.issues.slice(0, 6).map(item => <RankedIssueCard item={item} owner={owner} repo={repo} weights={ranked.data.weights} key={item.issue.number} />)}</div>
    </section>
  </AppLayout>
}
