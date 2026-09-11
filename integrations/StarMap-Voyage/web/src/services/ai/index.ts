import { createAIService } from './createAIService'
import { httpProvider } from './httpProvider'
import { mockProvider } from './mockProvider'
import type { AIProviderMode } from './types'

const AI_PROVIDER_MODE: AIProviderMode =
  import.meta.env.VITE_AI_PROVIDER === 'http' ? 'http' : 'mock'

const provider = AI_PROVIDER_MODE === 'http' ? httpProvider : mockProvider

export const aiService = createAIService(provider)

export { AIServiceError, getAIErrorMessage } from './types'
export type * from './provider'
export type * from './types'
