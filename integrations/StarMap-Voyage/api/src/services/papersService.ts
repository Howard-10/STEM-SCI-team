import { getOpenAIClient, getOpenAIModel } from './openaiClient.js'
import { ApiError } from '../utils/errors.js'
import { validatePaper, type Paper } from '../utils/validatePaper.js'

interface GeneratePaperInput {
  projectId?: string
  title: string
  abstract: string
  keywords: string[]
}

const paperJsonSchema = {
  name: 'paper_analysis',
  strict: true,
  schema: {
    type: 'object',
    additionalProperties: false,
    required: [
      'title', 'abstract', 'keywords', 'background', 'motivation',
      'coreProblem', 'method', 'innovation', 'experimentDesign',
      'datasets', 'metrics', 'strengths', 'limitation',
      'inspiration', 'contribution', 'isBaselineCandidate',
    ],
    properties: {
      title: { type: 'string' },
      abstract: { type: 'string' },
      keywords: { type: 'array', items: { type: 'string' } },
      background: { type: 'string' },
      motivation: { type: 'string' },
      coreProblem: { type: 'string' },
      method: { type: 'string' },
      innovation: { type: 'array', items: { type: 'string' } },
      experimentDesign: { type: 'string' },
      datasets: { type: 'array', items: { type: 'string' } },
      metrics: { type: 'array', items: { type: 'string' } },
      strengths: { type: 'array', items: { type: 'string' } },
      limitation: { type: 'string' },
      inspiration: { type: 'string' },
      contribution: { type: 'string' },
      isBaselineCandidate: { type: 'boolean' },
    },
  },
} as const

function buildSystemPrompt() {
  return [
    '你是科研论文精读分析助手。用户会提供论文标题、摘要和关键词。',
    '请基于这些信息，推断并生成该论文的完整结构化分析，包括：',
    '- background: 研究背景',
    '- motivation: 研究动机',
    '- coreProblem: 核心问题',
    '- method: 方法框架',
    '- innovation: 创新点列表（至少 2 条）',
    '- experimentDesign: 实验设计',
    '- datasets: 使用的数据集（至少 1 个）',
    '- metrics: 评价指标（至少 1 个）',
    '- strengths: 优点列表（至少 2 条）',
    '- limitation: 局限性',
    '- inspiration: 对后续研究的启发',
    '- contribution: 主要贡献',
    '- isBaselineCandidate: 是否适合做 baseline（true/false）',
    '必须只返回符合指定 schema 的 JSON。',
    '不要返回 Markdown，不要返回代码块，不要返回额外解释。',
  ].join('\n')
}

function buildUserPrompt(input: GeneratePaperInput) {
  return [
    `论文标题：${input.title}`,
    `论文摘要：${input.abstract}`,
    `关键词：${input.keywords.join('、')}`,
    '',
    '请生成该论文的完整结构化精读卡片。',
  ].join('\n')
}

export async function generatePaperAnalysis(
  input: GeneratePaperInput,
): Promise<Paper> {
  try {
    const client = getOpenAIClient()
    const model = getOpenAIModel()

    const completion = await client.chat.completions.create({
      model,
      max_tokens: 4096,
      messages: [
        { role: 'system', content: buildSystemPrompt() },
        { role: 'user', content: buildUserPrompt(input) },
      ],
      response_format: {
        type: 'json_schema',
        json_schema: paperJsonSchema,
      },
    })

    const content = completion.choices[0]?.message?.content

    if (!content) {
      throw new ApiError('invalid_response', '模型返回格式不符合 Paper 协议', 502)
    }

    let parsed: unknown
    try {
      parsed = JSON.parse(content)
    } catch {
      throw new ApiError('invalid_response', '模型返回格式不符合 Paper 协议', 502)
    }

    return validatePaper(parsed)
  } catch (error) {
    if (error instanceof ApiError) {
      throw error
    }

    console.error('[papers upstream error]', error)
    throw new ApiError('upstream_error', '模型调用失败', 502)
  }
}
