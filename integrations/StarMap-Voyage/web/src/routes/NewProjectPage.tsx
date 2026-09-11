import { useNavigate } from 'react-router-dom'
import Layout from '../components/layout/Layout'
import ProjectForm from '../components/project/ProjectForm'
import { createProject } from '../utils/storage'

function NewProjectPage() {
  const navigate = useNavigate()

  return (
    <Layout
      header={
        <div>
          <div className="text-sm font-semibold uppercase tracking-[0.2em] text-sky-700">Create</div>
          <h1 className="mt-2 text-3xl font-semibold text-slate-950">新建科研项目</h1>
          <p className="mt-2 text-sm leading-6 text-slate-500">
            项目建立后即可进入工作台，开始做领域报告、文献精读和后续研究规划。
          </p>
        </div>
      }
    >
      <ProjectForm
        onSubmit={(values) => {
          const project = createProject(values)
          navigate(`/projects/${project.id}`)
        }}
      />
    </Layout>
  )
}

export default NewProjectPage
