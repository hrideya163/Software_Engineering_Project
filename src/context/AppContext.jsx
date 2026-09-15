import { createContext, useContext, useState } from 'react'
const AppContext = createContext()
export function AppProvider({ children }) { const [currentRepository, setCurrentRepository] = useState(null); const [issues, setIssues] = useState([]); const [loading, setLoading] = useState(false); const value = { currentRepository, setCurrentRepository, issues, setIssues, loading, setLoading }; return <AppContext.Provider value={value}>{children}</AppContext.Provider> }
export const useApp = () => useContext(AppContext)
