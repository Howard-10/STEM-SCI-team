import { Link } from 'react-router-dom'
import Button from '../common/Button'

interface ModuleEntryCardProps {
  title: string
  description: string
  to: string
  badge?: string
}

function ModuleEntryCard({ title, description, to, badge }: ModuleEntryCardProps) {
  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-base font-semibold text-slate-900">{title}</h3>
        {badge ? <span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-500">{badge}</span> : null}
      </div>
      <p className="mt-3 text-sm leading-6 text-slate-600">{description}</p>
      <div className="mt-5">
        <Link to={to}>
          <Button variant="secondary">进入模块</Button>
        </Link>
      </div>
    </article>
  )
}

export default ModuleEntryCard
