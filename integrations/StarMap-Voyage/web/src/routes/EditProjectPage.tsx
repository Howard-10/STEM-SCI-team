import { useNavigate, useParams } from 'react-router-dom'
import EmptyState from '../components/common/EmptyState'
import Layout from '../components/layout/Layout'
import Sidebar from '../components/layout/Sidebar'
import ProjectForm, { type ProjectFormValues } from '../components/project/ProjectForm'
import { getProjectById, updateProjectBasicInfo } from '../utils/storage'

function EditProjectPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const project = getProjectById(id)

  const initialValues: ProjectFormValues | undefined = project
    ? {
        title: project.title,
        researchTopic: project.researchTopic,
        description: project.description,
        stage: project.stage,
      }
    : undefined

  return (
    <Layout
      sidebar={<Sidebar projectId={id} />}
      header={
        <div>
          <div className="text-sm font-semibold uppercase tracking-[0.2em] text-sky-700">Edit</div>
          <h1 className="mt-2 text-3xl font-semibold text-slate-950">编辑项目</h1>
          <p className="mt-2 text-sm text-slate-500">修改项目基本信息，并保持本地成果数据不变。</p>
        </div>
      }
    >
      {!project || !initialValues ? (
        <EmptyState title="未找到该项目" description="请返回项目列表重新进入有效项目。" />
      ) : (
        <ProjectForm
          initialValues={initialValues}
          title="编辑科研项目"
          description="更新项目名称、研究方向、简介和阶段信息。"
          submitLabel="保存修改"
          onSubmit={(values) => {
            const updated = updateProjectBasicInfo(id, values)
            if (updated) {
              navigate(`/projects/${id}`)
            }
          }}
        />
      )}
    </Layout>
  )
}

export default EditProjectPage
