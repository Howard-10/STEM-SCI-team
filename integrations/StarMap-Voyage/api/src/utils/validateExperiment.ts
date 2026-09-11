import { ApiError } from './errors.js'

export interface ChartSuggestion {
  chartType: string
  xAxis: string
  yAxis: string
  title: string
  highlight: string
  matplotlibSnippet: string
}

export interface ExperimentInsight {
  trend: string
  bestMethod: string
  metricChange: string
  outlierNote: string
  possibleReasons: string[]
  extraExperiments: string[]
  paperConclusion: string
  chartSuggestion: ChartSuggestion
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

const DANGEROUS_PATTERNS = [
  'os.system',
  'subprocess',
  'rm -rf',
  'rm -r',
  'requests.',
  '/etc/',
  'C:\\Windows',
  '/bin/',
  '__import__',
  'eval(',
  'exec(',
]

const INVALID_RESPONSE = '模型返回格式不符合 ExperimentInsight 协议'

export function validateExperimentInsight(value: unknown): ExperimentInsight {
  if (!isObject(value)) {
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  const requiredStrings = ['trend', 'bestMethod', 'metricChange', 'outlierNote', 'paperConclusion']
  for (const field of requiredStrings) {
    if (!isString(value[field])) {
      throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
    }
  }

  if (!isStringArray(value.possibleReasons) || (value.possibleReasons as string[]).length < 2) {
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  if (!isStringArray(value.extraExperiments) || (value.extraExperiments as string[]).length < 2) {
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  const chartSuggestion = value.chartSuggestion
  if (!isObject(chartSuggestion)) {
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  const chartFields = ['chartType', 'xAxis', 'yAxis', 'title', 'highlight', 'matplotlibSnippet']
  for (const field of chartFields) {
    if (!isString(chartSuggestion[field])) {
      throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
    }
  }

  const snippet = chartSuggestion.matplotlibSnippet as string
  if (!snippet.trim()) {
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  if (!snippet.includes('import matplotlib.pyplot as plt')) {
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  for (const pattern of DANGEROUS_PATTERNS) {
    if (snippet.includes(pattern)) {
      throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
    }
  }

  return {
    trend: value.trend as string,
    bestMethod: value.bestMethod as string,
    metricChange: value.metricChange as string,
    outlierNote: value.outlierNote as string,
    possibleReasons: value.possibleReasons as string[],
    extraExperiments: value.extraExperiments as string[],
    paperConclusion: value.paperConclusion as string,
    chartSuggestion: {
      chartType: chartSuggestion.chartType as string,
      xAxis: chartSuggestion.xAxis as string,
      yAxis: chartSuggestion.yAxis as string,
      title: chartSuggestion.title as string,
      highlight: chartSuggestion.highlight as string,
      matplotlibSnippet: snippet,
    },
  }
}
