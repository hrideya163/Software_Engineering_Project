import { Plus, Sparkles, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getRecommendations, getTrending } from '../api/contrimapApi'
import EmptyState from '../components/EmptyState'
import ErrorMessage from '../components/ErrorMessage'
import Loading from '../components/Loading'
import Navbar from '../components/Navbar'
import RankedIssueCard from '../components/RankedIssueCard'
import { useProfile } from '../hooks/useProfile'
import { parseGitHubUrl } from '../utils/helpers'

const MODES = [['balanced', 'Balanced'], ['learning', 'Learning opportunities'], ['quick_win', 'Quick wins']]
const KEY = 'contrimap.watchlist.v1'

export default function Recommendations() {
  const { profile, isSet } = useProfile()
  const [repositories, setRepositories] = useState(() => { try { return JSON.parse(window.localStorage.getItem(KEY) || '[]') } catch { return [] } })
  const [input, setInput] = useState('')
  const [mode, setMode] = useState('balanced')
  const [state, setState] = useState({ data: null, loading: false, error: '' })
  useEffect(() => { try { window.localStorage.setItem(KEY, JSON.stringify(repositories)) } catch { /* ignore */ } }, [repositories])
  useEffect(() => {
    if (repositories.length) return
    // Seed the watch list with trending repositories matching the user's stack.
    getTrending({ language: profile.tech_stack.find(item => ['Python', 'TypeScript', 'JavaScript', 'Go', 'Rust', 'Java'].includes(item)) || '', limit: 3 })
      .then(data => setRepositories(data.repositories.slice(0, 3).map(r => r.full_name))).catch(() => {})
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const add = event => {
    event.preventDefault()
    const parsed = parseGitHubUrl(input.includes('github.com') ? input : `github.com/${input}`)
    if (parsed && repositories.length < 6) setRepositories([...new Set([...repositories, `${parsed.owner}/${parsed.repo}`])])
    setInput('')
  }
  const run = () => {
    setState({ data: null, loading: true, error: '' })
    getRecommendations(profile, repositories, mode).then(data => setState({ data, loading: false, error: '' })).catch(error => setState({ data: null, loading: false, error: error.message }))
  }
  return <><Navbar /><main className="mx-auto max-w-6xl px-5 py-12">
    <p className="eyebrow">Personalised recommendations</p>
    <h1 className="mt-2 text-3xl font-extrabold">Issues picked for you.</h1>
    {!isSet && <div className="mt-6 rounded-xl bg-amber-50 p-4 text-sm text-amber-800">Recommendations need a profile. <Link to="/profile" className="font-bold underline">Set up your stack, interests and goals</Link> first.</div>}
    <div className="card mt-6 p-5">
      <p className="text-sm font-bold">Repositories to search (up to 6)</p>
      <div className="mt-3 flex flex-wrap gap-2">{repositories.map(name => <span key={name} className="inline-flex items-center gap-1 rounded-full bg-sky px-3 py-1 text-xs font-bold text-ink">{name}<button onClick={() => setRepositories(repositories.filter(r => r !== name))} aria-label={`Remove ${name}`}><X size={12} /></button></span>)}</div>
      <form onSubmit={add} className="mt-3 flex gap-2"><input value={input} onChange={event => setInput(event.target.value)} placeholder="owner/repo or GitHub URL" className="flex-1 rounded-xl border border-slate-200 px-3 py-2.5 text-sm outline-none" /><button className="btn-secondary py-2.5"><Plus size={15} />Add</button></form>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <select value={mode} onChange={event => setMode(event.target.value)} className="rounded-xl border border-slate-200 px-3 py-2.5 text-sm font-bold">{MODES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
        <button onClick={run} disabled={!isSet || !repositories.length || state.loading} className="btn-primary disabled:opacity-50"><Sparkles size={16} />Find issues</button>
        {mode === 'learning' && <p className="text-xs text-slate-500">Learning mode favours issues that practise your learning goals at a level slightly above your comfort zone.</p>}
      </div>
    </div>
    {state.loading && <Loading label="Snapshotting repositories and scoring issues - first run per repository takes a little longer…" />}
    {state.error && <div className="mt-5"><ErrorMessage message={state.error} /></div>}
    {state.data && <>
      {Object.entries(state.data.errors).map(([name, message]) => <div key={name} className="mt-4"><ErrorMessage message={`${name}: ${message}`} /></div>)}
      {!state.data.issues.length && <div className="mt-5"><EmptyState message="No open issues found in these repositories." /></div>}
      <div className="mt-6 grid gap-4 lg:grid-cols-2">{state.data.issues.map(item => <RankedIssueCard key={`${item.repository}#${item.issue.number}`} item={item} />)}</div>
    </>}
  </main></>
}
