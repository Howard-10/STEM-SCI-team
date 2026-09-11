import type {
  CompareRow,
  ExperimentInsight,
  OverviewReport,
  Paper,
  ResearchGapAnalysis,
  ReproductionGuide,
  WritingOutput,
} from '../../types'

export type AIProviderMode = 'mock' | 'http'
export type GenerationStatus = 'idle' | 'loading' | 'success' | 'error'
export type AIServiceErrorCode =
  | 'validation'
  | 'provider_not_configured'
  | 'provider_not_implemented'
  | 'request_failed'
  | 'invalid_response'

export class AIServiceError extends Error {
  code: AIServiceErrorCode

  constructor(code: AIServiceErrorCode, message: string) {
    super(message)
    this.name = 'AIServiceError'
    this.code = code
  }
}

export function getAIErrorMessage(
  error: unknown,
  fallback = '生成失败，请稍后重试。',
): string {
  if (error instanceof AIServiceError) {
    return error.message
  }

  if (error instanceof Error && error.message.trim()) {
    return error.message
  }

  return fallback
}

export interface GenerateOverviewInput {
  projectId?: string
  topic: string
  request: string
}

export interface AnalyzePaperInput {
  projectId?: string
  title: string
  abstract: string
  keywords: string[]
}

export interface ComparePapersInput {
  projectId?: string
  topic: string
  papers: Paper[]
}

export interface AnalyzeExperimentInput {
  projectId?: string
  name: string
  rawResult: string
  topic?: string
}

export interface GenerateWritingInput {
  projectId?: string
  topic: string
  type: string
  requirement: string
}

export interface AnalyzeReproductionInput {
  projectId?: string
  topic: string
  githubUrl: string
  errorLog: string
}

export type GenerateOverviewResult = OverviewReport
export type AnalyzePaperResult = Paper
export type AnalyzeExperimentResult = ExperimentInsight
export type GenerateWritingResult = WritingOutput
export type AnalyzeReproductionResult = ReproductionGuide

export interface ComparePapersResult {
  rows: CompareRow[]
  gapAnalysis: ResearchGapAnalysis
}
