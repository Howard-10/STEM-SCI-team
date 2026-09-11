import type {
  ExperimentRecord,
  HistoryRecordItem,
  OverviewReport,
  Paper,
  ResearchIdea,
  WritingDraft,
} from '../../types'
import { formatDateTime } from '../../utils/projectPresentation'
import Button from './Button'
import SectionCard from './SectionCard'
import PaperCard from '../research/PaperCard'

interface RecordDetailPanelProps {
  record?: HistoryRecordItem | null
  open: boolean
  onClose: () => void
}

function renderOverview(report: OverviewReport) {
  const sections = [
    ['领域背景', report.background],
    ['核心概念', report.coreConcepts.join(' / ')],
    ['主要研究任务', report.keyTasks.join(' / ')],
    ['主流方法', report.mainstreamMethods.join(' / ')],
    ['常用数据集', report.commonDatasets.join(' / ')],
    ['常用评价指标', report.commonMetrics.join(' / ')],
    ['当前挑战', report.challenges.join(' / ')],
    ['潜在研究切入点', report.entryPoints.join(' / ')],
    ['建议阅读路线', report.readingPath.join(' / ')],
  ]

  return (
    <div className="space-y-3">
      {sections.map(([title, content]) => (
        <div key={title} className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <div className="text-sm font-semibold text-slate-900">{title}</div>
          <div className="mt-2 text-sm leading-6 text-slate-600">{content}</div>
        </div>
      ))}
    </div>
  )
}

function renderExperiment(experiment: ExperimentRecord) {
  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
        <div className="text-sm font-semibold text-slate-900">原始结果</div>
        <div className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-600">
          {experiment.rawResult || '未填写'}
        </div>
      </div>
      <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
        <div className="text-sm font-semibold text-slate-900">分析内容</div>
        <div className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-600">
          {experiment.analysis}
        </div>
      </div>
      <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
        <div className="text-sm font-semibold text-slate-900">图表建议</div>
        <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs leading-6 text-slate-600">
          {experiment.chartSuggestion}
        </pre>
      </div>
    </div>
  )
}

function renderWriting(writing: WritingDraft) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
      <div className="text-sm font-semibold text-slate-900">写作内容</div>
      <div className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-600">
        {writing.content}
      </div>
    </div>
  )
}

function renderIdea(idea: ResearchIdea) {
  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
        <div className="text-sm font-semibold text-slate-900">描述</div>
        <div className="mt-2 text-sm leading-6 text-slate-600">{idea.description}</div>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-center">
          <div className="text-xs text-slate-500">创新性</div>
          <div className="mt-1 text-lg font-semibold text-slate-900">{idea.noveltyScore}</div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-center">
          <div className="text-xs text-slate-500">可行性</div>
          <div className="mt-1 text-lg font-semibold text-slate-900">{idea.feasibilityScore}</div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-center">
          <div className="text-xs text-slate-500">工作量</div>
          <div className="mt-1 text-lg font-semibold text-slate-900">{idea.workloadScore}</div>
        </div>
      </div>
    </div>
  )
}

function renderContent(record: HistoryRecordItem) {
  switch (record.type) {
    case 'overview':
      return renderOverview(record.detail as OverviewReport)
    case 'paper':
      return <PaperCard paper={record.detail as Paper} compact />
    case 'experiment':
      return renderExperiment(record.detail as ExperimentRecord)
    case 'writing':
      return renderWriting(record.detail as WritingDraft)
    case 'idea':
      return renderIdea(record.detail as ResearchIdea)
    default:
      return null
  }
}

function RecordDetailPanel({ record, open, onClose }: RecordDetailPanelProps) {
  if (!open || !record) return null

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-950/35">
      <button
        type="button"
        className="h-full flex-1 cursor-default"
        aria-label="Close detail panel"
        onClick={onClose}
      />
      <aside className="h-full w-full max-w-2xl overflow-y-auto bg-white p-6 shadow-2xl">
        <SectionCard
          title={record.title}
          description={`${record.type} · ${formatDateTime(record.createdAt)}`}
          action={
            <Button variant="ghost" onClick={onClose}>
              关闭
            </Button>
          }
        >
          {renderContent(record)}
        </SectionCard>
      </aside>
    </div>
  )
}

export default RecordDetailPanel
