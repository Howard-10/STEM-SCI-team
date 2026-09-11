import type { ReproductionGuide } from '../../types'
import SectionCard from '../common/SectionCard'

interface ReproductionDebugPanelProps {
  guide: ReproductionGuide
}

function ReproductionDebugPanel({ guide }: ReproductionDebugPanelProps) {
  return (
    <SectionCard title="复现与 Debug 建议" description="第一版先用 mock 输出承接 baseline 复现与环境排障流程。">
      <div className="grid gap-4 xl:grid-cols-2">
        <div className="info-block xl:col-span-2">
          <h4>仓库目标判断</h4>
          <p>{guide.repoGoal}</p>
        </div>
        <div className="info-block">
          <h4>README 分析</h4>
          <ul className="list-disc pl-5">
            {guide.readmeSummary.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
        <div className="info-block">
          <h4>Mock Debug 建议</h4>
          <ul className="list-disc pl-5">
            {guide.debugSuggestions.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <div className="rounded-2xl border border-slate-200 bg-slate-50 p-5">
          <h4 className="text-base font-semibold text-slate-900">环境配置命令展示区</h4>
          <pre className="mt-3 overflow-x-auto rounded-2xl bg-slate-900 p-4 text-xs leading-6 text-slate-100">
            <code>{guide.environmentCommands.join('\n')}</code>
          </pre>
        </div>
        <div className="info-block">
          <h4>下一步排查建议</h4>
          <ol className="list-decimal pl-5">
            {guide.nextSteps.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ol>
        </div>
      </div>
    </SectionCard>
  )
}

export default ReproductionDebugPanel
