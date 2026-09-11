import type { WritingOutput } from '../../types'
import Button from '../common/Button'
import SectionCard from '../common/SectionCard'

interface WritingOutputPanelProps {
  output: WritingOutput
}

function WritingOutputPanel({ output }: WritingOutputPanelProps) {
  const copyAll = async () => {
    const text = [
      output.paragraph,
      '',
      'PPT 大纲',
      ...output.pptOutline.map((item, index) => `${index + 1}. ${item}`),
      '',
      '讲解稿',
      ...output.speakerNotes.map((item, index) => `${index + 1}. ${item}`),
    ].join('\n')

    await navigator.clipboard.writeText(text)
  }

  return (
    <SectionCard
      title="写作输出"
      description="把研究内容整理为论文段落、PPT 页面结构和讲解稿。"
      action={
        <Button variant="secondary" onClick={copyAll}>
          复制内容
        </Button>
      }
    >
      <div className="space-y-5">
        <div className="info-block">
          <h4>论文段落</h4>
          <p>{output.paragraph}</p>
        </div>
        <div className="info-block">
          <h4>PPT 页面大纲</h4>
          <ol className="list-decimal pl-5">
            {output.pptOutline.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ol>
        </div>
        <div className="info-block">
          <h4>每页讲解稿</h4>
          <ol className="list-decimal pl-5">
            {output.speakerNotes.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ol>
        </div>
      </div>
    </SectionCard>
  )
}

export default WritingOutputPanel
