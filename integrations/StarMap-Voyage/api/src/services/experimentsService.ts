import { getOpenAIClient, getOpenAIModel } from './openaiClient.js'
import { ApiError } from '../utils/errors.js'
import { validateExperimentInsight, type ExperimentInsight } from '../utils/validateExperiment.js'

interface GenerateExperimentInput {
  projectId?: string
  name: string
  rawResult: string
  topic?: string
}

const experimentJsonSchema = {
  name: 'experiment_insight',
  strict: true,
  schema: {
    type: 'object',
    additionalProperties: false,
    required: [
      'trend', 'bestMethod', 'metricChange', 'outlierNote',
      'possibleReasons', 'extraExperiments', 'paperConclusion',
      'chartSuggestion',
    ],
    properties: {
      trend:            { type: 'string' },
      bestMethod:       { type: 'string' },
      metricChange:     { type: 'string' },
      outlierNote:      { type: 'string' },
      possibleReasons:  { type: 'array', items: { type: 'string' } },
      extraExperiments: { type: 'array', items: { type: 'string' } },
      paperConclusion:  { type: 'string' },
      chartSuggestion: {
        type: 'object',
        additionalProperties: false,
        required: ['chartType', 'xAxis', 'yAxis', 'title', 'highlight', 'matplotlibSnippet'],
        properties: {
          chartType:         { type: 'string' },
          xAxis:             { type: 'string' },
          yAxis:             { type: 'string' },
          title:             { type: 'string' },
          highlight:         { type: 'string' },
          matplotlibSnippet: { type: 'string' },
        },
      },
    },
  },
} as const

function buildSystemPrompt() {
  return [
    '你是实验结果分析助手。用户会提供实验名称、实验结果文本和可选的研究方向。',
    '请基于这些信息完成分析：',
    '',
    '1. trend: 总体趋势判断',
    '2. bestMethod: 当前最优方法/配置',
    '3. metricChange: 指标变化情况描述',
    '4. outlierNote: 异常值或波动点说明',
    '5. possibleReasons: 可能的原因分析（至少 2 条）',
    '6. extraExperiments: 建议补充的实验（至少 2 条）',
    '7. paperConclusion: 可直接写进论文的实验结论',
    '8. chartSuggestion: 图表建议',
    '   - chartType: 推荐图表类型（如"分组柱状图"、"折线图"等）',
    '   - xAxis / yAxis / title: 坐标轴和标题',
    '   - highlight: 需要突出的对比关系',
    '   - matplotlibSnippet: 一段可直接运行的 matplotlib 示例代码',
    '',
    'matplotlibSnippet 要求：',
    '- 使用 import matplotlib.pyplot as plt',
    '- 包含示例数据和方法标签',
    '- 代码完整可运行',
    '- 只能生成 matplotlib 绘图相关代码，不要包含系统命令、文件删除、网络请求、敏感路径读写等操作',
    '',
    '如果实验结果信息不足，基于实验名称和研究方向合理推断。',
    '必须只返回符合指定 schema 的 JSON。',
    '不要返回 Markdown，不要返回代码块，不要返回额外解释。',
  ].join('\n')
}

function buildUserPrompt(input: GenerateExperimentInput) {
  return [
    `实验名称：${input.name}`,
    `研究方向：${input.topic || '未提供'}`,
    `实验结果：`,
    input.rawResult,
    '',
    '请生成完整的实验结果分析。',
  ].join('\n')
}

export async function generateExperimentInsight(
  input: GenerateExperimentInput,
): Promise<ExperimentInsight> {
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
        json_schema: experimentJsonSchema,
      },
    })

    const content = completion.choices[0]?.message?.content

    if (!content) {
      throw new ApiError('invalid_response', '模型返回格式不符合 ExperimentInsight 协议', 502)
    }

    let parsed: unknown
    try {
      parsed = JSON.parse(content)
    } catch {
      throw new ApiError('invalid_response', '模型返回格式不符合 ExperimentInsight 协议', 502)
    }

    return validateExperimentInsight(parsed)
  } catch (error) {
    if (error instanceof ApiError) {
      throw error
    }

    console.error('[experiment upstream error]', error)
    throw new ApiError('upstream_error', '模型调用失败', 502)
  }
}
