// 集中管理各后端服务的地址，避免组件内散落的硬编码 IP/端口。
// 所有地址均可用 Vite 环境变量覆盖（见 .env.example）。

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, '')
}

// 教学设计 / 文献阅读 AI 后端（原「星图学航2.0」FastAPI 服务）
// 承载：/api/projects、/api/generate-plan、/api/literature/*、/api/experiment/*、/api/bridge/*、/api/progress/* 等
export const TEACHING_API_BASE = trimTrailingSlash(
  import.meta.env.VITE_TEACHING_API_URL || 'http://127.0.0.1:8002',
)

// 科研实验平台（原「Research-Copilot-OS」Streamlit 前端）
export const RESEARCH_STREAMLIT_URL = trimTrailingSlash(
  import.meta.env.VITE_RESEARCH_STREAMLIT_URL || 'http://127.0.0.1:8501',
)

// 课程案例模块（原「星图学航」自适应 STEM 学习路径服务）
export const COURSE_CASES_URL = trimTrailingSlash(
  import.meta.env.VITE_COURSE_CASE_URL || 'http://127.0.0.1:8800/app/',
)

// 文献阅读 AI 的 HTTP provider 基础地址（复用教学后端；mock 模式下不使用）
export const AI_API_BASE = trimTrailingSlash(import.meta.env.VITE_API_BASE_URL || '')
