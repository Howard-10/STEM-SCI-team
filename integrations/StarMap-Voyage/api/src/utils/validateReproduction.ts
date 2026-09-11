import { ApiError } from './errors.js'

export interface ReproductionGuide {
  repoGoal: string
  readmeSummary: string[]
  environmentCommands: string[]
  debugSuggestions: string[]
  nextSteps: string[]
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

const INVALID_RESPONSE = '模型返回格式不符合 ReproductionGuide 协议'

export function validateReproductionGuide(value: unknown): ReproductionGuide {
  if (!isObject(value)) {
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  if (!isString(value.repoGoal)) {
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  if (!isStringArray(value.readmeSummary) || (value.readmeSummary as string[]).length < 3) {
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  if (!isStringArray(value.environmentCommands) || (value.environmentCommands as string[]).length < 1) {
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  if (!isStringArray(value.debugSuggestions) || (value.debugSuggestions as string[]).length < 2) {
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  if (!isStringArray(value.nextSteps) || (value.nextSteps as string[]).length < 2) {
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  return {
    repoGoal: value.repoGoal as string,
    readmeSummary: value.readmeSummary as string[],
    environmentCommands: value.environmentCommands as string[],
    debugSuggestions: value.debugSuggestions as string[],
    nextSteps: value.nextSteps as string[],
  }
}
