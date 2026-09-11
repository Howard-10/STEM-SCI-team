import { useState } from 'react'
import { useParams } from 'react-router-dom'
import Button from '../components/common/Button'
import EmptyState from '../components/common/EmptyState'
import RecordDetailPanel from '../components/common/RecordDetailPanel'
import SectionCard from '../components/common/SectionCard'
import { useAsyncGeneration } from '../hooks/useAsyncGeneration'
import Layout from '../components/layout/Layout'
import Sidebar from '../components/layout/Sidebar'
import WritingOutputPanel from '../components/research/WritingOutputPanel'
import { aiService } from '../services/ai'
import type { HistoryRecordItem, WritingOutput } from '../types'
import {
  buildWritingMarkdown,
  createMarkdownFilename,
  exportMarkdown,
} from '../utils/exportMarkdown'
import { formatDateTime, getWritingSummary } from '../utils/projectPresentation'
import { addWritingToProject, deleteWritingFromProject, getProjectById } from '../utils/storage'

const writingTypes = [
  '论文 Introduction',
  'Related Work',
  'Method',
  'Experiment',
  'PPT 大纲',
  '答辩讲稿',
]

function WritingPage() {
  const { id = '' } = useParams()
  const [project, setProject] = useState(getProjectById(id))
  const [type, setType] = useState(writingTypes[0])
  const [requirement, setRequirement] = useState('')
  const [selectedRecord, setSelectedRecord] = useState<HistoryRecordItem | null>(null)
  const {
    data: output,
    error: generateError,
    isGenerating,
    run,
  } = useAsyncGeneration<WritingOutput>({
    fallbackMessage: '生成写作内容失败，请稍后重试。',
  })

  return (
    <Layout
      sidebar={<Sidebar projectId={id} />}
      header={
        <div>
          <div className="text-sm font-semibold uppercase tracking-[0.2em] text-sky-700">Writing</div>
          <h1 className="mt-2 text-3xl font-semibold text-slate-950">写作输出</h1>
          <p className="mt-2 text-sm text-slate-500">
            把研究内容转化为论文段落、PPT 大纲和汇报讲稿。
          </p>
        </div>
      }
    >
      {!project ? (
        <EmptyState title="未找到该项目" description="请返回项目列表后重新进入有效项目。" />
      ) : (
        <div className="space-y-6">
          <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
            <SectionCard title="输入区" description="当前仍使用 mock 模板生成写作结果，后续可无缝切换到真实模型。">
              <div className="space-y-5">
                <label className="field">
                  <span>写作类型选择</span>
                  <select value={type} onChange={(event) => setType(event.target.value)}>
                    {writingTypes.map((item) => (
                      <option key={item} value={item}>
                        {item}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>用户补充要求</span>
                  <textarea
                    rows={8}
                    value={requirement}
                    onChange={(event) => setRequirement(event.target.value)}
                    placeholder="例如：更学术、更适合 PPT 汇报，强调现有方法不足和系统设计价值。"
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
                        aiService.generateWriting({
                          projectId: id,
                          topic: project.researchTopic,
                          type,
                          requirement,
                        }),
                      )
                    }
                  >
                    {isGenerating ? '生成中...' : '生成内容'}
                  </Button>
                  <Button
                    variant="secondary"
                    disabled={!output}
                    onClick={() => {
                      if (!output) return
                      const updated = addWritingToProject(id, {
                        id: `writing-${Date.now()}`,
                        type,
                        content: [
                          output.paragraph,
                          '',
                          'PPT 大纲',
                          ...output.pptOutline,
                          '',
                          '讲解稿',
                          ...output.speakerNotes,
                        ].join('\n'),
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
              </div>
            </SectionCard>

            <div>
              {output ? (
                <WritingOutputPanel output={output} />
              ) : (
                <EmptyState
                  title="等待生成写作内容"
                  description={
                    generateError
                      ? '修正输入后可以再次点击“生成内容”。'
                      : '点击生成后，这里会展示论文段落、PPT 大纲和讲解稿。'
                  }
                />
              )}
            </div>
          </div>

          <SectionCard
            title="历史写作草稿列表"
            description={`当前项目已保存 ${project.writings.length} 条写作草稿。`}
          >
            {project.writings.length === 0 ? (
              <EmptyState title="还没有写作草稿" description="先生成并保存一条写作输出。" />
            ) : (
              <div className="space-y-3">
                {project.writings.map((writing) => {
                  const historyRecord: HistoryRecordItem = {
                    id: `writing-${writing.id}`,
                    type: 'writing',
                    title: writing.type,
                    summary: writing.content,
                    createdAt: writing.createdAt,
                    sourceId: writing.id,
                    detail: writing,
                  }

                  return (
                    <article
                      key={writing.id}
                      className="flex flex-col gap-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 lg:flex-row lg:items-start lg:justify-between"
                    >
                      <div>
                        <h3 className="text-base font-semibold text-slate-900">{writing.type}</h3>
                        <div className="mt-1 text-xs text-slate-400">{formatDateTime(writing.createdAt)}</div>
                        <p className="mt-3 text-sm leading-6 text-slate-600">{getWritingSummary(writing)}</p>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Button variant="secondary" onClick={() => setSelectedRecord(historyRecord)}>
                          查看详情
                        </Button>
                        <Button
                          variant="secondary"
                          onClick={async () => {
                            await navigator.clipboard.writeText(writing.content)
                          }}
                        >
                          复制
                        </Button>
                        <Button
                          variant="secondary"
                          onClick={() =>
                            project &&
                            exportMarkdown(
                              createMarkdownFilename(project.title, '写作草稿'),
                              buildWritingMarkdown(project, writing),
                            )
                          }
                        >
                          导出 Markdown
                        </Button>
                        <Button
                          variant="ghost"
                          onClick={() => {
                            if (!window.confirm('确认删除这条写作草稿吗？')) return
                            const updated = deleteWritingFromProject(id, writing.id)
                            if (updated) {
                              setProject(updated)
                              if (selectedRecord?.sourceId === writing.id) {
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

export default WritingPage
