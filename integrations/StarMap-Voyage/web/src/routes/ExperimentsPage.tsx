import { useState } from 'react'
import { useParams } from 'react-router-dom'
import Button from '../components/common/Button'
import EmptyState from '../components/common/EmptyState'
import RecordDetailPanel from '../components/common/RecordDetailPanel'
import SectionCard from '../components/common/SectionCard'
import { useAsyncGeneration } from '../hooks/useAsyncGeneration'
import Layout from '../components/layout/Layout'
import Sidebar from '../components/layout/Sidebar'
import ExperimentAnalysisPanel from '../components/research/ExperimentAnalysisPanel'
import { aiService } from '../services/ai'
import type { ExperimentInsight, HistoryRecordItem } from '../types'
import {
  buildExperimentMarkdown,
  createMarkdownFilename,
  exportMarkdown,
} from '../utils/exportMarkdown'
import { formatDateTime, getExperimentSummary } from '../utils/projectPresentation'
import {
  addExperimentToProject,
  deleteExperimentFromProject,
  getProjectById,
} from '../utils/storage'

function ExperimentsPage() {
  const { id = '' } = useParams()
  const [project, setProject] = useState(getProjectById(id))
  const [name, setName] = useState('')
  const [rawResult, setRawResult] = useState('')
  const [selectedRecord, setSelectedRecord] = useState<HistoryRecordItem | null>(null)
  const {
    data: insight,
    error: generateError,
    isGenerating,
    run,
  } = useAsyncGeneration<ExperimentInsight>({
    fallbackMessage: '生成实验分析失败，请稍后重试。',
  })

  return (
    <Layout
      sidebar={<Sidebar projectId={id} />}
      header={
        <div>
          <div className="text-sm font-semibold uppercase tracking-[0.2em] text-sky-700">Experiments</div>
          <h1 className="mt-2 text-3xl font-semibold text-slate-950">实验结果分析</h1>
          <p className="mt-2 text-sm text-slate-500">
            输入实验现象和结果文本，生成趋势解读与图表建议。
          </p>
        </div>
      }
    >
      {!project ? (
        <EmptyState title="未找到该项目" description="请返回项目列表后重新进入有效项目。" />
      ) : (
        <div className="space-y-6">
          <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
            <SectionCard title="输入区" description="先记录实验名称和主要现象，后续可以接真实实验管理逻辑。">
              <div className="space-y-5">
                <label className="field">
                  <span>实验名称</span>
                  <input
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder="例如：Ablation on structural priors"
                  />
                </label>
                <label className="field">
                  <span>实验结果文本框</span>
                  <textarea
                    rows={10}
                    value={rawResult}
                    onChange={(event) => setRawResult(event.target.value)}
                    placeholder="输入主要指标变化、异常现象或你的主观观察。"
                  />
                </label>
                {generateError ? (
                  <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                    {generateError}
                  </div>
                ) : null}
                <Button
                  disabled={isGenerating}
                  onClick={() =>
                    run(() =>
                      aiService.analyzeExperiment({
                        projectId: id,
                        name,
                        rawResult,
                        topic: project.researchTopic,
                      }),
                    )
                  }
                >
                  {isGenerating ? '生成中...' : '生成分析'}
                </Button>
                <Button
                  variant="secondary"
                  disabled={!insight}
                  onClick={() => {
                    if (!insight) return
                    const updated = addExperimentToProject(id, {
                      id: `experiment-${Date.now()}`,
                      name: name || '实验结果分析',
                      rawResult,
                      analysis: [
                        insight.trend,
                        insight.bestMethod,
                        insight.metricChange,
                        insight.paperConclusion,
                      ].join('\n'),
                      chartSuggestion: JSON.stringify(insight.chartSuggestion),
                      createdAt: new Date().toISOString(),
                    })
                    if (updated) {
                      setProject(updated)
                    }
                  }}
                >
                  保存到项目
                </Button>
              </div>
            </SectionCard>

            <div>
              {insight ? (
                <ExperimentAnalysisPanel insight={insight} />
              ) : (
                <EmptyState
                  title="等待生成实验分析"
                  description={
                    generateError
                      ? '修正输入后可以再次点击“生成分析”。'
                      : '点击生成后，这里会展示总体趋势、异常值说明和图表建议。'
                  }
                />
              )}
            </div>
          </div>

          <SectionCard
            title="历史实验分析列表"
            description={`当前项目已保存 ${project.experiments.length} 条实验分析记录。`}
          >
            {project.experiments.length === 0 ? (
              <EmptyState title="还没有实验分析记录" description="先生成并保存一条实验分析记录。" />
            ) : (
              <div className="space-y-3">
                {project.experiments.map((experiment) => {
                  const historyRecord: HistoryRecordItem = {
                    id: `experiment-${experiment.id}`,
                    type: 'experiment',
                    title: experiment.name,
                    summary: experiment.analysis || experiment.rawResult,
                    createdAt: experiment.createdAt,
                    sourceId: experiment.id,
                    detail: experiment,
                  }

                  return (
                    <article
                      key={experiment.id}
                      className="flex flex-col gap-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 lg:flex-row lg:items-start lg:justify-between"
                    >
                      <div>
                        <h3 className="text-base font-semibold text-slate-900">{experiment.name}</h3>
                        <div className="mt-1 text-xs text-slate-400">{formatDateTime(experiment.createdAt)}</div>
                        <p className="mt-3 text-sm leading-6 text-slate-600">{getExperimentSummary(experiment)}</p>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Button variant="secondary" onClick={() => setSelectedRecord(historyRecord)}>
                          查看详情
                        </Button>
                        <Button
                          variant="secondary"
                          onClick={() =>
                            project &&
                            exportMarkdown(
                              createMarkdownFilename(project.title, '实验分析'),
                              buildExperimentMarkdown(project, experiment),
                            )
                          }
                        >
                          导出 Markdown
                        </Button>
                        <Button
                          variant="ghost"
                          onClick={() => {
                            if (!window.confirm('确认删除这条实验分析记录吗？')) return
                            const updated = deleteExperimentFromProject(id, experiment.id)
                            if (updated) {
                              setProject(updated)
                              if (selectedRecord?.sourceId === experiment.id) {
                                setSelectedRecord(null)
                              }
                            }
                          }}
                        >
                          删除
                        </Button>
                      </div>
                    </article>
                  )
                })}
              </div>
            )}
          </SectionCard>

          <RecordDetailPanel
            open={Boolean(selectedRecord)}
            record={selectedRecord}
            onClose={() => setSelectedRecord(null)}
          />
        </div>
      )}
    </Layout>
  )
}

export default ExperimentsPage
