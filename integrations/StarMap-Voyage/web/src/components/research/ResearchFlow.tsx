const flowItems = [
  '领域入门',
  '文献精读',
  '论文对比',
  '研究空白',
  '想法推演',
  '代码复现',
  '实验分析',
  '写作输出',
]

function ResearchFlow() {
  return (
    <div className="grid gap-3 md:grid-cols-4">
      {flowItems.map((item, index) => (
        <div
          key={item}
          className="rounded-2xl border border-slate-200 bg-white/90 p-4 shadow-sm transition hover:-translate-y-0.5"
        >
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-sky-600">
            Step {index + 1}
          </div>
          <div className="mt-2 text-base font-semibold text-slate-900">{item}</div>
        </div>
      ))}
    </div>
  )
}

export default ResearchFlow
