import { useEffect, useState } from 'react'
import { RefreshCw, CheckCircle, FlaskConical } from 'lucide-react'
import Layout from '../components/layout/Layout'
import Button from '../components/common/Button'
import { getProjects } from '../utils/storage'
import { TEACHING_API_BASE, RESEARCH_STREAMLIT_URL } from '../config'

const SYNC_API = `${TEACHING_API_BASE}/api/bridge/sync-projects`

function ExperimentPage() {
  const [projects] = useState(() => getProjects())
  const [synced, setSynced] = useState(false)
  const [syncing, setSyncing] = useState(() => projects.length > 0)

  useEffect(() => {
    if (projects.length === 0) return

    const controller = new AbortController()
    fetch(SYNC_API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ projects }),
      signal: controller.signal,
    }).then(r => r.json()).then(d => {
      if (d.success) setSynced(true)
    }).catch(() => {}).finally(() => setSyncing(false))

    return () => controller.abort()
  }, [projects])

  function handleSync() {
    const projects = getProjects()
    if (projects.length === 0) return
    setSyncing(true)
    fetch(SYNC_API, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({projects})
    }).then(r => r.json()).then(d => {
      if (d.success) { setSynced(true); alert(`已同步 ${d.synced} 个项目到实验平台`) }
    }).catch(() => alert('同步失败，请确认教学后端已启动')).finally(() => setSyncing(false))
  }

  return (
    <Layout
      header={
        <div className="flex flex-col gap-4 rounded-3xl border border-indigo-100 bg-white p-6 shadow-sm">
          <div className="flex justify-between items-start">
            <div>
              <div className="inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50/80 px-3 py-1 text-xs font-semibold uppercase tracking-[0.15em] text-emerald-600">
                <FlaskConical size={13} /> Experiment Lab
              </div>
              <h1 className="text-3xl font-semibold text-indigo-950 mt-3">科研实验工作台</h1>
              <p className="text-sm text-indigo-400 mt-1">代码分析 · 数据处理 · 实验编排 · 可视化生成</p>
            </div>
            <Button variant="secondary" onClick={handleSync} disabled={syncing}>
              {syncing ? <RefreshCw size={16} className="mr-1.5 animate-spin" /> : synced ? <CheckCircle size={16} className="mr-1.5 text-emerald-500" /> : <RefreshCw size={16} className="mr-1.5" />}
              {syncing ? '同步中…' : synced ? '已同步' : '同步文献项目'}
            </Button>
          </div>
        </div>
      }
    >
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-indigo-100 bg-indigo-50/50 px-4 py-3">
        <p className="text-sm text-indigo-500">
          下方内嵌科研实验平台（Streamlit）。若空白，请确认已启动 <code className="rounded bg-white px-1.5 py-0.5 text-indigo-600">services/research</code> 的 Streamlit 服务。
        </p>
        <a href={`${RESEARCH_STREAMLIT_URL}/`} target="_blank" rel="noreferrer" className="text-sm font-medium text-indigo-600 hover:text-indigo-800 inline-flex items-center gap-1">
          在新标签页打开 ↗
        </a>
      </div>
      <div className="rounded-2xl border border-indigo-100 bg-white shadow-sm overflow-hidden">
        <iframe
          src={`${RESEARCH_STREAMLIT_URL}/`}
          title="科研实验"
          className="w-full border-0"
          style={{ height: 'calc(100vh - 220px)', minHeight: '600px' }}
        />
      </div>
    </Layout>
  )
}

export default ExperimentPage
