import type { PropsWithChildren, ReactNode } from 'react'
import Navbar from './Navbar'

interface LayoutProps {
  sidebar?: ReactNode
  header?: ReactNode
}

function Layout({ sidebar, header, children }: PropsWithChildren<LayoutProps>) {
  return (
    <div className="min-h-screen bg-gradient-to-b from-indigo-50/60 via-white to-white">
      <Navbar />
      <main className="mx-auto flex max-w-7xl flex-col gap-6 px-4 pt-6 pb-8 sm:px-6 lg:px-8">
        {header}
        {sidebar ? (
          <div className="flex flex-col gap-6 lg:flex-row">
            {sidebar}
            <div className="min-w-0 flex-1">{children}</div>
          </div>
        ) : (
          children
        )}
      </main>
    </div>
  )
}

export default Layout
