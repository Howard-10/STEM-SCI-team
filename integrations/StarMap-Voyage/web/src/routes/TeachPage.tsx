import { useState, useEffect } from 'react'
import Layout from '../components/layout/Layout'
import TeachHomePage from './teaching/TeachHomePage'
import TeachProjectPage from './teaching/TeachProjectPage'
import { API_BASE } from './teaching/TeachHomePage'

type Stage = 'home' | 'loading' | 'project'

interface TeachingPlan {
  markdown: string
  title?: string
  quality?: {
    ok?: boolean
  }
}

function currentProjectId(): string | null {
  return new URLSearchParams(window.location.search).get('project')
}

function TeachPage() {
  const [projectId] = useState(currentProjectId)
  const [stage, setStage] = useState<Stage>(() => projectId ? 'loading' : 'home')
  const [planMarkdown, setPlanMarkdown] = useState('')
  const [loadingText, setLoadingText] = useState(() => projectId ? '正在加载教案...' : '')
  const [loadError, setLoadError] = useState('')

  // 从 URL 参数重新打开已有教案
  useEffect(() => {
    if (projectId) {
      fetch(`${API_BASE}/api/project/${projectId}`).then(r => r.json()).then(d => {
        if (d.plan_markdown) {
          setPlanMarkdown(d.plan_markdown)
          setStage('project')
        } else {
          setLoadError('该项目没有可展示的教案内容。')
          setStage('home')
        }
      }).catch(() => {
        setLoadError('无法连接教学后端，请确认已启动（端口 8002）。')
        setStage('home')
      })
    }
  }, [projectId])

  function handleStartProject(q: string, g: string) {
    setLoadError('')
    generatePlan(q, g)
  }

  async function generatePlan(q: string, g: string) {
    setStage('loading')
    setLoadingText('正在为你生成完整教案...')
    try {
      const resp = await fetch(`${API_BASE}/api/generate-plan`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q, grade_level: g, include_3d_print: true })
      })
      const data = await resp.json().catch(() => ({}))
      if (data.success && data.plan) {
        // The backend may return a draft when the model could not satisfy the
        // lesson-completeness contract. Do not publish such a draft as a
        // finished project; otherwise it becomes indistinguishable from a
        // classroom-ready plan and may be persisted by the project endpoint.
        if (data.plan.quality && data.plan.quality.ok === false) {
          const warning = data.plan.quality_warning || '教案内容尚未完整生成，请重试。'
          console.warn('Teaching plan failed quality gate', data.plan.quality)
          setLoadError(warning)
          setStage('home')
          return
        }
        setLoadingText('正在检查教案完整性并保存...')
        await publishPlan(data.plan, q, g)
      } else {
        setLoadError(data.detail || '教案生成失败，请稍后重试。')
        setStage('home')
      }
    } catch (e) {
      console.error(e)
      setLoadError(e instanceof Error && e.message ? `教案生成请求失败：${e.message}` : '无法连接教学后端，请确认已启动（端口 8002）。')
      setStage('home')
    }
  }

  async function publishPlan(plan: TeachingPlan, q: string, g: string) {
    setLoadingText('正在保存教案...')
    try {
      const pubResp = await fetch(`${API_BASE}/api/publish-project`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan_markdown: plan.markdown, title: plan.title || q, grade_level: g })
      })
      const pubData = await pubResp.json()
      if (pubData.success) {
        setPlanMarkdown(pubData.plan_markdown || plan.markdown)
        setStage('project')
      } else {
        setLoadError('教案保存失败，请稍后重试。')
        setStage('home')
      }
    } catch (e) {
      console.error(e)
      setLoadError('无法连接教学后端（端口 8002）。')
      setStage('home')
    }
  }

  if (stage === 'loading') {
    return (
      <Layout>
        <div className="flex flex-col items-center justify-center py-32">
          <div className="w-12 h-12 border-4 border-indigo-200 border-t-indigo-600 rounded-full animate-spin mb-4" />
          <p className="text-slate-500">{loadingText}</p>
        </div>
      </Layout>
    )
  }

  if (stage === 'project') {
    return <TeachProjectPage planMarkdown={planMarkdown} onBack={() => setStage('home')} />
  }

  return (
    <>
      {loadError && (
        <div className="mx-auto max-w-7xl px-4 pt-6 sm:px-6 lg:px-8">
          <div className="flex items-center gap-3 rounded-2xl border border-amber-200 bg-amber-50/80 px-4 py-3 text-sm text-amber-700">
            <span className="text-base">⚠️</span>
            <span>{loadError}</span>
          </div>
        </div>
      )}
      <TeachHomePage onStartProject={handleStartProject} />
    </>
  )
}

export default TeachPage
