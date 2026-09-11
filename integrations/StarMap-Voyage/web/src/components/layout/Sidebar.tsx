import { NavLink } from 'react-router-dom'

interface SidebarProps {
  projectId: string
}

const buildItems = (projectId: string) => [
  { label: '项目概览', to: `/projects/${projectId}` },
  { label: '项目成果记录', to: `/projects/${projectId}/history` },
  { label: '领域快速入门', to: `/projects/${projectId}/overview` },
  { label: '文献精读', to: `/projects/${projectId}/papers` },
  { label: '多论文对比与研究空白', to: `/projects/${projectId}/compare` },
  { label: '代码复现辅助', to: `/projects/${projectId}/reproduction` },
  { label: '实验结果分析', to: `/projects/${projectId}/experiments` },
  { label: '写作输出', to: `/projects/${projectId}/writing` },
]

function Sidebar({ projectId }: SidebarProps) {
  return (
    <aside className="w-full rounded-2xl border border-slate-200 bg-white p-3 shadow-sm lg:w-72 lg:shrink-0">
      <div className="mb-3 px-3 pt-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
        Project Workspace
      </div>
      <nav className="space-y-1">
        {buildItems(projectId).map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === `/projects/${projectId}`}
            className={({ isActive }) =>
              `block rounded-xl px-3 py-3 text-sm transition ${
                isActive
                  ? 'bg-sky-50 font-medium text-sky-700'
                  : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
              }`
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}

export default Sidebar
