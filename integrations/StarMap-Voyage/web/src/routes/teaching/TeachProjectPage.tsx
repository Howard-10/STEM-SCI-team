import { useState } from 'react'
import Layout from '../../components/layout/Layout'
import Button from '../../components/common/Button'
import { API_BASE } from './TeachHomePage'

function renderMarkdown(md: string): string {
  let html = md.replace(/^```markdown\s*\n?/i,'').replace(/```\s*$/,'')
  html = html.replace(/```(\w*)\s*\n([\s\S]*?)```/g, (_,_lang,code) => `<pre class="bg-slate-950 text-slate-200 rounded-xl p-4 overflow-x-auto text-sm"><code>${code.trim().replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}</code></pre>`)
  html = html.replace(/^#### (.+)$/gm,'<h4 class="text-base font-semibold text-slate-800 mt-4 mb-2">$1</h4>')
  html = html.replace(/^### (.+)$/gm,'<h3 class="text-lg font-semibold text-slate-800 mt-5 mb-2">$1</h3>')
  html = html.replace(/^## (.+)$/gm,'<h2 class="text-xl font-semibold text-sky-700 mt-6 mb-3 border-b border-sky-100 pb-2">$1</h2>')
  html = html.replace(/^# (.+)$/gm,'<h1 class="text-2xl font-bold text-indigo-700 mt-8 mb-4 pl-4 border-l-4 border-indigo-500 bg-indigo-50 py-2 rounded-r-xl">$1</h1>')
  html = html.replace(/\*\*(.+?)\*\*/g,'<strong class="font-semibold text-slate-900">$1</strong>')
  html = html.replace(/`([^`]+)`/g,'<code class="bg-slate-100 text-indigo-700 px-1.5 py-0.5 rounded text-sm">$1</code>')
  html = html.replace(/^\|(.+)\|$/gm, line => {
    if (line.includes('---')) return ''
    const cells = line.split('|').filter(c=>c.trim())
    return '<tr>'+cells.map(c=>`<td class="border border-slate-200 px-3 py-2 text-sm">${c.trim()}</td>`).join('')+'</tr>'
  })
  html = html.replace(/(<tr>[\s\S]*?<\/tr>)+/g,'<table class="w-full border-collapse my-3">$&</table>')
  html = html.replace(/^[-*] (.+)$/gm,'<li class="text-sm text-slate-700 ml-4">$1</li>')
  html = html.replace(/(<li[\s\S]*?<\/li>)+/g,'<ul class="my-2">$&</ul>')
  html = html.replace(/^> (.+)$/gm,'<blockquote class="border-l-4 border-indigo-200 bg-indigo-50/50 pl-4 py-2 my-3 text-sm text-slate-600 rounded-r-xl">$1</blockquote>')
  html = html.replace(/^(?!<[a-z/])(.+)$/gm,'<p class="text-sm text-slate-700 leading-relaxed my-1.5">$1</p>')
  html = html.replace(/<p>\s*<\/p>/g,'')
  return html
}

type ResearchType = 'shuoke' | 'reflection' | 'analysis'

const RESEARCH_META: Record<ResearchType, { label: string; icon: string }> = {
  shuoke: { label: '说课稿', icon: '🎤' },
  reflection: { label: '教学反思', icon: '🔍' },
  analysis: { label: '教材/课标分析', icon: '📚' },
}

interface Props {
  planMarkdown: string
  onBack: () => void
}

function TeachProjectPage({ planMarkdown, onBack }: Props) {
  const [exporting, setExporting] = useState(false)
  const [researchType, setResearchType] = useState<ResearchType | null>(null)
  const [researchResult, setResearchResult] = useState('')
  const [researchLoading, setResearchLoading] = useState(false)

  function extractTitle(md: string): string {
    const h = md.match(/^#\s+(.+)$/m) || md.match(/\|\s*项目名称\s*\|\s*(.+?)\s*\|/m)
    return (h ? h[1].trim() : '教学设计').slice(0, 60)
  }

  function extractGrade(md: string): string {
    const m = md.match(/(小学[低中高]段|初中|高中)/)
    return m ? m[0] : '初中'
  }

  async function downloadDocx(markdown: string, title: string) {
    const resp = await fetch(`${API_BASE}/api/export-docx`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ markdown, title })
    })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${title}.docx`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  async function handleExportDocx() {
    if (exporting) return
    setExporting(true)
    try {
      await downloadDocx(planMarkdown, extractTitle(planMarkdown))
    } catch (e) {
      console.error(e)
      alert('导出失败，请确认教学后端已启动（8002）')
    } finally {
      setExporting(false)
    }
  }

  async function handleResearch(type: ResearchType) {
    if (researchLoading) return
    setResearchType(type)
    setResearchResult('')
    setResearchLoading(true)
    try {
      const resp = await fetch(`${API_BASE}/api/research/${type}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          plan_markdown: planMarkdown,
          title: extractTitle(planMarkdown),
          grade_level: extractGrade(planMarkdown)
        })
      })
      const data = await resp.json()
      if (data.success && data.result) setResearchResult(data.result)
      else setResearchResult('生成失败，请稍后重试。')
    } catch (e) {
      console.error(e)
      setResearchResult('无法连接教学后端（8002），请确认服务已启动。')
    } finally {
      setResearchLoading(false)
    }
  }

  const title = extractTitle(planMarkdown)

  return (
    <Layout
      header={
        <div className="flex items-center gap-4 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <Button variant="secondary" onClick={onBack}>← 返回</Button>
          <div className="flex-1 min-w-0">
            <h1 className="text-lg font-semibold text-slate-900 truncate">{title}</h1>
            <p className="text-xs text-slate-400">教案设计</p>
          </div>
          <Button variant="secondary" onClick={handleExportDocx} disabled={exporting}>
            {exporting ? '导出中…' : '导出 DOCX'}
          </Button>
        </div>
      }
    >
      {/* 助研工具 */}
      <div className="rounded-2xl border border-indigo-100 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-indigo-950">📚 助研工具</h2>
            <p className="text-xs text-indigo-400 mt-0.5">基于当前教案，一键生成教研材料</p>
          </div>
          <div className="flex gap-2 flex-wrap">
            {(Object.keys(RESEARCH_META) as ResearchType[]).map(type => (
              <Button
                key={type}
                variant={researchType === type ? 'primary' : 'secondary'}
                onClick={() => handleResearch(type)}
                disabled={researchLoading}
              >
                <span className="mr-1">{RESEARCH_META[type].icon}</span>
                {RESEARCH_META[type].label}
              </Button>
            ))}
          </div>
        </div>

        {researchLoading && (
          <div className="flex items-center gap-3 mt-4 rounded-xl bg-indigo-50/60 px-4 py-3">
            <div className="w-5 h-5 border-2 border-indigo-200 border-t-indigo-600 rounded-full animate-spin" />
            <p className="text-sm text-indigo-600">正在生成{RESEARCH_META[researchType!]?.label || '教研材料'}...</p>
          </div>
        )}

        {researchResult && !researchLoading && (
          <div className="mt-4 rounded-2xl border border-indigo-100 bg-indigo-50/40 p-5">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-semibold text-indigo-900">
                {RESEARCH_META[researchType!]?.label}生成结果
              </h3>
              <Button variant="ghost" onClick={() => downloadDocx(researchResult, `${title}-${RESEARCH_META[researchType!]?.label}`)}>
                导出 DOCX
              </Button>
            </div>
            <div className="prose prose-slate max-w-none" dangerouslySetInnerHTML={{ __html: renderMarkdown(researchResult) }} />
          </div>
        )}
      </div>

      {/* 教案正文 */}
      <div className="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
        <div className="prose prose-slate max-w-none" dangerouslySetInnerHTML={{ __html: renderMarkdown(planMarkdown) }} />
      </div>
    </Layout>
  )
}

export default TeachProjectPage
