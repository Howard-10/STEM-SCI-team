import { getOpenAIClient, getOpenAIModel } from './openaiClient.js'
import { ApiError } from '../utils/errors.js'
import { validateWritingOutput, type WritingOutput } from '../utils/validateWriting.js'

interface GenerateWritingInput {
  projectId?: string
  topic: string
  type: string
  requirement: string
}

const writingJsonSchema = {
  name: 'writing_output',
  strict: true,
  schema: {
    type: 'object',
    additionalProperties: false,
    required: ['paragraph', 'pptOutline', 'speakerNotes'],
    properties: {
      paragraph:    { type: 'string' },
      pptOutline:   { type: 'array', items: { type: 'string' } },
      speakerNotes: { type: 'array', items: { type: 'string' } },
    },
  },
} as const

function buildSystemPrompt() {
  return [
    '你是科研写作助手。根据用户提供的研究方向和写作类型，生成对应的学术写作内容。',
    '请输出：',
    '1. paragraph: 一段流畅的学术正文段落',
    '2. pptOutline: PPT 汇报大纲（至少 3 条）',
    '3. speakerNotes: 对应的演讲备注（至少 2 条）',
    '',
    '写作要求：',
    '- 语言简洁、逻辑清晰、适合口头汇报',
    '- 不要编造具体实验数据',
    '- pptOutline 每条建议不超过两句话',
    '- speakerNotes 应提供承上启下的讲解衔接建议',
    '',
    '必须只返回符合指定 schema 的 JSON。',
    '不要返回 Markdown，不要返回代码块，不要返回额外解释。',
  ].join('\n')
}

function buildUserPrompt(input: GenerateWritingInput) {
  return [
    `研究方向：${input.topic}`,
    `写作类型：${input.type}`,
    `具体要求：${input.requirement || '请生成标准学术写作内容'}`,
    '',
    '请生成写作输出。',
  ].join('\n')
}

export async function generateWritingOutput(
  input: GenerateWritingInput,
): Promise<WritingOutput> {
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
        json_schema: writingJsonSchema,
      },
    })

    const content = completion.choices[0]?.message?.content

    if (!content) {
      throw new ApiError('invalid_response', '模型返回格式不符合 WritingOutput 协议', 502)
    }

    let parsed: unknown
    try {
      parsed = JSON.parse(content)
    } catch {
      throw new ApiError('invalid_response', '模型返回格式不符合 WritingOutput 协议', 502)
    }

    return validateWritingOutput(parsed)
  } catch (error) {
    if (error instanceof ApiError) {
      throw error
    }

    console.error('[writing upstream error]', error)
    throw new ApiError('upstream_error', '模型调用失败', 502)
  }
}
