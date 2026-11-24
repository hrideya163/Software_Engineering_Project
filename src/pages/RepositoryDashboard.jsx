import { Activity, BookOpen, ExternalLink, FileCode2, FlaskConical, GitFork, GitPullRequest, HeartPulse, Star, Users } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getActivity, getRankedIssues, getRepositoryOverview } from '../api/contrimapApi'
import AppLayout from '../components/AppLayout'
import EmptyState from '../components/EmptyState'
import ErrorMessage from '../components/ErrorMessage'
import Loading from '../components/Loading'
import RankedIssueCard from '../components/RankedIssueCard'
import SkillTag from '../components/SkillTag'
import { useAsync, useProfile } from '../hooks/useProfile'
import { compact } from '../utils/formatters'
import RepositoryGate from '../components/RepositoryGate'

const PALETTE = ['#2d7ef7', '#0eaa7d', '#f59e0b', '#7c3aed', '#ef4444', '#06b6d4', '#64748b', '#ec4899']
const HEALTH_LABELS = {
  activity: ['Commit activity', 'commits in the last 90 days'], recency: ['Recently pushed', 'time since the last push'],
  merge_speed: ['Merge speed', 'median time from PR opened to merged'], acceptance: ['PR acceptance', 'share of closed PRs that were merged'],
  contributor_diversity: ['Maintainer spread', 'how many people write half the commits'], responsiveness: ['Issue replies', 'open issues with at least one comment'],
}
const HEALTH_TONE = { healthy: 'bg-emerald-100 text-emerald-700', moderate: 'bg-amber-100 text-amber-700', 'low activity': 'bg-slate-200 text-slate-700' }
const days = value => (value === null || value === undefined ? '-' : value < 1 ? `${Math.round(value * 24)} h` : `${value.toFixed(value < 10 ? 1 : 0)} d`)

function Stat({ icon: Icon, label, value, hint }) {
  return <div className="card p-4" title={hint}><Icon size={18} className="text-blue-700" /><p className="mt-3 text-2xl font-extrabold">{value}</p><p className="text-xs font-bold text-slate-500">{label}</p></div>
}

function Meter({ value }) {
  return <div className="h-1.5 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-mint" style={{ width: `${Math.max(3, value * 100)}%` }} /></div>
}

// Weekly commits: one series, one hue; hovering a bar shows its week and count.
function WeeklyCommits({ weekly }) {
  const [hover, setHover] = useState(null)
  const max = Math.max(1, ...weekly)
  return <div>
    <div className="flex h-24 items-end gap-[2px]" onMouseLeave={() => setHover(null)}>
      {weekly.map((count, index) => <div key={index} className="flex h-full flex-1 items-end" onMouseEnter={() => setHover(index)}>
        <div className={`w-full rounded-t ${hover === index ? 'bg-ink' : 'bg-[#2d7ef7]'}`} style={{ height: `${count ? Math.max(4, (count / max) * 100) : 0}%` }} />
      </div>)}
    </div>
    <div className="mt-1 h-px bg-slate-200" />
    <p className="mt-2 text-[11px] text-slate-500">{hover === null ? `${weekly.length} weeks, oldest left · hover a bar` : `${weekly.length - 1 - hover === 0 ? 'This week' : `${weekly.length - 1 - hover} weeks ago`}: ${weekly[hover]} commits`}</p>
  </div>
}

function Health({ owner, repo }) {
  const { data, loading, error } = useAsync(() => getActivity(owner, repo), [owner, repo])
  if (loading) return <section className="card mt-6 p-5"><p className="eyebrow">Repository health</p><p className="mt-3 text-sm text-slate-500">Reading recent commits, pull requests and issues…</p></section>
  if (error) return <section className="card mt-6 p-5"><p className="eyebrow">Repository health</p><p className="mt-3 text-sm text-amber-700">{error}</p></section>
  const health = data.health
  return <section className="mt-6 grid gap-5 lg:grid-cols-[1fr_1fr_1fr]">
    <div className="card p-5">
      <div className="flex items-center justify-between"><p className="eyebrow inline-flex items-center gap-2"><HeartPulse size={14} />Repository health</p><span className={`rounded-full px-2 py-0.5 text-xs font-extrabold ${HEALTH_TONE[health.label]}`}>{health.label}</span></div>
      <p className="mt-3 text-4xl font-extrabold text-ink">{Math.round(health.score * 100)}<span className="text-base text-slate-400">/100</span></p>
      <ul className="mt-4 space-y-2.5">{Object.entries(health.components).map(([key, value]) => <li key={key} title={HEALTH_LABELS[key]?.[1]}>
        <div className="mb-1 flex justify-between text-[11px] font-bold text-slate-500"><span>{HEALTH_LABELS[key]?.[0] || key}</span><span>{Math.round(value * 100)}</span></div>
        <Meter value={value} />
      </li>)}</ul>
      <p className="mt-4 text-[11px] leading-4 text-slate-400">{data.note}</p>
    </div>
    <div className="card p-5">
      <p className="eyebrow inline-flex items-center gap-2"><Activity size={14} />Commits per week</p>
      <p className="mt-2 text-sm text-slate-600"><b className="text-ink">{data.commits.total}{data.commits.capped ? '+' : ''}</b> commits in {data.window_days} days</p>
      <div className="mt-4"><WeeklyCommits weekly={data.commits.weekly} /></div>
      <div className="mt-5 grid grid-cols-2 gap-3 border-t pt-4 text-sm">
        <div><p className="text-lg font-extrabold">{days(data.pull_requests.median_days_to_merge)}</p><p className="text-[11px] font-bold text-slate-500">median time to merge</p></div>
        <div><p className="text-lg font-extrabold">{data.pull_requests.merged}/{data.pull_requests.sample}</p><p className="text-[11px] font-bold text-slate-500">recent closed PRs merged</p></div>
        <div><p className="text-lg font-extrabold">{days(data.issues.median_days_to_close)}</p><p className="text-[11px] font-bold text-slate-500">median issue close time</p></div>
        <div><p className="text-lg font-extrabold">{data.issues.unanswered}/{data.issues.open_sampled}</p><p className="text-[11px] font-bold text-slate-500">open issues without reply</p></div>
      </div>
    </div>
    <div className="card p-5">
      <p className="eyebrow inline-flex items-center gap-2"><Users size={14} />Contributors</p>
      <div className="mt-3 grid grid-cols-2 gap-3">
        <div><p className="text-2xl font-extrabold">{data.contributors.active}</p><p className="text-[11px] font-bold text-slate-500">active in {data.window_days} days</p></div>
        <div title="The fewest people who wrote half of the recent commits. 1 means the project leans on one maintainer."><p className="text-2xl font-extrabold">{data.contributors.bus_factor}</p><p className="text-[11px] font-bold text-slate-500">write half the commits</p></div>
      </div>
      <p className="mt-5 text-xs font-bold uppercase text-slate-500">Most active recently</p>
      <ul className="mt-2 space-y-1.5">{data.contributors.top.slice(0, 5).map(person => <li key={person.login} className="flex items-center justify-between text-xs"><a href={`https://github.com/${person.login}`} target="_blank" rel="noreferrer" className="font-semibold text-ink hover:text-blue-700">{person.login}</a><span className="text-slate-500">{person.commits} commits</span></li>)}</ul>
      {data.issues.newcomer_labelled > 0 && <p className="mt-4 rounded-lg bg-emerald-50 px-2 py-1.5 text-xs font-semibold text-emerald-700">{data.issues.newcomer_labelled} open issues are labelled for newcomers</p>}
    </div>
  </section>
}

function RepositoryDashboardContent() {
  const { owner, repo } = useParams()
  const { profile } = useProfile()
  const overview = useAsync(() => getRepositoryOverview(owner, repo), [owner, repo])
  const ranked = useAsync(() => getRankedIssues(owner, repo, { profile, limit: 20 }), [owner, repo])
  if (overview.loading) return <AppLayout><Loading label="Snapshotting the repository and building its code graph…" /></AppLayout>
  if (overview.error) return <AppLayout><ErrorMessage message={overview.error} onRetry={overview.retry} /></AppLayout>
  const details = overview.data
  return <AppLayout>
    <p className="eyebrow">Repository</p>
    <div className="mt-2 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-3xl font-extrabold">{owner} <span className="text-slate-400">/</span> {repo}</h1>
        {details.description && <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">{details.description}</p>}
        <div className="mt-3 flex flex-wrap gap-2 text-[11px] font-bold text-slate-500">
          {details.language && <span className="rounded-full bg-slate-100 px-2 py-0.5">{details.language}</span>}
          {details.license && <span className="rounded-full bg-slate-100 px-2 py-0.5">{details.license}</span>}
          {(details.topics || []).slice(0, 4).map(topic => <span key={topic} className="rounded-full bg-sky px-2 py-0.5 text-ink">{topic}</span>)}
          <span className="mono rounded-full bg-slate-100 px-2 py-0.5 font-normal">snapshot {details.sha?.slice(0, 10)}</span>
        </div>
      </div>
      <div className="flex gap-2">
        <a target="_blank" rel="noreferrer" href={`https://github.com/${owner}/${repo}`} className="btn-secondary">GitHub <ExternalLink size={14} /></a>
      </div>
    </div>
    {details.available === false && <div className="mt-4"><ErrorMessage message={`GitHub metadata unavailable (${details.reason}). Structure and models still work from the git snapshot.`} /></div>}
    <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-5">
      {details.stars !== undefined && <Stat icon={Star} label="stars" value={compact(details.stars)} />}
      {details.forks !== undefined && <Stat icon={GitFork} label="forks" value={compact(details.forks)} />}
      {details.open_issues !== undefined && <Stat icon={GitPullRequest} label="open issues + PRs" value={compact(details.open_issues)} />}
      <Stat icon={FileCode2} label="files in snapshot" value={compact(details.file_count)} />
      <Stat icon={FlaskConical} label="test files" value={compact(details.tests)} hint={`${details.file_count ? Math.round(details.tests / details.file_count * 100) : 0}% of files are tests`} />
    </div>

    <Health owner={owner} repo={repo} />

    <h2 className="mt-10 text-lg font-extrabold">Technology and structure</h2>
    <div className="mt-4 grid gap-5 lg:grid-cols-3">
      <section className="card p-5">
        <p className="eyebrow">Languages</p>
        <div className="mt-4 flex h-2 gap-[2px] overflow-hidden rounded-full">{details.languages_breakdown.map((l, i) => <div key={l.name} style={{ width: `${l.share * 100}%`, background: PALETTE[i % PALETTE.length] }} title={`${l.name} ${(l.share * 100).toFixed(1)}%`} />)}</div>
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">{details.languages_breakdown.map((l, i) => <span key={l.name} className="inline-flex items-center gap-1.5"><i className="inline-block h-2 w-2 rounded-full" style={{ background: PALETTE[i % PALETTE.length] }} />{l.name} {(l.share * 100).toFixed(1)}%</span>)}</div>
        <p className="eyebrow mt-6">Skills this project uses</p>
        <div className="mt-3 flex flex-wrap gap-2">{details.skills.slice(0, 12).map(skill => <span key={skill.id} title={skill.evidence.join('; ')}><SkillTag>{skill.name}</SkillTag></span>)}</div>
        {(details.contributing || details.readme) && <div className="mt-6 space-y-1 text-xs">{[details.contributing, details.readme].filter(Boolean).map(path => <a key={path} target="_blank" rel="noreferrer" href={`https://github.com/${owner}/${repo}/blob/${details.sha}/${path}`} className="flex items-center gap-1.5 font-bold text-blue-700"><BookOpen size={13} />{path}</a>)}</div>}
      </section>
      <section className="card p-5">
        <p className="eyebrow">Core files</p>
        <p className="mt-1 text-[11px] text-slate-400">Most imported, by import-graph PageRank</p>
        {details.core_files.length ? <ol className="mt-4 space-y-2">{details.core_files.slice(0, 8).map((file, i) => <li key={file.path} className="flex items-center gap-2 text-xs"><span className="w-4 font-bold text-slate-400">{i + 1}</span><Link to={`/repository/${owner}/${repo}/visualizer?file=${encodeURIComponent(file.path)}`} className="mono truncate text-ink hover:text-blue-700" title={file.path}>{file.path}</Link></li>)}</ol> : <p className="mt-4 text-sm text-slate-500">No resolvable imports found for this language.</p>}
        <p className="mt-5 text-xs text-slate-500">{details.graph_summary.import_edges} import edges · {details.graph_summary.communities} modules detected</p>
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
      {ranked.error && <div className="mt-4"><ErrorMessage message={ranked.error} onRetry={ranked.retry} /></div>}
      {ranked.data && !ranked.data.issues.length && <div className="mt-4"><EmptyState message="No open issues found for this repository." /></div>}
      <div className="mt-4 grid gap-4 md:grid-cols-2 2xl:grid-cols-3">{ranked.data?.issues.slice(0, 6).map(item => <RankedIssueCard item={item} owner={owner} repo={repo} weights={ranked.data.weights} key={item.issue.number} />)}</div>
    </section>
  </AppLayout>
}

// The page renders once the backend has snapshotted the repository; until then the gate shows build progress.
export default function RepositoryDashboard() {
  const { owner, repo } = useParams()
  return <RepositoryGate owner={owner} repo={repo}><RepositoryDashboardContent /></RepositoryGate>
}
