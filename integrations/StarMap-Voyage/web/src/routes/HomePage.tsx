import { Link } from 'react-router-dom'
import { BookOpen, GraduationCap, ArrowRight } from 'lucide-react'
import Layout from '../components/layout/Layout'

function HomePage() {
  return (
    <Layout>
      <section className="text-center py-10">
        <div className="inline-flex items-center gap-2 rounded-full border border-indigo-200 bg-indigo-50/80 px-4 py-2 text-xs font-semibold uppercase tracking-[0.2em] text-indigo-600">
          <GraduationCap size={14} /> Teaching Design
        </div>
        <h1 className="mt-6 text-4xl font-semibold tracking-tight text-indigo-950 lg:text-6xl" style={{ fontFamily: "'Baloo 2', sans-serif" }}>
          智研育航助学
        </h1>
        <p className="mt-3 text-xl text-indigo-600/70">STEM 教学设计与案例平台</p>
        <p className="mt-6 max-w-2xl mx-auto text-base leading-8 text-indigo-500">
          输入一个主题，AI 为你生成完整、贴合主题的 STEM 项目教学设计——从学情分析、教学目标到分课时教学过程与评价，一应俱全。
        </p>
      </section>

      <section className="grid gap-6 mt-2 lg:grid-cols-2">
        <Link
          to="/course-cases"
          className="group relative overflow-hidden rounded-2xl border border-indigo-100 bg-white p-8 transition-all duration-300 hover:shadow-xl hover:shadow-indigo-100 hover:-translate-y-1 cursor-pointer"
        >
          <div className="absolute top-0 left-0 right-0 h-1.5 bg-gradient-to-r from-sky-500 to-cyan-500" />
          <div className="mt-3 mb-5">
            <BookOpen size={36} strokeWidth={1.5} className="text-sky-600" />
          </div>
          <h3 className="text-xl font-semibold text-indigo-950 mb-3">教学案例</h3>
          <p className="text-sm text-indigo-400 leading-relaxed whitespace-pre-line">
            通过案例化题库与知识图谱开展探究式学习{'\n'}课程案例 → 答题练习 → 知识点 → 个性化学习路径
          </p>
          <div className="mt-5 inline-flex items-center gap-1.5 text-sm font-medium text-indigo-500 group-hover:text-indigo-700 transition-colors">
            进入模块 <ArrowRight size={15} className="group-hover:translate-x-0.5 transition-transform" />
          </div>
        </Link>

        <Link
          to="/teach"
          className="group relative overflow-hidden rounded-2xl border border-indigo-100 bg-white p-8 transition-all duration-300 hover:shadow-xl hover:shadow-indigo-100 hover:-translate-y-1 cursor-pointer"
        >
          <div className="absolute top-0 left-0 right-0 h-1.5 bg-gradient-to-r from-indigo-500 to-indigo-600" />
          <div className="mt-3 mb-5">
            <GraduationCap size={36} strokeWidth={1.5} className="text-indigo-600" />
          </div>
          <h3 className="text-xl font-semibold text-indigo-950 mb-3">教学设计</h3>
          <p className="text-sm text-indigo-400 leading-relaxed whitespace-pre-line">
            AI 生成个性化 STEM 教案{'\n'}课前测评 → 完整教案 → 项目空间 → 阶段小结 → 导出 DOCX
          </p>
          <div className="mt-5 inline-flex items-center gap-1.5 text-sm font-medium text-indigo-500 group-hover:text-indigo-700 transition-colors">
            进入模块 <ArrowRight size={15} className="group-hover:translate-x-0.5 transition-transform" />
          </div>
        </Link>
      </section>
    </Layout>
  )
}

export default HomePage
