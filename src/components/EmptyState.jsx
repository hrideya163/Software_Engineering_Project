import { Inbox } from 'lucide-react'

export default function EmptyState({ message = 'Nothing to show yet.', icon: Icon = Inbox, children }) {
  return <div className="card flex flex-col items-center gap-3 p-10 text-center">
    <span className="grid h-11 w-11 place-items-center rounded-xl bg-slate-100 text-slate-400"><Icon size={20} /></span>
    <p className="max-w-md text-sm text-slate-500">{message}</p>
    {children}
  </div>
}
