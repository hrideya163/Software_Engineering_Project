import Navbar from './Navbar'

// Shared shell for the non-repository pages: navigation, one content width, one header style.
export default function Page({ eyebrow, title, description, actions, width = 'max-w-6xl', children }) {
  return <>
    <Navbar />
    <main className={`mx-auto w-full ${width} px-5 py-10 md:py-12`}>
      {(title || eyebrow) && <PageHeader eyebrow={eyebrow} title={title} description={description} actions={actions} />}
      {children}
    </main>
  </>
}

export function PageHeader({ eyebrow, title, description, actions }) {
  return <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
    <div className="min-w-0 max-w-3xl">
      {eyebrow && <p className="eyebrow">{eyebrow}</p>}
      {title && <h1 className="mt-2 text-2xl font-extrabold leading-tight md:text-3xl">{title}</h1>}
      {description && <p className="mt-3 text-sm leading-6 text-slate-600">{description}</p>}
    </div>
    {actions && <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>}
  </div>
}
