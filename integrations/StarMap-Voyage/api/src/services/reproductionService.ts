import { getOpenAIClient, getOpenAIModel } from './openaiClient.js'
import { fetchRepoInfo } from './githubClient.js'
import { ApiError } from '../utils/errors.js'
import { validateReproductionGuide, type ReproductionGuide } from '../utils/validateReproduction.js'

interface GenerateReproductionInput {
  projectId?: string
  topic: string
  githubUrl: string
  errorLog: string
}

const reproductionJsonSchema = {
  name: 'reproduction_guide',
  strict: true,
  schema: {
    type: 'object',
    additionalProperties: false,
    required: [
      'repoGoal', 'readmeSummary', 'environmentCommands',
      'debugSuggestions', 'nextSteps',
    ],
    properties: {
      repoGoal:             { type: 'string' },
      readmeSummary:        { type: 'array', items: { type: 'string' } },
      environmentCommands:  { type: 'array', items: { type: 'string' } },
      debugSuggestions:     { type: 'array', items: { type: 'string' } },
      nextSteps:            { type: 'array', items: { type: 'string' } },
    },
  },
} as const

function buildSystemPrompt() {
  return [
    '你是代码复现分析助手。用户会提供：',
    '- 一个 GitHub 仓库的 README 内容（如果获取成功）',
    '- 仓库元数据（描述、语言、主题）',
    '- 项目的科研方向',
    '- 可选的报错日志',
    '',
    '请完成：',
    '1. repoGoal: 判断该仓库的目的和要复现的内容',
    '2. readmeSummary: 分析 README 中的关键信息（环境要求、数据准备、运行命令等，至少 3 条）',
    '3. environmentCommands: 从 README 中提取或推断可执行的环境配置命令序列。如果 README 没有明确安装命令，返回保守检查命令（如 python --version、pip --version、node --version、npm --version 等）',
    '4. debugSuggestions: 结合报错日志给出调试建议（至少 2 条），如无日志则给出常见问题预防建议',
    '5. nextSteps: 给出逻辑有序的排查步骤建议（至少 2 条）',
    '',
    '安全约束：',
    '- 不要生成删除系统文件、修改系统权限、执行未知远程脚本的危险命令',
    '- 对 sudo、rm -rf、curl | bash 等高风险命令必须提示谨慎确认',
    '- 环境命令应优先使用可解释、可检查、可回滚的命令',
    '',
    '如果 README 信息不足，基于仓库名称和科研方向合理推断。',
    '必须只返回符合指定 schema 的 JSON。',
    '不要返回 Markdown，不要返回代码块，不要返回额外解释。',
  ].join('\n')
}

function buildUserPrompt(input: GenerateReproductionInput, readmeContent: string, description: string, language: string, topics: string) {
  const truncated = readmeContent.slice(0, 8000)
  const truncateNote = readmeContent.length > 8000 ? '\n（README 内容已截断，完整内容请访问仓库链接）' : ''

  return [
    `研究方向：${input.topic}`,
    '',
    `GitHub 仓库：${input.githubUrl}`,
    `仓库描述：${description || '未获取到'}`,
    `主要语言：${language || '未获取到'}`,
    `主题标签：${topics || '未获取到'}`,
    '',
    `README 内容（前 8000 字符）：`,
    truncated,
    truncateNote,
    '',
    `报错日志：`,
    input.errorLog || '未提供',
    '',
    '请生成完整的代码复现指南。',
  ].join('\n')
}

export async function generateReproductionGuide(
  input: GenerateReproductionInput,
): Promise<ReproductionGuide> {
  let description = ''
  let language = ''
  let topics = ''
  let readmeContent = ''

  try {
    const repoInfo = await fetchRepoInfo(input.githubUrl)
    if (repoInfo) {
      description = repoInfo.description
      language = repoInfo.language
      topics = repoInfo.topics.join(', ')
      readmeContent = repoInfo.readmeContent
    }
  } catch {
    // 静默降级，不影响后续 OpenAI 调用
  }

  try {
    const client = getOpenAIClient()
    const model = getOpenAIModel()

    const completion = await client.chat.completions.create({
      model,
      max_tokens: 4096,
      messages: [
        { role: 'system', content: buildSystemPrompt() },
        { role: 'user', content: buildUserPrompt(input, readmeContent, description, language, topics) },
      ],
      response_format: {
        type: 'json_schema',
        json_schema: reproductionJsonSchema,
      },
    })

    const content = completion.choices[0]?.message?.content

    if (!content) {
      throw new ApiError('invalid_response', '模型返回格式不符合 ReproductionGuide 协议', 502)
    }

    let parsed: unknown
    try {
      parsed = JSON.parse(content)
    } catch {
      throw new ApiError('invalid_response', '模型返回格式不符合 ReproductionGuide 协议', 502)
    }

    return validateReproductionGuide(parsed)
  } catch (error) {
    if (error instanceof ApiError) {
      throw error
    }

    console.error('[reproduction upstream error]', error)
    throw new ApiError('upstream_error', '模型调用失败', 502)
  }
}
