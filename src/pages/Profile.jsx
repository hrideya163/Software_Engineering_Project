import { CheckCircle2, Github, Loader2, RotateCcw, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { getContributor } from '../api/contrimapApi'
import ErrorMessage from '../components/ErrorMessage'
import { Avatar } from '../components/Navbar'
import Page from '../components/Page'
import { useApp } from '../context/AppContext'
import { EMPTY_PROFILE, useProfile } from '../hooks/useProfile'

const LEVELS = [['beginner', 'Beginner', 'New to open source or to this stack'], ['intermediate', 'Intermediate', 'A few merged contributions'], ['advanced', 'Advanced', 'Comfortable in large codebases']]
const LEVEL_LABEL = Object.fromEntries(LEVELS.map(([value, label]) => [value, label]))
const SUGGESTIONS = {
  tech_stack: ['Python', 'JavaScript', 'TypeScript', 'React', 'Go', 'Rust', 'Java', 'Docker'],
  interests: ['Developer tooling', 'Web frameworks', 'Data science', 'Performance', 'Documentation', 'Security'],
  learning_goals: ['Testing', 'Type hints', 'Rust', 'CI/CD', 'Async programming', 'Accessibility'],
}
const normalise = profile => ({ ...EMPTY_PROFILE, ...profile, tech_stack: [...(profile.tech_stack || [])], interests: [...(profile.interests || [])], learning_goals: [...(profile.learning_goals || [])], login: profile.login || '' })
const comparable = form => JSON.stringify({ ...form, login: form.login || null, time_budget_hours: form.time_budget_hours ? Number(form.time_budget_hours) : null })

// Skills and topics as removable tags: type and press Enter (or a comma), Backspace removes the last one.
function TagInput({ id, values, onChange, placeholder, suggestions = [] }) {
  const [draft, setDraft] = useState('')
  const add = raw => {
    const value = raw.trim().replace(/,$/, '').trim()
    if (value && !values.some(item => item.toLowerCase() === value.toLowerCase())) onChange([...values, value])
    setDraft('')
  }
  const remaining = suggestions.filter(item => !values.some(value => value.toLowerCase() === item.toLowerCase())).slice(0, 6)
  return <div>
    <div className="flex min-h-[44px] flex-wrap items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-2 py-1.5 focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-100">
      {values.map(value => <span key={value} className="inline-flex items-center gap-1 rounded-lg bg-sky py-1 pl-2.5 pr-1 text-xs font-bold text-ink">{value}
        <button type="button" onClick={() => onChange(values.filter(item => item !== value))} className="rounded p-0.5 text-slate-500 hover:bg-white hover:text-ink" aria-label={`Remove ${value}`}><X size={12} /></button>
      </span>)}
      <input id={id} value={draft} onChange={event => event.target.value.endsWith(',') ? add(event.target.value) : setDraft(event.target.value)}
        onKeyDown={event => {
          if (event.key === 'Enter') { event.preventDefault(); add(draft) }
          if (event.key === 'Backspace' && !draft && values.length) onChange(values.slice(0, -1))
        }}
        onBlur={() => draft && add(draft)} placeholder={values.length ? '' : placeholder} className="min-w-[140px] flex-1 bg-transparent px-1 py-1 text-sm outline-none" />
    </div>
    {remaining.length > 0 && <div className="mt-2 flex flex-wrap gap-1.5">{remaining.map(item => <button key={item} type="button" onClick={() => add(item)} className="rounded-full border border-dashed border-slate-300 px-2.5 py-0.5 text-xs font-semibold text-slate-500 hover:border-ink hover:text-ink">+ {item}</button>)}</div>}
  </div>
}

// Settings-style row: what the setting is on the left, the control on the right.
function Section({ title, description, children, last }) {
  return <div className={`grid gap-4 px-6 py-6 md:grid-cols-[240px_1fr] md:gap-8 ${last ? '' : 'border-b border-slate-100'}`}>
    <div><h2 className="text-sm font-extrabold text-ink">{title}</h2>{description && <p className="mt-1 text-xs leading-5 text-slate-500">{description}</p>}</div>
    <div className="min-w-0">{children}</div>
  </div>
}

export default function Profile() {
  const { profile, save, isSet } = useProfile()
  const { auth } = useApp()
  const [form, setForm] = useState(() => normalise(profile))
  const [importing, setImporting] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  // A GitHub sign-in (or a profile restored from the server) can arrive after the page has loaded.
  useEffect(() => { setForm(normalise(profile)) }, [profile]) // eslint-disable-line react-hooks/exhaustive-deps

  const saved = useMemo(() => comparable(normalise(profile)), [profile])
  const dirty = comparable(form) !== saved
  const update = (key, value) => { setForm(previous => ({ ...previous, [key]: value })); setNotice('') }
  const toProfile = () => ({ ...EMPTY_PROFILE, level: form.level, tech_stack: form.tech_stack, interests: form.interests, learning_goals: form.learning_goals, time_budget_hours: form.time_budget_hours ? Number(form.time_budget_hours) : null, login: form.login.trim() || null })
  const submit = event => {
    event?.preventDefault()
    save(toProfile())
    setNotice('Profile saved.')
  }
  const reset = () => {
    const cleared = { ...EMPTY_PROFILE, login: profile.login }
    save(cleared, { sync: 'force' })
    setForm(normalise(cleared))
    setNotice('Profile reset.')
  }
  const importFromGitHub = () => {
    const login = form.login.trim()
    if (!login) return
    setImporting(true)
    setError('')
    getContributor(login)
      .then(data => {
        const suggestion = data.suggested_profile
        const merge = (current, extra) => [...current, ...extra.filter(item => !current.some(value => value.toLowerCase() === String(item).toLowerCase()))]
        setForm(previous => ({ ...previous, level: suggestion.level, tech_stack: merge(previous.tech_stack, suggestion.tech_stack), interests: merge(previous.interests, suggestion.interests) }))
        setNotice(`Imported from @${data.login}: ${data.merged_pull_requests} merged pull requests. Review the changes, then save.`)
      })
      .catch(err => setError(err.message))
      .finally(() => setImporting(false))
  }

  const user = auth.status === 'signed-in' ? auth.user : null
  const displayName = user?.name || form.login || 'Your contributor profile'
  return <Page width="max-w-4xl" eyebrow="Settings" title="Profile" description="Used to personalise issue rankings and recommendations. Saved in this browser and, when the server has storage, under your account.">
    {/* Identity */}
    <section className="card flex flex-col gap-5 p-6 sm:flex-row sm:items-center">
      <Avatar user={user || { name: form.login || 'You' }} size={64} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-lg font-extrabold text-ink">{displayName}</p>
        <p className="mt-0.5 truncate text-sm text-slate-500">{form.login ? `@${form.login}` : 'No GitHub account linked'}{user ? ` · signed in with ${user.provider === 'google' ? 'Google' : 'GitHub'}` : ''}</p>
        <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] font-bold">
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600">{LEVEL_LABEL[form.level]}</span>
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600">{form.tech_stack.length} skills</span>
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600">{form.learning_goals.length} learning goals</span>
        </div>
      </div>
      {form.login && <Link to={`/contributors/${form.login}`} className="btn-secondary shrink-0 py-2"><Github size={15} />Public activity</Link>}
    </section>

    {error && <div className="mt-5"><ErrorMessage message={error} /></div>}

    <form onSubmit={submit} className="card mt-6 overflow-hidden">
      <Section title="GitHub account" description="Link a username to import your languages and interests from merged pull requests, and to keep saved issues under your account.">
        <div className="flex flex-col gap-2 sm:flex-row">
          <label htmlFor="login" className="sr-only">GitHub username</label>
          <div className="flex flex-1 items-center rounded-xl border border-slate-200 bg-white focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-100">
            <span className="pl-3 text-sm text-slate-400">github.com/</span>
            <input id="login" value={form.login} onChange={event => update('login', event.target.value.trim())} placeholder="username" autoComplete="username" className="min-w-0 flex-1 bg-transparent py-2.5 pr-3 text-sm outline-none" />
          </div>
          <button type="button" onClick={importFromGitHub} disabled={!form.login || importing} className="btn-secondary py-2.5 disabled:opacity-50">{importing ? <Loader2 size={15} className="animate-spin" /> : <Github size={15} />}{importing ? 'Importing…' : 'Import from GitHub'}</button>
        </div>
        {auth.status === 'signed-out' && auth.configured && <p className="mt-2 text-xs text-slate-500"><Link to="/sign-in?next=%2Fprofile" className="font-bold text-blue-700 hover:underline">Sign in with GitHub</Link> to fill this in automatically.</p>}
      </Section>

      <Section title="Experience level" description="Matches issue difficulty to your experience.">
        <div className="grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label="Experience level">
          {LEVELS.map(([value, label, hint]) => <label key={value} className={`cursor-pointer rounded-xl border p-3 transition ${form.level === value ? 'border-ink bg-sky ring-1 ring-ink' : 'border-slate-200 hover:border-slate-300'}`}>
            <input type="radio" name="level" value={value} checked={form.level === value} onChange={() => update('level', value)} className="sr-only" />
            <span className="block text-sm font-bold text-ink">{label}</span><span className="mt-0.5 block text-xs leading-4 text-slate-500">{hint}</span>
          </label>)}
        </div>
      </Section>

      <Section title="Skills" description="Languages, frameworks and tools you already use. Issues that need them rank higher.">
        <TagInput id="skills" values={form.tech_stack} onChange={value => update('tech_stack', value)} placeholder="Add a skill and press Enter" suggestions={SUGGESTIONS.tech_stack} />
      </Section>

      <Section title="Interests" description="Areas you would enjoy working on.">
        <TagInput id="interests" values={form.interests} onChange={value => update('interests', value)} placeholder="Add an interest and press Enter" suggestions={SUGGESTIONS.interests} />
      </Section>

      <Section title="Learning goals" description="Skills you want to practise. The learning mode favours issues that use them.">
        <TagInput id="goals" values={form.learning_goals} onChange={value => update('learning_goals', value)} placeholder="Add a goal and press Enter" suggestions={SUGGESTIONS.learning_goals} />
      </Section>

      <Section title="Availability" description="Optional. Issues likely to take longer than this are flagged." last>
        <div className="flex items-center gap-2">
          <label htmlFor="hours" className="sr-only">Hours per contribution</label>
          <input id="hours" type="number" min="0" max="500" value={form.time_budget_hours ?? ''} onChange={event => update('time_budget_hours', event.target.value)} placeholder="—" className="w-28 rounded-xl border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100" />
          <span className="text-sm text-slate-500">hours per contribution</span>
        </div>
      </Section>

      {/* Save bar: stays in view while there are unsaved changes. */}
      <div className={`sticky bottom-0 flex flex-wrap items-center justify-between gap-3 border-t px-6 py-4 transition ${dirty ? 'border-amber-200 bg-amber-50' : 'border-slate-100 bg-slate-50'}`}>
        <p className="text-sm font-semibold">{dirty ? <span className="text-amber-800">You have unsaved changes.</span> : notice ? <span className="inline-flex items-center gap-1.5 text-emerald-700"><CheckCircle2 size={15} />{notice}</span> : <span className="text-slate-500">All changes saved.</span>}</p>
        <div className="flex gap-2">
          {dirty && <button type="button" onClick={() => { setForm(normalise(profile)); setNotice('') }} className="btn-secondary py-2">Discard</button>}
          <button className="btn-primary py-2 disabled:opacity-50" disabled={!dirty}>Save changes</button>
        </div>
      </div>
    </form>

    {isSet && <section className="mt-6 flex flex-col gap-3 rounded-2xl border border-rose-200 p-6 sm:flex-row sm:items-center sm:justify-between">
      <div><h2 className="text-sm font-extrabold text-ink">Reset profile</h2><p className="mt-1 text-xs text-slate-500">Clears your level, skills, interests, goals and availability. Saved and hidden issues are kept.</p></div>
      <button type="button" onClick={reset} className="inline-flex shrink-0 items-center gap-2 rounded-xl border border-rose-200 bg-white px-4 py-2 text-sm font-bold text-rose-700 hover:bg-rose-50"><RotateCcw size={15} />Reset profile</button>
    </section>}
  </Page>
}
