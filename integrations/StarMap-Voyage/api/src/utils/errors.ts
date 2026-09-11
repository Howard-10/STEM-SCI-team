import type { Response } from 'express'

export type ApiErrorCode =
  | 'validation_error'
  | 'config_error'
  | 'upstream_error'
  | 'invalid_response'

export class ApiError extends Error {
  code: ApiErrorCode
  status: number

  constructor(code: ApiErrorCode, message: string, status = 500) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }
}

export function sendErrorResponse(response: Response, error: unknown) {
  if (error instanceof ApiError) {
    response.status(error.status).json({
      error: error.code,
      message: error.message,
    })
    return
  }

  response.status(500).json({
    error: 'upstream_error',
    message: '模型调用失败',
  })
}
