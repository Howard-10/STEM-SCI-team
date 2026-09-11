import type { ResearchIdea } from '../../types'
import { aiEndpoints } from './endpoints'
import type { AIProvider } from './provider'
import { fetchJson } from './transport'
import { AIServiceError } from './types'
import type {
  AnalyzeExperimentInput,
  AnalyzeExperimentResult,
  AnalyzePaperInput,
  AnalyzePaperResult,
  AnalyzeReproductionInput,
  AnalyzeReproductionResult,
  ComparePapersInput,
  ComparePapersResult,
  GenerateOverviewInput,
  GenerateOverviewResult,
  GenerateWritingInput,
  GenerateWritingResult,
} from './types'

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function isString(value: unknown): value is string {
  return typeof value === 'string'
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isString)
}

interface GeneratedIdea {
  title: string
  description: string
}

function isGeneratedIdea(value: unknown): value is GeneratedIdea {
  return isObject(value) && isString(value.title) && isString(value.description)
}

function requireValue(value: string, message: string) {
  if (!value.trim()) {
    throw new AIServiceError('validation', message)
  }
}

function isResearchIdea(value: unknown): value is ResearchIdea {
  return (
    isObject(value) &&
    isString(value.id) &&
    isString(value.title) &&
    isString(value.description) &&
    typeof value.noveltyScore === 'number' &&
    typeof value.feasibilityScore === 'number' &&
    typeof value.workloadScore === 'number'
  )
}

function assertOverviewResult(value: unknown): asserts value is GenerateOverviewResult {
  if (
    !isObject(value) ||
    !isString(value.topic) ||
    !isString(value.request) ||
    !isString(value.background) ||
    !isStringArray(value.coreConcepts) ||
    !isStringArray(value.keyTasks) ||
    !isStringArray(value.mainstreamMethods) ||
    !isStringArray(value.commonDatasets) ||
    !isStringArray(value.commonMetrics) ||
    !isStringArray(value.challenges) ||
    !isStringArray(value.entryPoints) ||
    !isStringArray(value.readingPath)
  ) {
    throw new AIServiceError('invalid_response', '领域报告响应格式不正确。')
  }
}

function assertPaperResult(value: unknown): asserts value is AnalyzePaperResult {
  if (
    !isObject(value) ||
    !isString(value.id) ||
    !isString(value.title) ||
    !isString(value.abstract) ||
    !isStringArray(value.keywords) ||
    !isString(value.background) ||
    !isString(value.motivation) ||
    !isString(value.coreProblem) ||
    !isString(value.method) ||
    !isStringArray(value.innovation) ||
    !isString(value.experimentDesign) ||
    !isStringArray(value.datasets) ||
    !isStringArray(value.metrics) ||
    !isStringArray(value.strengths) ||
    !isString(value.limitation) ||
    !isString(value.inspiration) ||
    !isString(value.contribution) ||
    typeof value.isBaselineCandidate !== 'boolean' ||
    !isString(value.createdAt)
  ) {
    throw new AIServiceError('invalid_response', '论文精读响应格式不正确。')
  }
}

function assertCompareResult(value: unknown): asserts value is ComparePapersResult {
  const isCompareRow = (row: unknown) =>
    isObject(row) &&
    isString(row.title) &&
    isString(row.motivation) &&
    isString(row.method) &&
    isString(row.innovation) &&
    isString(row.datasets) &&
    isString(row.metrics) &&
    isString(row.strengths) &&
    isString(row.limitation) &&
    isString(row.inspiration)

  if (
    !isObject(value) ||
    !Array.isArray(value.rows) ||
    !value.rows.every(isCompareRow) ||
    !isObject(value.gapAnalysis) ||
    !isStringArray(value.gapAnalysis.commonProblems) ||
    !isStringArray(value.gapAnalysis.unresolvedIssues) ||
    !isStringArray(value.gapAnalysis.datasetGaps) ||
    !isStringArray(value.gapAnalysis.methodGaps) ||
    !isStringArray(value.gapAnalysis.transformableQuestions) ||
    !Array.isArray(value.gapAnalysis.ideas) ||
    !value.gapAnalysis.ideas.every(isResearchIdea)
  ) {
    throw new AIServiceError('invalid_response', '多论文对比响应格式不正确。')
  }
}

function assertExperimentResult(value: unknown): asserts value is AnalyzeExperimentResult {
  if (
    !isObject(value) ||
    !isString(value.trend) ||
    !isString(value.bestMethod) ||
    !isString(value.metricChange) ||
    !isString(value.outlierNote) ||
    !isStringArray(value.possibleReasons) ||
    !isStringArray(value.extraExperiments) ||
    !isString(value.paperConclusion) ||
    !isObject(value.chartSuggestion) ||
    !isString(value.chartSuggestion.chartType) ||
    !isString(value.chartSuggestion.xAxis) ||
    !isString(value.chartSuggestion.yAxis) ||
    !isString(value.chartSuggestion.title) ||
    !isString(value.chartSuggestion.highlight) ||
    !isString(value.chartSuggestion.matplotlibSnippet)
  ) {
    throw new AIServiceError('invalid_response', '实验分析响应格式不正确。')
  }
}

function assertWritingResult(value: unknown): asserts value is GenerateWritingResult {
  if (
    !isObject(value) ||
    !isString(value.paragraph) ||
    !isStringArray(value.pptOutline) ||
    !isStringArray(value.speakerNotes)
  ) {
    throw new AIServiceError('invalid_response', '写作输出响应格式不正确。')
  }
}

function assertReproductionResult(value: unknown): asserts value is AnalyzeReproductionResult {
  if (
    !isObject(value) ||
    !isString(value.repoGoal) ||
    !isStringArray(value.readmeSummary) ||
    !isStringArray(value.environmentCommands) ||
    !isStringArray(value.debugSuggestions) ||
    !isStringArray(value.nextSteps)
  ) {
    throw new AIServiceError('invalid_response', '代码复现响应格式不正确。')
  }
}

function unwrap<T>(payload: unknown, key: string): T {
  if (isObject(payload) && payload.success && key in payload) {
    return (payload as Record<string, unknown>)[key] as T
  }
  // Fallback: return payload as-is (for backwards compat)
  return payload as T
}

export const httpProvider: AIProvider = {
  async generateOverview(input: GenerateOverviewInput) {
    requireValue(input.topic, '请输入研究方向后再生成领域报告。')
    const raw = await fetchJson<unknown>(aiEndpoints.generateOverview, input)
    const result = unwrap<GenerateOverviewResult>(raw, 'report')
    assertOverviewResult(result)
    return result
  },

  async analyzePaper(input: AnalyzePaperInput) {
    requireValue(input.title, '请输入论文标题后再生成精读卡片。')
    requireValue(input.abstract, '请输入论文摘要后再生成精读卡片。')
    const raw = await fetchJson<unknown>(aiEndpoints.analyzePaper, input)
    const result = unwrap<AnalyzePaperResult>(raw, 'paper')
    assertPaperResult(result)
    return result
  },

  async comparePapers(input: ComparePapersInput) {
    if (input.papers.length < 2) {
      throw new AIServiceError('validation', '请至少选择 2 篇论文后再生成对比结果。')
    }
    const raw = await fetchJson<unknown>(aiEndpoints.comparePapers, input)
    const result = unwrap<ComparePapersResult>(raw, 'compareResult')
    assertCompareResult(result)
    return result
  },

  async analyzeExperiment(input: AnalyzeExperimentInput) {
    requireValue(input.name, '请输入实验名称后再生成分析。')
    requireValue(input.rawResult, '请输入实验结果文本后再生成分析。')
    const raw = await fetchJson<unknown>(aiEndpoints.analyzeExperiment, input)
    const result = unwrap<AnalyzeExperimentResult>(raw, 'insight')
    assertExperimentResult(result)
    return result
  },

  async generateWriting(input: GenerateWritingInput) {
    requireValue(input.type, '请选择写作类型后再生成内容。')
    requireValue(input.topic, '缺少项目研究方向，无法生成写作内容。')
    const raw = await fetchJson<unknown>(aiEndpoints.generateWriting, input)
    // generate-ideas returns {ideas: [...]} directly
    let result: unknown = unwrap<unknown>(raw, 'ideas')
    if (Array.isArray(result)) {
      if (!result.every(isGeneratedIdea)) {
        throw new AIServiceError('invalid_response', '研究想法响应格式不正确。')
      }
      // Convert ideas array to writing output format
      result = {
        paragraph: result.map((idea) => `**${idea.title}**\n${idea.description}`).join('\n\n'),
        pptOutline: result.map((idea) => idea.title),
        speakerNotes: result.map((idea) => idea.description),
      }
    }
    assertWritingResult(result)
    return result
  },

  async analyzeReproduction(input: AnalyzeReproductionInput) {
    requireValue(input.topic, '缺少项目研究方向，无法生成复现建议。')
    const raw = await fetchJson<unknown>(aiEndpoints.analyzeReproduction, input)
    const result = unwrap<AnalyzeReproductionResult>(raw, 'guide')
    assertReproductionResult(result)
    return result
  },
}
