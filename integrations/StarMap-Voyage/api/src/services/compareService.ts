import { getOpenAIClient, getOpenAIModel } from './openaiClient.js'
import { ApiError } from '../utils/errors.js'
import { validateCompareResult, type ComparePapersResult } from '../utils/validateCompare.js'

interface GenerateCompareInput {
  projectId?: string
  topic: string
  papers: Record<string, unknown>[]
}

const compareJsonSchema = {
  name: 'compare_result',
  strict: true,
  schema: {
    type: 'object',
    additionalProperties: false,
    required: ['rows', 'gapAnalysis'],
    properties: {
      rows: {
        type: 'array',
        items: {
          type: 'object',
          additionalProperties: false,
          required: [
            'title',
            'motivation',
            'method',
            'innovation',
            'datasets',
            'metrics',
            'strengths',
            'limitation',
            'inspiration',
          ],
          properties: {
            title: { type: 'string' },
            motivation: { type: 'string' },
            method: { type: 'string' },
            innovation: { type: 'string' },
            datasets: { type: 'string' },
            metrics: { type: 'string' },
            strengths: { type: 'string' },
            limitation: { type: 'string' },
            inspiration: { type: 'string' },
          },
        },
      },
      gapAnalysis: {
        type: 'object',
        additionalProperties: false,
        required: [
          'commonProblems',
          'unresolvedIssues',
          'datasetGaps',
          'methodGaps',
          'transformableQuestions',
          'ideas',
        ],
        properties: {
          commonProblems: { type: 'array', items: { type: 'string' } },
          unresolvedIssues: { type: 'array', items: { type: 'string' } },
          datasetGaps: { type: 'array', items: { type: 'string' } },
          methodGaps: { type: 'array', items: { type: 'string' } },
          transformableQuestions: { type: 'array', items: { type: 'string' } },
          ideas: {
            type: 'array',
            items: {
              type: 'object',
              additionalProperties: false,
              required: [
                'id',
                'title',
                'description',
                'noveltyScore',
                'feasibilityScore',
                'workloadScore',
              ],
              properties: {
                id: { type: 'string' },
                title: { type: 'string' },
                description: { type: 'string' },
                noveltyScore: { type: 'number' },
                feasibilityScore: { type: 'number' },
                workloadScore: { type: 'number' },
              },
            },
          },
        },
      },
    },
  },
} as const

function buildSystemPrompt() {
  return [
    '你是科研文献对比分析助手。你会收到一个研究方向和多篇论文的详细信息。',
    '请完成两项任务：',
    '1. 为每篇论文生成一行对比表，提取并精炼其 motivation、方法、创新点、数据集、指标、优点、局限性、对项目的启发。rows 数组长度必须严格等于输入论文数量。',
    '2. 基于所有论文的局限性、启发和贡献，生成研究空白分析，包括共性问题、未解决问题、数据缺口、方法缺口、可转化研究问题、以及 2-3 个新研究想法。每个想法包含 id、title、description 和 1-10 的三个评分（noveltyScore、feasibilityScore、workloadScore，必须为整数）。',
    '必须只返回符合指定 schema 的 JSON。',
    '不要返回 Markdown，不要返回代码块，不要返回额外解释。',
    'gapAnalysis 中每个数组至少包含 2 个元素。',
    'ideas 数组包含 2-3 个 idea。',
  ].join('\n')
}

const safeText = (value: unknown, fallback = '未提供') =>
  typeof value === 'string' && value.trim() ? value : fallback

const safeStringArray = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : []

function buildUserPrompt(input: GenerateCompareInput) {
  const papersBlock = input.papers
    .map(
      (p, i) =>
        [
          `论文${i + 1}：`,
          `标题：${safeText(p.title)}`,
          `摘要：${safeText(p.abstract)}`,
          `关键词：${safeStringArray(p.keywords).join('、') || '未提供'}`,
          `背景：${safeText(p.background)}`,
          `动机：${safeText(p.motivation)}`,
          `核心问题：${safeText(p.coreProblem)}`,
          `方法：${safeText(p.method)}`,
          `创新点：${safeStringArray(p.innovation).join('、') || '未提供'}`,
          `实验设计：${safeText(p.experimentDesign)}`,
          `数据集：${safeStringArray(p.datasets).join('、') || '未提供'}`,
          `评价指标：${safeStringArray(p.metrics).join('、') || '未提供'}`,
          `优点：${safeStringArray(p.strengths).join('、') || '未提供'}`,
          `局限性：${safeText(p.limitation)}`,
          `对项目启发：${safeText(p.inspiration)}`,
          `贡献：${safeText(p.contribution)}`,
          p.isBaselineCandidate ? '（标注为 baseline 候选）' : '',
        ].join('\n'),
    )
    .join('\n\n')

  return [
    `研究方向：${input.topic}`,
    '',
    '以下是要对比的论文：',
    '',
    papersBlock,
    '',
    '请生成结构化对比表和研究空白分析。',
  ].join('\n')
}

export async function generateCompareResult(
  input: GenerateCompareInput,
): Promise<ComparePapersResult> {
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
        json_schema: compareJsonSchema,
      },
    })

    const content = completion.choices[0]?.message?.content

    if (!content) {
      throw new ApiError('invalid_response', '模型返回格式不符合 ComparePapersResult 协议', 502)
    }

    let parsed: unknown
    try {
      parsed = JSON.parse(content)
    } catch {
      console.error('[compare JSON parse failed] content length:', content.length)
      throw new ApiError('invalid_response', '模型返回格式不符合 ComparePapersResult 协议', 502)
    }

    return validateCompareResult(parsed, input.papers.length)
  } catch (error) {
    if (error instanceof ApiError) {
      throw error
    }

    console.error('[compare upstream error]', error)
    throw new ApiError('upstream_error', '模型调用失败', 502)
  }
}
