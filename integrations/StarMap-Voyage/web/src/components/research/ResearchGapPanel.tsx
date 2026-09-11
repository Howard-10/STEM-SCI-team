import type { ResearchGapAnalysis } from '../../types'
import SectionCard from '../common/SectionCard'
import IdeaCard from './IdeaCard'

interface ResearchGapPanelProps {
  analysis: ResearchGapAnalysis
}

function ResearchGapPanel({ analysis }: ResearchGapPanelProps) {
  return (
    <SectionCard title="研究空白与 Idea 建议" description="基于已选论文的 limitation 和 inspiration，总结缺口并给出可推进的新 idea。">
      <div className="grid gap-4 xl:grid-cols-2">
        <div className="info-block">
          <h4>当前研究的共性问题</h4>
          <ul className="list-disc pl-5">
            {analysis.commonProblems.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
        <div className="info-block">
          <h4>现有方法未解决的问题</h4>
          <ul className="list-disc pl-5">
            {analysis.unresolvedIssues.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
        <div className="info-block">
          <h4>数据集或场景不足</h4>
          <ul className="list-disc pl-5">
            {analysis.datasetGaps.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
        <div className="info-block">
          <h4>方法设计不足</h4>
          <ul className="list-disc pl-5">
            {analysis.methodGaps.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
        <div className="info-block xl:col-span-2">
          <h4>可转化的研究问题</h4>
          <ul className="list-disc pl-5">
            {analysis.transformableQuestions.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      </div>

      <div className="mt-6 grid gap-4 xl:grid-cols-2">
        {analysis.ideas.map((idea) => (
          <IdeaCard key={idea.id} idea={idea} />
        ))}
      </div>
    </SectionCard>
  )
}

export default ResearchGapPanel
