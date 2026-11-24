import { Bookmark, Pencil, Plus, Sparkles, UserRound, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { feedbackUser, getFeedback, getRecommendations, getTrending } from '../api/contrimapApi'
import EmptyState from '../components/EmptyState'
import ErrorMessage from '../components/ErrorMessage'
import Loading from '../components/Loading'
import Page from '../components/Page'
import RankedIssueCard from '../components/RankedIssueCard'
import { useProfile } from '../hooks/useProfile'
import { parseRepository } from '../utils/helpers'

const MODES = [
  ['balanced', 'Best match', 'Issues that fit your stack, level and interests.'],
  ['learning', 'Learn something new', 'Issues that practise your learning goals, slightly above your comfort zone.'],
  ['quick_win', 'Quick wins', 'Well-scoped issues you are likely to finish and get merged.'],
]
const KEY = 'contrimap.watchlist.v1'
const MAX_REPOSITORIES = 6
const LANGUAGES = ['Python', 'TypeScript', 'JavaScript', 'Go', 'Rust', 'Java', 'C++', 'Ruby']

function Chips({ label, items, tone = 'bg-slate-100 text-slate-700' }) {
  if (!items?.length) return null
  return <div className="flex flex-wrap items-center gap-1.5"><span className="text-xs font-bold text-slate-500">{label}</span>{items.map(item => <span key={item} className={`rounded-full px-2 py-0.5 text-xs font-bold ${tone}`}>{item}</span>)}</div>
}

function ProfileSummary({ profile }) {
  return <section className="card flex flex-col gap-4 p-5 md:flex-row md:items-center md:justify-between">
    <div className="flex min-w-0 gap-4">
      <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-sky text-blue-700"><UserRound size={20} /></span>
      <div className="min-w-0 space-y-1.5">
        <p className="text-sm font-extrabold capitalize">{profile.level}{profile.login ? <span className="font-semibold normal-case text-slate-500"> · @{profile.login}</span> : null}{profile.time_budget_hours ? <span className="font-semibold normal-case text-slate-500"> · up to {profile.time_budget_hours} h</span> : null}</p>
        <Chips label="Stack" items={profile.tech_stack} tone="bg-sky text-ink" />
        <Chips label="Goals" items={profile.learning_goals} tone="bg-violet-50 text-violet-700" />
        <Chips label="Interests" items={profile.interests} />
      </div>
    </div>
    <Link to="/profile" className="btn-secondary shrink-0 py-2"><Pencil size={14} />Edit profile</Link>
  </section>
}

function RepositoryPicker({ repositories, setRepositories, suggestions }) {
  const [input, setInput] = useState('')
  const [error, setError] = useState('')
  const full = repositories.length >= MAX_REPOSITORIES
  const add = name => {
    if (!repositories.includes(name) && !full) setRepositories([...repositories, name])
  }
  const submit = event => {
    event.preventDefault()
    const parsed = parseRepository(input)
    if (!parsed) return setError('Use owner/name or a github.com URL.')
    add(`${parsed.owner}/${parsed.repo}`)
    setInput('')
    setError('')
  }
  const open = suggestions.filter(name => !repositories.includes(name)).slice(0, 6)
  return <section className="card p-5">
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <h2 className="font-extrabold">Repositories to search</h2>
      <span className="text-xs font-semibold text-slate-500">{repositories.length} of {MAX_REPOSITORIES}</span>
    </div>
    <div className="mt-3 flex flex-wrap gap-2">
      {repositories.map(name => <span key={name} className="inline-flex items-center gap-1.5 rounded-full bg-ink py-1 pl-3 pr-1.5 text-xs font-bold text-white">{name}<button type="button" onClick={() => setRepositories(repositories.filter(item => item !== name))} aria-label={`Remove ${name}`} className="rounded-full p-0.5 hover:bg-white/20"><X size={12} /></button></span>)}
      {!repositories.length && <span className="text-sm text-slate-500">Add at least one repository.</span>}
    </div>
    <form onSubmit={submit} className="mt-4 flex gap-2">
      <label htmlFor="add-repository" className="sr-only">Add a repository</label>
      <input id="add-repository" value={input} onChange={event => { setInput(event.target.value); setError('') }} disabled={full} placeholder={full ? 'Remove one to add another' : 'owner/name or GitHub URL'} className="min-w-0 flex-1 rounded-xl border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-blue-400 disabled:bg-slate-50" />
      <button className="btn-secondary py-2.5 disabled:opacity-50" disabled={full || !input.trim()}><Plus size={15} />Add</button>
    </form>
    {error && <p className="mt-2 text-xs font-semibold text-rose-700">{error}</p>}
    {open.length > 0 && !full && <div className="mt-4 flex flex-wrap items-center gap-1.5">
      <span className="text-xs font-bold text-slate-500">Trending in your stack:</span>
      {open.map(name => <button key={name} type="button" onClick={() => add(name)} className="inline-flex items-center gap-1 rounded-full border border-dashed border-slate-300 px-2.5 py-1 text-xs font-bold text-slate-600 hover:border-ink hover:text-ink"><Plus size={11} />{name}</button>)}
    </div>}
  </section>
}

function SavedIssues({ user, version }) {
  const [saved, setSaved] = useState([])
  useEffect(() => { if (user) getFeedback(user).then(data => setSaved(data.saved || [])).catch(() => setSaved([])) }, [user, version])
  if (!saved.length) return null
  return <section className="card p-5">
    <h2 className="inline-flex items-center gap-2 font-extrabold"><Bookmark size={16} />Saved for later</h2>
    <ul className="mt-3 divide-y divide-slate-100">{saved.slice(0, 8).map(item => {
      const [owner, repo] = item.repository.split('/')
      return <li key={`${item.repository}#${item.number}`} className="py-2"><Link to={`/repository/${owner}/${repo}/issues/${item.number}`} className="block text-sm hover:text-blue-700"><span className="mono text-xs text-slate-400">{item.repository}#{item.number}</span><span className="block truncate font-semibold">{item.title || 'Untitled issue'}</span></Link></li>
    })}</ul>
  </section>
}

export default function Recommendations() {
  const { profile, isSet } = useProfile()
  const [repositories, setRepositories] = useState(() => { try { return JSON.parse(window.localStorage.getItem(KEY) || '[]') } catch { return [] } })
  const [mode, setMode] = useState('balanced')
  const [suggestions, setSuggestions] = useState([])
  const [state, setState] = useState({ data: null, loading: false, error: '' })
  const [attempt, setAttempt] = useState(0)
  const [feedbackVersion, setFeedbackVersion] = useState(0)
  const language = useMemo(() => profile.tech_stack.find(item => LANGUAGES.some(name => name.toLowerCase() === item.toLowerCase())) || '', [profile.tech_stack])
  const user = feedbackUser(profile)

  useEffect(() => { try { window.localStorage.setItem(KEY, JSON.stringify(repositories)) } catch { /* ignore */ } }, [repositories])
  // Suggestions (and a starting list for first-time visitors) come from trending repositories in the user's main language.
  useEffect(() => {
    getTrending({ language, limit: 9 }).then(data => {
      const names = data.repositories.map(item => item.full_name)
      setSuggestions(names)
      setRepositories(previous => (previous.length ? previous : names.slice(0, 2)))
    }).catch(() => setSuggestions([]))
  }, [language])

  // Results follow the selection: re-ranked whenever the repositories, the mode or the profile change.
  const key = JSON.stringify([repositories, mode, profile, attempt])
  useEffect(() => {
    if (!isSet || !repositories.length) return setState({ data: null, loading: false, error: '' })
    let active = true
    const timer = setTimeout(() => {
      setState(previous => ({ ...previous, loading: true, error: '' }))
      getRecommendations(profile, repositories, mode)
        .then(data => active && setState({ data, loading: false, error: '' }))
        .catch(error => active && setState({ data: null, loading: false, error: error.message }))
    }, 400)
    return () => { active = false; clearTimeout(timer) }
  }, [key]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!isSet) return <Page eyebrow="For you" title="Issues picked for you.">
    <EmptyState icon={UserRound} message="Recommendations are based on your contributor profile: your stack, level, interests and learning goals. It takes a minute to set up, or you can import it from GitHub.">
      <Link to="/profile" className="btn-primary mt-2">Set up your profile</Link>
    </EmptyState>
  </Page>

  const data = state.data
  const errors = Object.entries(data?.errors || {})
  return <Page eyebrow="For you" title="Issues picked for you." description="Open issues from the repositories you choose, ranked by how well they fit your profile. Save issues to come back to them; hide the ones that are not for you and the ranking adapts.">
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="min-w-0 space-y-5">
        <ProfileSummary profile={profile} />
        <div role="tablist" aria-label="Ranking mode" className="grid gap-2 sm:grid-cols-3">
          {MODES.map(([value, label, hint]) => <button key={value} type="button" role="tab" aria-selected={mode === value} onClick={() => setMode(value)} className={`rounded-2xl border p-3 text-left transition ${mode === value ? 'border-ink bg-ink text-white' : 'border-slate-200 bg-white hover:border-slate-300'}`}>
            <span className="block text-sm font-extrabold">{label}</span>
            <span className={`mt-0.5 block text-xs leading-4 ${mode === value ? 'text-slate-300' : 'text-slate-500'}`}>{hint}</span>
          </button>)}
        </div>

        {state.loading && <Loading compact label="Ranking open issues. Repositories analysed for the first time take up to a minute." />}
        {state.error && <ErrorMessage message={state.error} onRetry={() => setAttempt(value => value + 1)} />}
        {!repositories.length && <EmptyState message="Add a repository on the right to see recommendations." />}
        {data && !state.loading && <>
          {errors.map(([name, message]) => <ErrorMessage key={name} title={name} message={message} />)}
          <p className="text-sm font-semibold text-slate-500">{data.issues.length} issues from {data.searched?.length ?? repositories.length} {data.searched?.length === 1 ? 'repository' : 'repositories'}{data.hidden ? ` · ${data.hidden} hidden by you` : ''}</p>
          {!data.issues.length && !errors.length && <EmptyState message="No open issues found in these repositories." />}
          <div className="grid gap-4 md:grid-cols-2">{data.issues.map(item => <RankedIssueCard key={`${item.repository}#${item.issue.number}`} item={item} weights={data.weights} onFeedback={() => setFeedbackVersion(value => value + 1)} />)}</div>
        </>}
      </div>

      <aside className="space-y-5 lg:sticky lg:top-24 lg:self-start">
        <RepositoryPicker repositories={repositories} setRepositories={setRepositories} suggestions={suggestions} />
        <SavedIssues user={user} version={feedbackVersion} />
        <p className="flex gap-2 px-1 text-xs leading-5 text-slate-500"><Sparkles size={14} className="mt-0.5 shrink-0" />Green tags name the strongest reasons for each score. Scores combine model estimates with your profile; they guide, they do not guarantee.</p>
      </aside>
    </div>
  </Page>
}
