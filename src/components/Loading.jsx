export default function Loading({ label = 'Loading…', compact = false }) {
  return <div className={`grid place-items-center ${compact ? 'py-10' : 'min-h-[35vh]'}`} role="status" aria-live="polite">
    <div className="text-center">
      <div className="mx-auto h-8 w-8 animate-spin rounded-full border-4 border-slate-200 border-t-ink" />
      <p className="mt-3 max-w-sm text-sm font-semibold text-slate-500">{label}</p>
    </div>
  </div>
}
