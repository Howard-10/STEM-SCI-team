import { ApiError } from './errors.js'

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

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isString(value: unknown): value is string {
  return typeof value === 'string'
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isString)
}

function isBoolean(value: unknown): value is boolean {
  return typeof value === 'boolean'
}

function generateId(): string {
  if (typeof crypto !== 'undefined' && typeof (crypto as any).randomUUID === 'function') {
    return `paper-${(crypto as any).randomUUID()}`
  }
  return `paper-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

const INVALID_RESPONSE = '模型返回格式不符合 Paper 协议'

export function validatePaper(value: unknown): Paper {
  if (!isObject(value)) {
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  const requiredStrings = [
    'title', 'abstract', 'background', 'motivation', 'coreProblem',
    'method', 'experimentDesign', 'limitation', 'inspiration', 'contribution',
  ]

  for (const field of requiredStrings) {
    if (!isString(value[field])) {
      throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
    }
  }

  if (!isStringArray(value.keywords) || (value.keywords as string[]).length < 1) {
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  if (!isStringArray(value.innovation) || (value.innovation as string[]).length < 2) {
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  if (!isStringArray(value.datasets) || (value.datasets as string[]).length < 1) {
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  if (!isStringArray(value.metrics) || (value.metrics as string[]).length < 1) {
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  if (!isStringArray(value.strengths) || (value.strengths as string[]).length < 2) {
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  if (!isBoolean(value.isBaselineCandidate)) {
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  return {
    id: generateId(),
    title: value.title as string,
    abstract: value.abstract as string,
    keywords: value.keywords as string[],
    background: value.background as string,
    motivation: value.motivation as string,
    coreProblem: value.coreProblem as string,
    method: value.method as string,
    innovation: value.innovation as string[],
    experimentDesign: value.experimentDesign as string,
    datasets: value.datasets as string[],
    metrics: value.metrics as string[],
    strengths: value.strengths as string[],
    limitation: value.limitation as string,
    inspiration: value.inspiration as string,
    contribution: value.contribution as string,
    isBaselineCandidate: value.isBaselineCandidate as boolean,
    createdAt: new Date().toISOString(),
  }
}
