import { useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import Button from '../components/common/Button'
import EmptyState from '../components/common/EmptyState'
import RecordDetailPanel from '../components/common/RecordDetailPanel'
import SectionCard from '../components/common/SectionCard'
import Layout from '../components/layout/Layout'
import Sidebar from '../components/layout/Sidebar'
import type { ExperimentRecord, HistoryRecordItem, Paper, ResearchIdea, WritingDraft } from '../types'
import {
  buildExperimentMarkdown,
  buildIdeaMarkdown,
  buildOverviewMarkdown,
  buildPaperMarkdown,
  buildWritingMarkdown,
  createMarkdownFilename,
  exportMarkdown,
} from '../utils/exportMarkdown'
import { formatDateTime, summarizeText } from '../utils/projectPresentation'
import {
  deleteExperimentFromProject,
  deleteIdeaFromProject,
  deleteOverviewFromProject,
  deletePaperFromProject,
  deleteWritingFromProject,
  getProjectById,
  getProjectHistory,
} from '../utils/storage'

const typeLabels: Record<HistoryRecordItem['type'], string> = {
  overview: '领域报告',
  paper: '论文精读',
  experiment: '实验分析',
  writing: '写作草稿',
  idea: '研究 Idea',
}

function HistoryPage() {
  const { id = '' } = useParams()
  const [project, setProject] = useState(getProjectById(id))
  const [selectedRecord, setSelectedRecord] = useState<HistoryRecordItem | null>(null)

  const history = useMemo(() => (project ? getProjectHistory(project.id) : []), [project])

  const sections = [
    { key: 'overview', title: '领域报告' },
    { key: 'paper', title: '论文精读卡片' },
    { key: 'experiment', title: '实验分析记录' },
    { key: 'writing', title: '写作草稿' },
    { key: 'idea', title: '研究 Idea' },
  ] as const

  const handleDelete = (record: HistoryRecordItem) => {
    if (!project) return
    if (!window.confirm(`确认删除这条${typeLabels[record.type]}记录吗？`)) return

    let updated
    switch (record.type) {
      case 'overview':
        updated = deleteOverviewFromProject(project.id)
        break
      case 'paper':
        updated = deletePaperFromProject(project.id, record.sourceId)
        break
      case 'experiment':
        updated = deleteExperimentFromProject(project.id, record.sourceId)
        break
      case 'writing':
        updated = deleteWritingFromProject(project.id, record.sourceId)
        break
      case 'idea':
        updated = deleteIdeaFromProject(project.id, record.sourceId)
        break
    }

    if (updated) {
      setProject(updated)
      if (selectedRecord?.id === record.id) {
        setSelectedRecord(null)
      }
    }
  }

  const handleExport = (record: HistoryRecordItem) => {
    if (!project) return

    switch (record.type) {
      case 'overview':
        exportMarkdown(
          createMarkdownFilename(project.title, '领域报告'),
          buildOverviewMarkdown(project, project.overviewReport),
        )
        break
      case 'paper':
        exportMarkdown(
          createMarkdownFilename(project.title, '论文精读'),
          buildPaperMarkdown(project, record.detail as Paper),
        )
        break
      case 'experiment':
        exportMarkdown(
          createMarkdownFilename(project.title, '实验分析'),
          buildExperimentMarkdown(project, record.detail as ExperimentRecord),
        )
        break
      case 'writing':
        exportMarkdown(
          createMarkdownFilename(project.title, '写作草稿'),
          buildWritingMarkdown(project, record.detail as WritingDraft),
        )
        break
      case 'idea':
        exportMarkdown(
          createMarkdownFilename(project.title, '研究Idea'),
          buildIdeaMarkdown(project, record.detail as ResearchIdea),
        )
        break
    }
  }

  return (
    <Layout
      sidebar={<Sidebar projectId={id} />}
      header={
        <div>
          <div className="text-sm font-semibold uppercase tracking-[0.2em] text-sky-700">History</div>
          <h1 className="mt-2 text-3xl font-semibold text-slate-950">项目成果记录</h1>
          <p className="mt-2 text-sm text-slate-500">集中查看并管理当前项目已经保存的报告、论文、实验、写作和 idea。</p>
        </div>
      }
    >
      {!project ? (
        <EmptyState title="未找到该项目" description="请返回项目列表重新进入有效项目。" />
      ) : (
        <>
          <div className="space-y-6">
            {sections.map((section) => {
              const records = history.filter((item) => item.type === section.key)
              return (
                <SectionCard
                  key={section.key}
                  title={section.title}
                  description={`当前共 ${records.length} 条记录`}
                >
                  {records.length === 0 ? (
                    <EmptyState
                      title={`${section.title}为空`}
                      description="当前项目还没有保存这一类成果，后续在对应模块中生成并保存后，这里会自动汇总。"
                    />
                  ) : (
                    <div className="space-y-3">
                      {records.map((record) => (
                        <article
                          key={record.id}
                          className="flex flex-col gap-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 lg:flex-row lg:items-start lg:justify-between"
                        >
                          <div className="min-w-0">
                            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-sky-700">
                              {typeLabels[record.type]}
                            </div>
                            <h3 className="mt-2 text-base font-semibold text-slate-900">{record.title}</h3>
                            <div className="mt-1 text-xs text-slate-400">{formatDateTime(record.createdAt)}</div>
                            <p className="mt-3 text-sm leading-6 text-slate-600">
                              {summarizeText(record.summary, 140)}
                            </p>
                          </div>
                          <div className="flex shrink-0 flex-wrap gap-2">
                            <Button variant="secondary" onClick={() => setSelectedRecord(record)}>
                              查看详情
                            </Button>
                            <Button variant="secondary" onClick={() => handleExport(record)}>
                              导出 Markdown
                            </Button>
                            <Button variant="ghost" onClick={() => handleDelete(record)}>
                              删除
                            </Button>
                          </div>
                        </article>
                      ))}
                    </div>
                  )}
                </SectionCard>
              )
            })}
          </div>

          <RecordDetailPanel
            open={Boolean(selectedRecord)}
            record={selectedRecord}
            onClose={() => setSelectedRecord(null)}
          />
        </>
      )}
    </Layout>
  )
}

export default HistoryPage
