import { useCallback, useState } from 'react'
import { getAIErrorMessage, type GenerationStatus } from '../services/ai'

interface UseAsyncGenerationOptions<TResult> {
  initialData?: TResult
  fallbackMessage?: string
  preserveDataOnError?: boolean
}

export function useAsyncGeneration<TResult>({
  initialData,
  fallbackMessage,
  preserveDataOnError = true,
}: UseAsyncGenerationOptions<TResult> = {}) {
  const [data, setData] = useState<TResult | undefined>(initialData)
  const [status, setStatus] = useState<GenerationStatus>('idle')
  const [error, setError] = useState('')

  const run = useCallback(
    async (task: () => Promise<TResult>) => {
      setError('')
      setStatus('loading')

      try {
        const result = await task()
        setData(result)
        setStatus('success')
        return result
      } catch (generationError) {
        if (!preserveDataOnError) {
          setData(undefined)
        }
        setError(getAIErrorMessage(generationError, fallbackMessage))
        setStatus('error')
        return undefined
      }
    },
    [fallbackMessage, preserveDataOnError],
  )

  const clearError = useCallback(() => {
    setError('')
    setStatus((current) => (current === 'error' ? 'idle' : current))
  }, [])

  return {
    data,
    setData,
    status,
    error,
    isGenerating: status === 'loading',
    hasError: status === 'error',
    hasData: data !== undefined,
    run,
    clearError,
  }
}
