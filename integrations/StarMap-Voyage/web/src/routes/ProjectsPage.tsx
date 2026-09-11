import { useState } from 'react'
import { Link } from 'react-router-dom'
import Button from '../components/common/Button'
import EmptyState from '../components/common/EmptyState'
import Layout from '../components/layout/Layout'
import ProjectCard from '../components/project/ProjectCard'
import { deleteProject, getProjects } from '../utils/storage'

function ProjectsPage() {
  const [projects, setProjects] = useState(getProjects())

  return (
    <Layout
      header={
        <div className="flex flex-col gap-4 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm md:flex-row md:items-end md:justify-between">
          <div>
            <div className="text-sm font-semibold uppercase tracking-[0.2em] text-sky-700">Projects</div>
            <h1 className="mt-2 text-3xl font-semibold text-slate-950">我的科研项目</h1>
            <p className="mt-2 text-sm leading-6 text-slate-500">
              以项目为中心管理研究方向、已读论文、研究想法和后续实验规划。
            </p>
          </div>
          <Link to="/projects/new">
            <Button>新建项目</Button>
          </Link>
        </div>
      }
    >
      {projects.length === 0 ? (
        <EmptyState
          title="还没有科研项目"
          description="先创建一个项目，后续所有 mock 报告、文献卡片和研究想法都会和该项目绑定。"
          action={
            <Link to="/projects/new">
              <Button>创建第一个项目</Button>
            </Link>
          }
        />
      ) : (
        <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          {projects.map((project) => (
            <ProjectCard
              key={project.id}
              project={project}
              onDelete={(projectId) => {
                if (!window.confirm('确认删除这个项目吗？该项目下的所有本地数据都会被移除。')) return
                setProjects(deleteProject(projectId))
              }}
            />
          ))}
        </div>
      )}
    </Layout>
  )
}

export default ProjectsPage
