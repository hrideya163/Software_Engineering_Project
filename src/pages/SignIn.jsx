import { Bookmark, Github, Info, ShieldCheck, UserRound } from 'lucide-react'
import { Link, Navigate, useSearchParams } from 'react-router-dom'
import { signIn } from '../api/authApi'
import Loading from '../components/Loading'
import Page from '../components/Page'
import { useApp } from '../context/AppContext'

export function GoogleIcon(props) {
  return <svg viewBox="0 0 18 18" width="18" height="18" aria-hidden="true" {...props}><path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92a8.78 8.78 0 0 0 2.68-6.62z" /><path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.81.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.71H.96v2.33A9 9 0 0 0 9 18z" /><path fill="#FBBC05" d="M3.97 10.71a5.4 5.4 0 0 1 0-3.42V4.96H.96a9 9 0 0 0 0 8.08l3.01-2.33z" /><path fill="#EA4335" d="M9 3.58c1.32 0 2.51.45 3.44 1.35l2.59-2.59A8.6 8.6 0 0 0 9 0 9 9 0 0 0 .96 4.96l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58z" /></svg>
}

const BENEFITS = [
  [UserRound, 'GitHub sign-in fills in your GitHub username, so your profile can be imported from your merged pull requests.'],
  [Bookmark, 'Issues you save or hide are remembered under your GitHub account instead of this browser only.'],
  [ShieldCheck, 'ContriMap only reads your public profile. Everything else works without signing in.'],
]

// Only in-app paths are accepted as a return target.
const safeNext = value => (value && value.startsWith('/') && !value.startsWith('//') ? value : '/')

export default function SignIn() {
  const { auth } = useApp()
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const notConfigured = params.get('error') === 'not_configured'

  if (auth.status === 'loading') return <Page width="max-w-lg"><Loading label="Checking your session…" /></Page>
  if (auth.status === 'signed-in' && !notConfigured) return <Navigate to={next} replace />

  const providers = [['github', 'Continue with GitHub', <Github key="g" size={18} />], ['google', 'Continue with Google', <GoogleIcon key="o" />]].filter(([name]) => auth.providers?.[name])
  return <Page width="max-w-lg">
    <div className="card p-7 md:p-8">
      <p className="eyebrow">Account</p>
      <h1 className="mt-2 text-2xl font-extrabold">Sign in to ContriMap</h1>
      <p className="mt-2 text-sm leading-6 text-slate-600">Signing in is optional. Repository analysis, issue ranking and recommendations all work without an account.</p>

      {auth.status === 'unavailable' && <p className="mt-6 flex gap-2 rounded-xl bg-amber-50 p-3 text-sm text-amber-800"><Info size={16} className="mt-0.5 shrink-0" />The ContriMap server can't be reached right now, so sign-in is unavailable.</p>}
      {(notConfigured || (auth.status === 'signed-out' && !providers.length)) && <p className="mt-6 flex gap-2 rounded-xl bg-sky p-3 text-sm text-ink"><Info size={16} className="mt-0.5 shrink-0" />Sign-in is not configured on this server. Add GitHub or Google OAuth credentials to the server's .env file to enable it.</p>}

      {providers.length > 0 && <div className="mt-6 space-y-3">
        {providers.map(([name, label, icon]) => <button key={name} type="button" onClick={() => signIn(name, next)} className={`flex w-full items-center justify-center gap-3 rounded-xl px-4 py-3 text-sm font-bold transition ${name === 'github' ? 'bg-ink text-white hover:bg-[#19365f]' : 'border border-slate-200 bg-white text-ink hover:bg-slate-50'}`}>{icon}{label}</button>)}
      </div>}

      <ul className="mt-7 space-y-3 border-t border-slate-100 pt-6">{BENEFITS.map(([Icon, text]) => <li key={text} className="flex gap-3 text-sm leading-6 text-slate-600"><Icon size={17} className="mt-0.5 shrink-0 text-blue-700" />{text}</li>)}</ul>
      <Link to={next} className="mt-6 inline-flex text-sm font-bold text-blue-700 hover:underline">Continue without signing in</Link>
    </div>
  </Page>
}
