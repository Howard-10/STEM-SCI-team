import { AIServiceError } from './types'

interface FetchJsonOptions {
  signal?: AbortSignal
}

function normalizeBaseUrl(baseUrl: string) {
  return baseUrl.endsWith('/') ? baseUrl : `${baseUrl}/`
}

function getApiBaseUrl() {
  const configured = import.meta.env.VITE_API_BASE_URL?.trim()

  if (!configured) {
    throw new AIServiceError(
      'provider_not_configured',
      '当前已切换到 HTTP provider，但未配置 VITE_API_BASE_URL。',
    )
  }

  return normalizeBaseUrl(configured)
}

function buildRequestUrl(endpoint: string) {
  const baseUrl = getApiBaseUrl()
  return new URL(endpoint.replace(/^\//, ''), baseUrl).toString()
}

function getResponseErrorMessage(payload: unknown, status: number, statusText: string) {
  if (payload && typeof payload === 'object') {
    const message = 'message' in payload ? payload.message : undefined
    const error = 'error' in payload ? payload.error : undefined

    if (typeof message === 'string' && message.trim()) {
      return message
    }

    if (typeof error === 'string' && error.trim()) {
      return error
    }
  }

  return `请求失败：${status} ${statusText}`.trim()
}

export async function fetchJson<TResponse>(
  endpoint: string,
  body: unknown,
  options: FetchJsonOptions = {},
): Promise<TResponse> {
  let response: Response

  try {
    response = await fetch(buildRequestUrl(endpoint), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      signal: options.signal,
    })
  } catch (error) {
    throw new AIServiceError(
      'request_failed',
      error instanceof Error && error.message.trim()
        ? `请求失败：${error.message}`
        : '请求失败：无法连接到后端服务。',
    )
  }

  let payload: unknown

  try {
    payload = await response.json()
  } catch {
    throw new AIServiceError('invalid_response', '后端返回了无法解析的 JSON 响应。')
  }

  if (!response.ok) {
    throw new AIServiceError(
      'request_failed',
      getResponseErrorMessage(payload, response.status, response.statusText),
    )
  }

  return payload as TResponse
}
