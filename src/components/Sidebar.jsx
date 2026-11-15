import { BarChart3, GitPullRequest, Network } from 'lucide-react'
import { NavLink, useParams } from 'react-router-dom'

function repositoryLinks(owner, repo) {
  const base = `/repository/${owner}/${repo}`
  return [['Dashboard', base, BarChart3, true], ['Issues', `${base}/issues`, GitPullRequest, false], ['Visualizer', `${base}/visualizer`, Network, true]]
}

export default function Sidebar() {
  const { owner, repo } = useParams()
  if (!owner) return null
  return <aside className="hidden w-60 shrink-0 border-r border-slate-200 bg-white p-4 lg:block">
    <p className="eyebrow mb-4 truncate px-3" title={`${owner}/${repo}`}>{owner}/{repo}</p>
    {repositoryLinks(owner, repo).map(([label, to, Icon, end]) => <NavLink end={end} key={label} to={to} className={({ isActive }) => `mb-1 flex items-center gap-3 rounded-xl px-3 py-3 text-sm font-bold ${isActive ? 'bg-sky text-ink' : 'text-slate-500 hover:bg-slate-50'}`}><Icon size={18} />{label}</NavLink>)}
  </aside>
}

// Small screens hide the sidebar; the same repository links appear as tabs above the page.
export function MobileRepositoryNav() {
  const { owner, repo } = useParams()
  if (!owner) return null
  return <nav className="sticky top-0 z-20 -mx-5 -mt-5 mb-5 border-b border-slate-200 bg-white/95 px-5 backdrop-blur md:-mx-8 md:-mt-8 md:px-8 lg:hidden" aria-label="Repository sections">
    <p className="eyebrow truncate pt-3">{owner}/{repo}</p>
    <div className="flex gap-1 overflow-x-auto">
      {repositoryLinks(owner, repo).map(([label, to, Icon, end]) => <NavLink end={end} key={label} to={to} className={({ isActive }) => `flex items-center gap-2 whitespace-nowrap border-b-2 px-3 py-3 text-sm font-bold ${isActive ? 'border-ink text-ink' : 'border-transparent text-slate-500'}`}><Icon size={16} />{label}</NavLink>)}
    </div>
  </nav>
}
