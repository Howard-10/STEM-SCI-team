import { Router } from 'express'
import { generateOverviewReport } from '../services/overviewService.js'
import { generateCompareResult } from '../services/compareService.js'
import { generatePaperAnalysis } from '../services/papersService.js'
import { generateReproductionGuide } from '../services/reproductionService.js'
import { generateWritingOutput } from '../services/writingService.js'
import { generateExperimentInsight } from '../services/experimentsService.js'
import { ApiError, sendErrorResponse } from '../utils/errors.js'

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

interface OverviewRequestBody {
  projectId?: unknown
  topic?: unknown
  request?: unknown
}

export const aiRouter = Router()

aiRouter.post('/overview', async (request, response) => {
  try {
    const body = (request.body ?? {}) as OverviewRequestBody

    if (typeof body.topic !== 'string' || !body.topic.trim()) {
      throw new ApiError('validation_error', 'topic 为必填字符串', 400)
    }

    if (body.request !== undefined && typeof body.request !== 'string') {
      throw new ApiError('validation_error', 'request 必须为字符串', 400)
    }

    if (body.projectId !== undefined && typeof body.projectId !== 'string') {
      throw new ApiError('validation_error', 'projectId 必须为字符串', 400)
    }

    const report = await generateOverviewReport({
      projectId: body.projectId,
      topic: body.topic,
      request: typeof body.request === 'string' ? body.request : '',
    })

    response.json(report)
  } catch (error) {
    sendErrorResponse(response, error)
  }
})

aiRouter.post('/compare', async (request, response) => {
  try {
    const body = (request.body ?? {}) as Record<string, unknown>

    if (typeof body.topic !== 'string' || !body.topic.trim()) {
      throw new ApiError('validation_error', 'topic 为必填字符串', 400)
    }

    if (!Array.isArray(body.papers)) {
      throw new ApiError('validation_error', 'papers 必须为数组', 400)
    }
    if (body.papers.length < 2) {
      throw new ApiError('validation_error', 'papers 至少需要 2 篇', 400)
    }
    if (body.papers.length > 6) {
      throw new ApiError('validation_error', 'papers 最多支持 6 篇', 400)
    }

    body.papers.forEach((paper: unknown, index: number) => {
      if (!isObject(paper)) {
        throw new ApiError('validation_error', `papers[${index}] 必须为对象`, 400)
      }
      const requiredStrings = ['title', 'motivation', 'method', 'limitation', 'inspiration']
      for (const field of requiredStrings) {
        if (typeof paper[field] !== 'string' || !(paper[field] as string).trim()) {
          throw new ApiError('validation_error', `papers[${index}].${field} 为必填字符串`, 400)
        }
      }
      const requiredArrays = ['innovation', 'datasets', 'metrics', 'strengths']
      for (const field of requiredArrays) {
        if (
          !Array.isArray(paper[field]) ||
          !(paper[field] as unknown[]).every((v: unknown) => typeof v === 'string')
        ) {
          throw new ApiError('validation_error', `papers[${index}].${field} 必须为字符串数组`, 400)
        }
      }
    })

    const result = await generateCompareResult({
      projectId: typeof body.projectId === 'string' ? body.projectId : undefined,
      topic: body.topic as string,
      papers: body.papers as Record<string, unknown>[],
    })

    response.json(result)
  } catch (error) {
    sendErrorResponse(response, error)
  }
})

aiRouter.post('/papers/analyze', async (request, response) => {
  try {
    const body = (request.body ?? {}) as Record<string, unknown>

    if (typeof body.title !== 'string' || !body.title.trim()) {
      throw new ApiError('validation_error', 'title 为必填字符串', 400)
    }

    if (typeof body.abstract !== 'string' || !body.abstract.trim()) {
      throw new ApiError('validation_error', 'abstract 为必填字符串', 400)
    }

    if (
      !Array.isArray(body.keywords) ||
      body.keywords.length < 1 ||
      !body.keywords.every(
        (v: unknown) => typeof v === 'string' && v.trim().length > 0,
      )
    ) {
      throw new ApiError(
        'validation_error',
        'keywords 必须为非空字符串数组且至少包含 1 个元素',
        400,
      )
    }

    const paper = await generatePaperAnalysis({
      projectId: typeof body.projectId === 'string' ? body.projectId : undefined,
      title: body.title as string,
      abstract: body.abstract as string,
      keywords: body.keywords as string[],
    })

    response.json(paper)
  } catch (error) {
    sendErrorResponse(response, error)
  }
})

aiRouter.post('/reproduction/analyze', async (request, response) => {
  try {
    const body = (request.body ?? {}) as Record<string, unknown>

    if (typeof body.topic !== 'string' || !body.topic.trim()) {
      throw new ApiError('validation_error', 'topic 为必填字符串', 400)
    }

    if (typeof body.githubUrl !== 'string' || !body.githubUrl.trim()) {
      throw new ApiError('validation_error', 'githubUrl 为必填字符串', 400)
    }

    if (body.errorLog !== undefined && typeof body.errorLog !== 'string') {
      throw new ApiError('validation_error', 'errorLog 必须为字符串', 400)
    }

    const guide = await generateReproductionGuide({
      projectId: typeof body.projectId === 'string' ? body.projectId : undefined,
      topic: body.topic as string,
      githubUrl: body.githubUrl as string,
      errorLog: typeof body.errorLog === 'string' ? body.errorLog : '',
    })

    response.json(guide)
  } catch (error) {
    sendErrorResponse(response, error)
  }
})

aiRouter.post('/writing/generate', async (request, response) => {
  try {
    const body = (request.body ?? {}) as Record<string, unknown>

    if (typeof body.topic !== 'string' || !body.topic.trim()) {
      throw new ApiError('validation_error', 'topic 为必填字符串', 400)
    }

    if (typeof body.type !== 'string' || !body.type.trim()) {
      throw new ApiError('validation_error', 'type 为必填字符串', 400)
    }

    if (body.requirement !== undefined && typeof body.requirement !== 'string') {
      throw new ApiError('validation_error', 'requirement 必须为字符串', 400)
    }

    const output = await generateWritingOutput({
      projectId: typeof body.projectId === 'string' ? body.projectId : undefined,
      topic: body.topic as string,
      type: body.type as string,
      requirement: typeof body.requirement === 'string' ? body.requirement : '',
    })

    response.json(output)
  } catch (error) {
    sendErrorResponse(response, error)
  }
})

aiRouter.post('/experiments/analyze', async (request, response) => {
  try {
    const body = (request.body ?? {}) as Record<string, unknown>

    if (typeof body.name !== 'string' || !body.name.trim()) {
      throw new ApiError('validation_error', 'name 为必填字符串', 400)
    }

    if (typeof body.rawResult !== 'string' || !body.rawResult.trim()) {
      throw new ApiError('validation_error', 'rawResult 为必填字符串', 400)
    }

    if (body.topic !== undefined && typeof body.topic !== 'string') {
      throw new ApiError('validation_error', 'topic 必须为字符串', 400)
    }

    const insight = await generateExperimentInsight({
      projectId: typeof body.projectId === 'string' ? body.projectId : undefined,
      name: body.name as string,
      rawResult: body.rawResult as string,
      topic: typeof body.topic === 'string' ? body.topic : undefined,
    })

    response.json(insight)
  } catch (error) {
    sendErrorResponse(response, error)
  }
})
