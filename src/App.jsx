import { useEffect } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import Contributor from './pages/Contributor'
import Home from './pages/Home'
import HowItWorks from './pages/HowItWorks'
import IssueAnalysis from './pages/IssueAnalysis'
import IssueExplorer from './pages/IssueExplorer'
import KnowledgeGraph from './pages/KnowledgeGraph'
import ModelCard from './pages/ModelCard'
import Profile from './pages/Profile'
import Recommendations from './pages/Recommendations'
import RepositoryDashboard from './pages/RepositoryDashboard'
import SignIn from './pages/SignIn'

// New pages start at the top (except in-page anchors such as /#analyze).
function ScrollToTop() {
  const { pathname, hash } = useLocation()
  useEffect(() => { if (!hash) window.scrollTo(0, 0) }, [pathname, hash])
  return null
}

export default function App() {
  return <>
    <ScrollToTop />
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/how-it-works" element={<HowItWorks />} />
      <Route path="/about" element={<Navigate to="/how-it-works" replace />} />
      <Route path="/sign-in" element={<SignIn />} />
      <Route path="/profile" element={<Profile />} />
      <Route path="/recommendations" element={<Recommendations />} />
      <Route path="/model-card" element={<ModelCard />} />
      <Route path="/contributors/:login" element={<Contributor />} />
      <Route path="/repository/:owner/:repo" element={<RepositoryDashboard />} />
      <Route path="/repository/:owner/:repo/issues" element={<IssueExplorer />} />
      <Route path="/repository/:owner/:repo/issues/:issueId" element={<IssueAnalysis />} />
      <Route path="/repository/:owner/:repo/visualizer" element={<KnowledgeGraph />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  </>
}
