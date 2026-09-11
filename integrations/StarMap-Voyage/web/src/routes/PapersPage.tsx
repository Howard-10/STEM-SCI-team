import { useState } from 'react'
import { useParams } from 'react-router-dom'
import Button from '../components/common/Button'
import EmptyState from '../components/common/EmptyState'
import SectionCard from '../components/common/SectionCard'
import { useAsyncGeneration } from '../hooks/useAsyncGeneration'
import Layout from '../components/layout/Layout'
import Sidebar from '../components/layout/Sidebar'
import PaperCard from '../components/research/PaperCard'
import { aiService } from '../services/ai'
import type { Paper } from '../types'
import {
  buildPaperMarkdown,
  createMarkdownFilename,
  exportMarkdown,
} from '../utils/exportMarkdown'
import { addPaperToProject, deletePaperFromProject, getProjectById } from '../utils/storage'

function PapersPage() {
  const { id = '' } = useParams()
  const [project, setProject] = useState(getProjectById(id))
  const [title, setTitle] = useState('')
  const [abstract, setAbstract] = useState('')
  const [keywords, setKeywords] = useState('')
  const [savedPapers, setSavedPapers] = useState(project?.papers ?? [])
  const {
    data: draftPaper,
    error: generateError,
    isGenerating,
    run,
  } = useAsyncGeneration<Paper>({
    fallbackMessage: '生成论文精读卡片失败，请稍后重试。',
  })

  return (
    <Layout
      sidebar={<Sidebar projectId={id} />}
      header={
        <div>
          <div className="text-sm font-semibold uppercase tracking-[0.2em] text-sky-700">Papers</div>
          <h1 className="mt-2 text-3xl font-semibold text-slate-950">文献精读</h1>
          <p className="mt-2 text-sm text-slate-500">
            把论文信息沉淀为结构化精读卡片，并保存到项目。
          </p>
        </div>
      }
    >
      {!project ? (
        <EmptyState title="未找到该项目" description="请返回项目列表后重新进入有效项目。" />
      ) : (
        <div className="space-y-6">
          <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
            <SectionCard title="输入区" description="先填入论文标题、摘要和关键词，生成 mock 精读卡片。">
              <div className="space-y-5">
                <label className="field">
                  <span>论文标题</span>
                  <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="输入论文标题" />
                </label>
                <label className="field">
                  <span>论文摘要</span>
                  <textarea
                    rows={8}
                    value={abstract}
                    onChange={(event) => setAbstract(event.target.value)}
                    placeholder="粘贴论文摘要"
                  />
                </label>
                <label className="field">
                  <span>论文关键词</span>
                  <input
                    value={keywords}
                    onChange={(event) => setKeywords(event.target.value)}
                    placeholder="例如：semantic segmentation, disaster scene, structural prior"
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
                        aiService.analyzePaper({
                          projectId: id,
                          title,
                          abstract,
                          keywords: keywords
                            .split(/[，,]/)
                            .map((item) => item.trim())
                            .filter(Boolean),
                        }),
                      )
                    }
                  >
                    {isGenerating ? '生成中...' : '生成精读卡片'}
                  </Button>
                  <Button
                    variant="secondary"
                    disabled={!draftPaper}
                    onClick={() => {
                      if (!draftPaper) return
                      const updated = addPaperToProject(id, draftPaper)
                      if (updated) {
                        setProject(updated)
                        setSavedPapers(updated.papers)
                      }
                    }}
                  >
                    保存到项目
                  </Button>
                </div>
              </div>
            </SectionCard>

            <div>
              {draftPaper ? (
                <PaperCard paper={draftPaper} />
              ) : (
                <EmptyState
                  title="等待生成精读卡片"
                  description={
                    generateError
                      ? '修正输入后可以再次点击“生成精读卡片”。'
                      : '生成后这里会展示研究背景、方法框架、创新点、局限性和 baseline 判断。'
                  }
                />
              )}
            </div>
          </div>

          <SectionCard title="已保存论文列表" description={`当前项目已保存 ${savedPapers.length} 篇论文。`}>
            {savedPapers.length === 0 ? (
              <EmptyState title="还没有保存论文" description="先在上方生成并保存至少一篇论文精读卡片。" />
            ) : (
              <div className="space-y-4">
                {savedPapers.map((paper) => (
                  <div key={paper.id} className="space-y-3">
                    <div className="flex justify-end gap-2">
                      <Button
                        variant="secondary"
                        onClick={() =>
                          project &&
                          exportMarkdown(
                            createMarkdownFilename(project.title, '论文精读'),
                            buildPaperMarkdown(project, paper),
                          )
                        }
                      >
                        导出 Markdown
                      </Button>
                      <Button
                        variant="ghost"
                        onClick={() => {
                          if (!window.confirm('确认删除这篇已保存论文吗？')) return
                          const updated = deletePaperFromProject(id, paper.id)
                          if (updated) {
                            setProject(updated)
                            setSavedPapers(updated.papers)
                          }
                        }}
                      >
                        删除
                      </Button>
                    </div>
                    <PaperCard paper={paper} compact />
                  </div>
                ))}
              </div>
            )}
          </SectionCard>
        </div>
      )}
    </Layout>
  )
}

export default PapersPage
