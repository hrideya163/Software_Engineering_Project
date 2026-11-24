import { BarChart3, ExternalLink, GitPullRequest, Network } from 'lucide-react'
import { NavLink, useParams } from 'react-router-dom'

function repositoryLinks(owner, repo) {
  const base = `/repository/${owner}/${repo}`
  return [['Overview', base, BarChart3, true], ['Issues', `${base}/issues`, GitPullRequest, false], ['Visualizer', `${base}/visualizer`, Network, true]]
}

// The one place repository pages link to each other (desktop: left rail; small screens: tabs above the page).
export default function Sidebar() {
  const { owner, repo } = useParams()
  if (!owner) return null
  return <aside className="hidden w-56 shrink-0 border-r border-slate-200 bg-white lg:block">
    <div className="sticky top-16 p-4">
      <p className="px-3 text-[11px] font-bold uppercase tracking-[.16em] text-slate-400">Repository</p>
      <p className="mono mt-1 truncate px-3 text-sm font-medium text-ink" title={`${owner}/${repo}`}>{owner}/<b>{repo}</b></p>
      <nav className="mt-4 space-y-1" aria-label="Repository sections">
        {repositoryLinks(owner, repo).map(([label, to, Icon, end]) => <NavLink end={end} key={label} to={to} className={({ isActive }) => `flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-bold transition ${isActive ? 'bg-sky text-ink' : 'text-slate-500 hover:bg-slate-50 hover:text-ink'}`}><Icon size={17} />{label}</NavLink>)}
      </nav>
      <a href={`https://github.com/${owner}/${repo}`} target="_blank" rel="noreferrer" className="mt-4 flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold text-slate-500 hover:bg-slate-50 hover:text-ink"><ExternalLink size={16} />Open on GitHub</a>
    </div>
  </aside>
}

export function MobileRepositoryNav() {
  const { owner, repo } = useParams()
  if (!owner) return null
  return <nav className="-mx-5 -mt-6 mb-6 border-b border-slate-200 bg-white px-5 md:-mx-8 md:-mt-8 md:px-8 lg:hidden" aria-label="Repository sections">
    <p className="mono truncate pt-3 text-xs text-slate-500">{owner}/<b className="text-ink">{repo}</b></p>
    <div className="flex gap-1 overflow-x-auto">
      {repositoryLinks(owner, repo).map(([label, to, Icon, end]) => <NavLink end={end} key={label} to={to} className={({ isActive }) => `flex items-center gap-2 whitespace-nowrap border-b-2 px-3 py-3 text-sm font-bold ${isActive ? 'border-ink text-ink' : 'border-transparent text-slate-500'}`}><Icon size={16} />{label}</NavLink>)}
    </div>
  </nav>
}
