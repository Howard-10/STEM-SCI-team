import { useEffect, useState } from 'react'
import Layout from '../components/layout/Layout'
import { TEACHING_API_BASE } from '../config'

interface Achievement {
  id: string
  project_title?: string
  student_name?: string
  grade_level?: string
  description?: string
  published_at: string
}

function AchievementPage() {
  const [achievements, setAchievements] = useState<Achievement[]>([])
  const [offline, setOffline] = useState(false)

  useEffect(() => {
    fetch(`${TEACHING_API_BASE}/api/achievements`).then(r => r.json()).then(d => {
      setAchievements(d.achievements || [])
    }).catch(() => setOffline(true))
  }, [])

  return (
    <Layout
      header={
        <div className="flex flex-col gap-4 rounded-3xl border border-indigo-100 bg-white p-6 shadow-sm">
          <div className="text-sm font-semibold uppercase tracking-[0.2em] text-indigo-600">Showcase</div>
          <h1 className="text-3xl font-semibold text-indigo-950">成果展示墙</h1>
          <p className="text-sm text-indigo-400">同学们完成的项目作品展示</p>
        </div>
      }
    >
      {offline ? (
        <div className="flex items-center gap-3 rounded-2xl border border-amber-200 bg-amber-50/80 px-4 py-3 text-sm text-amber-700">
          <span className="text-base">⚠️</span>
          <span>无法连接教学后端（{TEACHING_API_BASE}），成果墙暂不可用。请先启动 <code className="rounded bg-amber-100 px-1.5 py-0.5">services/teaching</code> 服务。</span>
        </div>
      ) : achievements.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-indigo-200 bg-white px-6 py-16 text-center">
          <div className="text-4xl mb-4">🏆</div>
          <h3 className="text-lg font-semibold text-indigo-900">还没有成果展示</h3>
          <p className="text-sm text-indigo-400 mt-2">完成教学设计项目后，发布到成果墙与大家分享</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {achievements.map(a => (
            <div key={a.id} className="rounded-2xl border border-indigo-100 bg-white shadow-sm overflow-hidden hover:shadow-md transition-shadow cursor-pointer">
              <div className="h-32 bg-gradient-to-br from-indigo-100 to-indigo-50 flex items-center justify-center text-4xl">
                🏆
              </div>
              <div className="p-4">
                <h3 className="text-sm font-semibold text-indigo-900">{a.project_title || 'STEM 项目'}</h3>
                <div className="flex items-center gap-2 mt-2 text-xs text-indigo-400">
                  <span>👤 {a.student_name || '匿名'}</span>
                  <span>·</span>
                  <span>{a.grade_level || ''}</span>
                </div>
                {a.description && <p className="text-xs text-indigo-400 mt-2">{a.description}</p>}
                <div className="text-xs text-indigo-300 mt-2">{new Date(a.published_at).toLocaleDateString('zh-CN')}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </Layout>
  )
}

export default AchievementPage
