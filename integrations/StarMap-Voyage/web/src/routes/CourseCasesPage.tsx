import { ExternalLink, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import Layout from '../components/layout/Layout'
import { COURSE_CASES_URL } from '../config'

function CourseCasesPage() {
  const [hasLoadError, setHasLoadError] = useState(false)

  return (
    <Layout>
      <section className="flex flex-col gap-5">
        <div className="flex flex-col gap-3 rounded-2xl border border-indigo-100 bg-white p-6 shadow-sm sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-indigo-500">课程案例</p>
            <h1 className="mt-2 text-2xl font-semibold text-indigo-950">自适应 STEM 学习路径规划</h1>
            <p className="mt-2 max-w-2xl text-sm leading-7 text-indigo-500">
              通过案例化题库、知识图谱和学习路径推荐，完成 STEM 课程案例的探究式学习。
            </p>
          </div>
          <a
            href={COURSE_CASES_URL}
            target="_blank"
            rel="noreferrer"
            className="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl border border-indigo-200 bg-white px-4 py-2.5 text-sm font-medium text-indigo-700 transition hover:border-indigo-300 hover:bg-indigo-50"
          >
            <ExternalLink size={16} />
            新窗口打开
          </a>
        </div>

        {hasLoadError ? (
          <div className="flex items-center justify-between gap-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            <span>课程案例服务暂时无法连接，请确认 8800 端口的服务已启动。</span>
            <button
              type="button"
              onClick={() => {
                setHasLoadError(false)
                window.location.reload()
              }}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 font-medium text-amber-900 transition hover:bg-amber-100"
            >
              <RefreshCw size={14} />
              重试
            </button>
          </div>
        ) : null}

        <div className="overflow-hidden rounded-2xl border border-indigo-100 bg-white shadow-sm">
          <iframe
            title="自适应 STEM 学习路径规划系统"
            src={COURSE_CASES_URL}
            className="min-h-[720px] w-full border-0"
            loading="eager"
            onError={() => setHasLoadError(true)}
          />
        </div>
      </section>
    </Layout>
  )
}

export default CourseCasesPage
