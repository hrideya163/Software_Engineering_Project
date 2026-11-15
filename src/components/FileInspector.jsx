import { ArrowDownLeft, ArrowUpRight, Braces, ExternalLink, FileCode2, FlaskConical, GitCommitHorizontal, X } from 'lucide-react'
import { useState } from 'react'
import { getFileDetails } from '../api/contrimapApi'
import { useAsync } from '../hooks/useProfile'

const TABS = [['code', 'Code'], ['links', 'Links'], ['symbols', 'Symbols'], ['history', 'History']]
const KIND_STYLE = { class: 'bg-violet-100 text-violet-700', function: 'bg-blue-100 text-blue-700', method: 'bg-sky text-ink', type: 'bg-emerald-100 text-emerald-700' }

function PathList({ title, icon: Icon, paths, total, onNavigate }) {
  return <div className="mt-4 first:mt-0">
    <p className="inline-flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide text-slate-500"><Icon size={12} />{title} ({total ?? paths.length})</p>
    {paths.length ? <ul className="mt-1.5 space-y-0.5">{paths.map(path => <li key={path}>
      <button type="button" onClick={() => onNavigate(path)} className="mono w-full truncate rounded-lg px-2 py-1 text-left text-xs text-ink hover:bg-slate-50" title={path}>{path}</button>
    </li>)}</ul> : <p className="mt-1 px-2 text-xs text-slate-400">None resolved.</p>}
  </div>
}

/** Side panel for one file: code preview, imports/dependents, defined symbols and who uses them, recent commits. */
export default function FileInspector({ owner, repo, path, onNavigate, onClose, badge }) {
  const [tab, setTab] = useState('code')
  const { data, loading, error } = useAsync(() => getFileDetails(owner, repo, path), [owner, repo, path])
  const blob = line => `${data?.html_url}${line ? `#L${line}` : ''}`
  return <div>
    <div className="flex items-start justify-between gap-2">
      <div className="min-w-0">
        <p className="eyebrow inline-flex items-center gap-1.5"><FileCode2 size={13} />File inspector</p>
        <p className="mono mt-1 break-all text-sm font-medium text-ink">{path}</p>
      </div>
      <button type="button" onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-ink" aria-label="Close inspector"><X size={16} /></button>
    </div>
    {badge}
    {loading && <p className="mt-4 text-xs text-slate-500">Reading the file and its dependents…</p>}
    {error && <p className="mt-4 text-xs text-amber-700">{error}</p>}
    {data && <>
      <div className="mt-3 flex flex-wrap gap-1.5 text-[11px] font-bold">
        {data.language && <span className="rounded-full bg-slate-100 px-2 py-0.5">{data.language}</span>}
        <span className="rounded-full bg-slate-100 px-2 py-0.5">{data.lines.toLocaleString()} lines</span>
        <span className="rounded-full bg-sky px-2 py-0.5 text-ink" title="Position by import-graph PageRank">more central than {Math.round(data.importance_percentile * 100)}% of files</span>
        {data.is_test && <span className="rounded-full bg-violet-100 px-2 py-0.5 text-violet-700">test</span>}
      </div>
      <div className="mt-4 flex gap-1 border-b border-slate-200">{TABS.map(([id, label]) => <button key={id} type="button" onClick={() => setTab(id)} className={`border-b-2 px-2.5 py-2 text-xs font-bold ${tab === id ? 'border-ink text-ink' : 'border-transparent text-slate-500 hover:text-ink'}`}>{label}</button>)}</div>
      <div className="mt-3">
        {tab === 'code' && (data.preview ? <>
          <pre className="mono max-h-[420px] overflow-auto rounded-xl bg-[#0f1b2e] p-3 text-[11px] leading-[1.55] text-slate-200">{data.preview.split('\n').map((line, index) => <div key={index} className="flex"><span className="mr-3 w-7 shrink-0 select-none text-right text-slate-500">{index + 1}</span><span className="whitespace-pre">{line || ' '}</span></div>)}</pre>
          {data.preview_truncated && <p className="mt-2 text-[11px] text-slate-400">First 120 of {data.lines.toLocaleString()} lines.</p>}
        </> : <p className="text-xs text-slate-500">The code could not be read from the git snapshot.</p>)}
        {tab === 'links' && <>
          <PathList title="Imports" icon={ArrowUpRight} paths={data.imports} total={data.imports_total} onNavigate={onNavigate} />
          <PathList title="Imported by" icon={ArrowDownLeft} paths={data.dependents} total={data.dependents_total} onNavigate={onNavigate} />
          <PathList title="Tests" icon={FlaskConical} paths={data.tests} onNavigate={onNavigate} />
        </>}
        {tab === 'symbols' && <>
          {data.symbols.length ? <ul className="max-h-[220px] space-y-0.5 overflow-auto">{data.symbols.filter(s => !s.private).slice(0, 40).map(symbol => <li key={symbol.name}>
            <a href={blob(symbol.line)} target="_blank" rel="noreferrer" className="flex items-center gap-2 rounded-lg px-2 py-1 hover:bg-slate-50">
              <span className={`w-14 shrink-0 rounded px-1 text-center text-[9px] font-bold uppercase ${KIND_STYLE[symbol.kind] || 'bg-slate-100'}`}>{symbol.kind}</span>
              <span className="mono min-w-0 flex-1 truncate text-xs text-ink">{symbol.name}</span><span className="text-[10px] text-slate-400">L{symbol.line}</span>
            </a>
          </li>)}</ul> : <p className="text-xs text-slate-500">No functions or classes detected.</p>}
          {data.symbol_dependents.length > 0 && <>
            <p className="mt-4 inline-flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide text-slate-500"><Braces size={12} />Which files use which names</p>
            <ul className="mt-1.5 space-y-2">{data.symbol_dependents.slice(0, 8).map(item => <li key={item.name} className="text-xs">
              <span className="mono font-bold text-ink">{item.name}</span>
              <span className="text-slate-400"> used by </span>
              {item.used_by.slice(0, 4).map((file, index) => <button key={file} type="button" onClick={() => onNavigate(file)} className="mono text-blue-800 hover:underline">{index ? ', ' : ''}{file.split('/').pop()}</button>)}
              {item.used_by.length > 4 && <span className="text-slate-400"> +{item.used_by.length - 4}</span>}
            </li>)}</ul>
            <p className="mt-2 text-[10px] text-slate-400">Name matches in importing files; not type-checked.</p>
          </>}
        </>}
        {tab === 'history' && <>
          {data.related_issues.length > 0 && <><p className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Related closed issues</p><ul className="mt-1.5 mb-4 space-y-1">{data.related_issues.map(item => <li key={item.number}><a href={item.html_url} target="_blank" rel="noreferrer" className="text-xs text-blue-800 hover:underline">#{item.number} {item.title}</a></li>)}</ul></>}
          {data.commits.length ? <ul className="space-y-2">{data.commits.map(commit => <li key={commit.sha} className="flex gap-2 text-xs">
            <GitCommitHorizontal size={14} className="mt-0.5 shrink-0 text-slate-400" />
            <div className="min-w-0"><a href={commit.html_url} target="_blank" rel="noreferrer" className="line-clamp-2 text-ink hover:text-blue-800">{commit.message}</a><p className="text-[10px] text-slate-400">{commit.author} · {commit.date?.slice(0, 10)}{commit.pull_request ? ` · PR #${commit.pull_request}` : ''}</p></div>
          </li>)}</ul> : <p className="text-xs text-slate-500">{data.history_error || 'No commit history available.'}</p>}
        </>}
      </div>
      <a href={blob()} target="_blank" rel="noreferrer" className="btn-secondary mt-4 w-full py-2"><ExternalLink size={14} />Open on GitHub</a>
    </>}
  </div>
}
