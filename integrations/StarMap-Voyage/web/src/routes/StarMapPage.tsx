import { useEffect, useState } from 'react'
import Layout from '../components/layout/Layout'
import { TEACHING_API_BASE } from '../config'

const CATEGORIES = [
  { name: '物理', color: '#74b9ff', icon: '⚡' },
  { name: '化学', color: '#a29bfe', icon: '🧪' },
  { name: '生物', color: '#00b894', icon: '🧬' },
  { name: '地学', color: '#fdcb6e', icon: '🌍' },
  { name: '工程', color: '#e17055', icon: '⚙️' },
  { name: '编程', color: '#fd79a8', icon: '💻' },
  { name: '数学', color: '#00cec9', icon: '📐' },
  { name: 'AI', color: '#6366f1', icon: '🤖' },
]

interface TeachingProject {
  title: string
}

function StarMapPage() {
  const [stars, setStars] = useState<string[]>([])
  const [projects, setProjects] = useState<TeachingProject[]>([])
  const [offline, setOffline] = useState(false)

  useEffect(() => {
    fetch(`${TEACHING_API_BASE}/api/progress/student_001`).then(r => r.json()).then(p => {
      setStars(p.knowledge_stars || [])
    }).catch(() => setOffline(true))
    fetch(`${TEACHING_API_BASE}/api/projects`).then(r => r.json()).then(d => {
      setProjects(d.projects || [])
    }).catch(() => setOffline(true))
  }, [])

  const allConcepts = [...new Set([...stars, ...projects.map(p => p.title)])]
  const litCount = stars.length
  const totalCount = allConcepts.length || 15

  return (
    <Layout
      header={
        <div className="flex flex-col gap-4 rounded-3xl border border-indigo-100 bg-white p-6 shadow-sm">
          <div className="flex justify-between items-center">
            <div>
              <div className="text-sm font-semibold uppercase tracking-[0.2em] text-indigo-600">Knowledge Map</div>
              <h1 className="text-3xl font-semibold text-indigo-950 mt-1">知识星图</h1>
              <p className="text-sm text-indigo-400 mt-1">每完成一个项目，相关的知识点就会被点亮</p>
            </div>
            <div className="text-right">
              <div className="text-3xl font-bold text-indigo-600">{litCount}</div>
              <div className="text-xs text-indigo-400">已掌握 / {totalCount} 总量</div>
            </div>
          </div>
        </div>
      }
    >
      {offline && (
        <div className="flex items-center gap-3 rounded-2xl border border-amber-200 bg-amber-50/80 px-4 py-3 text-sm text-amber-700">
          <span className="text-base">⚠️</span>
          <span>无法连接教学后端（{TEACHING_API_BASE}），星图数据暂不可用。请先启动 <code className="rounded bg-amber-100 px-1.5 py-0.5">services/teaching</code> 服务。</span>
        </div>
      )}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {CATEGORIES.map(cat => {
          const catStars = stars.filter(s => {
            const kw: Record<string,string[]> = {
              '物理': ['力','运动','光','声','电','磁','热'],
              '化学': ['反应','分子','元素','溶液','酸','碱'],
              '生物': ['细胞','基因','DNA','植物','动物'],
              '地学': ['地球','气象','天文','地质','地震'],
              '工程': ['搭建','组装','机械','结构','设计'],
              '编程': ['代码','程序','算法','Python','Arduino'],
              '数学': ['数','计算','几何','统计','方程'],
              'AI': ['智能','机器','模型','训练','识别'],
            }
            return (kw[cat.name]||[]).some(k => s.includes(k))
          })
          const catTotal = Math.max(catStars.length, 1)
          return (
            <div key={cat.name} className="rounded-2xl border border-indigo-100 bg-white p-5 shadow-sm">
              <div className="flex items-center gap-2 mb-3">
                <span className="text-xl">{cat.icon}</span>
                <span className="text-sm font-semibold text-indigo-900">{cat.name}</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="flex-1 h-2 bg-indigo-50 rounded-full overflow-hidden">
                  <div className="h-full rounded-full transition-all duration-500" style={{ width: `${Math.round(catStars.length/catTotal*100)}%`, backgroundColor: cat.color }} />
                </div>
                <span className="text-xs font-medium text-indigo-400">{catStars.length}</span>
              </div>
            </div>
          )
        })}
      </div>
    </Layout>
  )
}

export default StarMapPage
