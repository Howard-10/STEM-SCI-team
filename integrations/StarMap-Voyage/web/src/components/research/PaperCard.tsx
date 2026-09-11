import type { Paper } from '../../types'
import SectionCard from '../common/SectionCard'

interface PaperCardProps {
  paper: Paper
  compact?: boolean
}

function PaperCard({ paper, compact = false }: PaperCardProps) {
  return (
    <SectionCard
      title={paper.title}
      description={`关键词：${paper.keywords.join(' / ')}${paper.isBaselineCandidate ? ' · 适合作为 baseline' : ''}`}
    >
      <div className={`grid gap-4 ${compact ? 'md:grid-cols-2' : 'xl:grid-cols-2'}`}>
        <div className="info-block">
          <h4>研究背景</h4>
          <p>{paper.background}</p>
        </div>
        <div className="info-block">
          <h4>Motivation</h4>
          <p>{paper.motivation}</p>
        </div>
        <div className="info-block">
          <h4>核心问题</h4>
          <p>{paper.coreProblem}</p>
        </div>
        <div className="info-block">
          <h4>方法框架</h4>
          <p>{paper.method}</p>
        </div>
        <div className="info-block">
          <h4>创新点</h4>
          <ul className="list-disc pl-5">
            {paper.innovation.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
        <div className="info-block">
          <h4>实验设计</h4>
          <p>{paper.experimentDesign}</p>
        </div>
        <div className="info-block">
          <h4>数据集</h4>
          <p>{paper.datasets.join(' / ')}</p>
        </div>
        <div className="info-block">
          <h4>评价指标</h4>
          <p>{paper.metrics.join(' / ')}</p>
        </div>
        <div className="info-block">
          <h4>优点</h4>
          <ul className="list-disc pl-5">
            {paper.strengths.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
        <div className="info-block">
          <h4>局限性</h4>
          <p>{paper.limitation}</p>
        </div>
        <div className="info-block xl:col-span-2">
          <h4>对当前项目的启发</h4>
          <p>{paper.inspiration}</p>
        </div>
      </div>
    </SectionCard>
  )
}

export default PaperCard
