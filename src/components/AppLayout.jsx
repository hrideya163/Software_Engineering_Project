import Navbar from './Navbar'
import Sidebar, { MobileRepositoryNav } from './Sidebar'

// Shell for repository pages: main navigation, repository section rail and one content area.
export default function AppLayout({ children }) {
  return <>
    <Navbar />
    <div className="mx-auto flex min-h-[calc(100vh-4rem)] max-w-[1600px]">
      <Sidebar />
      <main className="min-w-0 flex-1 px-5 py-6 md:p-8"><MobileRepositoryNav />{children}</main>
    </div>
  </>
}
