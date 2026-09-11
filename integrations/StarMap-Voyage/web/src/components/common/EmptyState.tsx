import type { ReactNode } from 'react'

interface EmptyStateProps {
  title: string
  description: string
  action?: ReactNode
}

function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-6 py-12 text-center">
      <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
      <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-slate-500">{description}</p>
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  )
}

export default EmptyState
