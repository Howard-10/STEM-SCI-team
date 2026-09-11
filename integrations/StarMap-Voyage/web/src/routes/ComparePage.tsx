import { useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import Button from '../components/common/Button'
import EmptyState from '../components/common/EmptyState'
import SectionCard from '../components/common/SectionCard'
import { useAsyncGeneration } from '../hooks/useAsyncGeneration'
import Layout from '../components/layout/Layout'
import Sidebar from '../components/layout/Sidebar'
import PaperCompareTable from '../components/research/PaperCompareTable'
import ResearchGapPanel from '../components/research/ResearchGapPanel'
import { aiService, type ComparePapersResult } from '../services/ai'
import { getProjectById } from '../utils/storage'

function ComparePage() {
  const { id = '' } = useParams()
  const project = getProjectById(id)
  const [selected, setSelected] = useState<string[]>(
    project?.papers.slice(0, 2).map((paper) => paper.id) ?? [],
  )
  const {
    data: compareResult,
    error: generateError,
    isGenerating,
    run,
  } = useAsyncGeneration<ComparePapersResult>({
    fallbackMessage: '生成论文对比结果失败，请稍后重试。',
  })

  const chosenPapers = useMemo(
    () => project?.papers.filter((paper) => selected.includes(paper.id)) ?? [],
    [project?.papers, selected],
  )
  const selectedCount = chosenPapers.length

  return (
    <Layout
      sidebar={<Sidebar projectId={id} />}
      header={
        <div>
          <div className="text-sm font-semibold uppercase tracking-[0.2em] text-sky-700">Compare</div>
          <h1 className="mt-2 text-3xl font-semibold text-slate-950">多论文对比与研究空白</h1>
          <p className="mt-2 text-sm text-slate-500">
            从项目中已保存的论文出发，生成结构化对比表与研究空白分析。
          </p>
        </div>
      }
    >
      {!project ? (
        <EmptyState title="未找到该项目" description="请返回项目列表后重新进入有效项目。" />
      ) : (
        <div className="space-y-6">
          <SectionCard
            title="已保存论文多选区域"
            description="勾选至少 2 篇论文后，点击“生成对比表”再输出结构化比较结果。"
            action={
              <Button
                disabled={selectedCount < 2 || isGenerating}
                onClick={() =>
                  run(() =>
                    aiService.comparePapers({
                      projectId: id,
                      topic: project.researchTopic,
                      papers: chosenPapers,
                    }),
                  )
                }
              >
                {isGenerating ? '生成中...' : '生成对比表'}
              </Button>
            }
          >
            {project.papers.length === 0 ? (
              <EmptyState title="暂无论文可对比" description="请先到“文献精读”模块保存论文卡片。" />
            ) : (
              <div className="space-y-4">
                <div className="rounded-2xl border border-sky-100 bg-sky-50 px-4 py-3 text-sm text-sky-800">
                  当前已选择 {selectedCount} 篇论文。至少选择 2 篇后才能生成正式对比表。
                </div>
                {generateError ? (
                  <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                    {generateError}
                  </div>
                ) : null}
                <div className="grid gap-3 md:grid-cols-2">
                  {project.papers.map((paper) => {
                    const checked = selected.includes(paper.id)
                    return (
                      <label
                        key={paper.id}
                        className={`flex cursor-pointer items-start gap-3 rounded-2xl border p-4 transition ${
                          checked ? 'border-sky-200 bg-sky-50' : 'border-slate-200 bg-white'
                        }`}
                      >
                        <input
                          type="checkbox"
                          className="mt-1"
                          checked={checked}
                          onChange={(event) => {
                            setSelected((current) =>
                              event.target.checked
                                ? [...current, paper.id]
                                : current.filter((item) => item !== paper.id),
                            )
                          }}
                        />
                        <div className="min-w-0">
                          <div className="font-medium text-slate-900">{paper.title}</div>
                          <div className="mt-1 text-sm text-slate-500">{paper.method}</div>
                          <div className="mt-2 text-xs leading-5 text-slate-500">
                            Motivation：{paper.motivation}
                          </div>
                        </div>
                      </label>
                    )
                  })}
                </div>
              </div>
            )}
          </SectionCard>

          {project.papers.length < 2 ? (
            <EmptyState
              title="至少保存两篇论文后再做正式对比"
              description="当前页面仍保留完整结构，但建议先补充文献样本后再做研究空白分析。"
            />
          ) : compareResult ? (
            <>
              <PaperCompareTable rows={compareResult.rows} />
              <ResearchGapPanel analysis={compareResult.gapAnalysis} />
            </>
          ) : (
            <EmptyState
              title="等待生成对比结果"
              description={
                generateError
                  ? '修正选择后可以再次点击“生成对比表”。'
                  : '先勾选至少两篇论文，再点击上方“生成对比表”输出对比表和研究空白分析。'
              }
            />
          )}
        </div>
      )}
    </Layout>
  )
}

export default ComparePage
