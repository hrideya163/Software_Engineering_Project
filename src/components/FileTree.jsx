import { ChevronDown, ChevronRight, FileCode2, Folder } from 'lucide-react'
import { useState } from 'react'

function TreeNode({ node, depth }) {
  const [open, setOpen] = useState(depth < 1 || node.highlighted > 0)
  const isDirectory = node.type === 'directory'
  const pad = { paddingLeft: depth * 14 }
  if (!isDirectory) return <div style={pad} className={`flex items-center gap-1.5 py-0.5 text-xs ${node.rank ? 'font-bold text-rose-700' : 'text-slate-600'}`}>
    <FileCode2 size={12} className="shrink-0" /><span className="mono truncate">{node.name}</span>{node.rank && <span className="rounded bg-rose-100 px-1.5 text-[10px]">#{node.rank}</span>}
  </div>
  return <div>
    <button onClick={() => setOpen(!open)} style={pad} className={`flex w-full items-center gap-1.5 py-0.5 text-left text-xs ${node.highlighted ? 'font-bold text-ink' : 'text-slate-500'}`}>
      {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}<Folder size={12} className="shrink-0" /><span className="mono truncate">{node.name || '/'}</span>{node.highlighted > 0 && <span className="text-[10px] text-rose-600">{node.highlighted}</span>}
    </button>
    {open && <>{node.children.map(child => <TreeNode key={child.path} node={child} depth={depth + 1} />)}{node.hidden_children > 0 && <p style={{ paddingLeft: (depth + 1) * 14 }} className="py-0.5 text-[11px] text-slate-400">+{node.hidden_children} more</p>}</>}
  </div>
}

// Repository tree with the issue's predicted files highlighted (expanded along their paths).
export default function FileTree({ tree }) {
  if (!tree) return null
  return <div className="max-h-[420px] overflow-auto">{tree.children.map(child => <TreeNode key={child.path} node={child} depth={0} />)}</div>
}
