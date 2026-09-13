import { Link, useLocation } from 'react-router-dom'
import { BookOpen, GraduationCap } from 'lucide-react'

const MODULES = [
  { path: '/course-cases', label: '教学案例', icon: BookOpen },
  { path: '/teach', label: '教学设计', icon: GraduationCap },
]

function Navbar() {
  const location = useLocation()
  const path = location.pathname

  function getActiveModule(): string {
    if (path.startsWith('/teach')) return '/teach'
    if (path.startsWith('/course-cases')) return '/course-cases'
    return ''
  }

  const activeModule = getActiveModule()

  return (
    <header className="sticky top-3 z-30 mx-4 sm:mx-6 lg:mx-8">
      <div className="mx-auto flex max-w-7xl items-center justify-between rounded-2xl glass-strong px-5 py-3 shadow-sm">
        <Link to="/" className="flex items-center gap-3 shrink-0">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600 text-sm font-bold text-white shadow-md shadow-indigo-200">
            XT
          </div>
          <div className="hidden sm:block">
            <div className="text-sm font-semibold tracking-wide text-indigo-950">智研育航助学</div>
            <div className="text-xs text-indigo-400">STEM 教学设计与案例平台</div>
          </div>
        </Link>

        <nav className="flex items-center gap-1 rounded-xl bg-indigo-50/60 p-1">
          {MODULES.map(m => {
            const isActive = activeModule === m.path
            const Icon = m.icon
            return (
              <Link
                key={m.path}
                to={m.path}
                className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-all duration-200 ${
                  isActive
                    ? 'bg-white text-indigo-700 shadow-sm'
                    : 'text-indigo-500 hover:text-indigo-700 hover:bg-white/50'
                }`}
              >
                <Icon size={17} strokeWidth={2} />
                <span className="hidden sm:inline">{m.label}</span>
              </Link>
            )
          })}
        </nav>

        <div className="flex items-center gap-1 text-sm shrink-0">
          <Link to="/star-map" className="rounded-lg px-2.5 py-2 text-indigo-400 transition hover:bg-indigo-50 hover:text-indigo-600 text-xs">
            🌟 星图
          </Link>
          <Link to="/achievements" className="rounded-lg px-2.5 py-2 text-indigo-400 transition hover:bg-indigo-50 hover:text-indigo-600 text-xs">
            🏆 成果
          </Link>
          {activeModule === '/teach' ? (
            <Link to="/teach/projects" className="rounded-lg px-3 py-2 text-indigo-500 transition hover:bg-indigo-50 hover:text-indigo-700 text-xs">
              我的项目
            </Link>
          ) : null}
        </div>
      </div>
    </header>
  )
}

export default Navbar
