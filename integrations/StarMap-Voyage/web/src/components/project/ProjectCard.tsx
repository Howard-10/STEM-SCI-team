import { Link } from 'react-router-dom'
import type { Project } from '../../types'
import Button from '../common/Button'

interface ProjectCardProps {
  project: Project
  onDelete?: (projectId: string) => void
}

function formatDate(value: string) {
  return new Date(value).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function ProjectCard({ project, onDelete }: ProjectCardProps) {
  return (
    <article className="flex h-full flex-col rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-xl font-semibold text-slate-900">{project.title}</h3>
          <p className="mt-2 text-sm text-slate-500">{project.researchTopic}</p>
        </div>
        <span className="rounded-full bg-sky-50 px-3 py-1 text-xs font-medium text-sky-700">
          {project.stage}
        </span>
      </div>
      <p className="mt-4 line-clamp-3 text-sm leading-6 text-slate-600">{project.description}</p>
      <dl className="mt-6 grid grid-cols-2 gap-3 text-sm">
        <div className="rounded-2xl bg-slate-50 p-3">
          <dt className="text-slate-500">已保存论文</dt>
          <dd className="mt-1 text-lg font-semibold text-slate-900">{project.papers.length}</dd>
        </div>
        <div className="rounded-2xl bg-slate-50 p-3">
          <dt className="text-slate-500">已生成 Idea</dt>
          <dd className="mt-1 text-lg font-semibold text-slate-900">{project.ideas.length}</dd>
        </div>
      </dl>
      <div className="mt-6 flex items-center justify-between gap-3">
        <div className="text-xs text-slate-400">最近更新：{formatDate(project.updatedAt)}</div>
        <div className="flex gap-2">
          {onDelete ? (
            <Button variant="ghost" onClick={() => onDelete(project.id)}>
              删除
            </Button>
          ) : null}
          <Link to={`/projects/${project.id}`}>
            <Button>进入项目</Button>
          </Link>
        </div>
      </div>
    </article>
  )
}

export default ProjectCard
