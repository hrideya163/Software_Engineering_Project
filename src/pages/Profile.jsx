import { Github, Save } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { getContributor } from '../api/contrimapApi'
import ErrorMessage from '../components/ErrorMessage'
import Navbar from '../components/Navbar'
import { EMPTY_PROFILE, useProfile } from '../hooks/useProfile'

const split = value => value.split(',').map(item => item.trim()).filter(Boolean)
const join = list => (list || []).join(', ')

export default function Profile() {
  const { profile, save } = useProfile()
  const [form, setForm] = useState({ ...profile, tech_stack: join(profile.tech_stack), interests: join(profile.interests), learning_goals: join(profile.learning_goals) })
  const [login, setLogin] = useState(profile.login || '')
  const [importing, setImporting] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const update = (key, value) => setForm(previous => ({ ...previous, [key]: value }))
  const submit = event => {
    event.preventDefault()
    save({ ...EMPTY_PROFILE, level: form.level, tech_stack: split(form.tech_stack), interests: split(form.interests), learning_goals: split(form.learning_goals), time_budget_hours: form.time_budget_hours ? Number(form.time_budget_hours) : null, login: login || null })
    setMessage('Saved in this browser. Rankings and analyses now use your profile.')
  }
  const importFromGitHub = () => {
    if (!login) return
    setImporting(true)
    setError('')
    getContributor(login)
      .then(data => {
        const suggestion = data.suggested_profile
        setForm(previous => ({ ...previous, level: suggestion.level, tech_stack: join([...new Set([...split(previous.tech_stack), ...suggestion.tech_stack])]), interests: join([...new Set([...split(previous.interests), ...suggestion.interests])]) }))
        setMessage(`Imported from ${data.login}: ${data.merged_pull_requests} merged pull requests, top languages ${data.top_languages.map(l => l.name).join(', ') || 'n/a'}. Review and save.`)
      })
      .catch(err => setError(err.message))
      .finally(() => setImporting(false))
  }
  const field = 'mt-2 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-blue-400'
  return <><Navbar /><main className="mx-auto max-w-3xl px-5 py-12">
    <p className="eyebrow">Your contributor profile</p>
    <h1 className="mt-2 text-3xl font-extrabold">Tell ContriMap what you want to work on.</h1>
    <p className="mt-3 text-sm leading-6 text-slate-600">Used to personalise issue ranking: stack match, interest similarity, difficulty fit for your level, learning opportunities for your goals and estimated merge odds. Stored only in this browser.</p>
    <div className="card mt-8 flex flex-col gap-3 p-4 sm:flex-row sm:items-end">
      <label className="flex-1 text-sm font-bold">GitHub username<input value={login} onChange={event => setLogin(event.target.value.trim())} placeholder="octocat" className={field} /></label>
      <button type="button" onClick={importFromGitHub} disabled={!login || importing} className="btn-secondary"><Github size={16} />{importing ? 'Importing…' : 'Import from GitHub'}</button>
      {login && <Link to={`/contributors/${login}`} className="text-xs font-bold text-blue-700 sm:mb-3">View profile</Link>}
    </div>
    {error && <div className="mt-4"><ErrorMessage message={error} /></div>}
    <form onSubmit={submit} className="card mt-5 space-y-5 p-6">
      <label className="block text-sm font-bold">Skill level
        <select value={form.level} onChange={event => update('level', event.target.value)} className={field}>
          <option value="beginner">Beginner - new to open source or this stack</option>
          <option value="intermediate">Intermediate - a few contributions</option>
          <option value="advanced">Advanced - comfortable in large codebases</option>
        </select>
      </label>
      <label className="block text-sm font-bold">Technical stack <span className="font-normal text-slate-500">(comma separated)</span><input value={form.tech_stack} onChange={event => update('tech_stack', event.target.value)} placeholder="Python, React, TypeScript, Docker" className={field} /></label>
      <label className="block text-sm font-bold">Interests<input value={form.interests} onChange={event => update('interests', event.target.value)} placeholder="data visualisation, developer tooling, performance" className={field} /></label>
      <label className="block text-sm font-bold">Learning goals<input value={form.learning_goals} onChange={event => update('learning_goals', event.target.value)} placeholder="Rust, testing, type hints" className={field} /></label>
      <label className="block text-sm font-bold">Time per contribution (hours, optional)<input type="number" min="0" max="500" value={form.time_budget_hours ?? ''} onChange={event => update('time_budget_hours', event.target.value)} className={field} /></label>
      <button className="btn-primary"><Save size={16} />Save profile</button>
      {message && <p className="text-sm font-semibold text-emerald-700">{message}</p>}
    </form>
  </main></>
}
