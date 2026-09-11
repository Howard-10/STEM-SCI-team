import { useState, useEffect } from 'react'
import Button from '../../components/common/Button'
import { API_BASE } from './TeachHomePage'

interface QuizQuestion {
  id: string
  text: string
  concept?: string
  options?: Record<string, string>
}

interface Quiz {
  questions: QuizQuestion[]
}

interface QuizModalProps {
  query: string
  grade: string
  onStartPlan: (answers: Record<string,string>, quizQuestions: QuizQuestion[]) => void
  onSkip: () => void
}

function QuizModal({ query, grade, onStartPlan, onSkip }: QuizModalProps) {
  const [quiz, setQuiz] = useState<Quiz | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [started, setStarted] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    fetch(`${API_BASE}/api/generate-quiz?topic=${encodeURIComponent(query)}&grade_level=${encodeURIComponent(grade)}`, {
      method:'POST',
      signal: controller.signal,
    }).then(r => r.json()).then(d => {
      if (d.success && d.quiz) setQuiz(d.quiz)
      else setError('测评生成失败，可跳过直接生成教案。')
    }).catch(() => {
      setError('无法连接教学后端（8002），可跳过直接生成教案。')
    }).finally(() => setLoading(false))

    return () => controller.abort()
  }, [query, grade])

  const answers: Record<string,string> = {}

  function handleStart() { setStarted(true) }
  function handleSkip() { onSkip() }

  async function handleSubmit() {
    if (submitting) return
    setSubmitting(true)
    document.querySelectorAll<HTMLElement>('.quiz-opt.selected').forEach((el) => {
      if (el.dataset.qid && el.dataset.key) {
        answers[el.dataset.qid] = el.dataset.key
      }
    })
    onStartPlan(answers, quiz?.questions || [])
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm" onClick={handleSkip}>
      <div className="relative max-h-[85vh] w-full max-w-[560px] overflow-y-auto rounded-3xl border border-slate-200 bg-white p-8 shadow-2xl" onClick={e => e.stopPropagation()}>
        <h2 className="text-xl font-semibold text-slate-900 text-center">课前小测</h2>
        <p className="text-sm text-slate-500 text-center mt-1 mb-6">先来看看你对这个主题了解多少吧！</p>

        {loading ? (
          <div className="flex flex-col items-center py-10">
            <div className="w-10 h-10 border-4 border-indigo-200 border-t-indigo-600 rounded-full animate-spin mb-4" />
            <p className="text-sm text-slate-500">正在生成测评题...</p>
          </div>
        ) : error || !quiz ? (
          <div className="text-center">
            <p className="text-sm text-amber-700 mb-4">{error || '测评暂不可用'}</p>
            <Button variant="secondary" onClick={handleSkip}>跳过测评，直接生成教案</Button>
          </div>
        ) : !started ? (
          <div className="flex gap-3 justify-center">
            <Button onClick={handleStart}>开始测评</Button>
            <Button variant="secondary" onClick={handleSkip}>跳过</Button>
          </div>
        ) : (
          <>
            {(quiz.questions||[]).map((q, i: number) => (
              <div key={q.id} className="mb-5 pb-5 border-b border-slate-100 last:border-0">
                <p className="text-sm font-semibold text-slate-800 mb-1">{i+1}. {q.text}</p>
                <p className="text-xs text-slate-400 mb-3">考察: {q.concept}</p>
                <div className="grid gap-2">
                  {Object.entries(q.options||{}).map(([k, v]) => (
                    <button
                      key={k}
                      data-qid={q.id}
                      data-key={k}
                      className="quiz-opt text-left rounded-xl border border-slate-200 px-4 py-2.5 text-sm text-slate-700 hover:border-indigo-300 hover:bg-indigo-50 transition"
                      onClick={(e) => {
                        const btn = e.currentTarget
                        const parent = btn.parentElement
                        parent?.querySelectorAll('.quiz-opt').forEach(b => b.classList.remove('selected','!border-indigo-500','!bg-indigo-50'))
                        btn.classList.add('selected','!border-indigo-500','!bg-indigo-50')
                      }}
                    >
                      {k}. {v}
                    </button>
                  ))}
                </div>
              </div>
            ))}
            <div className="flex gap-3 justify-center mt-6">
              <Button onClick={handleSubmit} disabled={submitting}>{submitting ? '提交中...' : '提交测评'}</Button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default QuizModal
