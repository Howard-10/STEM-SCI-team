export interface GitHubRepoInfo {
  owner: string
  repo: string
  description: string
  language: string
  topics: string[]
  readmeContent: string
}

function parseGitHubUrl(rawUrl: string): { owner: string; repo: string } | null {
  if (!rawUrl || typeof rawUrl !== 'string') {
    return null
  }

  const trimmed = rawUrl.trim()
  if (!trimmed) {
    return null
  }

  const withProtocol = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`

  let url: URL
  try {
    url = new URL(withProtocol)
  } catch {
    return null
  }

  if (url.hostname !== 'github.com') {
    return null
  }

  const parts = url.pathname.split('/').filter(Boolean)
  if (parts.length < 2) {
    return null
  }

  const owner = parts[0]
  let repo = parts[1]

  // 去掉 .git 后缀
  if (repo.endsWith('.git')) {
    repo = repo.slice(0, -4)
  }

  return { owner, repo }
}

export { parseGitHubUrl }

function buildHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    Accept: 'application/vnd.github+json',
    'User-Agent': 'ResearchPilot/1.0',
  }

  const token = process.env.GITHUB_TOKEN?.trim()
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  return headers
}

async function fetchRepoMeta(
  owner: string,
  repo: string,
): Promise<{ description: string; language: string; topics: string[] }> {
  const response = await fetch(`https://api.github.com/repos/${owner}/${repo}`, {
    headers: buildHeaders(),
  })

  if (!response.ok) {
    throw new Error(`GitHub meta API returned ${response.status}`)
  }

  const data = (await response.json()) as Record<string, unknown>
  return {
    description: typeof data.description === 'string' ? data.description : '',
    language: typeof data.language === 'string' ? data.language : '',
    topics: Array.isArray(data.topics) ? data.topics.filter((t): t is string => typeof t === 'string') : [],
  }
}

async function fetchReadmeContent(owner: string, repo: string): Promise<string> {
  const response = await fetch(`https://api.github.com/repos/${owner}/${repo}/readme`, {
    headers: buildHeaders(),
  })

  if (!response.ok) {
    throw new Error(`GitHub readme API returned ${response.status}`)
  }

  const data = (await response.json()) as Record<string, unknown>
  if (typeof data.content !== 'string') {
    return ''
  }

  const normalized = data.content.replace(/\s/g, '')
  return Buffer.from(normalized, 'base64').toString('utf-8')
}

export async function fetchRepoInfo(rawUrl: string): Promise<GitHubRepoInfo | null> {
  const parsed = parseGitHubUrl(rawUrl)
  if (!parsed) {
    return null
  }

  const { owner, repo } = parsed

  const [metaResult, readmeResult] = await Promise.allSettled([
    fetchRepoMeta(owner, repo),
    fetchReadmeContent(owner, repo),
  ])

  let description = ''
  let language = ''
  let topics: string[] = []
  let readmeContent = ''

  if (metaResult.status === 'fulfilled') {
    description = metaResult.value.description
    language = metaResult.value.language
    topics = metaResult.value.topics
  } else if (metaResult.status === 'rejected') {
    // 检查是否限流
    const err = metaResult.reason as Error | undefined
    if (err?.message?.includes('403')) {
      return null
    }
  }

  if (readmeResult.status === 'fulfilled') {
    readmeContent = readmeResult.value
  } else if (readmeResult.status === 'rejected') {
    const err = readmeResult.reason as Error | undefined
    if (err?.message?.includes('403')) {
      return null
    }
  }

  return {
    owner: parsed.owner,
    repo: parsed.repo,
    description,
    language,
    topics,
    readmeContent,
  }
}
