import { ArrowRight, BrainCircuit, Database, GitBranch, History, Network, Route, Sparkles, Target } from 'lucide-react'
import { Link } from 'react-router-dom'
import Page from '../components/Page'

const STEPS = [
  [GitBranch, 'Prepare the repository', 'ContriMap reads the file tree and source code with a lightweight Git clone (no token needed) and caches a snapshot per commit. Progress is shown while this runs the first time.'],
  [Network, 'Map the code', 'Imports and test links become a knowledge graph. PageRank finds the core files and community detection groups them into modules.'],
  [Target, 'Locate likely files', 'A learning-to-rank model scores every file against the issue, then re-ranks the top 50 after reading their code.'],
  [BrainCircuit, 'Estimate difficulty and effort', 'Models trained on thousands of resolved issues estimate difficulty with a confidence level and give an effort range.'],
  [History, 'Find similar past fixes', 'Recently closed issues and merged pull requests are searched for similar work and the files those fixes changed.'],
  [Sparkles, 'Rank and personalise', 'Open issues are ranked by readiness, clarity and availability, and, with a profile, by how well they match your skills and goals.'],
  [Route, 'Guide the contribution', 'Each issue gets a reading order, the tests to run, setup commands and a plain-language explanation.'],
]

export default function HowItWorks() {
  return <Page width="max-w-4xl" eyebrow="How it works" title="From a repository to a confident first pull request." description="ContriMap brings repository context, skill requirements, likely impact and practical next steps together, so choosing an issue feels less like guesswork. Every prediction is measured on repositories the models never saw.">
    <ol className="relative space-y-4 border-l-2 border-slate-200 pl-6">
      {STEPS.map(([Icon, title, text], index) => <li key={title} className="relative">
        <span className="absolute -left-[37px] top-5 grid h-6 w-6 place-items-center rounded-full bg-ink text-[11px] font-extrabold text-white">{index + 1}</span>
        <div className="card flex gap-4 p-5">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-sky text-blue-700"><Icon size={19} /></span>
          <div><h2 className="font-extrabold">{title}</h2><p className="mt-1 text-sm leading-6 text-slate-600">{text}</p></div>
        </div>
      </li>)}
    </ol>
    <div className="card mt-8 flex flex-col gap-4 p-6 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex gap-3"><Database size={20} className="mt-0.5 shrink-0 text-blue-700" /><p className="text-sm leading-6 text-slate-600">Predictions are guidance, not guarantees: every model is evaluated on repositories it never saw, against simple baselines.</p></div>
      <div className="flex shrink-0 gap-2"><Link to="/#analyze" className="btn-primary">Try it <ArrowRight size={16} /></Link></div>
    </div>
  </Page>
}
