import { mockProjects } from '../data/mockData'
import type {
  ExperimentRecord,
  HistoryRecordItem,
  OverviewReport,
  Paper,
  Project,
  ResearchIdea,
  ResearchStage,
  WritingDraft,
} from '../types'

const STORAGE_KEY = 'research-pilot-projects'

function canUseStorage() {
  return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined'
}

export function saveProjects(projects: Project[]) {
  if (!canUseStorage()) return
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(projects))
}

export function seedProjectsIfEmpty() {
  if (!canUseStorage()) return
  const existing = window.localStorage.getItem(STORAGE_KEY)
  if (!existing) {
    saveProjects(mockProjects)
  }
}

export function getProjects(): Project[] {
  if (!canUseStorage()) return mockProjects
  seedProjectsIfEmpty()
  const raw = window.localStorage.getItem(STORAGE_KEY)

  if (!raw) return mockProjects

  try {
    return JSON.parse(raw) as Project[]
  } catch {
    saveProjects(mockProjects)
    return mockProjects
  }
}

export function getProjectById(id: string) {
  return getProjects().find((project) => project.id === id)
}

function updateProjectCollection(projectId: string, updater: (project: Project) => Project) {
  const project = getProjectById(projectId)
  if (!project) return undefined

  const updated = updater(project)
  return updateProject({
    ...updated,
    updatedAt: new Date().toISOString(),
  })
}

export function updateProject(project: Project) {
  const projects = getProjects()
  const next = projects.map((item) => (item.id === project.id ? project : item))
  saveProjects(next)
  return project
}

export function createProject(input: {
  title: string
  researchTopic: string
  description: string
  stage: ResearchStage
}) {
  const timestamp = new Date().toISOString()
  const project: Project = {
    id: `project-${Date.now()}`,
    title: input.title,
    researchTopic: input.researchTopic,
    description: input.description,
    stage: input.stage,
    papers: [],
    ideas: [],
    experiments: [],
    writings: [],
    createdAt: timestamp,
    updatedAt: timestamp,
  }

  const projects = getProjects()
  saveProjects([project, ...projects])
  return project
}

export function deleteProject(projectId: string) {
  const projects = getProjects()
  const next = projects.filter((item) => item.id !== projectId)
  saveProjects(next)
  return next
}

export function updateProjectBasicInfo(
  projectId: string,
  fields: {
    title: string
    researchTopic: string
    description: string
    stage: ResearchStage
  },
) {
  return updateProjectCollection(projectId, (project) => ({
    ...project,
    ...fields,
  }))
}

export function addPaperToProject(projectId: string, paper: Paper) {
  return updateProjectCollection(projectId, (project) => ({
    ...project,
    papers: [paper, ...project.papers],
  }))
}

export function deletePaperFromProject(projectId: string, paperId: string) {
  return updateProjectCollection(projectId, (project) => ({
    ...project,
    papers: project.papers.filter((paper) => paper.id !== paperId),
  }))
}

export function addExperimentToProject(projectId: string, experiment: ExperimentRecord) {
  return updateProjectCollection(projectId, (project) => ({
    ...project,
    experiments: [experiment, ...project.experiments],
  }))
}

export function deleteExperimentFromProject(projectId: string, experimentId: string) {
  return updateProjectCollection(projectId, (project) => ({
    ...project,
    experiments: project.experiments.filter((experiment) => experiment.id !== experimentId),
  }))
}

export function addWritingToProject(projectId: string, writing: WritingDraft) {
  return updateProjectCollection(projectId, (project) => ({
    ...project,
    writings: [writing, ...project.writings],
  }))
}

export function deleteWritingFromProject(projectId: string, writingId: string) {
  return updateProjectCollection(projectId, (project) => ({
    ...project,
    writings: project.writings.filter((writing) => writing.id !== writingId),
  }))
}

export function saveOverviewToProject(projectId: string, overviewReport: OverviewReport) {
  return updateProjectCollection(projectId, (project) => ({
    ...project,
    overviewReport: {
      ...overviewReport,
      savedAt: new Date().toISOString(),
    },
  }))
}

export function deleteOverviewFromProject(projectId: string) {
  return updateProjectCollection(projectId, (project) => ({
    ...project,
    overviewReport: undefined,
  }))
}

export function deleteIdeaFromProject(projectId: string, ideaId: string) {
  return updateProjectCollection(projectId, (project) => ({
    ...project,
    ideas: project.ideas.filter((idea) => idea.id !== ideaId),
  }))
}

function buildIdeaRecord(project: Project, idea: ResearchIdea): HistoryRecordItem {
  return {
    id: `idea-${idea.id}`,
    type: 'idea',
    title: idea.title,
    summary: idea.description,
    createdAt: idea.createdAt ?? project.createdAt,
    sourceId: idea.id,
    detail: idea,
  }
}

export function getProjectHistory(projectId: string): HistoryRecordItem[] {
  const project = getProjectById(projectId)
  if (!project) return []

  const items: HistoryRecordItem[] = []

  if (project.overviewReport) {
    items.push({
      id: `overview-${project.id}`,
      type: 'overview',
      title: `${project.title} 领域报告`,
      summary: project.overviewReport.background,
      createdAt: project.overviewReport.savedAt ?? project.updatedAt,
      sourceId: project.id,
      detail: project.overviewReport,
    })
  }

  project.papers.forEach((paper) => {
    items.push({
      id: `paper-${paper.id}`,
      type: 'paper',
      title: paper.title,
      summary: paper.inspiration,
      createdAt: paper.createdAt,
      sourceId: paper.id,
      detail: paper,
    })
  })

  project.experiments.forEach((experiment) => {
    items.push({
      id: `experiment-${experiment.id}`,
      type: 'experiment',
      title: experiment.name,
      summary: experiment.analysis || experiment.rawResult,
      createdAt: experiment.createdAt,
      sourceId: experiment.id,
      detail: experiment,
    })
  })

  project.writings.forEach((writing) => {
    items.push({
      id: `writing-${writing.id}`,
      type: 'writing',
      title: writing.type,
      summary: writing.content,
      createdAt: writing.createdAt,
      sourceId: writing.id,
      detail: writing,
    })
  })

  project.ideas.forEach((idea) => {
    items.push(buildIdeaRecord(project, idea))
  })

  return items.sort((left, right) => +new Date(right.createdAt) - +new Date(left.createdAt))
}
