import type {
  CompareRow,
  ExperimentInsight,
  OverviewReport,
  Paper,
  Project,
  ResearchGapAnalysis,
  ResearchIdea,
  ResearchStage,
  ReproductionGuide,
  WritingOutput,
} from '../types'

const now = () => new Date().toISOString()

export const stageOptions: ResearchStage[] = [
  '领域入门',
  '文献综述',
  '实验复现',
  '结果分析',
  '写作汇报',
]

const visionIdeas: ResearchIdea[] = [
  {
    id: 'idea-vision-1',
    title: '面向复杂灾害场景的跨尺度感知框架',
    description: '结合多尺度语义先验与拓扑约束，提升复杂遮挡环境下的鲁棒性。',
    noveltyScore: 8,
    feasibilityScore: 7,
    workloadScore: 6,
  },
  {
    id: 'idea-vision-2',
    title: '弱监督场景下的轻量化特征蒸馏',
    description: '通过教师模型引导轻量网络，减少标注压力并兼顾部署效率。',
    noveltyScore: 7,
    feasibilityScore: 8,
    workloadScore: 5,
  },
]

const nlpIdeas: ResearchIdea[] = [
  {
    id: 'idea-nlp-1',
    title: '领域知识驱动的检索增强阅读助手',
    description: '面向科研场景构建知识图谱约束的阅读与总结链路。',
    noveltyScore: 8,
    feasibilityScore: 8,
    workloadScore: 5,
  },
]

const seedPapers: Paper[] = [
  {
    id: 'paper-seed-1',
    title: 'Multi-Scale Disaster Scene Understanding with Structural Priors',
    abstract:
      'This paper studies disaster scene understanding under cluttered environments and proposes a multi-scale framework with structural priors.',
    keywords: ['disaster scene', 'multi-scale', 'structural prior'],
    background: '灾害场景图像存在遮挡、尺度变化大和类别不均衡问题。',
    motivation: '现有方法在复杂道路阻断与障碍识别中泛化较弱。',
    coreProblem: '如何在复杂场景中稳定识别可通行区域与关键障碍目标。',
    method: '基于多尺度特征融合和结构先验的双分支建模。',
    innovation: ['引入拓扑结构先验', '联合优化全局语义与局部细节'],
    experimentDesign: '在两类灾害数据集上与 6 个基线方法对比，并进行消融实验。',
    datasets: ['RescueNet', 'xBD'],
    metrics: ['mIoU', 'F1', 'Precision'],
    strengths: ['结构清晰', '可解释性较强', '适合作为 baseline'],
    limitation: '对长尾类别和极端光照场景仍较敏感。',
    inspiration: '可以借鉴其结构先验设计到路径规划和障碍理解的联合模型中。',
    contribution: '提出结构先验驱动的多尺度灾害场景理解框架。',
    isBaselineCandidate: true,
    createdAt: now(),
  },
  {
    id: 'paper-seed-2',
    title: 'Retrieval-Augmented Scientific Reading Assistant',
    abstract:
      'The work organizes literature evidence with retrieval pipelines to improve scientific reading and note-taking.',
    keywords: ['retrieval augmented generation', 'scientific reading', 'knowledge organization'],
    background: '科研初学者在跨主题阅读时容易丢失术语和证据链。',
    motivation: '需要一种结构化方式帮助用户完成文献吸收与比较。',
    coreProblem: '如何让阅读辅助系统给出更稳定、更可追踪的知识总结。',
    method: '结合主题检索、段落证据聚合与结构化模板输出。',
    innovation: ['强调证据链组织', '输出结构固定便于比较'],
    experimentDesign: '通过用户研究和阅读任务完成时间评估系统效能。',
    datasets: ['SciDocs', '自建阅读任务集'],
    metrics: ['ROUGE', 'Task Success Rate'],
    strengths: ['适合产品原型', '模板结构稳定'],
    limitation: '不直接解决深层方法推理问题。',
    inspiration: '可直接借鉴其结构化阅读模板到 ResearchPilot 的文献精读模块。',
    contribution: '构建科研阅读的检索增强范式。',
    isBaselineCandidate: false,
    createdAt: now(),
  },
]

export const mockProjects: Project[] = [
  {
    id: 'project-vision',
    title: '灾害场景路径规划辅助研究',
    researchTopic: '计算机视觉与灾害场景理解',
    description:
      '围绕灾害环境中的可通行区域识别、障碍物理解与路径规划辅助展开前期研究，目标是探索科研想法并建立复现基线。',
    stage: '文献综述',
    papers: [seedPapers[0]],
    ideas: visionIdeas,
    experiments: [],
    writings: [],
    overviewReport: undefined,
    createdAt: now(),
    updatedAt: now(),
  },
  {
    id: 'project-nlp',
    title: '科研阅读与写作助手设计',
    researchTopic: '自然语言处理与科研工作流',
    description:
      '聚焦文献整理、研究空白识别和结构化写作输出，先完成产品化前端工作台演示。',
    stage: '领域入门',
    papers: [seedPapers[1]],
    ideas: nlpIdeas,
    experiments: [],
    writings: [],
    overviewReport: undefined,
    createdAt: now(),
    updatedAt: now(),
  },
]

const hasVisionKeyword = (text: string) =>
  /(vision|image|scene|segmentation|灾害|图像|视觉|路径)/i.test(text)

const hasNlpKeyword = (text: string) =>
  /(nlp|language|llm|rag|写作|文献|阅读|科研助手)/i.test(text)

export function generateOverviewReport(topic: string, request: string): OverviewReport {
  const merged = `${topic} ${request}`.trim()

  if (hasVisionKeyword(merged)) {
    return {
      topic,
      request,
      background:
        '该方向聚焦复杂场景中的语义理解、目标识别与决策支持，常见于灾害响应、遥感监测和自动驾驶等高风险应用。',
      coreConcepts: ['场景理解', '语义分割', '结构先验', '跨尺度特征融合'],
      keyTasks: ['可通行区域识别', '障碍物检测', '风险区域评估', '路径辅助决策'],
      mainstreamMethods: ['CNN/Transformer 编码器', '多尺度特征金字塔', '检测与分割联合建模'],
      commonDatasets: ['RescueNet', 'xBD', 'LoveDA', 'Cityscapes'],
      commonMetrics: ['mIoU', 'F1 Score', 'Precision', 'Recall'],
      challenges: ['复杂遮挡', '类别不平衡', '跨域泛化弱', '真实部署成本高'],
      entryPoints: ['结构约束与先验融合', '弱监督标注节省', '多模态辅助决策'],
      readingPath: [
        '先读综述或 benchmark 文章理解任务定义',
        '再读 2 到 3 篇 baseline 论文梳理方法脉络',
        '最后集中看最近 2 年关注鲁棒性和部署性的工作',
      ],
      savedAt: now(),
    }
  }

  if (hasNlpKeyword(merged)) {
    return {
      topic,
      request,
      background:
        '该方向面向科研过程中的知识获取、结构化阅读和内容生成，重点是让系统提供稳定、可追踪的辅助链路。',
      coreConcepts: ['检索增强生成', '结构化摘要', '知识组织', '工作流编排'],
      keyTasks: ['文献筛选', '精读总结', '多文献对比', '写作草稿生成'],
      mainstreamMethods: ['RAG 框架', '模板化输出', '知识图谱辅助', '工作流 Agent'],
      commonDatasets: ['SciDocs', 'S2ORC', 'PubMed', 'ArXiv 摘要集'],
      commonMetrics: ['ROUGE', 'Faithfulness', 'Task Completion', 'User Satisfaction'],
      challenges: ['幻觉问题', '长文证据对齐', '领域术语漂移', '过程可追踪性不足'],
      entryPoints: ['基于证据链的输出模板', '面向科研流程的多模块协作', '项目级记忆管理'],
      readingPath: [
        '先了解学术搜索和阅读辅助综述',
        '再阅读 RAG 与长文处理相关工作',
        '最后观察科研助手产品如何落地结构化交互',
      ],
      savedAt: now(),
    }
  }

  return {
    topic,
    request,
    background:
      '这是一个适合进行科研工作流拆解和方法调研的方向，建议先从任务定义、数据资源和评价方式三部分建立结构化理解。',
    coreConcepts: ['任务定义', '方法范式', '评价标准', '研究问题'],
    keyTasks: ['快速领域入门', '文献筛选', '方法归类', '研究问题收敛'],
    mainstreamMethods: ['经典基线梳理', '近期代表方法对比', '实验设计复盘'],
    commonDatasets: ['公开 benchmark', '领域内常用数据集', '自建实验集'],
    commonMetrics: ['准确率类指标', '鲁棒性指标', '效率指标'],
    challenges: ['术语分散', '方法脉络复杂', '研究问题边界不清'],
    entryPoints: ['做综述表格', '看 benchmark', '建立问题树'],
    readingPath: ['先读综述', '再看高被引 baseline', '最后跟踪最新会议工作'],
    savedAt: now(),
  }
}

export function generatePaperAnalysis(input: {
  title: string
  abstract: string
  keywords: string[]
}): Paper {
  const basis = `${input.title} ${input.abstract} ${input.keywords.join(' ')}`
  const isVision = hasVisionKeyword(basis)

  return {
    id: `paper-${Date.now()}`,
    title: input.title,
    abstract: input.abstract,
    keywords: input.keywords,
    background: isVision
      ? '该论文针对复杂视觉场景中的语义理解和鲁棒识别问题展开。'
      : '该论文面向科研辅助或结构化知识组织任务，强调稳定输出与证据利用。',
    motivation: isVision
      ? '作者试图解决传统单尺度表征在复杂场景中信息缺失的问题。'
      : '作者希望让系统在长文本科研任务中提供更可追踪的中间结果。',
    coreProblem: isVision
      ? '如何在复杂背景与尺度变化下提升关键目标识别效果。'
      : '如何将文献内容转化为结构化、可比较、可复用的知识单元。',
    method: isVision
      ? '采用多尺度特征编码与任务特定先验约束的联合框架。'
      : '采用检索、摘要和模板填充相结合的结构化生成流程。',
    innovation: isVision
      ? ['引入结构先验增强局部细节建模', '兼顾全局语义与局部鲁棒性']
      : ['强调证据组织而非自由生成', '输出结构固定，便于科研流程下游复用'],
    experimentDesign: isVision
      ? '与主流分割或检测 baseline 进行对比，并通过消融分析验证各模块贡献。'
      : '通过阅读任务完成率和用户主观反馈评估系统在科研场景中的帮助程度。',
    datasets: isVision ? ['RescueNet', 'xBD'] : ['SciDocs', '自建阅读任务集'],
    metrics: isVision ? ['mIoU', 'F1', 'Recall'] : ['ROUGE', 'Task Success Rate', 'User Satisfaction'],
    strengths: isVision
      ? ['适合做视觉 baseline', '方法结构清晰', '可迁移到相关任务']
      : ['结构化输出稳定', '适合产品化展示', '方便跨论文比较'],
    limitation: isVision
      ? '对数据分布变化和极端场景的泛化能力仍需要补强。'
      : '若检索环节不稳定，后续生成质量会明显下降。',
    inspiration: isVision
      ? '可将结构先验与当前项目的通行区域分析结合，并设计专门的消融实验。'
      : '可借鉴其固定模板，将文献精读结果沉淀为项目级知识卡片。',
    contribution: isVision
      ? '提出一种鲁棒的复杂视觉场景建模范式。'
      : '提出一种适配科研工作流的结构化阅读与组织方式。',
    isBaselineCandidate: isVision,
    createdAt: now(),
  }
}

export function generateCompareRows(papers: Paper[]): CompareRow[] {
  return papers.map((paper) => ({
    title: paper.title,
    motivation: paper.motivation,
    method: paper.method,
    innovation: paper.innovation.join('；'),
    datasets: paper.datasets.join(' / '),
    metrics: paper.metrics.join(' / '),
    strengths: paper.strengths.join('；'),
    limitation: paper.limitation,
    inspiration: paper.inspiration,
  }))
}

function uniqueStrings(items: string[]) {
  return Array.from(new Set(items.filter(Boolean)))
}

function summarizePhrase(text: string) {
  const normalized = text.replace(/\s+/g, ' ').trim()
  if (normalized.length <= 34) return normalized
  return `${normalized.slice(0, 34)}...`
}

function buildSyntheticIdeas(topic: string, papers: Paper[]): ResearchIdea[] {
  const base = hasVisionKeyword(topic) ? visionIdeas : nlpIdeas
  const limitationHint = papers[0]?.limitation ?? '现有方法在真实科研使用中稳定性不足'
  const inspirationHint = papers[0]?.inspiration ?? '将多模块结果沉淀为项目级知识资产'

  const generated: ResearchIdea[] = [
    ...base,
    {
      id: `idea-synth-${papers.length || 0}`,
      title: hasVisionKeyword(topic)
        ? '基于对比证据的鲁棒性增强研究'
        : '面向科研流程的证据可追踪工作台',
      description: `结合所选论文暴露的限制“${summarizePhrase(
        limitationHint,
      )}”与启发“${summarizePhrase(inspirationHint)}”，设计更适合当前项目推进的新方案。`,
      noveltyScore: 8,
      feasibilityScore: 7,
      workloadScore: 6,
    },
  ]

  return generated.slice(0, 3)
}

export function generateResearchGapAnalysis(topic: string, papers: Paper[] = []): ResearchGapAnalysis {
  const isVision = hasVisionKeyword(topic)
  const limitations = uniqueStrings(papers.map((paper) => summarizePhrase(paper.limitation)))
  const inspirations = uniqueStrings(papers.map((paper) => summarizePhrase(paper.inspiration)))
  const datasets = uniqueStrings(papers.flatMap((paper) => paper.datasets))
  const methods = uniqueStrings(papers.map((paper) => summarizePhrase(paper.method)))
  const motivations = uniqueStrings(papers.map((paper) => summarizePhrase(paper.motivation)))

  const commonProblems =
    limitations.length > 0
      ? limitations.slice(0, 3).map((item) => `多篇论文都暴露出“${item}”这一共性问题。`)
      : isVision
        ? ['方法普遍依赖高质量标注', '复杂遮挡与长尾目标处理不足']
        : ['系统多关注摘要质量，缺少跨步骤协同', '过程可追踪性不够']

  const unresolvedIssues =
    motivations.length > 0
      ? motivations.slice(0, 3).map((item) => `虽然论文都关注“${item}”，但对应问题仍未被完全解决。`)
      : isVision
        ? ['部署时对硬件资源敏感', '跨场景泛化性能不稳定']
        : ['证据引用与最终输出之间链路不透明', '用户长期项目记忆不足']

  const datasetGaps =
    datasets.length > 0
      ? [
          `当前选中论文主要围绕 ${datasets.join(' / ')} 展开，跨场景验证范围仍偏窄。`,
          datasets.length < 3
            ? '数据集覆盖面较有限，建议补充不同场景或不同标注粒度的数据。'
            : '已有多个数据集，但仍需关注真实应用场景与 benchmark 间的差距。',
        ]
      : isVision
        ? ['真实灾害场景数据稀缺', '极端天气和夜间样本不足']
        : ['科研辅助场景的公开评测集不足', '跨学科任务覆盖不均']

  const methodGaps =
    methods.length > 0
      ? [
          `所选论文的方法路线集中在 ${methods.join(' / ')}，方法多样性仍有限。`,
          inspirations.length > 0
            ? `现有启发更多停留在“${inspirations[0]}”层面，缺少系统化整合方案。`
            : '已有方法能解决局部问题，但缺少统一的工作流整合视角。',
        ]
      : isVision
        ? ['结构先验与大模型知识没有形成统一框架']
        : ['模块之间缺少统一状态管理与可审阅中间件']

  const transformableQuestions =
    inspirations.length > 0
      ? inspirations.slice(0, 3).map((item) => `如何把“${item}”转化为可验证的研究问题？`)
      : isVision
        ? ['如何在少标注场景下提升通行区域识别稳定性？', '如何联合感知结果和规划反馈优化模型？']
        : ['如何让科研助手输出具备更强的证据可追踪性？', '如何从单次问答升级为项目级工作流系统？']

  return {
    commonProblems,
    unresolvedIssues,
    datasetGaps,
    methodGaps,
    transformableQuestions,
    ideas: buildSyntheticIdeas(topic, papers),
  }
}

export function generateExperimentInsight(name: string, raw: string): ExperimentInsight {
  return {
    trend: `实验 ${name} 显示，随着关键模块逐步加入，整体表现呈稳步上升趋势。`,
    bestMethod: '当前最佳结果来自加入结构先验/知识组织模块后的增强版本。',
    metricChange: '核心指标相对基线提升约 2% 到 5%，但不同子任务的收益分布不均。',
    outlierNote: raw
      ? '日志中存在个别波动点，建议检查数据划分、随机种子和早停策略。'
      : '暂未提供详细日志，建议补充每轮实验配置和指标曲线。',
    possibleReasons: ['模型对少量边界样本更敏感', '训练轮数与学习率设置可能影响稳定性', '数据清洗策略尚不统一'],
    extraExperiments: ['增加消融实验验证模块贡献', '补充跨数据集泛化实验', '统计推理耗时与参数量'],
    paperConclusion:
      '实验结果表明，所提出的增强模块能够稳定提升主指标，并在复杂场景下展现更好的鲁棒性。',
    chartSuggestion: {
      chartType: '分组柱状图 + 折线趋势图',
      xAxis: '方法版本 / 实验配置',
      yAxis: '核心评价指标',
      title: '不同方法在核心指标上的性能对比',
      highlight: '突出 baseline 与增强方法之间的差距，并标注最优结果',
      matplotlibSnippet: `import matplotlib.pyplot as plt

methods = ["Baseline", "Ours-A", "Ours-B"]
scores = [72.4, 75.1, 76.3]

plt.figure(figsize=(8, 4))
plt.bar(methods, scores, color=["#94a3b8", "#60a5fa", "#1d4ed8"])
plt.ylabel("Score")
plt.title("Performance Comparison")
for idx, score in enumerate(scores):
    plt.text(idx, score + 0.2, f"{score:.1f}", ha="center")
plt.tight_layout()
plt.show()`,
    },
  }
}

export function generateWritingOutput(type: string, requirement: string, topic: string): WritingOutput {
  return {
    paragraph: `围绕“${topic}”这一研究主题，本文关注当前方法在复杂任务链路中的结构化不足，并提出以流程化科研辅助为核心的工作台设计。${
      requirement ? ` 在写作时特别强调：${requirement}。` : ''
    }首版系统通过项目级状态管理、模板化分析和可追踪的 mock 输出，为后续真实模型接入提供稳定前端骨架。`,
    pptOutline: [
      '研究背景与问题定义',
      '现有方法痛点与研究空白',
      'ResearchPilot 系统设计',
      '核心模块演示与案例',
      '下一步实验与产品迭代计划',
    ],
    speakerNotes: [
      `${type} 部分建议先讲清研究场景和用户痛点，避免直接进入实现细节。`,
      '说明系统不是通用聊天机器人，而是强调流程化、结构化与项目记忆。',
      '最后用一页总结当前 MVP 价值与后续可扩展能力。',
    ],
  }
}

export function generateReproductionGuide(topic: string, githubUrl: string, errorLog: string): ReproductionGuide {
  return {
    repoGoal: githubUrl
      ? `该仓库大概率用于复现与“${topic}”相关的 baseline 或实验流程，建议先识别任务类型、依赖环境和数据准备方式。`
      : `当前未提供 GitHub 链接，建议先明确与“${topic}”最相关的 baseline 仓库，再进入环境配置和 debug。`,
    readmeSummary: [
      '优先确认 README 中的任务定义、环境要求和数据准备步骤。',
      '标记是否存在指定 Python 版本、CUDA 版本或第三方编译依赖。',
      '如果 README 示例命令较旧，应检查 issue 区域或近期 commit 的变动说明。',
    ],
    environmentCommands: [
      'conda create -n researchpilot python=3.10',
      'conda activate researchpilot',
      'pip install -r requirements.txt',
      'python train.py --config configs/baseline.yaml',
    ],
    debugSuggestions: errorLog
      ? [
          '先根据报错关键字判断是依赖缺失、路径错误还是设备环境不匹配。',
          '如果出现 CUDA/torch 版本冲突，优先锁定 Python 与 PyTorch 版本组合。',
          '如果是文件不存在，检查数据集路径、工作目录和配置文件中的相对路径。',
        ]
      : [
          '尚未提供报错日志，建议先运行最小命令并记录完整 stack trace。',
          '优先验证环境、数据路径和预训练权重是否齐全。',
          '用最小 batch size 或 demo 配置先打通推理流程。',
        ],
    nextSteps: [
      '把 README 命令拆成环境、数据、训练、评估四段逐步验证。',
      '每解决一类错误都沉淀为项目复现记录，便于后续复用。',
      '成功运行 baseline 后再开始参数改动或模块替换实验。',
    ],
  }
}
