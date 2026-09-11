请生成一张系统架构图，算法论文配图风格。深色背景，节点圆角矩形，细线箭头连接，字体统一使用无衬线。整体呈现从左到右的数据流向。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
标题（顶部居中）

ResearchPilot: AI-Augmented Research Workbench
A Dual-Provider Architecture with Structured Output Guarantees

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
图层结构（从左到右四列）

【Column A — Presentation】

标签行：Presentation Layer

纵向排列 6 个功能块（每个块内文字居中，块大小一致）：

┌──────────┐
│  Domain  │
│ Overview │
└──────────┘

┌──────────┐
│  Paper   │
│ Analysis │
└──────────┘

┌──────────┐
│  Cross   │
│ Compare  │
└──────────┘

┌──────────┐
│  Code    │
│ Repro.   │
└──────────┘

┌──────────┐
│  Result  │
│ Analysis │
└──────────┘

┌──────────┐
│  Writing │
│  Output  │
└──────────┘

这 6 个块统一向下汇聚到一个横条：
┌──────────────────────┐
│  useAsyncGeneration  │
│  (state machine hook)│
└──────────────────────┘

从该横条引出一条水平箭头指向 Column B。

──────────────────────────────

【Column B — AI Service Abstraction】

标签行：AI Service Layer (Provider Pattern)

中间放置一个圆角框：

┌────────────────────────────┐
│       aiService            │
│    createAIService(        │
│      provider: Provider    │
│    )                       │
│                            │
│  Runtime dispatch:         │
│  VITE_AI_PROVIDER          │
│    ├─ "mock" → mockProvider│
│    └─ "http" → httpProvider│
└────────────────────────────┘

从该框分叉出两条路径，上下排列：

上方路径（标注：Demo Mode · Zero Dependencies）：
mockProvider
  ├─ 规则引擎 (mockData.ts)
  ├─ 关键词匹配 → 模板填充
  ├─ 随机延迟 300-600ms
  └─ 输出：结构化 TypeScript 对象

下方路径（标注：Production Mode · Real LLM Inference）：
httpProvider
  ├─ fetchJson transport
  ├─ POST → Express Server (:3001)
  └─ response assertion (类型守卫)

上下两条路径最终汇合，引出一条水平箭头指向 Column C。

──────────────────────────────

【Column C — Backend Services】

标签行：Backend Service Layer

纵向排列两个核心模块，模块间有分隔：

上部模块（面积大）：
┌──────────────────────────────────┐
│     Express 5 + TypeScript        │
│                                   │
│  ┌─────────────────────────────┐ │
│  │      6 × REST Endpoints      │ │
│  │                              │ │
│  │  POST /api/ai/overview      │ │
│  │  POST /api/ai/papers/analyze│ │
│  │  POST /api/ai/compare       │ │
│  │  POST /api/ai/experiments/  │ │
│  │       analyze               │ │
│  │  POST /api/ai/writing/      │ │
│  │       generate              │ │
│  │  POST /api/ai/reproduction/ │ │
│  │       analyze               │ │
│  └──────────────┬──────────────┘ │
│                 │                 │
│  ┌──────────────┴──────────────┐ │
│  │    Service Layer (×6)        │ │
│  │    each with:                │ │
│  │    • custom system prompt    │ │
│  │    • JSON Schema definition  │ │
│  │    • validate() guard        │ │
│  └──────────────┬──────────────┘ │
│                 │                 │
│  ┌──────────────┴──────────────┐ │
│  │   OpenAI SDK v6              │ │
│  │   Model: GPT-4o-mini         │ │
│  │   response_format:           │ │
│  │     json_schema (strict)     │ │
│  └──────────────────────────────┘ │
└───────────────────────────────────┘

下部模块（面积小，与上面用虚线隔开）：
┌──────────────────────────────────┐
│   GitHub REST API Client         │
│   ├─ GET /repos/{owner}/{repo}  │
│   └─ GET /repos/{...}/readme    │
│   用途：提取 README + meta       │
│   作为 LLM 上下文输入             │
└──────────────────────────────────┘

──────────────────────────────

【Column D — Structured Guarantee Chain】

标签行：Output Integrity Pipeline

纵向排列三个阶段，用粗向下箭头串联：

┌──────────────────────────┐
│  Stage 1                 │
│  Schema-Constrained      │
│  Generation              │
│                          │
│  OpenAI Structured       │
│  Output API              │
│  strict: true            │
│  additionalProperties:   │
│    false                 │
└────────────┬─────────────┘
             ▼
┌──────────────────────────┐
│  Stage 2                 │
│  Server-Side Validation  │
│                          │
│  validateXxx(value)      │
│  • field existence check │
│  • type narrowing        │
│  • array element guard   │
│  • throw ApiError on     │
│    mismatch              │
└────────────┬─────────────┘
             ▼
┌──────────────────────────┐
│  Stage 3                 │
│  Client-Side Assertion   │
│                          │
│  assertXxx(value)        │
│  • final type guard      │
│  • AIServiceError on     │
│    failure               │
│  • friendly error UI     │
└──────────────────────────┘

三个 Stage 形成从宽到窄的倒三角漏斗形状，顶部最宽、底部最窄，视觉上制造"层层过滤"的效果。

底部标注一行文字：
Even if the LLM hallucinates, malformed output never reaches the render layer or corrupts local storage.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
连接箭头说明

- Column A → B：一条粗水平箭头，颜色亮蓝
- Column B 内部分叉：用虚线分两条路径，上路径标注色为蓝灰，下路径标注色为亮蓝
- B → C：一条粗水平箭头，颜色亮蓝
- C 内部：细线连接上下模块
- C → D：一条虚线水平箭头，标注 "Response flows through integrity pipeline before reaching UI"
- D 内部：三个 Stage 之间的箭头为粗竖线箭头，从上到下颜色逐渐加深

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
配色规范

- 画布背景：#0B1120（深藏青）
- 列标签字号：10pt，颜色 #64748B，大写字母间距
- 功能模块块：填充 #1E293B，边框 1px #334155，圆角 6px，文字白色 #F1F5F9
- 核心节点块（aiService、Express、OpenAI SDK）：填充 #1E3A5F，边框 1px #3B82F6，文字 #F8FAFC
- 安全保障链（Stage 1/2/3）：从 #1E3A5F 渐变到 #1E40AF 到 #1D4ED8，体现过滤加深
- 箭头：0.75px，亮色路径用 #3B82F6，虚线路径用 #475569
- 标注文字：9pt，颜色 #94A3B8
- 标题：16pt 白色粗体，副标题 11pt #94A3B8

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
风格要求

扁平化，无渐变背景，无阴影，纯矢量。节点排列工整对齐，空白留足。整体观感应类似于系统设计论文中的 Figure 2: System Architecture Overview。文字全部英文，保持术语一致。不要任何图标、emoji 或装饰元素。
