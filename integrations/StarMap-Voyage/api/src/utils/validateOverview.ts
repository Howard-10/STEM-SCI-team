import { ApiError } from './errors.js'

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

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function isString(value: unknown): value is string {
  return typeof value === 'string'
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isString)
}

export function validateOverviewReport(value: unknown): OverviewReport {
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
    throw new ApiError(
      'invalid_response',
      '模型返回格式不符合 OverviewReport 协议',
      502,
    )
  }

  const report: OverviewReport = {
    topic: value.topic,
    request: value.request,
    background: value.background,
    coreConcepts: value.coreConcepts,
    keyTasks: value.keyTasks,
    mainstreamMethods: value.mainstreamMethods,
    commonDatasets: value.commonDatasets,
    commonMetrics: value.commonMetrics,
    challenges: value.challenges,
    entryPoints: value.entryPoints,
    readingPath: value.readingPath,
  }

  if (isString(value.savedAt)) {
    report.savedAt = value.savedAt
  }

  return report
}
