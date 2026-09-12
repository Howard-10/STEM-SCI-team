import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Search, FolderOpen } from 'lucide-react'
import Layout from '../../components/layout/Layout'
import Button from '../../components/common/Button'
import { TEACHING_API_BASE } from '../../config'

const API_BASE = TEACHING_API_BASE
const BUBBLES = [
  {id:'light_refraction',title:'光的折射与透镜探究',difficulty:2,subjects:['物理','数学'],color:'from-amber-400 to-orange-500'},
  {id:'acid_base_indicator',title:'自制酸碱指示剂',difficulty:2,subjects:['化学','生物'],color:'from-emerald-400 to-teal-500'},
  {id:'seed_germination',title:'种子发芽条件探究',difficulty:2,subjects:['生物','环境'],color:'from-green-400 to-emerald-500'},
  {id:'paper_bridge',title:'纸桥承重挑战赛',difficulty:2,subjects:['物理','工程'],color:'from-sky-400 to-blue-500'},
  {id:'auto_watering',title:'智能自动浇花系统',difficulty:3,subjects:['生物','编程'],color:'from-cyan-400 to-teal-500'},
  {id:'obstacle_robot',title:'避障机器人挑战',difficulty:4,subjects:['工程','编程'],color:'from-red-400 to-rose-500'},
  {id:'waste_sorting_survey',title:'社区垃圾分类调查',difficulty:2,subjects:['环境','社会'],color:'from-lime-400 to-green-500'},
  {id:'dialect_survey',title:'方言保护小调查',difficulty:2,subjects:['社会','语言'],color:'from-purple-400 to-violet-500'},
  {id:'history_timeline',title:'历史事件时间线可视化',difficulty:3,subjects:['社会','编程'],color:'from-fuchsia-400 to-pink-500'},
  {id:'carbon_footprint',title:'我的家庭碳足迹计算',difficulty:3,subjects:['环境','数学'],color:'from-teal-400 to-cyan-500'},
  {id:'campus_plant_atlas',title:'校园植物图鉴制作',difficulty:2,subjects:['生物','艺术'],color:'from-lime-400 to-emerald-500'},
  {id:'future_city_design',title:'设计未来城市模型',difficulty:3,subjects:['工程','艺术'],color:'from-indigo-400 to-blue-500'},
]

interface Props {
  onStartProject: (query: string, grade: string, include3D: boolean) => void
}

function TeachHomePage({ onStartProject }: Props) {
  const [query, setQuery] = useState('')
  const [grade, setGrade] = useState('初中')
  const [include3D, setInclude3D] = useState(true)

  return (
    <Layout
      header={
        <div className="flex flex-col gap-4 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex justify-between items-start">
            <div>
              <div className="inline-flex items-center gap-2 rounded-full border border-indigo-200 bg-indigo-50/80 px-3 py-1 text-xs font-semibold uppercase tracking-[0.15em] text-indigo-600 w-fit">
                <Search size={13} /> Teaching Design
              </div>
            </div>
            <Link to="/teach/projects" className="inline-flex items-center gap-1.5 rounded-xl border border-indigo-200 bg-white px-4 py-2 text-sm font-medium text-indigo-600 hover:bg-indigo-50 transition">
              <FolderOpen size={16} /> 我的项目
            </Link>
          </div>
          <h1 className="text-3xl font-semibold text-slate-950">设计 STEM 教案</h1>
          <p className="text-sm leading-6 text-slate-500">输入课题或选择一个主题，AI 为你生成完整、贴合主题的教案，并支持说课稿、教学反思、教材课标分析等教研材料</p>

          {/* Search */}
          <div className="flex gap-3 mt-2">
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="输入课题，例如：光的折射与透镜探究..."
              className="flex-1"
              onKeyDown={e => { if (e.key==='Enter' && query.trim()) onStartProject(query.trim(), grade, include3D) }}
            />
            <Button onClick={() => query.trim() && onStartProject(query.trim(), grade, include3D)}>生成教案</Button>
          </div>

          {/* Filters */}
          <div className="flex gap-3 flex-wrap items-center">
            <select value={grade} onChange={e => setGrade(e.target.value)} className="!w-auto !rounded-xl !py-2 !px-4 !text-sm">
              <option value="小学低段">小学低段</option>
              <option value="小学中段">小学中段</option>
              <option value="小学高段">小学高段</option>
              <option value="初中">初中</option>
              <option value="高中">高中</option>
            </select>
            <label className="inline-flex items-center gap-2 text-sm text-slate-500 cursor-pointer">
              <input type="checkbox" checked={include3D} onChange={e => setInclude3D(e.target.checked)} className="!w-auto" />
              含3D打印
            </label>
          </div>
        </div>
      }
    >
      {/* Bubble Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
        {BUBBLES.map((b) => (
          <button
            key={b.id}
            onClick={() => onStartProject(`设计一份关于「${b.title}」的STEM教案`, grade, include3D)}
            className="group relative cursor-pointer rounded-2xl border border-indigo-100 bg-white p-5 text-center transition-all duration-300 hover:border-indigo-300 hover:shadow-lg hover:shadow-indigo-50 hover:-translate-y-1"
          >
            <div className={`mx-auto mb-3 h-14 w-14 rounded-2xl bg-gradient-to-br ${b.color} flex items-center justify-center shadow-sm`}>
              <span className="text-2xl font-bold text-white" style={{ fontFamily: "'Baloo 2', sans-serif" }}>
                {b.title.charAt(0)}
              </span>
            </div>
            <div className="text-sm font-semibold text-indigo-900">{b.title}</div>
            <div className="mt-1 text-xs text-indigo-400">{(b.subjects||[]).join(' · ')}</div>
            <div className="mt-2 flex justify-center gap-0.5">
              {Array.from({length: b.difficulty}).map((_, i) => (
                <div key={i} className="h-1.5 w-1.5 rounded-full bg-indigo-300 group-hover:bg-amber-400 transition-colors" />
              ))}
            </div>
          </button>
        ))}
      </div>
    </Layout>
  )
}

export { BUBBLES, API_BASE }
export default TeachHomePage
