import { Search, UserRound } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getRankedIssues } from '../api/contrimapApi'
import AppLayout from '../components/AppLayout'
import EmptyState from '../components/EmptyState'
import ErrorMessage from '../components/ErrorMessage'
import Loading from '../components/Loading'
import RankedIssueCard from '../components/RankedIssueCard'
import { useAsync, useProfile } from '../hooks/useProfile'

const MODES = [['balanced', 'Balanced'], ['learning', 'Learn something new'], ['quick_win', 'Quick win']]

export default function IssueExplorer() {
  const { owner, repo } = useParams()
  const { profile, isSet } = useProfile()
  const [personal, setPersonal] = useState(isSet)
  const [mode, setMode] = useState('balanced')
  const [query, setQuery] = useState('')
  const [difficulty, setDifficulty] = useState('All')
  const { data, loading, error } = useAsync(() => getRankedIssues(owner, repo, { profile: personal ? profile : null, mode, limit: 40 }), [owner, repo, personal, mode])
  const filtered = useMemo(() => (data?.issues || []).filter(item => (difficulty === 'All' || item.difficulty === difficulty) && `${item.issue.title} ${item.summary} ${(item.issue.labels || []).join(' ')}`.toLowerCase().includes(query.toLowerCase())), [data, query, difficulty])
  return <AppLayout>
    <p className="eyebrow">Issue discovery</p>
    <h1 className="mt-2 text-3xl font-extrabold">Ranked open issues</h1>
    <p className="mt-2 max-w-3xl text-sm text-slate-600">Each issue is scored by the models (difficulty, actionability, localization focus) and by availability and freshness{personal ? ', plus how well it matches your stack, interests, level and learning goals' : ''}. Bars show the strongest components.</p>
    <div className="card mt-6 flex flex-col gap-3 p-4 lg:flex-row lg:items-center">
      <label className="flex flex-1 items-center gap-2 rounded-xl border border-slate-200 px-3"><Search size={18} className="text-slate-400" /><input value={query} onChange={event => setQuery(event.target.value)} className="w-full py-3 outline-none" placeholder="Search title, text or labels" /></label>
      <select value={difficulty} onChange={event => setDifficulty(event.target.value)} className="rounded-xl border border-slate-200 px-3 py-3 text-sm font-bold">{['All', 'Easy', 'Medium', 'Hard'].map(level => <option key={level}>{level}</option>)}</select>
      {isSet ? <label className="inline-flex items-center gap-2 text-sm font-bold"><input type="checkbox" checked={personal} onChange={event => setPersonal(event.target.checked)} />Personalise</label>
        : <Link to="/profile" className="btn-secondary"><UserRound size={16} />Set up profile</Link>}
      {personal && <select value={mode} onChange={event => setMode(event.target.value)} className="rounded-xl border border-slate-200 px-3 py-3 text-sm font-bold">{MODES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>}
    </div>
    {loading && <Loading label="Scoring issues…" />}
    {error && <div className="mt-4"><ErrorMessage message={error} /></div>}
    {!loading && data && <>
      <p className="mt-6 text-sm font-semibold text-slate-500">{filtered.length} of {data.issues.length} issues</p>
      <div className="mt-4 grid gap-4 xl:grid-cols-2">{filtered.map(item => <RankedIssueCard item={item} owner={owner} repo={repo} weights={data.weights} key={item.issue.number} />)}</div>
      {!filtered.length && <div className="mt-4"><EmptyState message="No issues match your filters." /></div>}
    </>}
  </AppLayout>
}
