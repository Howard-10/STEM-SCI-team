import {
  generateCompareRows,
  generateExperimentInsight,
  generateOverviewReport,
  generatePaperAnalysis,
  generateReproductionGuide,
  generateResearchGapAnalysis,
  generateWritingOutput,
} from '../../data/mockData'
import type { AIProvider } from './provider'
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
import { AIServiceError } from './types'

function randomDelay() {
  return 300 + Math.floor(Math.random() * 301)
}

async function withMockDelay<T>(factory: () => T): Promise<T> {
  await new Promise((resolve) => window.setTimeout(resolve, randomDelay()))
  return factory()
}

function requireValue(value: string, message: string) {
  if (!value.trim()) {
    throw new AIServiceError('validation', message)
  }
}

async function generateOverview(
  input: GenerateOverviewInput,
): Promise<GenerateOverviewResult> {
  requireValue(input.topic, '请输入研究方向后再生成领域报告。')

  return withMockDelay(() => generateOverviewReport(input.topic, input.request))
}

async function analyzePaper(input: AnalyzePaperInput): Promise<AnalyzePaperResult> {
  requireValue(input.title, '请输入论文标题后再生成精读卡片。')
  requireValue(input.abstract, '请输入论文摘要后再生成精读卡片。')

  return withMockDelay(() =>
    generatePaperAnalysis({
      title: input.title,
      abstract: input.abstract,
      keywords: input.keywords,
    }),
  )
}

async function comparePapers(
  input: ComparePapersInput,
): Promise<ComparePapersResult> {
  if (input.papers.length < 2) {
    throw new AIServiceError('validation', '请至少选择 2 篇论文后再生成对比结果。')
  }

  return withMockDelay(() => ({
    rows: generateCompareRows(input.papers),
    gapAnalysis: generateResearchGapAnalysis(input.topic, input.papers),
  }))
}

async function analyzeExperiment(
  input: AnalyzeExperimentInput,
): Promise<AnalyzeExperimentResult> {
  requireValue(input.name, '请输入实验名称后再生成分析。')
  requireValue(input.rawResult, '请输入实验结果文本后再生成分析。')

  return withMockDelay(() => generateExperimentInsight(input.name, input.rawResult))
}

async function generateWriting(
  input: GenerateWritingInput,
): Promise<GenerateWritingResult> {
  requireValue(input.type, '请选择写作类型后再生成内容。')
  requireValue(input.topic, '缺少项目研究方向，无法生成写作内容。')

  return withMockDelay(() =>
    generateWritingOutput(input.type, input.requirement, input.topic),
  )
}

async function analyzeReproduction(
  input: AnalyzeReproductionInput,
): Promise<AnalyzeReproductionResult> {
  requireValue(input.topic, '缺少项目研究方向，无法生成复现建议。')

  return withMockDelay(() =>
    generateReproductionGuide(input.topic, input.githubUrl, input.errorLog),
  )
}

export const mockProvider: AIProvider = {
  generateOverview,
  analyzePaper,
  comparePapers,
  analyzeExperiment,
  generateWriting,
  analyzeReproduction,
}

export {
  analyzeExperiment,
  analyzePaper,
  analyzeReproduction,
  comparePapers,
  generateOverview,
  generateWriting,
}
