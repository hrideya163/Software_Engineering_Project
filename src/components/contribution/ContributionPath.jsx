import { Check, Terminal } from 'lucide-react'
import { useEffect, useState } from 'react'

// Steps come from the backend (contrimap_ml/guidance.py); progress is remembered per issue in this browser.
// `guide` (step id -> {title, detail}) is the AI-written version of the steps; files and commands always come
// from the repository analysis. `action` is shown in the header (the "Explain with ..." control).
export default function ContributionPath({ path, storageKey, guide = null, action = null, writtenBy = null }) {
  const steps = (path?.steps || []).map(step => ({ ...step, ...(guide?.[step.id] || {}) }))
  const [done, setDone] = useState([])
  useEffect(() => {
    try { setDone(JSON.parse(window.localStorage.getItem(storageKey) || '[]')) } catch { setDone([]) }
  }, [storageKey])
  const toggle = id => setDone(previous => {
    const next = previous.includes(id) ? previous.filter(x => x !== id) : [...previous, id]
    try { window.localStorage.setItem(storageKey, JSON.stringify(next)) } catch { /* ignore */ }
    return next
  })
  if (!steps.length) return null
  return <section className="card overflow-hidden">
    <div className="border-b bg-[#f8fffd] p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="eyebrow text-emerald-700">Guided workflow</p>
          <h2 className="mt-1 text-xl font-extrabold">Your contribution path</h2>
          {writtenBy && <p className="mt-1 text-[11px] font-bold text-slate-400">steps written by {writtenBy} for this issue; commands and files come from the repository</p>}
        </div>
        {action}
      </div>
      {path.fits_time_budget === false && <p className="mt-2 text-xs font-semibold text-amber-700">The estimated effort exceeds the time budget in your profile.</p>}
    </div>
    <div className="p-5">
      <div className="mb-5 h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full bg-mint transition-all" style={{ width: `${done.length / steps.length * 100}%` }} /></div>
      <ol className="space-y-5">{steps.map((step, i) => <li key={step.id} className="flex gap-3">
        <button onClick={() => toggle(step.id)} aria-label={`Mark "${step.title}" done`} className={`grid h-7 w-7 shrink-0 place-items-center rounded-full border text-xs font-bold ${done.includes(step.id) ? 'border-mint bg-mint text-ink' : 'border-slate-300 text-slate-500'}`}>{done.includes(step.id) ? <Check size={15} /> : i + 1}</button>
        <div className="min-w-0 flex-1">
          <p className={`text-sm font-bold ${done.includes(step.id) ? 'text-slate-400 line-through' : 'text-ink'}`}>{step.title}</p>
          <p className="mt-1 text-sm leading-6 text-slate-600 [overflow-wrap:anywhere]">{step.detail}</p>
          {step.files?.length > 0 && <ul className="mt-2 space-y-1">{step.files.map(file => typeof file === 'string'
            ? <li key={file} className="mono truncate text-xs text-blue-800" title={file}>{file}</li>
            : <li key={file.path} className="text-xs"><span className="mono break-all text-blue-800">{file.path}</span> <span className="text-slate-500">- {file.why}</span></li>)}</ul>}
          {step.commands?.filter(Boolean).length > 0 && <div className="mt-2 space-y-1">{step.commands.filter(Boolean).map(command => <code key={command} className="mono flex items-start gap-2 rounded-lg bg-ink px-3 py-2 text-xs text-white"><Terminal size={12} className="mt-0.5 shrink-0 text-mint" /><span className="min-w-0 break-all">{command}</span></code>)}</div>}
        </div>
      </li>)}</ol>
    </div>
  </section>
}
