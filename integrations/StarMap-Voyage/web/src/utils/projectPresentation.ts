import type { ExperimentRecord, OverviewReport, Project, WritingDraft } from '../types'

export function formatDateTime(value?: string) {
  if (!value) return '未记录时间'
  return new Date(value).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function summarizeText(text: string, maxLength = 90) {
  const normalized = text.replace(/\s+/g, ' ').trim()
  if (normalized.length <= maxLength) return normalized
  return `${normalized.slice(0, maxLength)}...`
}

export function getOverviewSummary(report?: OverviewReport) {
  if (!report) return '尚未保存领域报告。'
  return summarizeText(report.background, 88)
}

export function getExperimentSummary(experiment: ExperimentRecord) {
  return summarizeText(experiment.analysis || experiment.rawResult, 88)
}

export function getWritingSummary(writing: WritingDraft) {
  return summarizeText(writing.content, 88)
}

export function getProjectNextSteps(project: Project) {
  const steps: Array<{ title: string; description: string; to: string }> = []

  if (!project.overviewReport) {
    steps.push({
      title: '先完成领域快速入门',
      description: '先沉淀研究方向背景、主流方法和建议阅读路线。',
      to: `/projects/${project.id}/overview`,
    })
  }

  if (project.papers.length === 0) {
    steps.push({
      title: '添加并精读至少 3 篇论文',
      description: '当前项目还没有文献积累，先建立基础文献池。',
      to: `/projects/${project.id}/papers`,
    })
  } else if (project.papers.length < 2) {
    steps.push({
      title: '继续积累文献',
      description: '建议至少保存两篇以上论文，便于后续做对比和研究空白分析。',
      to: `/projects/${project.id}/papers`,
    })
  }

  if (project.experiments.length === 0) {
    steps.push({
      title: '进入实验分析模块',
      description: '开始记录实验结果、分析趋势并沉淀图表建议。',
      to: `/projects/${project.id}/experiments`,
    })
  }

  if (project.writings.length === 0) {
    steps.push({
      title: '进入写作输出模块',
      description: '把已有研究材料转化为论文段落、PPT 大纲或答辩讲稿。',
      to: `/projects/${project.id}/writing`,
    })
  }

  if (steps.length === 0) {
    steps.push({
      title: '推进多论文对比与研究空白分析',
      description: '当前基础材料已经具备，可以继续收敛研究问题和新 idea。',
      to: `/projects/${project.id}/compare`,
    })
  }

  return steps
}
