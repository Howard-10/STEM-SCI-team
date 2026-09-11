import { useParams } from 'react-router-dom'
import EmptyState from '../components/common/EmptyState'
import Layout from '../components/layout/Layout'
import Sidebar from '../components/layout/Sidebar'
import ProjectDashboard from '../components/project/ProjectDashboard'
import { getProjectById } from '../utils/storage'

function ProjectDetailPage() {
  const { id = '' } = useParams()
  const project = getProjectById(id)

  return (
    <Layout
      sidebar={<Sidebar projectId={id} />}
      header={
        <div>
          <div className="text-sm font-semibold uppercase tracking-[0.2em] text-sky-700">Dashboard</div>
          <h1 className="mt-2 text-3xl font-semibold text-slate-950">项目工作台</h1>
        </div>
      }
    >
      {project ? (
        <ProjectDashboard project={project} />
      ) : (
        <EmptyState
          title="未找到该项目"
          description="项目 id 可能无效，或者本地存储已被清空。请返回项目列表重新选择。"
        />
      )}
    </Layout>
  )
}

export default ProjectDetailPage
