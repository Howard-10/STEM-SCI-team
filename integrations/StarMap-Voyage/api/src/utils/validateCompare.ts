import { ApiError } from './errors.js'

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

export interface ResearchIdea {
  id: string
  title: string
  description: string
  noveltyScore: number
  feasibilityScore: number
  workloadScore: number
}

export interface ResearchGapAnalysis {
  commonProblems: string[]
  unresolvedIssues: string[]
  datasetGaps: string[]
  methodGaps: string[]
  transformableQuestions: string[]
  ideas: ResearchIdea[]
}

export interface ComparePapersResult {
  rows: CompareRow[]
  gapAnalysis: ResearchGapAnalysis
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isString(value: unknown): value is string {
  return typeof value === 'string'
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isString)
}

function isValidScore(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 1 && value <= 10
}

function isCompareRow(value: unknown): value is CompareRow {
  return (
    isObject(value) &&
    isString(value.title) &&
    isString(value.motivation) &&
    isString(value.method) &&
    isString(value.innovation) &&
    isString(value.datasets) &&
    isString(value.metrics) &&
    isString(value.strengths) &&
    isString(value.limitation) &&
    isString(value.inspiration)
  )
}

function isResearchIdea(value: unknown): value is ResearchIdea {
  return (
    isObject(value) &&
    isString(value.id) &&
    isString(value.title) &&
    isString(value.description) &&
    isValidScore(value.noveltyScore) &&
    isValidScore(value.feasibilityScore) &&
    isValidScore(value.workloadScore)
  )
}

const INVALID_RESPONSE = '模型返回格式不符合 ComparePapersResult 协议'

export function validateCompareResult(
  value: unknown,
  expectedPaperCount: number,
): ComparePapersResult {
  if (!isObject(value)) {
    console.error('[validateCompare] root is not an object')
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  if (!Array.isArray(value.rows)) {
    console.error('[validateCompare] rows is not an array')
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  if (value.rows.length !== expectedPaperCount) {
    console.error(`[validateCompare] rows.length=${value.rows.length}, expected=${expectedPaperCount}`)
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  const badRowIndex = value.rows.findIndex((row) => !isCompareRow(row))
  if (badRowIndex !== -1) {
    console.error(`[validateCompare] rows[${badRowIndex}] failed CompareRow check:`, JSON.stringify(value.rows[badRowIndex]))
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  const gapAnalysis = value.gapAnalysis
  if (!isObject(gapAnalysis)) {
    console.error('[validateCompare] gapAnalysis is not an object')
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  const arraysWithMin2: (keyof ResearchGapAnalysis)[] = [
    'commonProblems',
    'unresolvedIssues',
    'datasetGaps',
    'methodGaps',
    'transformableQuestions',
  ]

  for (const field of arraysWithMin2) {
    const arr = gapAnalysis[field]
    if (!isStringArray(arr)) {
      console.error(`[validateCompare] gapAnalysis.${field} is not a string array, type=${typeof arr}, isArray=${Array.isArray(arr)}`)
      throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
    }
    if ((arr as string[]).length < 2) {
      console.error(`[validateCompare] gapAnalysis.${field} has only ${(arr as string[]).length} items`)
      throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
    }
  }

  const ideas = gapAnalysis.ideas
  if (!Array.isArray(ideas)) {
    console.error(`[validateCompare] ideas is not an array`)
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }
  if (ideas.length < 2 || ideas.length > 3) {
    console.error(`[validateCompare] ideas.length=${ideas.length}`)
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  const badIdeaIndex = ideas.findIndex((idea) => !isResearchIdea(idea))
  if (badIdeaIndex !== -1) {
    console.error(`[validateCompare] ideas[${badIdeaIndex}] failed ResearchIdea check:`, JSON.stringify(ideas[badIdeaIndex]))
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  return {
    rows: value.rows as CompareRow[],
    gapAnalysis: {
      commonProblems: gapAnalysis.commonProblems as string[],
      unresolvedIssues: gapAnalysis.unresolvedIssues as string[],
      datasetGaps: gapAnalysis.datasetGaps as string[],
      methodGaps: gapAnalysis.methodGaps as string[],
      transformableQuestions: gapAnalysis.transformableQuestions as string[],
      ideas: ideas as ResearchIdea[],
    },
  }
}
