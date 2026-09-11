请生成一张系统架构图，算法论文配图风格。深色背景，无衬线字体，全英文标注，扁平矢量风格。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
标题（顶部居中，白色粗体）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ResearchPilot Agent Architecture
Multi-Agent Collaboration · ReAct Tool Use · Reflexive Refinement

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
整体布局：从上到下四层，层间用细线箭头连接
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【Layer 0 — 顶部入口层】

一行文字标注（灰色小字）：User Input → Project Context (localStorage)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【Layer 1 — Agent Orchestration Layer】

标题标签：Agent Orchestrator (orchestrator.ts)

中间一个大圆角矩形，内部结构：

┌──────────────────────────────────────────────────────────────┐
│                    Agent Orchestrator                        │
│                                                              │
│  ┌──────────────────────┐    ┌────────────────────────────┐  │
│  │   Task Decomposer    │    │    Context Manager          │  │
│  │                      │    │                             │  │
│  │  Input: user request │    │  Shared Blackboard          │  │
│  │  Output: subtask DAG │    │  Project Papers             │  │
│  │  Assign: specialist  │    │  Experiment Logs            │  │
│  │          agents      │    │  Previous Agent Messages    │  │
│  └──────────┬───────────┘    └──────────────┬─────────────┘  │
│             │                               │                │
│             └───────────┬───────────────────┘                │
│                         │                                    │
│              ┌──────────┴──────────┐                         │
│              │  Message Router     │                         │
│              │  agent → agent      │                         │
│              │  structured JSON    │                         │
│              │  typed envelopes    │                         │
│              └──────────┬──────────┘                         │
└─────────────────────────┼────────────────────────────────────┘
                          │
         三条向下的箭头，分别指向 Layer 2 的三个协议块

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【Layer 2 — Agent Protocols】

标题标签：Agent Collaboration Protocols

三个并列的大圆角矩形，从左到右排列：

┌─ Protocol A (左) ──────┐  ┌─ Protocol B (中) ──────┐  ┌─ Protocol C (右) ──────┐
│                         │  │                         │  │                         │
│  Multi-Agent Debate     │  │  ReAct Tool-Use Loop    │  │  Reflexive Refinement   │
│  (debate.ts)            │  │  (reactAgent.ts)        │  │  (reflexive.ts)         │
│                         │  │                         │  │                         │
│  ┌───────┐ ┌───────┐   │  │  ┌───────────────────┐  │  │  ┌───────┐              │
│  │Method │ │Dataset│   │  │  │ Thought            │  │  │  │Draft  │              │
│  │Analyst│ │Analyst│   │  │  │ "I need to find    │  │  │  │Agent  │              │
│  └───┬───┘ └───┬───┘   │  │  │  related work..."  │  │  │  └───┬───┘              │
│      │         │       │  │  └─────────┬─────────┘  │  │      │                  │
│      │  ┌──────┴──────┐│  │            │            │  │      ▼                  │
│      │  │Theory       ││  │  ┌─────────┴─────────┐  │  │  ┌───────┐              │
│      │  │Analyst      ││  │  │ Action             │  │  │  │Critic │              │
│      │  └──────┬──────┘│  │  │ search_arxiv(      │  │  │  │Agent  │              │
│      │         │       │  │  │   "RAG scientific  │  │  │  └───┬───┘              │
│      └────┬────┴───────┘│  │  │    literature")    │  │  │      │                  │
│           │             │  │  └─────────┬─────────┘  │  │      ▼                  │
│           ▼             │  │            │            │  │  ┌───────┐              │
│  ┌─────────────────┐    │  │  ┌─────────┴─────────┐  │  │  │Revise │     ≤3轮     │
│  │  Critic Agent   │    │  │  │ Observation        │  │  │  │Agent  │              │
│  │  finds conflicts│    │  │  │ { papers: [...],   │  │  │  └───┬───┘              │
│  │  & blind spots  │    │  │  │   citations: [...]}│  │  │      │                  │
│  └────────┬────────┘    │  │  └─────────┬─────────┘  │  │      ▼                  │
│           │             │  │            │            │  │  ┌───────┐              │
│           ▼             │  │            ▼            │  │  │Final  │              │
│  ┌─────────────────┐    │  │    (loop until goal    │  │  │Output │              │
│  │  Synthesizer    │    │  │     or max 5 steps)    │  │  └───────┘              │
│  │  merges & scores│    │  │                         │  │                         │
│  └─────────────────┘    │  │  Module: Overview,      │  │  Module: Writing,       │
│                         │  │  Reproduction            │  │  Idea Generation        │
│  Module: Compare        │  │                         │  │                         │
│  (Research Gap)         │  │                         │  │                         │
└─────────────────────────┘  └─────────────────────────┘  └─────────────────────────┘

三个协议块下方各有一条向下箭头，汇聚到 Layer 3。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【Layer 3 — Specialist Agent Pool】

标题标签：Specialist Agent Pool (specialists.ts)

纵向排列 6 个 Agent 卡片，每个卡片大小一致、等距排列：

┌──────────────────────────────┐
│  LiteratureAgent              │
│  role: "literature_reviewer" │
│  prompt: paper deep-reading  │
│  tools: [get_paper_detail]   │
│  output: Paper struct        │
└──────────────────────────────┘

┌──────────────────────────────┐
│  MethodAgent                  │
│  role: "methodology_analyst" │
│  prompt: method comparison   │
│  tools: [compare_methods]    │
│  output: MethodAnalysis      │
└──────────────────────────────┘

┌──────────────────────────────┐
│  ExperimentAgent              │
│  role: "experiment_designer" │
│  prompt: result analysis     │
│  tools: [read_exp_logs]      │
│  output: ExperimentInsight   │
└──────────────────────────────┘

┌──────────────────────────────┐
│  CriticAgent                  │
│  role: "adversarial_reviewer"│
│  prompt: find flaws & gaps   │
│  tools: [cross_check]        │
│  output: CritiqueReport      │
└──────────────────────────────┘

┌──────────────────────────────┐
│  WritingAgent                 │
│  role: "academic_writer"     │
│  prompt: structured drafting │
│  tools: [format_output]      │
│  output: WritingDraft        │
└──────────────────────────────┘

┌──────────────────────────────┐
│  SynthesisAgent               │
│  role: "research_synthesizer"│
│  prompt: merge & reconcile   │
│  tools: [score_ideas]        │
│  output: FinalReport         │
└──────────────────────────────┘

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【Layer 4 — 底部基础设施层】

标题标签：Infrastructure

三个横向小方块并排：

┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  Tool Registry    │  │  OpenAI SDK v6   │  │  Output Guard     │
│  (tools.ts)       │  │  GPT-4o-mini      │  │                   │
│                   │  │                   │  │  JSON Schema      │
│  search_arxiv     │  │  Structured       │  │  (strict)         │
│  fetch_github_    │  │  Output           │  │       ↓           │
│    readme         │  │  (json_schema)    │  │  Backend validate │
│  read_project_    │  │                   │  │       ↓           │
│    papers         │  │                   │  │  Frontend assert  │
│  compare_         │  │                   │  │                   │
│    experiments    │  │                   │  │  Triple-layer      │
│                   │  │                   │  │  integrity chain   │
└──────────────────┘  └──────────────────┘  └──────────────────┘

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
配色规范（精确色号）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

画布背景：       #0B1120
Layer 背景条：   #0F172A（极淡区分）
标题文字：       白色 #F8FAFC，16pt bold
副标题：         #94A3B8，10pt
层标签：         #64748B，10pt，大写字母间距 0.15em
普通节点填充：   #1E293B，边框 1px #334155，圆角 6px
关键节点填充：   #172554，边框 1px #3B82F6，圆角 8px
Agent 卡片填充： #1E3A5F，边框 1px #2563EB，圆角 8px
Agent 名称：     白色 #F8FAFC，11pt bold
Agent 字段：     #94A3B8，9pt
箭头主线：       1px #3B82F6
箭头辅线：       0.75px #475569
数据流向箭头：   1.5px #60A5FA
高亮标注色：     #3B82F6
协议块标题：     白色，11pt bold

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
布局约束
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- 四层从上到下依次排列，层间距相等
- Layer 2 三个协议块水平等距排列，宽度占比 1:1:1
- Layer 3 六个 Agent 卡片排列：上方一排 3 个（LiteratureAgent, MethodAgent, ExperimentAgent），下方一排 3 个（CriticAgent, WritingAgent, SynthesisAgent），等距排列
- Layer 4 三个基础设施块水平等距
- 箭头：Layer1 → Layer2（3条向下箭头），Layer2 → Layer3（汇聚后1条），Layer3 → Layer4（1条向下箭头）
- 整体比例适合 16:9 宽屏 PPT 全页展示
- 所有文字必须可读，最小字号不低于 8pt
- 无图标、无 emoji、无渐变、无阴影
