import { useState } from 'react'
import { useParams } from 'react-router-dom'
import Button from '../components/common/Button'
import EmptyState from '../components/common/EmptyState'
import SectionCard from '../components/common/SectionCard'
import { useAsyncGeneration } from '../hooks/useAsyncGeneration'
import Layout from '../components/layout/Layout'
import Sidebar from '../components/layout/Sidebar'
import ReproductionDebugPanel from '../components/research/ReproductionDebugPanel'
import { aiService } from '../services/ai'
import type { ReproductionGuide } from '../types'
import { getProjectById } from '../utils/storage'

function ReproductionPage() {
  const { id = '' } = useParams()
  const project = getProjectById(id)
  const [githubUrl, setGithubUrl] = useState('')
  const [errorLog, setErrorLog] = useState('')
  const {
    data: guide,
    error: generateError,
    isGenerating,
    run,
  } = useAsyncGeneration<ReproductionGuide>({
    fallbackMessage: '生成复现建议失败，请稍后重试。',
  })

  return (
    <Layout
      sidebar={<Sidebar projectId={id} />}
      header={
        <div>
          <div className="text-sm font-semibold uppercase tracking-[0.2em] text-sky-700">Reproduction</div>
          <h1 className="mt-2 text-3xl font-semibold text-slate-950">代码复现辅助</h1>
          <p className="mt-2 text-sm text-slate-500">
            围绕 baseline 复现、环境配置和 Debug 建议构建统一的工程支持入口。
          </p>
        </div>
      }
    >
      {!project ? (
        <EmptyState title="未找到该项目" description="请返回项目列表后重新进入有效项目。" />
      ) : (
        <div className="space-y-6">
          <SectionCard title="输入区" description="当前不访问真实 GitHub，只根据项目主题和输入内容生成 mock 复现建议。">
            <div className="grid gap-5 xl:grid-cols-2">
              <label className="field">
                <span>GitHub 链接</span>
                <input
                  value={githubUrl}
                  onChange={(event) => setGithubUrl(event.target.value)}
                  placeholder="https://github.com/owner/repo"
                />
              </label>
              <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm leading-6 text-slate-600">
                README 分析区域会基于仓库地址和项目主题生成检查建议，后续可以平滑替换成真实仓库解析能力。
              </div>
            </div>
            <label className="field mt-5">
              <span>报错日志输入区</span>
              <textarea
                rows={8}
                value={errorLog}
                onChange={(event) => setErrorLog(event.target.value)}
                placeholder="粘贴复现过程中的报错日志或关键异常信息。"
              />
            </label>
            {generateError ? (
              <div className="mt-5 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                {generateError}
              </div>
            ) : null}
            <div className="mt-5">
              <Button
                disabled={isGenerating}
                onClick={() =>
                  run(() =>
                    aiService.analyzeReproduction({
                      projectId: id,
                      topic: project.researchTopic,
                      githubUrl,
                      errorLog,
                    }),
                  )
                }
              >
                {isGenerating ? '生成中...' : '生成复现建议'}
              </Button>
            </div>
          </SectionCard>

          {guide ? (
            <ReproductionDebugPanel guide={guide} />
          ) : (
            <EmptyState
              title="等待生成复现建议"
              description={
                generateError
                  ? '修正输入后可以再次点击“生成复现建议”。'
                  : '点击生成后，这里会展示 README 分析、环境命令和 Debug 建议。'
              }
            />
          )}
        </div>
      )}
    </Layout>
  )
}

export default ReproductionPage
