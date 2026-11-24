import { ArrowRight, Gauge, History, Network, Sparkles, Target } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import AnimatedLogoBackground from '../components/AnimatedLogoBackground'
import Navbar from '../components/Navbar'
import TrendingRepos from '../components/TrendingRepos'
import { parseRepository } from '../utils/helpers'

const CAPABILITIES = [
  [Target, 'Likely files to change', 'A two-stage ranker reads the code of its top candidates and points to where a fix is likely to land.'],
  [Gauge, 'Difficulty and effort', 'Easy, medium or hard with a confidence level, plus a realistic effort range.'],
  [History, 'Similar past fixes', 'Closed issues and merged pull requests that solved something similar, with the files they changed.'],
  [Network, 'Architecture and impact', 'An interactive map of how the code fits together and what a change could affect.'],
]

export default function Home() {
  const [value, setValue] = useState('')
  const [error, setError] = useState('')
  const navigate = useNavigate()
  const location = useLocation()
  const input = useRef(null)
  useEffect(() => { if (location.hash === '#analyze') input.current?.focus() }, [location.hash])
  const submit = event => {
    event.preventDefault()
    const result = parseRepository(value)
    if (!result) return setError('Enter a GitHub repository as owner/name or a github.com URL, for example pallets/click.')
    navigate(`/repository/${result.owner}/${result.repo}`)
  }
  return <>
    <Navbar />
    <main>
      <section className="relative overflow-hidden bg-[#091322] px-5 py-20 text-center md:py-24">
        <AnimatedLogoBackground />
        <div className="relative z-10 mx-auto max-w-3xl">
          <p className="eyebrow text-sky-300">Open-source contribution guide</p>
          <h1 className="mt-5 text-4xl font-extrabold tracking-tight text-white md:text-6xl">Find your next <span className="text-sky-300">open-source</span> contribution.</h1>
          <p className="mx-auto mt-6 max-w-2xl text-base leading-7 text-slate-300">ContriMap ranks a repository's open issues, shows where each fix is likely to land, how hard it is and what similar fixes looked like, so you can choose with confidence.</p>
          <form id="analyze" onSubmit={submit} className="mx-auto mt-8 flex max-w-2xl flex-col gap-3 rounded-2xl bg-white p-2.5 shadow-soft sm:flex-row" noValidate>
            <label htmlFor="repository" className="sr-only">GitHub repository</label>
            <input id="repository" ref={input} value={value} onChange={event => { setValue(event.target.value); setError('') }} placeholder="owner/name or github.com URL" autoComplete="off" className="min-w-0 flex-1 rounded-xl px-4 py-3 outline-none" aria-invalid={Boolean(error)} aria-describedby={error ? 'repository-error' : undefined} />
            <button className="btn-primary">Analyze repository <ArrowRight size={17} /></button>
          </form>
          {error && <p id="repository-error" className="mt-3 text-sm font-semibold text-rose-300">{error}</p>}
          <p className="mt-5 text-sm text-slate-400">Try <button type="button" onClick={() => navigate('/repository/pallets/click')} className="font-bold text-white hover:text-sky-300">pallets/click</button> or pick a trending repository below.</p>
        </div>
      </section>

      <TrendingRepos />

      <section className="border-t border-slate-200 bg-white px-5 py-16">
        <div className="mx-auto max-w-6xl">
          <p className="eyebrow">What you get for every issue</p>
          <h2 className="mt-3 max-w-2xl text-3xl font-extrabold">Context before code.</h2>
          <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{CAPABILITIES.map(([Icon, title, text]) => <div key={title} className="rounded-2xl border border-slate-200 p-5">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-sky text-blue-700"><Icon size={19} /></span>
            <h3 className="mt-4 font-extrabold">{title}</h3>
            <p className="mt-2 text-sm leading-6 text-slate-600">{text}</p>
          </div>)}</div>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link to="/recommendations" className="btn-primary"><Sparkles size={16} />Get issues picked for you</Link>
            <Link to="/model-card" className="btn-secondary">See how accurate the models are</Link>
          </div>
        </div>
      </section>
    </main>
  </>
}
