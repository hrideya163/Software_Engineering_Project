import { ChevronDown, Compass, LogIn, LogOut, Menu, UserRound, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import { useApp } from '../context/AppContext'

export const NAV_LINKS = [['Explore', '/', true], ['For You', '/recommendations'], ['Profile', '/profile'], ['How It Works', '/how-it-works']]
const PROVIDER_NAMES = { github: 'GitHub', google: 'Google' }

export function Avatar({ user, size = 32 }) {
  const initials = (user?.name || user?.login || '?').split(/[\s@._-]+/).filter(Boolean).slice(0, 2).map(part => part[0].toUpperCase()).join('')
  return user?.avatarUrl
    ? <img src={user.avatarUrl} alt="" width={size} height={size} className="shrink-0 rounded-full ring-1 ring-slate-200" style={{ width: size, height: size }} />
    : <span className="grid shrink-0 place-items-center rounded-full bg-sky text-xs font-extrabold text-ink" style={{ width: size, height: size }}>{initials}</span>
}

function AccountMenu({ onNavigate }) {
  const { auth, signOut } = useApp()
  const location = useLocation()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return
    const close = event => { if (!ref.current?.contains(event.target)) setOpen(false) }
    const escape = event => event.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', escape) }
  }, [open])

  if (auth.status === 'loading') return <span className="h-9 w-24 animate-pulse rounded-xl bg-slate-100" aria-hidden="true" />
  if (auth.status !== 'signed-in') {
    // Without a configured provider there is nothing to sign in to; the app works fully signed-out.
    if (!auth.configured) return null
    const next = `${location.pathname}${location.search}`
    return <Link to={`/sign-in?next=${encodeURIComponent(next)}`} onClick={onNavigate} className="btn-secondary py-2"><LogIn size={16} />Sign in</Link>
  }
  const user = auth.user
  return <div className="relative" ref={ref}>
    <button type="button" onClick={() => setOpen(!open)} aria-haspopup="menu" aria-expanded={open} className="flex items-center gap-2 rounded-xl py-1 pl-1 pr-2 hover:bg-slate-100">
      <Avatar user={user} />
      <span className="max-w-[140px] truncate text-sm font-bold">{user.name || user.login}</span>
      <ChevronDown size={14} className="text-slate-400" />
    </button>
    {open && <div role="menu" className="absolute right-0 z-50 mt-2 w-64 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-soft">
      <div className="flex items-center gap-3 border-b border-slate-100 p-4">
        <Avatar user={user} size={40} />
        <div className="min-w-0"><p className="truncate text-sm font-extrabold">{user.name || user.login}</p><p className="truncate text-xs text-slate-500">{user.login} · {PROVIDER_NAMES[user.provider] || user.provider}</p></div>
      </div>
      <Link role="menuitem" to="/profile" onClick={() => { setOpen(false); onNavigate?.() }} className="flex items-center gap-2 px-4 py-3 text-sm font-semibold hover:bg-slate-50"><UserRound size={16} />Contributor profile</Link>
      <button role="menuitem" type="button" onClick={() => { setOpen(false); onNavigate?.(); signOut() }} className="flex w-full items-center gap-2 border-t border-slate-100 px-4 py-3 text-left text-sm font-semibold text-rose-700 hover:bg-rose-50"><LogOut size={16} />Sign out</button>
    </div>}
  </div>
}

function Notice() {
  const { notice, setNotice } = useApp()
  useEffect(() => {
    if (!notice) return
    const timer = setTimeout(() => setNotice(null), 6000)
    return () => clearTimeout(timer)
  }, [notice, setNotice])
  if (!notice) return null
  const [tone, text] = notice
  const style = tone === 'error' ? 'bg-rose-50 text-rose-800 border-rose-200' : tone === 'success' ? 'bg-emerald-50 text-emerald-800 border-emerald-200' : 'bg-sky text-ink border-blue-100'
  return <div role="status" className={`border-b ${style}`}>
    <div className="mx-auto flex max-w-[1600px] items-center justify-between gap-3 px-5 py-2.5 text-sm font-semibold">
      <span>{text}</span>
      <button type="button" onClick={() => setNotice(null)} aria-label="Dismiss" className="rounded p-1 hover:bg-black/5"><X size={14} /></button>
    </div>
  </div>
}

const linkClass = ({ isActive }) => `rounded-lg px-3 py-2 text-sm font-semibold transition ${isActive ? 'bg-sky text-ink' : 'text-slate-600 hover:bg-slate-50 hover:text-ink'}`

export default function Navbar() {
  const [open, setOpen] = useState(false)
  const location = useLocation()
  useEffect(() => setOpen(false), [location.pathname])
  return <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/95 backdrop-blur">
    <nav className="mx-auto flex h-16 max-w-[1600px] items-center justify-between gap-4 px-5" aria-label="Main">
      <Link to="/" className="flex items-center gap-2 font-extrabold text-ink"><span className="grid h-9 w-9 place-items-center rounded-xl bg-ink text-mint"><Compass size={20} /></span>ContriMap</Link>
      <div className="hidden items-center gap-1 lg:flex">{NAV_LINKS.map(([name, to, end]) => <NavLink key={to} to={to} end={end} className={linkClass}>{name}</NavLink>)}</div>
      <div className="hidden lg:block"><AccountMenu /></div>
      <button type="button" className="rounded-lg p-2 hover:bg-slate-100 lg:hidden" onClick={() => setOpen(!open)} aria-label={open ? 'Close menu' : 'Open menu'} aria-expanded={open}>{open ? <X /> : <Menu />}</button>
    </nav>
    {open && <div className="border-t border-slate-200 px-5 pb-4 pt-2 lg:hidden">
      <div className="flex flex-col">{NAV_LINKS.map(([name, to, end]) => <NavLink key={to} to={to} end={end} className={linkClass}>{name}</NavLink>)}</div>
      <div className="mt-3 border-t border-slate-100 pt-3"><AccountMenu onNavigate={() => setOpen(false)} /></div>
    </div>}
    <Notice />
  </header>
}
