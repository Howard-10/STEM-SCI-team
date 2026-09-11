import { useState } from 'react'
import { stageOptions } from '../../data/mockData'
import type { ResearchStage } from '../../types'
import Button from '../common/Button'
import SectionCard from '../common/SectionCard'

export interface ProjectFormValues {
  title: string
  researchTopic: string
  description: string
  stage: ResearchStage
}

interface ProjectFormProps {
  onSubmit: (values: ProjectFormValues) => void
  initialValues?: ProjectFormValues
  submitLabel?: string
  title?: string
  description?: string
}

const defaultValues: ProjectFormValues = {
  title: '',
  researchTopic: '',
  description: '',
  stage: '领域入门',
}

function ProjectForm({
  onSubmit,
  initialValues,
  submitLabel = '创建项目并进入工作台',
  title = '创建科研项目',
  description = '先定义研究主题、当前阶段和项目简介，后续所有 mock 输出都会围绕这个项目上下文组织。',
}: ProjectFormProps) {
  const [values, setValues] = useState<ProjectFormValues>({
    ...defaultValues,
    ...initialValues,
  })

  const updateField = <K extends keyof ProjectFormValues>(key: K, value: ProjectFormValues[K]) => {
    setValues((current) => ({ ...current, [key]: value }))
  }

  return (
    <SectionCard
      title={title}
      description={description}
      className="max-w-3xl"
    >
      <form
        className="space-y-5"
        onSubmit={(event) => {
          event.preventDefault()
          onSubmit(values)
        }}
      >
        <div className="grid gap-5 md:grid-cols-2">
          <label className="field">
            <span>项目名称</span>
            <input
              value={values.title}
              onChange={(event) => updateField('title', event.target.value)}
              placeholder="例如：灾害场景路径规划辅助研究"
              required
            />
          </label>
          <label className="field">
            <span>研究方向</span>
            <input
              value={values.researchTopic}
              onChange={(event) => updateField('researchTopic', event.target.value)}
              placeholder="例如：计算机视觉与灾害场景理解"
              required
            />
          </label>
        </div>

        <label className="field">
          <span>项目简介</span>
          <textarea
            value={values.description}
            onChange={(event) => updateField('description', event.target.value)}
            placeholder="简要描述研究目标、当前问题和预期产出"
            rows={5}
            required
          />
        </label>

        <label className="field">
          <span>当前阶段</span>
          <select
            value={values.stage}
            onChange={(event) => updateField('stage', event.target.value as ResearchStage)}
          >
            {stageOptions.map((stage) => (
              <option key={stage} value={stage}>
                {stage}
              </option>
            ))}
          </select>
        </label>

        <div className="flex justify-end">
          <Button type="submit">{submitLabel}</Button>
        </div>
      </form>
    </SectionCard>
  )
}

export default ProjectForm
