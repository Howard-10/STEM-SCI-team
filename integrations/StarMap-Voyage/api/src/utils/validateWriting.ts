import { ApiError } from './errors.js'

export interface WritingOutput {
  paragraph: string
  pptOutline: string[]
  speakerNotes: string[]
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

const INVALID_RESPONSE = '模型返回格式不符合 WritingOutput 协议'

export function validateWritingOutput(value: unknown): WritingOutput {
  if (!isObject(value)) {
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  if (!isString(value.paragraph) || !value.paragraph.trim()) {
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  if (!isStringArray(value.pptOutline) || (value.pptOutline as string[]).length < 3) {
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  if (!isStringArray(value.speakerNotes) || (value.speakerNotes as string[]).length < 2) {
    throw new ApiError('invalid_response', INVALID_RESPONSE, 502)
  }

  return {
    paragraph: value.paragraph as string,
    pptOutline: value.pptOutline as string[],
    speakerNotes: value.speakerNotes as string[],
  }
}
