import { CheckCircle2, Github, RotateCcw, Save, Sparkles } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getContributor } from '../api/contrimapApi'
import ErrorMessage from '../components/ErrorMessage'
import Page from '../components/Page'
import { useApp } from '../context/AppContext'
import { EMPTY_PROFILE, useProfile } from '../hooks/useProfile'
import { SignedInBadge } from './SignIn'

const split = value => value.split(',').map(item => item.trim()).filter(Boolean)
const join = list => (list || []).join(', ')
const toForm = profile => ({ ...profile, tech_stack: join(profile.tech_stack), interests: join(profile.interests), learning_goals: join(profile.learning_goals), login: profile.login || '' })
const LEVELS = [['beginner', 'Beginner', 'New to open source or to this stack'], ['intermediate', 'Intermediate', 'A few merged contributions'], ['advanced', 'Advanced', 'Comfortable in large codebases']]

export default function Profile() {
  const { profile, save, isSet } = useProfile()
  const { auth } = useApp()
  const [form, setForm] = useState(() => toForm(profile))
  const [importing, setImporting] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  // A GitHub sign-in can fill in the username after the page has loaded.
  useEffect(() => { if (profile.login && !form.login) setForm(previous => ({ ...previous, login: profile.login })) }, [profile.login]) // eslint-disable-line react-hooks/exhaustive-deps

  const update = (key, value) => { setForm(previous => ({ ...previous, [key]: value })); setMessage('') }
  const toProfile = () => ({ ...EMPTY_PROFILE, level: form.level, tech_stack: split(form.tech_stack), interests: split(form.interests), learning_goals: split(form.learning_goals), time_budget_hours: form.time_budget_hours ? Number(form.time_budget_hours) : null, login: form.login.trim() || null })
  const dirty = JSON.stringify(toProfile()) !== JSON.stringify({ ...EMPTY_PROFILE, ...profile })
  const submit = event => {
    event.preventDefault()
    save(toProfile())
    setMessage('Saved in this browser. Rankings and analyses now use your profile.')
  }
  const reset = () => { save(EMPTY_PROFILE); setForm(toForm(EMPTY_PROFILE)); setMessage('Profile cleared.') }
  const importFromGitHub = () => {
    const login = form.login.trim()
    if (!login) return
    setImporting(true)
    setError('')
    getContributor(login)
      .then(data => {
        const suggestion = data.suggested_profile
        setForm(previous => ({ ...previous, level: suggestion.level, tech_stack: join([...new Set([...split(previous.tech_stack), ...suggestion.tech_stack])]), interests: join([...new Set([...split(previous.interests), ...suggestion.interests])]) }))
        setMessage(`Imported from @${data.login}: ${data.merged_pull_requests} merged pull requests${data.top_languages.length ? `, mostly ${data.top_languages.map(l => l.name).slice(0, 3).join(', ')}` : ''}. Review the fields, then save.`)
      })
      .catch(err => setError(err.message))
      .finally(() => setImporting(false))
  }
  const field = 'mt-2 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm font-normal outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100'

  return <Page width="max-w-5xl" eyebrow="Contributor profile" title="Tell ContriMap what you want to work on." description="Your profile personalises issue ranking and For You recommendations. It is stored only in this browser." actions={<SignedInBadge />}>
    <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
      <form onSubmit={submit} className="space-y-5">
        <section className="card p-6">
          <h2 className="font-extrabold">Start from GitHub</h2>
          <p className="mt-1 text-sm text-slate-500">Import your level, languages and interests from public merged pull requests.</p>
          <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
            <label className="flex-1 text-sm font-bold">GitHub username<input value={form.login} onChange={event => update('login', event.target.value.trim())} placeholder="octocat" className={field} autoComplete="username" /></label>
            <button type="button" onClick={importFromGitHub} disabled={!form.login || importing} className="btn-secondary disabled:opacity-50"><Github size={16} />{importing ? 'Importing…' : 'Import'}</button>
          </div>
          {form.login && <Link to={`/contributors/${form.login}`} className="mt-3 inline-flex text-xs font-bold text-blue-700 hover:underline">View @{form.login}'s extracted skills</Link>}
          {error && <div className="mt-4"><ErrorMessage message={error} /></div>}
        </section>

        <section className="card space-y-5 p-6">
          <fieldset>
            <legend className="text-sm font-bold">Experience level</legend>
            <div className="mt-2 grid gap-2 sm:grid-cols-3">{LEVELS.map(([value, label, hint]) => <label key={value} className={`cursor-pointer rounded-xl border p-3 transition ${form.level === value ? 'border-ink bg-sky' : 'border-slate-200 hover:border-slate-300'}`}>
              <input type="radio" name="level" value={value} checked={form.level === value} onChange={() => update('level', value)} className="sr-only" />
              <span className="block text-sm font-bold">{label}</span><span className="mt-0.5 block text-xs text-slate-500">{hint}</span>
            </label>)}</div>
          </fieldset>
          <label className="block text-sm font-bold">Technical stack <span className="font-normal text-slate-500">(comma separated)</span><input value={form.tech_stack} onChange={event => update('tech_stack', event.target.value)} placeholder="Python, React, TypeScript, Docker" className={field} /></label>
          <label className="block text-sm font-bold">Interests<input value={form.interests} onChange={event => update('interests', event.target.value)} placeholder="developer tooling, data visualisation, performance" className={field} /></label>
          <label className="block text-sm font-bold">Learning goals<input value={form.learning_goals} onChange={event => update('learning_goals', event.target.value)} placeholder="Rust, testing, type hints" className={field} /></label>
          <label className="block text-sm font-bold">Time per contribution <span className="font-normal text-slate-500">(hours, optional)</span><input type="number" min="0" max="500" value={form.time_budget_hours ?? ''} onChange={event => update('time_budget_hours', event.target.value)} className={`${field} sm:max-w-[180px]`} /></label>
          <div className="flex flex-wrap items-center gap-3 border-t border-slate-100 pt-5">
            <button className="btn-primary disabled:opacity-50" disabled={!dirty}><Save size={16} />Save profile</button>
            {isSet && <button type="button" onClick={reset} className="btn-secondary"><RotateCcw size={15} />Clear</button>}
            {message && <p className="inline-flex items-center gap-1.5 text-sm font-semibold text-emerald-700"><CheckCircle2 size={15} />{message}</p>}
          </div>
        </section>
      </form>

      <aside className="space-y-4 self-start lg:sticky lg:top-24">
        <section className="card p-5 text-sm leading-6 text-slate-600">
          <h2 className="font-extrabold text-ink">How it is used</h2>
          <ul className="mt-3 list-disc space-y-1.5 pl-5">
            <li><b className="text-ink">Stack</b>: issues that need skills you have rank higher.</li>
            <li><b className="text-ink">Level</b>: difficulty is matched to your experience.</li>
            <li><b className="text-ink">Learning goals</b>: the learning mode favours issues that practise them.</li>
            <li><b className="text-ink">Time</b>: issues likely to take longer are flagged.</li>
          </ul>
        </section>
        <Link to="/recommendations" className={`btn-primary w-full ${isSet ? '' : 'pointer-events-none opacity-50'}`} aria-disabled={!isSet}><Sparkles size={16} />See issues for you</Link>
        {auth.status === 'signed-out' && auth.configured && <p className="text-center text-xs text-slate-500"><Link to="/sign-in?next=%2Fprofile" className="font-bold text-blue-700">Sign in with GitHub</Link> to fill in your username automatically.</p>}
      </aside>
    </div>
  </Page>
}
