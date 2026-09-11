export type ResearchStage =
  | '领域入门'
  | '文献综述'
  | '实验复现'
  | '结果分析'
  | '写作汇报'

export interface OverviewReport {
  topic: string
  request: string
  background: string
  coreConcepts: string[]
  keyTasks: string[]
  mainstreamMethods: string[]
  commonDatasets: string[]
  commonMetrics: string[]
  challenges: string[]
  entryPoints: string[]
  readingPath: string[]
  savedAt?: string
}

export interface Paper {
  id: string
  title: string
  abstract: string
  keywords: string[]
  background: string
  motivation: string
  coreProblem: string
  method: string
  innovation: string[]
  experimentDesign: string
  datasets: string[]
  metrics: string[]
  strengths: string[]
  limitation: string
  inspiration: string
  contribution: string
  isBaselineCandidate: boolean
  createdAt: string
}

export interface ResearchIdea {
  id: string
  title: string
  description: string
  noveltyScore: number
  feasibilityScore: number
  workloadScore: number
  createdAt?: string
}

export interface ExperimentRecord {
  id: string
  name: string
  rawResult: string
  analysis: string
  chartSuggestion: string
  createdAt: string
}

export interface WritingDraft {
  id: string
  type: string
  content: string
  createdAt: string
}

export interface Project {
  id: string
  title: string
  researchTopic: string
  description: string
  stage: ResearchStage
  papers: Paper[]
  ideas: ResearchIdea[]
  experiments: ExperimentRecord[]
  writings: WritingDraft[]
  overviewReport?: OverviewReport
  createdAt: string
  updatedAt: string
}

export interface CompareRow {
  title: string
  motivation: string
  method: string
  innovation: string
  datasets: string
  metrics: string
  strengths: string
  limitation: string
  inspiration: string
}

export interface ResearchGapAnalysis {
  commonProblems: string[]
  unresolvedIssues: string[]
  datasetGaps: string[]
  methodGaps: string[]
  transformableQuestions: string[]
  ideas: ResearchIdea[]
}

export interface ExperimentInsight {
  trend: string
  bestMethod: string
  metricChange: string
  outlierNote: string
  possibleReasons: string[]
  extraExperiments: string[]
  paperConclusion: string
  chartSuggestion: {
    chartType: string
    xAxis: string
    yAxis: string
    title: string
    highlight: string
    matplotlibSnippet: string
  }
}

export interface WritingOutput {
  paragraph: string
  pptOutline: string[]
  speakerNotes: string[]
}

export interface ReproductionGuide {
  repoGoal: string
  readmeSummary: string[]
  environmentCommands: string[]
  debugSuggestions: string[]
  nextSteps: string[]
}

export type HistoryRecordType =
  | 'overview'
  | 'paper'
  | 'experiment'
  | 'writing'
  | 'idea'

export interface HistoryRecordItem {
  id: string
  type: HistoryRecordType
  title: string
  summary: string
  createdAt: string
  sourceId: string
  detail: OverviewReport | Paper | ExperimentRecord | WritingDraft | ResearchIdea
}
