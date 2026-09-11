import type { CompareRow } from '../../types'
import SectionCard from '../common/SectionCard'

interface PaperCompareTableProps {
  rows: CompareRow[]
}

function PaperCompareTable({ rows }: PaperCompareTableProps) {
  return (
    <SectionCard title="论文对比表" description="围绕 motivation、方法框架、创新点和项目启发做结构化比较。">
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-slate-50 text-slate-500">
            <tr>
              {['论文名称', 'Motivation', '方法框架', '创新点', '数据集', '评价指标', '优点', '局限性', '对项目启发'].map((header) => (
                <th key={header} className="px-4 py-3 font-medium">
                  {header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.title} className="border-t border-slate-200 align-top">
                <td className="px-4 py-3 font-medium text-slate-900">{row.title}</td>
                <td className="px-4 py-3 text-slate-600">{row.motivation}</td>
                <td className="px-4 py-3 text-slate-600">{row.method}</td>
                <td className="px-4 py-3 text-slate-600">{row.innovation}</td>
                <td className="px-4 py-3 text-slate-600">{row.datasets}</td>
                <td className="px-4 py-3 text-slate-600">{row.metrics}</td>
                <td className="px-4 py-3 text-slate-600">{row.strengths}</td>
                <td className="px-4 py-3 text-slate-600">{row.limitation}</td>
                <td className="px-4 py-3 text-slate-600">{row.inspiration}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </SectionCard>
  )
}

export default PaperCompareTable
