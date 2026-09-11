import { getOpenAIClient, getOpenAIModel } from './openaiClient.js'
import { ApiError } from '../utils/errors.js'
import type { OverviewReport } from '../utils/validateOverview.js'
import { validateOverviewReport } from '../utils/validateOverview.js'

interface GenerateOverviewInput {
  projectId?: string
  topic: string
  request: string
}

const overviewJsonSchema = {
  name: 'overview_report',
  strict: true,
  schema: {
    type: 'object',
    additionalProperties: false,
    required: [
      'topic',
      'request',
      'background',
      'coreConcepts',
      'keyTasks',
      'mainstreamMethods',
      'commonDatasets',
      'commonMetrics',
      'challenges',
      'entryPoints',
      'readingPath',
    ],
    properties: {
      topic: { type: 'string' },
      request: { type: 'string' },
      background: { type: 'string' },
      coreConcepts: { type: 'array', items: { type: 'string' } },
      keyTasks: { type: 'array', items: { type: 'string' } },
      mainstreamMethods: { type: 'array', items: { type: 'string' } },
      commonDatasets: { type: 'array', items: { type: 'string' } },
      commonMetrics: { type: 'array', items: { type: 'string' } },
      challenges: { type: 'array', items: { type: 'string' } },
      entryPoints: { type: 'array', items: { type: 'string' } },
      readingPath: { type: 'array', items: { type: 'string' } },
    },
  },
} as const

function buildSystemPrompt() {
  return [
    '你是科研入门分析助手。',
    '你必须只返回符合指定 schema 的 JSON。',
    '不要返回 Markdown，不要返回代码块，不要返回额外解释。',
    '所有数组字段都必须是字符串数组。',
    '字段名必须严格匹配：topic、request、background、coreConcepts、keyTasks、mainstreamMethods、commonDatasets、commonMetrics、challenges、entryPoints、readingPath。',
  ].join('\n')
}

function buildUserPrompt(input: GenerateOverviewInput) {
  return [
    `研究方向：${input.topic}`,
    `具体需求：${input.request || '请生成领域快速入门报告'}`,
    '请输出一个结构化领域快速入门报告，覆盖背景、核心概念、研究任务、方法、数据集、评价指标、挑战、切入点与阅读路线。',
  ].join('\n')
}

export async function generateOverviewReport(
  input: GenerateOverviewInput,
): Promise<OverviewReport> {
  try {
    const client = getOpenAIClient()
    const model = getOpenAIModel()

    const completion = await client.chat.completions.create({
      model,
      messages: [
        { role: 'system', content: buildSystemPrompt() },
        { role: 'user', content: buildUserPrompt(input) },
      ],
      response_format: {
        type: 'json_schema',
        json_schema: overviewJsonSchema,
      },
    })

    const content = completion.choices[0]?.message?.content

    if (!content) {
      throw new ApiError('invalid_response', '模型返回格式不符合 OverviewReport 协议', 502)
    }

    const parsed = JSON.parse(content) as unknown
    return validateOverviewReport(parsed)
  } catch (error) {
    if (error instanceof ApiError) {
      throw error
    }

    console.error('[overview upstream error]', error)
    throw new ApiError('upstream_error', '模型调用失败', 502)
  }
}
