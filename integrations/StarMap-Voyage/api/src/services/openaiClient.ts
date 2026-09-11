import OpenAI from 'openai'
import { ApiError } from '../utils/errors.js'

let cachedClient: OpenAI | null = null

function getRequiredEnv(name: 'OPENAI_API_KEY' | 'OPENAI_MODEL') {
  const value = process.env[name]?.trim()

  if (!value) {
    throw new ApiError('config_error', `${name} 未配置`, 500)
  }

  return value
}

export function getOpenAIModel() {
  return getRequiredEnv('OPENAI_MODEL')
}

export function getOpenAIClient() {
  if (cachedClient) {
    return cachedClient
  }

  const apiKey = getRequiredEnv('OPENAI_API_KEY')
  const baseURL = process.env.OPENAI_BASE_URL?.trim()

  cachedClient = baseURL
    ? new OpenAI({ apiKey, baseURL })
    : new OpenAI({ apiKey })

  return cachedClient
}
