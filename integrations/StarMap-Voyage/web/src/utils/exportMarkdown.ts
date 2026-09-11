import type { ExperimentRecord, OverviewReport, Paper, Project, ResearchIdea, WritingDraft } from '../types'
import {
  getExperimentSummary,
  getOverviewSummary,
  getProjectNextSteps,
  getWritingSummary,
} from './projectPresentation'

function sanitizeFileName(value: string) {
  return value.replace(/[\\/:*?"<>|]/g, '-').replace(/\s+/g, '-')
}

function timestampForFile() {
  const date = new Date()
  const year = date.getFullYear()
  const month = `${date.getMonth() + 1}`.padStart(2, '0')
  const day = `${date.getDate()}`.padStart(2, '0')
  const hour = `${date.getHours()}`.padStart(2, '0')
  const minute = `${date.getMinutes()}`.padStart(2, '0')
  return `${year}${month}${day}-${hour}${minute}`
}

export function exportMarkdown(filename: string, content: string) {
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

export function createMarkdownFilename(projectTitle: string, section: string) {
  return `${sanitizeFileName(projectTitle)}-${sanitizeFileName(section)}-${timestampForFile()}.md`
}

function bulletList(items: string[]) {
  if (items.length === 0) return '- 暂无'
  return items.map((item) => `- ${item}`).join('\n')
}

export function buildOverviewMarkdown(project: Project, overview?: OverviewReport) {
  const report = overview ?? project.overviewReport
  if (!report) {
    return `# ${project.title}\n\n## 领域报告\n\n当前项目尚未保存领域报告。`
  }

  return `# ${project.title}

## 研究方向

${project.researchTopic}

## 项目简介

${project.description}

## 当前阶段

${project.stage}

## 领域报告摘要

${getOverviewSummary(report)}

## 领域背景

${report.background}

## 核心概念

${bulletList(report.coreConcepts)}

## 主要研究任务

${bulletList(report.keyTasks)}

## 主流方法

${bulletList(report.mainstreamMethods)}

## 常用数据集

${bulletList(report.commonDatasets)}

## 常用评价指标

${bulletList(report.commonMetrics)}

## 当前挑战

${bulletList(report.challenges)}

## 潜在研究切入点

${bulletList(report.entryPoints)}

## 建议阅读路线

${bulletList(report.readingPath)}
`
}

export function buildPaperMarkdown(project: Project, paper: Paper) {
  return `# ${project.title}

## 研究方向

${project.researchTopic}

## 论文标题

${paper.title}

## 摘要

${paper.abstract}

## 关键词

${paper.keywords.join(' / ')}

## 研究背景

${paper.background}

## Motivation

${paper.motivation}

## 核心问题

${paper.coreProblem}

## 方法框架

${paper.method}

## 创新点

${bulletList(paper.innovation)}

## 实验设计

${paper.experimentDesign}

## 数据集

${bulletList(paper.datasets)}

## 评价指标

${bulletList(paper.metrics)}

## 优点

${bulletList(paper.strengths)}

## 局限性

${paper.limitation}

## 对项目启发

${paper.inspiration}
`
}

export function buildExperimentMarkdown(project: Project, experiment: ExperimentRecord) {
  return `# ${project.title}

## 研究方向

${project.researchTopic}

## 实验名称

${experiment.name}

## 实验摘要

${getExperimentSummary(experiment)}

## 原始结果

${experiment.rawResult || '未填写'}

## 分析内容

${experiment.analysis}

## 图表建议

\`\`\`json
${experiment.chartSuggestion}
\`\`\`
`
}

export function buildWritingMarkdown(project: Project, writing: WritingDraft) {
  return `# ${project.title}

## 研究方向

${project.researchTopic}

## 写作类型

${writing.type}

## 草稿摘要

${getWritingSummary(writing)}

## 写作内容

${writing.content}
`
}

export function buildIdeaMarkdown(project: Project, idea: ResearchIdea) {
  return `# ${project.title}

## 研究方向

${project.researchTopic}

## Idea 标题

${idea.title}

## 描述

${idea.description}

## 评分

- 创新性：${idea.noveltyScore}
- 可行性：${idea.feasibilityScore}
- 工作量：${idea.workloadScore}
`
}

export function buildProjectSummaryMarkdown(project: Project) {
  const nextSteps = getProjectNextSteps(project)
  const latestPaper = project.papers[0]
  const latestExperiment = project.experiments[0]
  const latestWriting = project.writings[0]

  return `# ${project.title}

## 研究方向

${project.researchTopic}

## 项目简介

${project.description}

## 当前阶段

${project.stage}

## 领域报告

${project.overviewReport ? buildOverviewMarkdown(project, project.overviewReport) : '当前项目尚未保存领域报告。'}

## 论文精读

${latestPaper ? buildPaperMarkdown(project, latestPaper) : '当前项目尚未保存论文精读卡片。'}

## 实验分析

${latestExperiment ? buildExperimentMarkdown(project, latestExperiment) : '当前项目尚未保存实验分析记录。'}

## 写作草稿

${latestWriting ? buildWritingMarkdown(project, latestWriting) : '当前项目尚未保存写作草稿。'}

## 下一步建议

${nextSteps.map((item) => `- ${item.title}：${item.description}`).join('\n')}
`
}
