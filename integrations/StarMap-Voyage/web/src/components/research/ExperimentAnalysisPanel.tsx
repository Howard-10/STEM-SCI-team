import type { ExperimentInsight } from '../../types'
import SectionCard from '../common/SectionCard'

interface ExperimentAnalysisPanelProps {
  insight: ExperimentInsight
}

function ExperimentAnalysisPanel({ insight }: ExperimentAnalysisPanelProps) {
  return (
    <SectionCard title="实验结果分析" description="基于输入的实验描述生成趋势解读与图表建议。">
      <div className="grid gap-4 xl:grid-cols-2">
        <div className="info-block">
          <h4>总体趋势</h4>
          <p>{insight.trend}</p>
        </div>
        <div className="info-block">
          <h4>最优方法</h4>
          <p>{insight.bestMethod}</p>
        </div>
        <div className="info-block">
          <h4>指标变化</h4>
          <p>{insight.metricChange}</p>
        </div>
        <div className="info-block">
          <h4>异常值说明</h4>
          <p>{insight.outlierNote}</p>
        </div>
        <div className="info-block">
          <h4>可能原因</h4>
          <ul className="list-disc pl-5">
            {insight.possibleReasons.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
        <div className="info-block">
          <h4>补充实验建议</h4>
          <ul className="list-disc pl-5">
            {insight.extraExperiments.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
        <div className="info-block xl:col-span-2">
          <h4>可写进论文的实验结论</h4>
          <p>{insight.paperConclusion}</p>
        </div>
      </div>

      <div className="mt-6 rounded-2xl border border-slate-200 bg-slate-50 p-5">
        <h4 className="text-base font-semibold text-slate-900">图表建议</h4>
        <div className="mt-3 grid gap-3 text-sm text-slate-600 md:grid-cols-2">
          <p>
            <strong className="text-slate-900">推荐图表类型：</strong>
            {insight.chartSuggestion.chartType}
          </p>
          <p>
            <strong className="text-slate-900">横轴：</strong>
            {insight.chartSuggestion.xAxis}
          </p>
          <p>
            <strong className="text-slate-900">纵轴：</strong>
            {insight.chartSuggestion.yAxis}
          </p>
          <p>
            <strong className="text-slate-900">图标题：</strong>
            {insight.chartSuggestion.title}
          </p>
        </div>
        <p className="mt-3 text-sm text-slate-600">
          <strong className="text-slate-900">需要突出的对比关系：</strong>
          {insight.chartSuggestion.highlight}
        </p>
        <pre className="mt-4 overflow-x-auto rounded-2xl bg-slate-900 p-4 text-xs leading-6 text-slate-100">
          <code>{insight.chartSuggestion.matplotlibSnippet}</code>
        </pre>
      </div>
    </SectionCard>
  )
}

export default ExperimentAnalysisPanel
