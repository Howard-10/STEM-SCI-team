import { useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import Button from '../components/common/Button'
import EmptyState from '../components/common/EmptyState'
import SectionCard from '../components/common/SectionCard'
import { useAsyncGeneration } from '../hooks/useAsyncGeneration'
import Layout from '../components/layout/Layout'
import Sidebar from '../components/layout/Sidebar'
import { aiService } from '../services/ai'
import type { OverviewReport } from '../types'
import { getProjectById, saveOverviewToProject } from '../utils/storage'

type ReportGroup = {
  title: string
  description: string
  sections: Array<{
    label: string
    content: string | string[]
  }>
}

function OverviewPage() {
  const { id = '' } = useParams()
  const project = getProjectById(id)
  const [topic, setTopic] = useState(project?.researchTopic ?? '')
  const [request, setRequest] = useState('')
  const {
    data: report,
    setData: setReport,
    error: generateError,
    isGenerating,
    run,
  } = useAsyncGeneration<OverviewReport>({
    initialData: project?.overviewReport,
    fallbackMessage: '生成领域报告失败，请稍后重试。',
  })

  const reportGroups = useMemo<ReportGroup[]>(
    () =>
      report
        ? [
            {
              title: '基础认知',
              description: '先快速理解这个方向在做什么、核心概念是什么。',
              sections: [
                { label: '领域背景', content: report.background },
                { label: '核心概念', content: report.coreConcepts },
              ],
            },
            {
              title: '研究版图',
              description: '聚合主要任务、主流方法和当前痛点，避免拆成太多卡片。',
              sections: [
                { label: '主要研究任务', content: report.keyTasks },
                { label: '主流方法', content: report.mainstreamMethods },
                { label: '当前挑战', content: report.challenges },
              ],
            },
            {
              title: '数据与评估',
              description: '把数据集和评价指标放在同一组，便于横向查看。',
              sections: [
                { label: '常用数据集', content: report.commonDatasets },
                { label: '常用评价指标', content: report.commonMetrics },
              ],
            },
            {
              title: '切入与路线',
              description: '最后看潜在研究切入点和建议阅读路线。',
              sections: [
                { label: '潜在研究切入点', content: report.entryPoints },
                { label: '建议阅读路线', content: report.readingPath },
              ],
            },
          ]
        : [],
    [report],
  )

  return (
    <Layout
      sidebar={<Sidebar projectId={id} />}
      header={
        <div>
          <div className="text-sm font-semibold uppercase tracking-[0.2em] text-sky-700">Overview</div>
          <h1 className="mt-2 text-3xl font-semibold text-slate-950">领域快速入门</h1>
          <p className="mt-2 text-sm text-slate-500">
            输入研究方向与具体需求，生成结构化领域报告。
          </p>
        </div>
      }
    >
      {!project ? (
        <EmptyState title="未找到该项目" description="请返回项目列表后重新进入有效项目。" />
      ) : (
        <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
          <SectionCard title="输入区" description="当前仍使用 mock 规则生成，但调用链路已经切到统一 AI 服务层。">
            <div className="space-y-5">
              <label className="field">
                <span>研究方向</span>
                <input
                  value={topic}
                  onChange={(event) => setTopic(event.target.value)}
                  placeholder="输入研究方向"
                />
              </label>
              <label className="field">
                <span>具体需求</span>
                <textarea
                  rows={8}
                  value={request}
                  onChange={(event) => setRequest(event.target.value)}
                  placeholder="例如：我想先了解这个方向的主流方法、数据集、评价指标以及可能的研究切入点。"
                />
              </label>
              {generateError ? (
                <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                  {generateError}
                </div>
              ) : null}
              <div className="flex gap-3">
                <Button
                  disabled={isGenerating}
                  onClick={() =>
                    run(() =>
                      aiService.generateOverview({
                        projectId: id,
                        topic: topic || project.researchTopic,
                        request,
                      }),
                    )
                  }
                >
                  {isGenerating ? '生成中...' : '生成报告'}
                </Button>
                <Button
                  variant="secondary"
                  disabled={!report}
                  onClick={() => {
                    if (!report) return
                    const saved = saveOverviewToProject(id, report)
                    if (saved?.overviewReport) {
                      setReport(saved.overviewReport)
                    }
                  }}
                >
                  保存到项目
                </Button>
              </div>
            </div>
          </SectionCard>

          <div className="grid gap-4 xl:grid-cols-2">
            {report ? (
              reportGroups.map((group) => (
                <SectionCard
                  key={group.title}
                  title={group.title}
                  description={group.description}
                  className="h-full"
                >
                  <div className="space-y-4">
                    {group.sections.map((section) => (
                      <div key={section.label} className="info-block">
                        <h4>{section.label}</h4>
                        {Array.isArray(section.content) ? (
                          <div className="flex flex-wrap gap-2">
                            {section.content.map((item) => (
                              <span key={item} className="info-chip">
                                {item}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <p className="text-sm leading-7 text-slate-600">{section.content}</p>
                        )}
                      </div>
                    ))}
                  </div>
                </SectionCard>
              ))
            ) : (
              <EmptyState
                title="等待生成领域报告"
                description={
                  generateError
                    ? '修正输入后可以再次点击“生成报告”。'
                    : '点击左侧“生成报告”后，这里会展示结构化的领域背景、任务脉络和阅读路线。'
                }
              />
            )}
          </div>
        </div>
      )}
    </Layout>
  )
}

export default OverviewPage
