import type { PropsWithChildren, ReactNode } from 'react'

interface SectionCardProps {
  title: string
  description?: string
  action?: ReactNode
  className?: string
}

function SectionCard({
  title,
  description,
  action,
  className = '',
  children,
}: PropsWithChildren<SectionCardProps>) {
  return (
    <section className={`rounded-2xl border border-slate-200 bg-white p-6 shadow-sm ${className}`}>
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
          {description ? <p className="mt-1 text-sm text-slate-500">{description}</p> : null}
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}

export default SectionCard
