import { AlertTriangle, RotateCcw } from 'lucide-react'

export default function ErrorMessage({ message, onRetry, title }) {
  return <div className="flex items-start gap-3 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800" role="alert">
    <AlertTriangle size={18} className="mt-0.5 shrink-0" />
    <div className="min-w-0 flex-1">
      {title && <p className="font-extrabold">{title}</p>}
      <p className="font-semibold">{message}</p>
    </div>
    {onRetry && <button type="button" onClick={onRetry} className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-rose-200 bg-white px-2.5 py-1.5 text-xs font-bold text-rose-800 hover:bg-rose-100"><RotateCcw size={13} />Try again</button>}
  </div>
}
