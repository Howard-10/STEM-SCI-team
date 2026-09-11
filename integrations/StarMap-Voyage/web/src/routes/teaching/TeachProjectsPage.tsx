import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../../components/layout/Layout'
import Button from '../../components/common/Button'
import { FolderOpen, Plus, Clock, Star, ArrowRight, Trash2 } from 'lucide-react'
import { TEACHING_API_BASE } from '../../config'

const API_BASE = TEACHING_API_BASE

interface ProjectMeta {
  id: string
  title: string
  grade_level: string
  created_at: string
  has_3d_print: boolean
  code_files: number
  status: string
}

interface StoredStage {
  completed?: boolean
}

function TeachProjectsPage() {
  const [projects, setProjects] = useState<ProjectMeta[]>([])
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    fetch(`${API_BASE}/api/projects`).then(r => r.json()).then(d => {
      setProjects(d.projects || [])
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [])

  // Load stage progress from localStorage
  function getProgress(projId: string): { done: number; total: number } {
    try {
      const saved = JSON.parse(localStorage.getItem(`stages_${projId}`) || '{}')
      const stages = Object.values(saved) as StoredStage[]
      const done = stages.filter((stage) => stage.completed).length
      return { done, total: stages.length || 4 }
    } catch { return { done: 0, total: 4 } }
  }

  function openProject(id: string) {
    navigate(`/teach?project=${id}`)
  }

  async function deleteProject(id: string, e: React.MouseEvent) {
    e.stopPropagation()
    if (!confirm('确定删除此项目？项目文件和进度将被永久删除。')) return
    await fetch(`${API_BASE}/api/project/${id}`, { method: 'DELETE' })
    setProjects(prev => prev.filter(p => p.id !== id))
  }

  return (
    <Layout
      header={
        <div className="flex flex-col gap-4 rounded-3xl border border-indigo-100 bg-white p-6 shadow-sm">
          <div className="flex justify-between items-start">
            <div>
              <div className="text-sm font-semibold uppercase tracking-[0.2em] text-indigo-600">
                <FolderOpen size={14} className="inline mr-1" /> Project Repository
              </div>
              <h1 className="text-3xl font-semibold text-indigo-950 mt-1">我的教学项目</h1>
              <p className="text-sm text-indigo-400 mt-1">所有 AI 生成的 STEM 教案项目，进度自动保存</p>
            </div>
            <Button onClick={() => navigate('/teach')}>
              <Plus size={16} className="mr-1" /> 新建项目
            </Button>
          </div>
        </div>
      }
    >
      {loading ? (
        <div className="flex justify-center py-20">
          <div className="w-10 h-10 border-4 border-indigo-200 border-t-indigo-600 rounded-full animate-spin" />
        </div>
      ) : projects.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-indigo-200 bg-white px-6 py-16 text-center">
          <div className="text-4xl mb-4">📭</div>
          <h3 className="text-lg font-semibold text-indigo-900">还没有教学项目</h3>
          <p className="text-sm text-indigo-400 mt-2 mb-4">去首页选择一个主题，AI 将为你生成第一个 STEM 教案</p>
          <Button onClick={() => navigate('/teach')}>去创建</Button>
        </div>
      ) : (
        <div className="grid gap-4">
          {projects.map(p => {
            const prog = getProgress(p.id)
            const pct = prog.total > 0 ? Math.round(prog.done / prog.total * 100) : 0
            return (
              <div
                key={p.id}
                onClick={() => openProject(p.id)}
                className="group cursor-pointer rounded-2xl border border-indigo-100 bg-white p-5 shadow-sm hover:border-indigo-300 hover:shadow-md transition-all flex items-center gap-5"
              >
                {/* Progress ring */}
                <div className="relative w-14 h-14 shrink-0">
                  <svg className="w-full h-full -rotate-90" viewBox="0 0 36 36">
                    <circle cx="18" cy="18" r="15" fill="none" stroke="#EEF2FF" strokeWidth="3" />
                    <circle cx="18" cy="18" r="15" fill="none" stroke={pct >= 70 ? '#22C55E' : '#4F46E5'} strokeWidth="3"
                      strokeDasharray={`${pct * 0.94} 94`} strokeLinecap="round" />
                  </svg>
                  <div className="absolute inset-0 flex items-center justify-center text-xs font-bold text-indigo-700">{pct}%</div>
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <h3 className="text-sm font-semibold text-indigo-900 group-hover:text-indigo-700">{p.title}</h3>
                  <div className="flex items-center gap-3 mt-1.5 text-xs text-indigo-400">
                    <span className="inline-flex items-center gap-1"><Clock size={12} /> {p.grade_level}</span>
                    <span className="inline-flex items-center gap-1"><Star size={12} /> {prog.done}/{prog.total} 阶段完成</span>
                    {p.has_3d_print && <span className="text-indigo-300">🔧 3D</span>}
                    {p.code_files > 0 && <span className="text-indigo-300">💻 {p.code_files}代码</span>}
                  </div>
                </div>

                {/* Date + Actions */}
                <div className="text-right shrink-0 flex items-center gap-2">
                  <div>
                    <div className="text-xs text-indigo-300">{new Date(p.created_at).toLocaleDateString('zh-CN')}</div>
                  </div>
                  <button onClick={(e) => deleteProject(p.id, e)}
                    className="p-1.5 rounded-lg text-indigo-300 hover:text-red-500 hover:bg-red-50 transition"
                    title="删除项目">
                    <Trash2 size={15} />
                  </button>
                  <ArrowRight size={16} className="text-indigo-300 group-hover:text-indigo-600 group-hover:translate-x-0.5 transition-all" />
                </div>
              </div>
            )
          })}
        </div>
      )}
    </Layout>
  )
}

export default TeachProjectsPage
