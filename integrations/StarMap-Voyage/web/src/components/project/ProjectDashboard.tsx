import { Link } from 'react-router-dom'
import type { Project } from '../../types'
import { buildProjectSummaryMarkdown, createMarkdownFilename, exportMarkdown } from '../../utils/exportMarkdown'
import {
  formatDateTime,
  getExperimentSummary,
  getOverviewSummary,
  getProjectNextSteps,
  getWritingSummary,
  summarizeText,
} from '../../utils/projectPresentation'
import Button from '../common/Button'
import SectionCard from '../common/SectionCard'
import ModuleEntryCard from './ModuleEntryCard'

interface ProjectDashboardProps {
  project: Project
}

const buildModules = (projectId: string) => [
  {
    title: '项目成果记录',
    description: '按领域报告、论文、实验、写作和 idea 汇总当前项目的重要成果。',
    to: `/projects/${projectId}/history`,
  },
  {
    title: '领域快速入门',
    description: '快速建立研究方向全景图，形成概念、任务、数据集和评价指标的结构化报告。',
    to: `/projects/${projectId}/overview`,
  },
  {
    title: '文献精读',
    description: '把论文标题、摘要和关键词沉淀为精读卡片，方便后续比较和复用。',
    to: `/projects/${projectId}/papers`,
  },
  {
    title: '多论文对比与研究空白',
    description: '从已保存论文中生成对比表，总结共性问题、研究空白和可转化议题。',
    to: `/projects/${projectId}/compare`,
  },
  {
    title: '科研想法推演',
    description: '当前先并入“多论文对比与研究空白”页，通过研究问题和 idea 卡片承接想法细化。',
    to: `/projects/${projectId}/compare`,
    badge: '并入对比页',
  },
  {
    title: '代码复现辅助',
    description: '围绕 baseline 仓库复现、环境配置与 Debug 建议提供工程化辅助骨架。',
    to: `/projects/${projectId}/reproduction`,
  },
  {
    title: '实验结果分析',
    description: '输入实验现象和指标，生成趋势分析、补充实验建议和图表方案。',
    to: `/projects/${projectId}/experiments`,
  },
  {
    title: '写作输出',
    description: '把前面沉淀的研究内容组织为论文段落、PPT 大纲和汇报讲稿。',
    to: `/projects/${projectId}/writing`,
  },
]

function ProjectDashboard({ project }: ProjectDashboardProps) {
  const latestPaper = project.papers[0]
  const latestExperiment = project.experiments[0]
  const latestWriting = project.writings[0]
  const nextSteps = getProjectNextSteps(project)

  return (
    <div className="space-y-6">
      <SectionCard
        title={project.title}
        description={`${project.researchTopic} · 当前阶段：${project.stage}`}
        action={
          <div className="flex gap-2">
            <Link to={`/projects/${project.id}/edit`}>
              <Button variant="secondary">编辑项目</Button>
            </Link>
            <Button
              onClick={() =>
                exportMarkdown(
                  createMarkdownFilename(project.title, '项目总结'),
                  buildProjectSummaryMarkdown(project),
                )
              }
            >
              导出项目 Markdown
            </Button>
          </div>
        }
      >
        <p className="text-sm leading-7 text-slate-600">{project.description}</p>
        <dl className="mt-6 grid gap-4 md:grid-cols-4">
          <div className="metric-card">
            <dt>文献数量</dt>
            <dd>{project.papers.length}</dd>
          </div>
          <div className="metric-card">
            <dt>研究想法数量</dt>
            <dd>{project.ideas.length}</dd>
          </div>
          <div className="metric-card">
            <dt>实验记录数量</dt>
            <dd>{project.experiments.length}</dd>
          </div>
          <div className="metric-card">
            <dt>写作草稿数量</dt>
            <dd>{project.writings.length}</dd>
          </div>
        </dl>
      </SectionCard>

      <SectionCard
        title="最近成果摘要"
        description="帮助你快速了解当前项目最近沉淀的报告、论文、实验和写作内容。"
      >
        <div className="grid gap-4 xl:grid-cols-2">
          <article className="rounded-2xl border border-slate-200 bg-slate-50 p-5">
            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">领域报告</div>
            <h3 className="mt-2 text-base font-semibold text-slate-900">
              {project.overviewReport ? `${project.title} 领域报告` : '尚未保存领域报告'}
            </h3>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              {getOverviewSummary(project.overviewReport)}
            </p>
            <div className="mt-3 text-xs text-slate-400">
              {formatDateTime(project.overviewReport?.savedAt)}
            </div>
            <div className="mt-4">
              <Link to={`/projects/${project.id}/overview`}>
                <Button variant="secondary">查看报告</Button>
              </Link>
            </div>
          </article>

          <article className="rounded-2xl border border-slate-200 bg-slate-50 p-5">
            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">最近论文</div>
            <h3 className="mt-2 text-base font-semibold text-slate-900">
              {latestPaper?.title ?? '尚未保存论文精读卡片'}
            </h3>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              {latestPaper ? summarizeText(latestPaper.inspiration, 88) : '建议先添加并精读至少一篇论文。'}
            </p>
            <div className="mt-3 text-xs text-slate-400">{formatDateTime(latestPaper?.createdAt)}</div>
            <div className="mt-4">
              <Link to={`/projects/${project.id}/papers`}>
                <Button variant="secondary">查看论文</Button>
              </Link>
            </div>
          </article>

          <article className="rounded-2xl border border-slate-200 bg-slate-50 p-5">
            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">最近实验</div>
            <h3 className="mt-2 text-base font-semibold text-slate-900">
              {latestExperiment?.name ?? '尚未保存实验分析记录'}
            </h3>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              {latestExperiment
                ? getExperimentSummary(latestExperiment)
                : '建议开始记录实验结果并形成分析结论。'}
            </p>
            <div className="mt-3 text-xs text-slate-400">{formatDateTime(latestExperiment?.createdAt)}</div>
            <div className="mt-4">
              <Link to={`/projects/${project.id}/experiments`}>
                <Button variant="secondary">查看实验</Button>
              </Link>
            </div>
          </article>

          <article className="rounded-2xl border border-slate-200 bg-slate-50 p-5">
            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">最近写作</div>
            <h3 className="mt-2 text-base font-semibold text-slate-900">
              {latestWriting?.type ?? '尚未保存写作草稿'}
            </h3>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              {latestWriting
                ? getWritingSummary(latestWriting)
                : '建议把已有材料转成 Introduction、PPT 大纲或答辩讲稿。'}
            </p>
            <div className="mt-3 text-xs text-slate-400">{formatDateTime(latestWriting?.createdAt)}</div>
            <div className="mt-4">
              <Link to={`/projects/${project.id}/writing`}>
                <Button variant="secondary">查看草稿</Button>
              </Link>
            </div>
          </article>
        </div>

        <div className="mt-5">
          <Link to={`/projects/${project.id}/history`}>
            <Button variant="secondary">查看成果记录</Button>
          </Link>
        </div>
      </SectionCard>

      <SectionCard title="当前项目下一步建议" description="根据当前项目数据自动生成下一步动作建议。">
        <div className="space-y-3">
          {nextSteps.map((step) => (
            <div
              key={step.title}
              className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-4 md:flex-row md:items-center md:justify-between"
            >
              <div>
                <div className="text-sm font-semibold text-slate-900">{step.title}</div>
                <div className="mt-1 text-sm text-slate-600">{step.description}</div>
              </div>
              <Link to={step.to}>
                <Button variant="secondary">前往处理</Button>
              </Link>
            </div>
          ))}
        </div>
      </SectionCard>

      <SectionCard
        title="科研闭环模块"
        description="从领域入门到写作输出，以项目为中心沉淀过程结果。"
      >
        <div className="grid gap-4 xl:grid-cols-2">
          {buildModules(project.id).map((module) => (
            <ModuleEntryCard key={module.title} {...module} />
          ))}
        </div>
      </SectionCard>
    </div>
  )
}

export default ProjectDashboard
