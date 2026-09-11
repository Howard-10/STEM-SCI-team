import type { ResearchIdea } from '../../types'

interface IdeaCardProps {
  idea: ResearchIdea
}

function IdeaCard({ idea }: IdeaCardProps) {
  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h4 className="text-base font-semibold text-slate-900">{idea.title}</h4>
      <p className="mt-2 text-sm leading-6 text-slate-600">{idea.description}</p>
      <dl className="mt-4 grid grid-cols-3 gap-3 text-center text-sm">
        <div className="rounded-xl bg-slate-50 p-3">
          <dt className="text-slate-500">创新性</dt>
          <dd className="mt-1 text-lg font-semibold text-slate-900">{idea.noveltyScore}</dd>
        </div>
        <div className="rounded-xl bg-slate-50 p-3">
          <dt className="text-slate-500">可行性</dt>
          <dd className="mt-1 text-lg font-semibold text-slate-900">{idea.feasibilityScore}</dd>
        </div>
        <div className="rounded-xl bg-slate-50 p-3">
          <dt className="text-slate-500">工作量</dt>
          <dd className="mt-1 text-lg font-semibold text-slate-900">{idea.workloadScore}</dd>
        </div>
      </dl>
    </article>
  )
}

export default IdeaCard
