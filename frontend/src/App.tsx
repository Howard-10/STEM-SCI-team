import { useEffect, useMemo, useRef, useState } from "react";
import {
  authApi,
  clearAuth,
  readStoredAuth,
  saveAuth,
  type ApiConversationSummary,
  type ApiDocumentVersion,
  type ApiProjectDocument,
  type ApiResearchProject,
  type AuthState,
  type PhysicsValidationReport,
} from "./api/auth";
import { qaApi, type QAAnswerResponse, type QAContextMode } from "./api/qa";
import {
  workflowApi,
  type AgentExecutionPlan,
  type AgentExecutionMode,
  type AgentPageMaterial,
  type AgentOutputSummary,
  type FormalEvidenceRecord,
  type WorkflowState,
  type ControllerWorkflowState,
  type DataPipelineState,
  type RuntimeStatus,
  type SciDAVisExport,
  type ConversationCommandResult,
  type EvidenceReviewPackage,
  type OrchestrationControlState,
  type OrchestrationGate,
  type OrchestrationBlocker,
  type OrchestrationTask,
  type ResearchBeliefGraph,
  type ResearchBranch,
  type OrchestrationEvent,
  type ProjectClaim,
  type ReproducibilityReviewResult,
} from "./api/workflow";
import { api } from "./api/client";
import type {
  DiscoveryAssetResponse,
  KnowledgeAssetSummary,
  SearchResult,
  SharedCorpusSummary,
} from "./types/context";
import type { BackendHealth } from "./api/client";
import { demoBundle, demoCorpus, demoQAResponse, demoRuntime } from "./demo/data";
import { demoDocumentContents, demoDocumentsByProject, demoProjects } from "./demo/projectHub";
import { ResearchProgressBoard } from "./components/ResearchProgressBoard";
import { ResearchAnalysisWorkbench } from "./components/ResearchAnalysisWorkbench";
import { RichMarkdown } from "./components/RichMarkdown";
import { TechnicalTrace } from "./components/TechnicalTrace";
import { TeachingWorkspaceFrame } from "./components/TeachingWorkspaceFrame";
import { WorkspaceModeSelector } from "./components/WorkspaceModeSelector";

type WorkspaceView = "knowledge" | "codex" | "analysis" | "audit";
type ContextTab = "workspace" | "evidence" | "agent-work" | "agent-plan" | "agent-outputs";
export type WorkspaceTab = "home" | "workspace" | "editor" | "agent" | "audit";
type OutputSectionId = "questions" | "evidence" | "data" | "code" | "paper" | "review";
type OutputWorkbenchId = "overview" | "research-design" | "evidence-review" | "data-audit" | "code-review" | "paper-review" | "final-review";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  response?: QAAnswerResponse;
  attachments?: ChatAttachment[];
  orchestration?: ConversationCommandResult;
};

type ChatAttachment = {
  id: string;
  name: string;
  kind: "PDF" | "WORD" | "IMAGE" | "CSV";
  sizeLabel: string;
  file: File;
};

type OrchestrationArtifactContent = {
  artifact_id: string;
  artifact_type: string;
  version: number;
  body: Record<string, unknown>;
  created_at: string;
};

type ManuscriptFigureEntry = {
  figure_number: number;
  caption: string;
  url: string;
  alt_text: string;
};

type ConversationalHistoryEntry = {
  turn_id: string;
  message: string;
  response: ConversationCommandResult | null;
  status: string;
  created_at: string;
};

type PaneWidths = {
  sidebar: number;
  output: number;
};

type KnowledgeAssetKind = "source" | "candidate" | "manuscript" | "evidence" | "claim" | "audit";

type KnowledgeAsset = {
  id: string;
  kind: KnowledgeAssetKind;
  title: string;
  summary: string;
  status: string;
  version?: string;
  provenance?: string;
  updatedAt?: string;
  action?: string;
};

type SelectedDocument = {
  document: ApiProjectDocument;
  version: ApiDocumentVersion | null;
};

type SelectedCitation = QAAnswerResponse["citations"][number];

type DialogueBranchOption = {
  id: string;
  title: string;
  description: string;
  benefits: string[];
  risks: string[];
  prerequisites: string[];
  message: string;
};

type BackendStatus = "checking" | "online" | "offline";
type WorkspaceMode = "research" | "teaching" | null;

function workspaceModeFromPath(): WorkspaceMode {
  if (window.location.pathname === "/workspace/research") return "research";
  if (window.location.pathname === "/workspace/teaching") return "teaching";
  return null;
}

const demoProjectId = import.meta.env.VITE_PROJECT_ID && import.meta.env.VITE_PROJECT_ID !== "demo"
  ? import.meta.env.VITE_PROJECT_ID
  : "physics-ai-demo";
const demoMode = import.meta.env.VITE_DEMO_MODE === "true";
const starMapWebUrl = import.meta.env.VITE_STARMAP_WEB_URL
  || (import.meta.env.DEV ? "http://127.0.0.1:5178" : "/teaching/");
// Agent selection and planning are internal implementation details.  The
// researcher drives the workflow through the conversation; structured results
// remain available in the right-hand research output pane.
const legacyAgentPlannerEnabled = false;

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function asText(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

// Provenance identifiers belong in the audit trail, not in the researcher-facing
// conversation or manuscript preview. Keep the transformation presentation-only;
// the stored artifact remains unchanged for reproducibility.
function cleanResearchPresentation(value: string): string {
  return value
    .replace(/分析输入：document:\/\/[^；。\n]+(?:；SHA-256：[^；。\n]+)?[；。]?/gi, "分析输入：已冻结的公开资料版本（具体定位见审计附录）。")
    .replace(/document:\/\/[^\s；，。)]+/gi, "已冻结资料")
    .replace(/SHA-256：?[a-f0-9]{32,64}/gi, "数据指纹已记录于审计附录")
    .replace(/segment-\d+/gi, "资料片段")
    .replace(/claim:[a-z0-9:_-]+/gi, "主张记录")
    .replace(/artifact-[a-z0-9_-]+/gi, "研究产物")
    .replace(/\b(?:shared_evd|evd|ctx|src)_[A-Za-z0-9_-]+\b/gi, "相关证据片段")
    .replace(/\b(?:task|plan|run)_[A-Za-z0-9_-]+\b/gi, "研究记录")
    .replace(/当前全文资源尚未挂载/g, "当前正式全文索引尚未完成");
}

const manuscriptSectionLabels: Record<string, string> = {
  title: "标题",
  abstract: "摘要",
  keywords: "关键词",
  introduction: "引言",
  evidence_review: "证据综述",
  theoretical_framework: "理论框架",
  research_questions: "研究问题",
  methods: "方法",
  analysis_plan: "分析方案",
  statistical_analysis: "统计分析与稳健性检查",
  results: "结果",
  results_table: "结果表",
  discussion: "讨论",
  conclusion: "结论",
  expected_contribution: "预期贡献",
  reproducibility: "可复现性与审查链",
  ethics_limitations: "伦理与局限",
  limitations: "局限",
  references: "参考文献",
  subtitle_and_notice: "副标题与数据说明",
  appendix_a: "附录 A 无 AI 独立迁移评分量规",
  supplement_s1: "补充材料 S1 审计字段",
  supplement_s2: "补充材料 S2 模拟数据生成规范",
  body: "正文",
  full_text: "正文",
};

const manuscriptSectionOrder = Object.keys(manuscriptSectionLabels);

function manuscriptSectionEntries(body: Record<string, unknown> | null) {
  if (!body) return [];
  const sections = asRecord(body.sections) ?? {};
  const sectionKeys = [
    ...manuscriptSectionOrder,
    ...Object.keys(sections).filter((key) => !manuscriptSectionOrder.includes(key)),
  ];
  const seen = new Set<string>();
  const entries = sectionKeys.flatMap((key) => {
    const text = asText(sections[key]);
    if (!text || seen.has(text.trim())) return [];
    seen.add(text.trim());
    return [{
      key,
      label: manuscriptSectionLabels[key] ?? key.replaceAll("_", " "),
      text,
    }];
  });
  const fullText = asText(body.full_text);
  if (fullText && entries.length === 0 && !seen.has(fullText.trim())) {
    entries.push({ key: "full_text", label: manuscriptSectionLabels.full_text, text: fullText });
  }
  return entries;
}

function manuscriptSectionMarkdown(text: string) {
  return text.replace(/^\s{0,3}#{1,6}\s+[^\n]+\n+/, "").trim();
}

function statisticalResultLabel(key: string): string {
  const labels: Record<string, string> = {
    participants_total: "学生总数",
    teams_total: "团队总数",
    complete_cases: "完整案例",
    adjusted_mean_difference: "调整后均值差",
    confidence_interval_lower: "95% CI 下限",
    confidence_interval_upper: "95% CI 上限",
    cr2_p_value: "CR2 p 值",
    wild_cluster_bootstrap_p_value: "Wild bootstrap p 值",
    paired_randomization_p_value: "配对随机化 p 值",
    interrater_icc_2_k: "评分者 ICC(2,k)",
    sensitivity_effect_lower: "缺失敏感性下界",
    sensitivity_effect_upper: "缺失敏感性上界",
  };
  return labels[key] ?? key.replaceAll("_", " ");
}

function runtimeReasonLabel(value: string | null | undefined, fallback: string): string {
  const labels: Record<string, string> = {
    CODEX_PROVIDER_NOT_SELECTED: "尚未选择代码生成服务，可先使用受控模板。",
    CODING_PROVIDER_NOT_CONFIGURED: "代码生成服务尚未配置。",
    SPSS_EXECUTABLE_NOT_CONFIGURED: "SPSS 批处理程序尚未配置。",
    SPSS_EXECUTABLE_NOT_FOUND: "本机暂未检测到 SPSS 批处理程序，可先使用内置审计与脚本校验流程。",
    SCIDAVIS_EXECUTABLE_NOT_CONFIGURED: "SciDAVis 程序尚未配置。",
    SCIDAVIS_EXECUTABLE_NOT_FOUND: "本机暂未检测到 SciDAVis 程序，可先保留 CSV 结果并在安装后复核。",
  };
  if (!value) return fallback;
  return labels[value] ?? cleanResearchPresentation(value);
}

function corpusStatusLabel(summary: SharedCorpusSummary | null | undefined): string {
  if (summary?.formal_evidence_ready) return "正式证据可用";
  if (summary?.discovery_ready) return "发现模式可用";
  return "正式索引待完善";
}

function corpusRiskFlagLabel(value: string): string {
  if (/asset_missing/i.test(value)) return "部分本地索引资产待生成，当前不影响已上传资料的发现式检索。";
  if (/formal_locator/i.test(value)) return "正式页码定位索引待完善，当前证据可先按文本片段追溯。";
  if (/vector|vectordb/i.test(value)) return "向量索引仍在补齐，可继续使用已登记资料与文本证据。";
  return cleanResearchPresentation(value);
}

function compactResearchText(value: string | null | undefined, fallback: string): string {
  if (!value?.trim()) return fallback;
  const cleaned = cleanResearchPresentation(value)
    .replace(/请(?:基于|据此|进入|帮我|先|继续|启动)[^。！？]{12,120}[。！？]?/g, "")
    .replace(/涉及候选产物[^。！？]+[。！？]?/g, "")
    .replace(/\s+/g, " ")
    .trim();
  const readable = cleaned || value.trim();
  return readable.length > 120 ? `${readable.slice(0, 118)}...` : readable;
}

function formatReviewNumber(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return String(value ?? "-");
  return value.toFixed(3);
}

function intakeWorkflowState(projectId: string): WorkflowState {
  return {
    project_id: projectId,
    current_stage: "INTAKE",
    pending_approval_ref: null,
    last_agent_run_id: null,
    last_route_decision: null,
    research_state: null,
  };
}

const agentRows = [
  ["01", "mentor_planning", "导师规划", "界定研究问题与范围"],
  ["02", "evidence_review", "证据审查", "筛选、核验和组织文献证据"],
  ["03", "research_design", "研究设计", "形成可审批的研究方案"],
  ["04", "data_analysis", "数据分析", "编译分析计划与结果检查"],
  ["05", "paper_writing", "论文写作", "生成基于证据的写作草案"],
  ["06", "independent_review", "独立审查", "检查风险、引用和方法"],
] as const;

const agentCompletionStages: Record<string, string[]> = {
  mentor_planning: ["SCOPED", "EVIDENCE_READY", "STUDY_PROTOCOL_APPROVED", "DATA_READY", "ANALYZED", "DRAFTED", "VERIFIED", "RELEASED"],
  evidence_review: ["EVIDENCE_READY", "STUDY_PROTOCOL_APPROVED", "DATA_READY", "ANALYZED", "DRAFTED", "VERIFIED", "RELEASED"],
  research_design: ["STUDY_PROTOCOL_APPROVED", "DATA_READY", "ANALYZED", "DRAFTED", "VERIFIED", "RELEASED"],
  data_analysis: ["ANALYZED", "DRAFTED", "VERIFIED", "RELEASED"],
  paper_writing: ["DRAFTED", "VERIFIED", "RELEASED"],
  independent_review: ["VERIFIED", "RELEASED"],
};

function workflowAgentStatus(
  agentId: string,
  workflow: WorkflowState | null,
): "已完成" | "待审批" | "进行中" | "待启动" {
  if (!workflow) return "待启动";
  const currentStage = workflow.current_stage;
  if (agentCompletionStages[agentId]?.includes(currentStage)) return "已完成";
  if (workflow.last_route_decision?.selected_route === agentId && currentStage === "WAITING_HUMAN") {
    return "待审批";
  }
  if (workflow.last_route_decision?.selected_route === agentId) return "进行中";
  return "待启动";
}

const dataPipelineLabels: Record<string, string> = {
  WAITING_RAW_DATA: "等待原始 CSV",
  WAITING_PROCESSING_APPROVAL: "等待数据处理审批",
  WAITING_FREEZE_APPROVAL: "等待数据冻结审批",
  WAITING_EXECUTION_APPROVAL: "等待分析执行审批",
  ANALYZED: "分析结果已验证",
  REWORK: "需要返工",
  BLOCKED: "流程已阻断",
};

const completedAgentsByStage: Record<string, string[]> = {
  INTAKE: [],
  SCOPED: ["mentor_planning"],
  EVIDENCE_READY: ["mentor_planning", "evidence_review"],
  STUDY_PROTOCOL_APPROVED: ["mentor_planning", "evidence_review", "research_design"],
  DATA_READY: ["mentor_planning", "evidence_review", "research_design"],
  ANALYZED: ["mentor_planning", "evidence_review", "research_design", "data_analysis"],
  DRAFTED: ["mentor_planning", "evidence_review", "research_design", "data_analysis", "paper_writing"],
  VERIFIED: ["mentor_planning", "evidence_review", "research_design", "data_analysis", "paper_writing", "independent_review"],
  RELEASED: ["mentor_planning", "evidence_review", "research_design", "data_analysis", "paper_writing", "independent_review"],
};

const agentDisplayNames: Record<string, string> = {
  mentor_planning: "导师规划",
  evidence_review: "证据审查",
  research_design: "研究设计",
  data_analysis: "数据分析",
  paper_writing: "论文写作",
  independent_review: "独立审查",
};

const agentTaskStatusLabels: Record<string, string> = {
  PLANNED: "待执行",
  WAITING_DEPENDENCY: "等待依赖",
  SKIPPED: "已跳过",
  RUNNING: "执行中",
  COMPLETED: "已完成",
  FAILED: "失败",
  BLOCKED: "已阻断",
};

const agentPlanStatusLabels: Record<string, string> = {
  PENDING_APPROVAL: "等待批准",
  APPROVED: "已批准，等待执行",
  RUNNING: "执行中",
  COMPLETED: "已完成",
  PARTIAL: "部分完成",
  REJECTED: "已拒绝",
  BLOCKED: "已阻断",
  WAITING_TASK_APPROVAL: "等待逐项确认",
  REWORK_REQUIRED: "等待返工",
};

const agentOutputDecisionLabels: Record<string, string> = {
  candidate: "候选",
  retained: "已保留",
  applied: "已应用",
  promoted: "已提升",
  review_required: "待核验",
  reject: "已拒绝",
};

const agentTargetPages: Record<string, string[]> = {
  mentor_planning: ["research_questions", "workspace"],
  evidence_review: ["knowledge_evidence", "evidence_gate"],
  research_design: ["research_design", "data_collection"],
  data_analysis: ["data_analysis", "codex"],
  paper_writing: ["paper_editor"],
  independent_review: ["audit_validation"],
};

function isFormalCitation(citation: SelectedCitation) {
  return (
    citation.verification_status === "source_verified"
    || citation.verification_status === "human_verified"
  ) && citation.locator_status === "RESOLVED";
}

function citationStatusLabel(citation: SelectedCitation) {
  if (citation.source_type === "paper") return "候选论文";
  if (isFormalCitation(citation)) {
    return citation.verification_status === "human_verified" ? "人工核验" : "来源已核验";
  }
  if (citation.locator_status === "RESOLVED") return "已定位，待核验";
  return "待定位/核验";
}

function citationPageLabel(citation: SelectedCitation) {
  if (citation.page_start == null) return "页码待补充";
  return `第 ${citation.page_start}${citation.page_end && citation.page_end !== citation.page_start ? `-${citation.page_end}` : ""} 页`;
}

function claimStatusLabel(value: string | null | undefined) {
  const labels: Record<string, string> = {
    NOT_REQUIRED: "无需额外核验",
    PENDING: "待审核",
    REVIEW_REQUIRED: "待审核",
    VERIFIED: "已核验",
    APPROVED: "已确认",
  };
  if (!value) return "待审核";
  return labels[value] ?? value.replaceAll("_", " ");
}

function claimSectionLabel(value: string) {
  const labels: Record<string, string> = {
    introduction: "引言",
    methods: "方法",
    results: "结果",
    discussion: "讨论",
    ethics_limitations: "伦理与局限",
  };
  return labels[value] ?? value;
}

function agentStatus(snapshot: ControllerWorkflowState | null, agentId: string): string {
  if (!snapshot) return "读取中";
  const routeAgent = snapshot.last_route_decision?.selected_route;
  if (snapshot.current_stage === "WAITING_HUMAN" && routeAgent === agentId) {
    return "等待审批";
  }
  if (snapshot.current_stage === "REWORK" && snapshot.research_state?.rework_target_agent === agentId) {
    return "待返工";
  }
  if (completedAgentsByStage[snapshot.current_stage]?.includes(agentId)) {
    return "已完成";
  }
  return "待启动";
}

function outputSummariesFromPlan(plan: AgentExecutionPlan): AgentOutputSummary[] {
  return plan.tasks
    .filter((task) => task.status !== "PLANNED" && task.status !== "WAITING_DEPENDENCY" && task.status !== "SKIPPED")
    .filter((task) => task.persisted_artifact_ids.length > 0 || task.error || task.status === "BLOCKED")
    .map((task) => ({
      plan_id: plan.plan_id,
      task_id: task.task_id,
      project_id: plan.project_id,
      user_request: plan.user_request,
      conversation_id: plan.conversation_id,
      turn_id: plan.turn_id,
      agent_id: task.agent_id,
      task_type: task.task_type,
      status: task.status,
      input_refs: task.input_refs,
      depends_on: task.depends_on,
      risk_level: task.risk_level,
      output_types: task.output_refs.map((ref) => ref.split("/").at(-1) ?? ref),
      artifact_ids: task.persisted_artifact_ids,
      artifact_refs: task.output_refs,
      evidence_refs: task.evidence_refs,
      output_previews: [],
      risk_flags: task.risk_flags,
      unresolved_questions: task.unresolved_questions,
      decision: "candidate",
      target_pages: agentTargetPages[task.agent_id] ?? ["workspace"],
      error: task.error,
      primary_artifact_id: null,
      researcher_answer: "",
      summary_mode: "deterministic",
    }));
}
const stageRows = [
  ["01", "研究接入", "明确研究对象、问题与边界", "已完成"],
  ["02", "范围确认", "确认研究问题和证据范围", "已完成"],
  ["03", "证据综述", "筛选、核验和组织文献证据", "进行中"],
  ["04", "研究设计", "形成可审批的研究方案", "待进入"],
  ["05", "数据准备", "确认数据来源、质量和分析口径", "待进入"],
  ["06", "分析执行", "运行分析并记录可复核结果", "待进入"],
  ["07", "论文草稿", "生成基于证据的写作草案", "待进入"],
  ["08", "独立审查", "检查风险、引用和方法", "待进入"],
  ["09", "发布准备", "完成最终确认与版本归档", "待进入"],
];

const capabilityCards = [
  {
    icon: "⌕",
    title: "论文检索",
    description: "从当前项目和共享知识库中找到相关论文与原文片段。",
    prompt: "帮我梳理这个研究方向的核心文献与研究空白",
  },
  {
    icon: "◈",
    title: "证据回答",
    description: "回答会带有检索轨迹、引用和待核验风险提示。",
    prompt: "根据当前证据给出一个有引用的研究结论",
  },
  {
    icon: "✦",
    title: "研究流程",
    description: "把研究问题拆成可追踪的阶段、证据和研究产物。",
    prompt: "根据当前证据设计一个师范生 Python 物理建模实验",
  },
  {
    icon: "⌘",
    title: "代码与审查",
    description: "为数据分析生成代码草案，并在执行前经过审查。",
    prompt: "检查我的研究问题、变量和数据分析方案是否一致",
  },
];

function makeWelcome(projectTitle: string, freshThread = false): ChatMessage {
  return {
    id: "welcome",
    role: "assistant",
    content: freshThread
      ? `已开始一段新对话。它不会带入上一段聊天文字，但仍会使用当前项目“${projectTitle}”中已经上传的论文、数据和研究记录。若要做完全隔离的测试，请新建一个项目。`
      : `你好，我是 STEM-SSCI/SCI 研究助手。当前项目是“${projectTitle}”。\n\n你可以直接提问、比较方案、补充条件或修改想法；涉及检索、冻结方案、执行分析等高风险动作时，我会在对话中向你确认。`,
  };
}

function researchEventLabel(event: OrchestrationEvent): string {
  const labels: Record<string, string> = {
    PROJECT_CREATED: "研究项目已建立",
    ROUTE_SELECTED: "已选择研究方向",
    TASK_ENQUEUED: "研究任务已排队",
    TASK_CLAIMED: "研究任务开始执行",
    TASK_COMPLETED: "研究任务已完成",
    TASK_FAILED: "研究任务执行失败",
    EVIDENCE_RETRIEVED: "已整理新的证据",
    EVIDENCE_REVIEWED: "证据审阅完成",
    CONVERSATION_CHECKPOINT_RESPONDED: "已纳入你的研究判断",
    RESEARCH_SCOPE_REVISED: "研究范围已更新",
    GATE_CREATED: "出现需要明确判断的研究事项",
    GATE_DECIDED: "已记录正式研究决定",
    ROUTE_PROPOSED: "已提出研究路线候选",
    TASK_QUEUED: "已排队处理下一项研究动作",
    AUTOMATIC_ACTION_COMPLETED: "后台研究动作已完成",
    "route proposed": "已提出研究路线候选",
    "task queued": "已排队处理下一项研究动作",
    "automatic action completed": "后台研究动作已完成",
  };
  return labels[event.event_type] ?? event.event_type.replaceAll("_", " ").toLowerCase();
}

function researchEventNarrative(event: OrchestrationEvent): string {
  const payload = event.payload ?? {};
  const explicit = asText(payload.message) ?? asText(payload.checkpoint) ?? asText(payload.reason);
  if (explicit) return cleanResearchPresentation(explicit);
  const narratives: Record<string, string> = {
    "route proposed": "系统已根据当前研究目标提出一条可追溯的研究路线；这只是候选方案，后续仍可修改。",
    "task queued": "这项研究动作已进入后台队列，完成后会把产物和证据带回当前对话。",
    "automatic action completed": "后台动作已完成，新的研究产物已回写到项目记录；下一处需要研究者判断的边界会在对话中说明。",
    TASK_QUEUED: "这项研究动作已进入后台队列，完成后会把产物和证据带回当前对话。",
    TASK_COMPLETED: "后台研究动作已完成，产物和证据已经回写到项目记录。",
    ROUTE_PROPOSED: "系统已根据当前研究目标提出一条可追溯的研究路线；这只是候选方案，后续仍可修改。",
    AUTOMATIC_ACTION_COMPLETED: "后台动作已完成，新的研究产物已回写到项目记录；下一处需要研究者判断的边界会在对话中说明。",
    GATE_CREATED: "系统发现一个会影响后续结论的研究边界，已暂停在这里等待你的判断。",
    GATE_DECIDED: "你的正式研究决定已应用到当前版本，后续动作会遵守这项边界。",
    CONVERSATION_CHECKPOINT_RESPONDED: "你的取舍已经纳入研究版本，系统会据此生成下一份可检查的产物。",
  };
  return narratives[event.event_type]
    ?? `研究动作“${researchEventLabel(event)}”已完成；具体证据和影响见右侧研究产出。`;
}

const agentIntentPatterns = [
  /研究方案|研究设计|研究计划|研究流程|全流程/,
  /证据核验|逐条核验|证据综述|正式证据/,
  /数据准备|数据分析|分析执行|论文草稿|独立审查|发布准备/,
  /调用\s*agent/i,
];

function shouldAutoInvokeAgent(text: string): boolean {
  return agentIntentPatterns.some((pattern) => pattern.test(text));
}

export function App() {
  const [auth, setAuth] = useState<AuthState | null>(() => readStoredAuth());
  const [workspaceMode, setWorkspaceMode] = useState<WorkspaceMode>(() => workspaceModeFromPath());
  const [projects, setProjects] = useState<ApiResearchProject[]>(demoMode ? demoProjects : []);
  const [projectsReady, setProjectsReady] = useState(!readStoredAuth()?.access_token);
  const [projectId, setProjectId] = useState(demoMode ? (demoProjects[0]?.project_id ?? demoProjectId) : "");
  const [view, setView] = useState<WorkspaceView>("knowledge");
  const [contextTab, setContextTab] = useState<ContextTab>("evidence");
  const [mode, setMode] = useState<QAContextMode>("discovery");
  const [question, setQuestion] = useState("");
  const [conversationId, setConversationId] = useState<string>();
  const [messages, setMessages] = useState<ChatMessage[]>([
    makeWelcome(demoMode ? (demoProjects[0]?.title ?? "科研项目") : "科研项目"),
  ]);
  // Keep the landing view conversational. Demo evidence/workflow data is
  // loaded only after the researcher asks for it, rather than presenting a
  // project that appears to be mid-process on first open.
  const [lastResponse, setLastResponse] = useState<QAAnswerResponse | null>(null);
  const [workflowState, setWorkflowState] = useState<WorkflowState | null>(null);
  const [busy, setBusy] = useState(false);
  const [loginValue, setLoginValue] = useState("");
  const [passwordValue, setPasswordValue] = useState("");
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [registerUsername, setRegisterUsername] = useState("");
  const [registerEmail, setRegisterEmail] = useState("");
  const [registerDisplayName, setRegisterDisplayName] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState("");
  const [projectMenuOpen, setProjectMenuOpen] = useState(false);
  const [createProjectOpen, setCreateProjectOpen] = useState(false);
  const [projectForm, setProjectForm] = useState({
    project_id: "",
    title: "",
    research_direction: "",
    abstract: "",
  });
  const [projectBusy, setProjectBusy] = useState(false);
  const [projectError, setProjectError] = useState("");
  const [documents, setDocuments] = useState<ApiProjectDocument[]>([]);
  const [conversations, setConversations] = useState<ApiConversationSummary[]>([]);
  const [documentsBusy, setDocumentsBusy] = useState(false);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const primaryDataInputRef = useRef<HTMLInputElement>(null);
  const [primaryDataBusy, setPrimaryDataBusy] = useState(false);
  const rawCsvInputRef = useRef<HTMLInputElement>(null);
  const evidenceInputRef = useRef<HTMLInputElement>(null);
  const analysisInputRef = useRef<HTMLInputElement>(null);
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatus>(demoRuntime);
  const [workflowSnapshot, setWorkflowSnapshot] = useState<ControllerWorkflowState | null>(null);
  const [analysisState, setAnalysisState] = useState<DataPipelineState | null>(null);
  const [analysisStage, setAnalysisStage] = useState("INTAKE");
  const [analysisBusy, setAnalysisBusy] = useState(false);
  const [analysisError, setAnalysisError] = useState("");
  const [scidavisExport, setScidavisExport] = useState<SciDAVisExport | null>(null);
  const [scidavisBusy, setScidavisBusy] = useState(false);
  const chatAttachmentInputRef = useRef<HTMLInputElement>(null);
  const [chatAttachments, setChatAttachments] = useState<ChatAttachment[]>([]);
  const [attachmentError, setAttachmentError] = useState("");
  const [selectedDocument, setSelectedDocument] = useState<SelectedDocument | null>(null);
  const [documentTitleDraft, setDocumentTitleDraft] = useState("");
  const [documentContentDraft, setDocumentContentDraft] = useState("");
  const [paperSourceEditing, setPaperSourceEditing] = useState(false);
  const [documentEditBusy, setDocumentEditBusy] = useState(false);
  const [documentEditError, setDocumentEditError] = useState("");
  const [manuscriptApplyError, setManuscriptApplyError] = useState("");
  const [selectedCitation, setSelectedCitation] = useState<SelectedCitation | null>(null);
  const [selectedTurnId, setSelectedTurnId] = useState<string | null>(null);
  const [sidebarVisible, setSidebarVisible] = useState(true);
  const [physicsSource, setPhysicsSource] = useState("import math\n\n# 在这里粘贴你的 Python 物理建模代码\nt = [0, 1, 2]\nx = [0, 1, 4]\n");
  const [physicsEquations, setPhysicsEquations] = useState("F=m*a\nv=v0+a*t");
  const [physicsReport, setPhysicsReport] = useState<PhysicsValidationReport | null>(null);
  const [physicsBusy, setPhysicsBusy] = useState(false);
  const [physicsError, setPhysicsError] = useState("");
  const [analysisWorkbenchOpen, setAnalysisWorkbenchOpen] = useState(false);
  const [backendStatus, setBackendStatus] = useState<BackendStatus>("checking");
  const [backendHealth, setBackendHealth] = useState<BackendHealth | null>(null);
  const [rightPaneVisible, setRightPaneVisible] = useState(false);
  const [topResearchInfoOpen, setTopResearchInfoOpen] = useState(false);
  const [selectedOutputSection, setSelectedOutputSection] = useState<OutputSectionId>("questions");
  const [activeOutputWorkbench, setActiveOutputWorkbench] = useState<OutputWorkbenchId>("overview");
  const [workbenchExpanded, setWorkbenchExpanded] = useState(false);
  const [expandedEvidenceRowId, setExpandedEvidenceRowId] = useState<string | null>(null);
  const [codeArtifactDrafts, setCodeArtifactDrafts] = useState<Record<string, string>>({});
  const [codeSaveBusy, setCodeSaveBusy] = useState<string | null>(null);
  const [codeSaveError, setCodeSaveError] = useState("");
  const [expandedCodeArtifactId, setExpandedCodeArtifactId] = useState<string | null>(null);
  const [paneWidths, setPaneWidths] = useState<PaneWidths>({ sidebar: 246, output: 680 });
  const [draggingPane, setDraggingPane] = useState<"sidebar" | "output" | null>(null);
  const [workflow, setWorkflow] = useState<WorkflowState | null>(null);
  const [workflowBusy, setWorkflowBusy] = useState(false);
  const [workflowError, setWorkflowError] = useState("");
  const [evidenceRows, setEvidenceRows] = useState<SearchResult[]>([]);
  const [evidenceBusy, setEvidenceBusy] = useState(false);
  const [evidenceError, setEvidenceError] = useState("");
  const [citationActionBusy, setCitationActionBusy] = useState(false);
  const [citationActionError, setCitationActionError] = useState("");
  const [corpusSummary, setCorpusSummary] = useState<SharedCorpusSummary | null>(null);
  const [knowledgeAssetSummary, setKnowledgeAssetSummary] = useState<KnowledgeAssetSummary | null>(null);
  const [discoveryAssets, setDiscoveryAssets] = useState<DiscoveryAssetResponse | null>(null);
  const [agentPlan, setAgentPlan] = useState<AgentExecutionPlan | null>(null);
  const [agentPlans, setAgentPlans] = useState<AgentExecutionPlan[]>([]);
  const [agentOutputs, setAgentOutputs] = useState<AgentOutputSummary[]>([]);
  const [pageMaterials, setPageMaterials] = useState<AgentPageMaterial[]>([]);
  const [formalEvidence, setFormalEvidence] = useState<FormalEvidenceRecord[]>([]);
  const [agentPlanDraft, setAgentPlanDraft] = useState("");
  const [selectedAgentTaskIds, setSelectedAgentTaskIds] = useState<string[]>([]);
  const [agentPlanBusy, setAgentPlanBusy] = useState(false);
  const [agentPlanError, setAgentPlanError] = useState("");
  const [agentOutputDecisions, setAgentOutputDecisions] = useState<Record<string, string>>({});
  const [agentOutputTargets, setAgentOutputTargets] = useState<Record<string, string>>({});
  const [agentPlanPanelOpen, setAgentPlanPanelOpen] = useState(true);
  const [agentOutputBoxOpen, setAgentOutputBoxOpen] = useState(true);
  const [agentOutputScope, setAgentOutputScope] = useState<"turn" | "question" | "project">("turn");
  const [agentExecutionMode, setAgentExecutionMode] = useState<AgentExecutionMode>("automatic");
  const [conversationControl, setConversationControl] = useState<ConversationCommandResult | null>(null);
  const [researchCanvas, setResearchCanvas] = useState<ResearchBeliefGraph | null>(null);
  const [researchBranches, setResearchBranches] = useState<ResearchBranch[]>([]);
  const [orchestrationState, setOrchestrationState] = useState<OrchestrationControlState | null>(null);
  const [projectBlockers, setProjectBlockers] = useState<OrchestrationBlocker[]>([]);
  const [orchestrationTasks, setOrchestrationTasks] = useState<OrchestrationTask[]>([]);
  const [researchEvents, setResearchEvents] = useState<OrchestrationEvent[]>([]);
  const [orchestrationHistory, setOrchestrationHistory] = useState<ConversationalHistoryEntry[]>([]);
  const [evidenceReviewPackage, setEvidenceReviewPackage] = useState<EvidenceReviewPackage | null>(null);
  const [orchestrationArtifacts, setOrchestrationArtifacts] = useState<OrchestrationArtifactContent[]>([]);
  const [projectClaims, setProjectClaims] = useState<ProjectClaim[]>([]);
  const [reproducibilityReview, setReproducibilityReview] = useState<ReproducibilityReviewResult | null>(null);
  const [reproducibilityBusy, setReproducibilityBusy] = useState(false);
  const [reproducibilityError, setReproducibilityError] = useState("");
  const [publicationTarget, setPublicationTarget] = useState("International Journal of STEM Education");
  const [publicationArticleType, setPublicationArticleType] = useState("Research Article");
  const [publicationTargetBusy, setPublicationTargetBusy] = useState(false);
  const [publicationTargetError, setPublicationTargetError] = useState("");
  const [conversationGateBusy, setConversationGateBusy] = useState(false);
  const [conversationGateError, setConversationGateError] = useState("");
  const [reviewerUsername, setReviewerUsername] = useState("");
  const [reviewerBusy, setReviewerBusy] = useState(false);
  const conversationGateActionRef = useRef(false);
  const autoContinuedWorkflowRef = useRef<string | null>(null);
  const orchestrationEventCursorRef = useRef<string | undefined>(undefined);
  // A refresh should restore the latest persisted conversation. A deliberate
  // "new conversation" action should remain blank until the researcher sends
  // a new message, so the restore effect does not immediately reopen history.
  const suppressConversationRestoreRef = useRef(false);

  const buildGateFromState = (state: OrchestrationControlState): OrchestrationGate | null => {
    if (!state.active_gate_id) return null;
    const action = state.workstreams.find((item) => item.workstream_id === state.active_workstream_id)?.current_action;
    const gateTypes: Record<string, string> = {
      claim_evidence_support: "evidence_sufficiency_review",
    };
    const labels: Record<string, string> = {
      evidence_sufficiency_review: "文献与证据审阅",
      research_question_design: "研究问题设计",
      research_design: "研究方案",
      causal_DAG: "DAG 结构检查",
      power_analysis: "样本量与统计功效分析",
      preregistration_freeze: "研究方案确认与预注册冻结",
      raw_data_import: "导入原始研究数据",
      data_audit: "数据审计",
      data_processing_approval: "数据处理审批",
      dataset_freeze_hash: "数据冻结与哈希",
      analysis_code_generation: "分析代码生成",
      physics_code_validation: "物理代码校验",
      code_review: "代码审查",
      manual_execution_approval: "人工执行审批",
      sandbox_analysis_execution: "受控分析执行",
      statistical_result_validation: "统计结果验证",
      bootstrap_robustness: "Bootstrap 稳健性分析",
      permutation_test: "置换检验",
      result_direction_consistency: "结果方向一致性检查",
      uncertainty_gate: "结果可靠性确认",
      statistical_result_card: "统计结果卡",
      qualitative_design: "定性研究设计",
      thematic_analysis: "主题分析",
      qualitative_validation: "定性结果复核",
      journal_style_revision: "投稿格式化与 LaTeX",
      manuscript_citation_verification: "论文引用核验",
      reviewer_final_confirmation: "独立审稿与最终确认",
      mixed_methods_merge: "合并定性与定量论文",
    };
    return {
      gate_id: state.active_gate_id,
      project_id: state.project_id,
      workstream_id: state.active_workstream_id ?? "",
      gate_type: action ? gateTypes[action] ?? `${action}_approval` : "orchestration_approval",
      level: "G1",
      status: "PENDING",
      artifact_ids: [],
      reason: action ? `请审核${labels[action] ?? action}候选产物后继续下一阶段。` : "请确认当前研究阶段后继续。",
      warnings: state.route_decision?.uncertainties ?? [],
      risk_acceptance: [],
      requested_by: "orchestrator",
      decided_by: null,
      decision_reason: null,
      created_at: state.updated_at,
      decided_at: null,
    };
  };

  const gateActionLabel = (gate: OrchestrationGate) => {
    const action = gate.gate_type.replace(/_approval$/, "");
    const labels: Record<string, string> = {
      evidence_sufficiency_review: "文献与证据审阅",
      research_question_design: "研究问题设计",
      research_design: "研究方案",
      causal_DAG: "DAG 结构检查",
      power_analysis: "样本量与统计功效分析",
      preregistration_freeze: "研究方案确认与预注册冻结",
      raw_data_import: "导入原始研究数据",
      data_audit: "数据审计",
      data_processing_approval: "数据处理审批",
      dataset_freeze_hash: "数据冻结与哈希",
      analysis_code_generation: "分析代码生成",
      physics_code_validation: "物理代码校验",
      code_review: "代码审查",
      manual_execution_approval: "人工执行审批",
      sandbox_analysis_execution: "受控分析执行",
      statistical_result_validation: "统计结果验证",
      bootstrap_robustness: "Bootstrap 稳健性分析",
      permutation_test: "置换检验",
      result_direction_consistency: "结果方向一致性检查",
      uncertainty_gate: "结果可靠性确认",
      statistical_result_card: "统计结果卡",
      qualitative_design: "定性研究设计",
      thematic_analysis: "主题分析",
      qualitative_validation: "定性结果复核",
      writing: "论文写作和引用核验",
      manuscript_citation_verification: "论文引用核验",
      reviewer_final_confirmation: "独立审稿与最终确认",
      mixed_methods_merge: "合并定性与定量论文",
    };
    return labels[action] ?? action;
  };

  const gateNeedsExplicitCommit = (gate: OrchestrationGate) =>
    [
      "preregistration_freeze_approval",
      "dataset_freeze_hash_approval",
      "manual_execution_approval_approval",
      "reviewer_final_confirmation_approval",
      "manuscript_citation_verification_approval",
    ].includes(gate.gate_type);

  // Research review boundaries stay available to the conversation, but are
  // not presented as blocking approval cards. Only irreversible submissions
  // should create a visible confirmation state.
  const conversationCommitGate = conversationControl?.gate && gateNeedsExplicitCommit(conversationControl.gate)
    ? conversationControl.gate
    : null;

  const focusConversationGate = () => {
    document.querySelector<HTMLTextAreaElement>(".composer-box textarea")?.focus();
  };

  const openOutputWorkspace = (
    section: OutputSectionId = selectedOutputSection,
    workbench: OutputWorkbenchId = "overview",
  ) => {
    setView("audit");
    setContextTab("workspace");
    setSelectedOutputSection(section);
    setActiveOutputWorkbench(workbench);
    setWorkbenchExpanded(false);
    setRightPaneVisible(true);
  };

  const openDedicatedWorkbench = (
    section: OutputSectionId = selectedOutputSection,
    workbench: OutputWorkbenchId = activeOutputWorkbench,
  ) => {
    setView("audit");
    setContextTab("workspace");
    setSelectedOutputSection(section);
    setActiveOutputWorkbench(workbench);
    setRightPaneVisible(true);
    setWorkbenchExpanded(true);
  };

  const openKnowledgeLibrary = () => {
    setView("knowledge");
    setContextTab("evidence");
    setWorkbenchExpanded(false);
    setRightPaneVisible(true);
  };

  const focusResearchDialogue = () => {
    setWorkbenchExpanded(false);
    setRightPaneVisible(false);
    document.querySelector<HTMLTextAreaElement>(".composer-box textarea")?.focus();
  };

  useEffect(() => {
    if (contextTab === "agent-plan" || contextTab === "agent-outputs") {
      setContextTab("agent-work");
    }
  }, [contextTab]);

  // Dedicated workspace entries should open their own result surface instead
  // of retaining the chat-oriented research canvas from the previous view.
  useEffect(() => {
    if (view !== "knowledge" && contextTab !== "workspace") {
      setContextTab("workspace");
    }
  }, [contextTab, view]);

  useEffect(() => {
    const expireSession = () => {
      clearAuth();
      setAuth(null);
      setWorkspaceMode(null);
      window.history.replaceState({}, "", "/");
    };
    window.addEventListener("stem-sci-auth-expired", expireSession);
    return () => window.removeEventListener("stem-sci-auth-expired", expireSession);
  }, []);

  useEffect(() => {
    const handleWorkspaceRoute = () => setWorkspaceMode(workspaceModeFromPath());
    window.addEventListener("popstate", handleWorkspaceRoute);
    return () => window.removeEventListener("popstate", handleWorkspaceRoute);
  }, []);

  useEffect(() => {
    let mounted = true;
    setBackendStatus("checking");
    void api.getHealth()
      .then((health) => {
        if (!mounted) return;
        setBackendHealth(health);
        setBackendStatus(health.status === "ok" ? "online" : "offline");
      })
      .catch(() => {
        if (!mounted) return;
        setBackendHealth(null);
        setBackendStatus("offline");
      });
    return () => {
      mounted = false;
    };
  }, []);

  const activeProject = useMemo(
    () => projects.find((project) => project.project_id === projectId) ?? projects[0] ?? null,
    [projectId, projects],
  );

  useEffect(() => {
    let mounted = true;
    if (!auth?.access_token || !projectId || !projectsReady) {
      setResearchCanvas(null);
      return () => { mounted = false; };
    }
    void workflowApi.getResearchCanvas(projectId).then((canvas) => {
      if (mounted) setResearchCanvas(canvas);
    }).catch(() => {
      if (mounted) setResearchCanvas(null);
    });
    void workflowApi.listResearchBranches(projectId).then((branches) => {
      if (mounted) setResearchBranches(Array.isArray(branches) ? branches : []);
    }).catch(() => {
      if (mounted) setResearchBranches([]);
    });
    return () => { mounted = false; };
  }, [auth?.access_token, projectId, projectsReady]);
  const latestArtifact = (artifactType: string) => [...orchestrationArtifacts]
    .reverse()
    .find((item) => item.artifact_type === artifactType) ?? null;
  const latestResearchQuestion = latestArtifact("ResearchQuestionTree");
  const latestStudyProtocol = latestArtifact("StudyProtocolCandidate");
  const latestDataAudit = latestArtifact("DataAuditCandidate");
  const codeWorkbenchArtifactTypes = new Set([
    "CodeSpecificationDraft",
    "AnalysisCodePlanCandidate",
    "PhysicsCodeValidationCandidate",
    "CodeReviewCandidate",
    "ManualExecutionApprovalCandidate",
    "SandboxExecutionCandidate",
    "StatisticalResultValidationCandidate",
    "BootstrapRobustnessCandidate",
    "PermutationTestCandidate",
    "ResultDirectionCandidate",
    "UncertaintyGateCandidate",
    "StatisticalResultCard",
  ]);
  const codeWorkbenchArtifactLabels: Record<string, string> = {
    CodeSpecificationDraft: "Python 分析代码",
    AnalysisCodePlanCandidate: "分析代码计划",
    PhysicsCodeValidationCandidate: "物理代码校验",
    CodeReviewCandidate: "代码审查",
    ManualExecutionApprovalCandidate: "人工执行许可",
    SandboxExecutionCandidate: "受控分析执行",
    StatisticalResultValidationCandidate: "结果校验",
    BootstrapRobustnessCandidate: "Bootstrap 稳健性",
    PermutationTestCandidate: "置换检验",
    ResultDirectionCandidate: "方向一致性",
    UncertaintyGateCandidate: "不确定性边界",
    StatisticalResultCard: "统计结果卡片",
  };
  const codeWorkbenchArtifacts = Array.from(new Map(
    orchestrationArtifacts
      .filter((item) => codeWorkbenchArtifactTypes.has(item.artifact_type))
      .map((item) => [item.artifact_id, item]),
  ).values());
  const latestManuscriptArtifact = [...orchestrationArtifacts]
    .reverse()
    .find((item) => item.artifact_type === "ManuscriptDraftZh" || item.artifact_type === "ManuscriptOutline") ?? null;
  const effectiveStatisticalResultCard = analysisState?.statistical_result_card ?? null;
  const manuscriptFigureManifest: ManuscriptFigureEntry[] = (
    Array.isArray(latestManuscriptArtifact?.body.figure_manifest)
      ? latestManuscriptArtifact.body.figure_manifest
      : []
  ).flatMap((item) => {
    const record = asRecord(item);
    const figureNumber = Number(record?.figure_number);
    const caption = asText(record?.caption);
    const url = asText(record?.url);
    const altText = asText(record?.alt_text);
    return Number.isFinite(figureNumber) && caption && url
      ? [{ figure_number: figureNumber, caption, url, alt_text: altText || caption }]
      : [];
  });
  const latestManuscriptSectionEntries = manuscriptSectionEntries(latestManuscriptArtifact?.body ?? null);
  const latestManuscriptTitle = latestManuscriptSectionEntries.find((section) => section.key === "title")?.text
    ?? asText(latestManuscriptArtifact?.body.title)
    ?? "候选论文草稿";
  const dataAuditDetails = asRecord(latestDataAudit?.body.data_audit);
  const dataManifest = asRecord(latestDataAudit?.body.data_manifest);
  const auditColumns = Array.isArray(dataManifest?.header)
    ? dataManifest.header.filter((item): item is string => typeof item === "string")
    : [];
  const missingByColumn = asRecord(dataAuditDetails?.missing_values_by_column);
  useEffect(() => {
    const title = activeProject?.title;
    if (!title) return;
    setMessages((current) => {
      if (current.length !== 1 || current[0]?.id !== "welcome") return current;
      return [makeWelcome(title)];
    });
  }, [activeProject?.title]);
  const addIndependentReviewer = async () => {
    if (!auth?.access_token || !projectId || !reviewerUsername.trim() || reviewerBusy) return;
    setReviewerBusy(true);
    setConversationGateError("");
    try {
      await authApi.addProjectReviewer(auth.access_token, projectId, reviewerUsername.trim());
      setReviewerUsername("");
    } catch (error) {
      setConversationGateError(error instanceof Error ? error.message : "无法添加独立审稿人");
    } finally {
      setReviewerBusy(false);
    }
  };
  const activeDocuments = auth?.access_token
    ? documents
    : demoMode
      ? demoDocumentsByProject[projectId] ?? demoDocumentsByProject[demoProjectId] ?? []
      : [];
  const draftDocuments = activeDocuments.filter((document) => document.document_type === "manuscript");
  const datasetDocuments = activeDocuments.filter((document) => document.document_type === "dataset" || document.format === "csv");
  const projectPapers = activeDocuments.filter((document) => document.document_type !== "manuscript");
  const selectedTurnResponse = messages.find(
    (message) => message.id === selectedTurnId && message.role === "assistant",
  )?.response;
  const activeResponse = selectedTurnResponse ?? lastResponse;
  const citations = activeResponse?.citations ?? [];
  const activeOrchestrationStream = orchestrationState?.workstreams.find(
    (item) => item.workstream_id === orchestrationState.active_workstream_id,
  );
  const orchestrationActionLabels: Record<string, string> = {
    claim_evidence_support: "证据核验",
    research_question_design: "研究问题设计",
    research_design: "研究方案确认",
    data_audit: "数据审计",
    data_processing_approval: "数据处理审批",
    dataset_freeze_hash: "数据冻结与哈希",
    analysis_code_generation: "分析代码生成",
    sandbox_analysis_execution: "受控分析执行",
    statistical_result_card: "统计结果卡",
    writing: "论文写作",
    manuscript_citation_verification: "论文引用核验",
    reviewer_final_confirmation: "独立审稿与最终确认",
  };
  const activeOrchestrationStep = activeOrchestrationStream
    && activeOrchestrationStream.current_step_index < activeOrchestrationStream.workflow_steps.length
    ? activeOrchestrationStream.workflow_steps[activeOrchestrationStream.current_step_index]
    : activeOrchestrationStream?.current_action;
  const orchestrationProgress = activeOrchestrationStream
    ? `${Math.min(activeOrchestrationStream.current_step_index + 1, activeOrchestrationStream.workflow_steps.length)} / ${activeOrchestrationStream.workflow_steps.length}`
    : null;
  const orchestrationPhaseLabels: Record<string, string> = {
    EVIDENCE_PREPARATION: "证据准备",
    RESEARCH_DESIGN: "研究设计",
    DATA_ANALYSIS: "数据分析",
    WRITING_PUBLICATION: "论文与发布",
  };
  const canRetryOrchestrationTask = (task: OrchestrationTask) => {
    const currentAction = activeOrchestrationStream && activeOrchestrationStream.current_step_index < activeOrchestrationStream.workflow_steps.length
      ? activeOrchestrationStream.workflow_steps[activeOrchestrationStream.current_step_index]
      : activeOrchestrationStream?.current_action;
    return ["FAILED", "STALE", "CANCELLED"].includes(task.status)
      && task.workstream_id === orchestrationState?.active_workstream_id
      && !orchestrationState?.active_gate_id
      && currentAction === task.action;
  };
  const evidenceReviewPending = Boolean(
    evidenceReviewPackage
    && orchestrationState?.active_gate_id
    && activeOrchestrationStream?.current_action === "claim_evidence_support",
  );
  // Keep the writing surface out of the evidence phase. A draft may be shown
  // earlier only when a persisted manuscript already exists (for example,
  // after a refresh or when revising an older version).
  const writingStepIds = new Set([
    "writing",
    "journal_style_revision",
    "manuscript_citation_verification",
    "reviewer_final_confirmation",
    "mixed_methods_merge",
  ]);
  const writingSurfaceVisible = draftDocuments.length > 0
    || ["DRAFTED", "VERIFIED", "RELEASED"].includes(workflowState?.current_stage ?? "")
    || orchestrationState?.workstreams.some((stream) => {
      const currentStep = stream.workflow_steps[stream.current_step_index];
      return stream.phase === "WRITING_PUBLICATION" || Boolean(currentStep && writingStepIds.has(currentStep));
    }) === true;

  const knowledgeAssets: KnowledgeAsset[] = [
    ...projectPapers.map((document) => ({
      id: document.document_id,
      kind: "source" as const,
      title: document.title,
      summary: document.document_type === "dataset"
        ? "项目原始数据，保留在项目范围内，后续审计和冻结均从该版本开始。"
        : "用户上传的原始论文或研究资料，可供检索、证据定位和对话引用。",
      status: document.status === "active" ? "已登记" : "已归档",
      version: `v${document.current_version}`,
      provenance: document.format.toUpperCase(),
      updatedAt: document.updated_at,
      action: document.document_type === "dataset" ? "打开数据审查" : "查看原始资料",
    })),
    ...draftDocuments.map((document) => ({
      id: document.document_id,
      kind: "manuscript" as const,
      title: document.title,
      summary: "审核后的论文草稿，保留可编辑版本和每次保存记录，不与候选产出混淆。",
      status: "可编辑草稿",
      version: `v${document.current_version}`,
      provenance: "项目文档",
      updatedAt: document.updated_at,
      action: "打开论文工作台",
    })),
    ...(latestManuscriptArtifact ? [{
      id: latestManuscriptArtifact.artifact_id,
      kind: "candidate" as const,
      title: latestManuscriptTitle,
      summary: "后端生成的候选论文正文，保留章节内容、主张关系和证据边界，等待人工审核后再写入正式论文。",
      status: "候选待审核",
      version: `v${latestManuscriptArtifact.created_at ? new Date(latestManuscriptArtifact.created_at).toLocaleDateString() : "当前"}`,
      provenance: "论文产出工作区",
      updatedAt: latestManuscriptArtifact.created_at,
      action: "打开论文工作台",
    }] : []),
    ...agentOutputs.filter((output) => (
      output.agent_id === "paper_writing"
      && output.output_previews.some((preview) => ["ManuscriptDraftZh", "ManuscriptOutline"].includes(preview.artifact_type))
      && !output.output_previews.some((preview) => preview.artifact_id === latestManuscriptArtifact?.artifact_id)
    )).map((output) => ({
      id: output.task_id,
      kind: "candidate" as const,
      title: (() => {
        const preview = output.output_previews.find((item) => item.artifact_type === "ManuscriptDraftZh")
          ?? output.output_previews.find((item) => item.artifact_type === "ManuscriptOutline");
        return asText(preview?.content.title) ?? "候选论文草稿";
      })(),
      summary: "对话生成的候选论文，尚未覆盖正式草稿；可进入论文工作台人工编辑后保存。",
      status: "候选待审核",
      version: "候选版本",
      provenance: "论文产出工作区",
      updatedAt: undefined,
      action: "打开论文工作台",
    })),
    ...(evidenceReviewPackage ? [{
      id: evidenceReviewPackage.artifact_id,
      kind: "evidence" as const,
      title: "本项目证据审阅包",
      summary: `包含 ${evidenceReviewPackage.body.coverage.source_count} 个来源、${evidenceReviewPackage.body.coverage.evidence_count} 条证据片段和 ${evidenceReviewPackage.body.evidence_matrix.length} 条主张对应。`,
      status: evidenceReviewPackage.body.status === "READY" ? "候选包已就绪" : "仍需补充",
      version: `v${evidenceReviewPackage.version}`,
      provenance: "证据与文献工作台",
      action: "打开证据工作台",
    }] : []),
    ...formalEvidence.map((record) => {
      const ref = record.evidence_ref;
      return {
        id: record.evidence_id,
        kind: "evidence" as const,
        title: typeof ref.paper_title === "string" ? ref.paper_title : "正式证据片段",
        summary: typeof ref.excerpt === "string" ? cleanResearchPresentation(ref.excerpt) : "来源已核验并进入正式证据链。",
        status: "正式证据",
        version: record.promoted_at ? new Date(record.promoted_at).toLocaleDateString() : "已提升",
        provenance: `${record.provenance.length} 次产出关联`,
        updatedAt: record.promoted_at,
        action: "查看证据定位",
      };
    }),
    ...projectClaims.map((claim) => ({
      id: claim.claim_id,
      kind: "claim" as const,
      title: `${claimSectionLabel(claim.section)} · ${claim.claim_type}`,
      summary: cleanResearchPresentation(claim.claim_text),
      status: claimStatusLabel(claim.reviewer_status || claim.verification_status),
      version: `${claim.support_evidence_ids.length + claim.support_result_ids.length + claim.support_artifact_ids.length} 项绑定`,
      provenance: claim.support_type,
      action: "查看主张绑定",
    })),
    ...(latestDataAudit ? [{
      id: latestDataAudit.artifact_id,
      kind: "audit" as const,
      title: "数据审计记录",
      summary: `已记录 ${String(dataAuditDetails?.row_count ?? dataManifest?.row_count ?? "-")} 行、${String(dataAuditDetails?.column_count ?? auditColumns.length ?? "-")} 列的审计结果。`,
      status: "可复核",
      version: "当前审计",
      provenance: "数据与审计工作台",
      updatedAt: latestDataAudit.created_at,
      action: "打开审计记录",
    }] : []),
  ];

  useEffect(() => {
    if (!auth?.access_token) {
      setProjects(demoMode ? demoProjects : []);
      setProjectId(demoMode ? (demoProjects[0]?.project_id ?? demoProjectId) : "");
      setProjectsReady(true);
      return;
    }
    setProjectsReady(false);
    setProjects([]);
    let mounted = true;
    void authApi.listProjects(auth.access_token).then((next) => {
      if (!mounted) return;
      setProjects(next);
      if (next.length && !next.some((project) => project.project_id === projectId)) {
        setProjectId(next[0].project_id);
      } else if (!next.length) {
        setProjectId("");
      }
    }).catch(() => {
      if (mounted) {
        setProjects([]);
        setProjectId("");
        setProjectsReady(true);
      }
    }).finally(() => {
      if (mounted) setProjectsReady(true);
    });
    return () => {
      mounted = false;
    };
  }, [auth?.access_token]);

  useEffect(() => {
    let mounted = true;
    void api.listSharedCorpora().then((corpora) => {
      if (mounted) {
        const summary = corpora[0] ?? null;
        setCorpusSummary(summary);
        if (summary?.formal_evidence_ready) setMode("formal");
      }
    }).catch(() => {
      if (mounted) setCorpusSummary(null);
    });
    void api.getKnowledgeAssetSummary().then((summary) => {
      if (mounted) setKnowledgeAssetSummary(summary);
    }).catch(() => {
      if (mounted) setKnowledgeAssetSummary(null);
    });
    void api.getDiscoveryAssets().then((assets) => {
      if (mounted) setDiscoveryAssets(assets);
    }).catch(() => {
      if (mounted) setDiscoveryAssets(null);
    });
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    let mounted = true;
    setDocumentsBusy(true);
    setSelectedDocument(null);
    setSelectedCitation(null);
    setConversations([]);
    if (!projectId || !projectsReady) {
      setDocuments(demoMode && projectId
        ? demoDocumentsByProject[projectId] ?? demoDocumentsByProject[demoProjectId] ?? []
        : []);
      setDocumentsBusy(false);
      return () => {
        mounted = false;
      };
    }
    if (!auth?.access_token) {
      setDocuments(demoMode ? demoDocumentsByProject[projectId] ?? demoDocumentsByProject[demoProjectId] ?? [] : []);
      setConversations([]);
      setDocumentsBusy(false);
      return () => {
        mounted = false;
      };
    }

    void Promise.all([
      authApi.listDocuments(auth.access_token, projectId),
      authApi.listConversations(auth.access_token, projectId),
    ]).then(([nextDocuments, nextConversations]) => {
      if (!mounted) return;
      setDocuments(nextDocuments);
      setConversations(nextConversations);
    }).catch(() => {
      if (!mounted) return;
      setDocuments([]);
      setConversations([]);
    }).finally(() => {
      if (mounted) setDocumentsBusy(false);
    });

    return () => {
      mounted = false;
    };
  }, [auth?.access_token, projectId, projectsReady]);

  // Project conversations are scoped to the selected project. Clear the
  // in-memory thread when that scope changes, then let the restore effect
  // below load the newest persisted thread for the new project.
  useEffect(() => {
    if (!projectId) return;
    suppressConversationRestoreRef.current = false;
    setConversationId(undefined);
    setMessages([makeWelcome(activeProject?.title ?? "科研项目")]);
    setLastResponse(demoMode ? demoQAResponse : null);
    setSelectedTurnId(null);
    setConversationControl(null);
    setConversationGateError("");
  }, [projectId, auth?.access_token]);

  useEffect(() => {
    if (!auth?.access_token || !projectId || !projectsReady) {
      setProjectBlockers([]);
      setOrchestrationTasks([]);
      setResearchEvents([]);
      setOrchestrationHistory([]);
      return;
    }
    let mounted = true;
    let lastEvidenceRevision: number | null = null;
    const syncControlState = async () => {
      try {
        const latestState = await workflowApi.getControlState(projectId);
        if (!mounted) return;
        setOrchestrationState(latestState);
        void workflowApi.listProjectBlockers(projectId)
          .then((blockers) => {
            if (mounted) setProjectBlockers(blockers);
          })
          .catch(() => {
            if (mounted) setProjectBlockers([]);
          });
        void workflowApi.listOrchestrationTasks(projectId)
          .then((tasks) => {
            if (mounted) setOrchestrationTasks(tasks);
          })
          .catch(() => {
            if (mounted) setOrchestrationTasks([]);
          });
        // The orchestration journal is the durable, project-scoped record of
        // every workflow command.  Keep it separate from the ordinary QA
        // conversation index so a refresh still exposes the full research
        // dialogue, including Gate decisions and checkpoint replies.
        void workflowApi.getResearchHistory(projectId)
          .then((history) => {
            if (mounted) setOrchestrationHistory(Array.isArray(history) ? history : []);
          })
          .catch(() => {
            if (mounted) setOrchestrationHistory([]);
          });
        void workflowApi.listProjectClaims(projectId)
          .then((claims) => {
            if (mounted) setProjectClaims(claims);
          })
          .catch(() => {
            if (mounted) setProjectClaims([]);
          });
        if (lastEvidenceRevision !== latestState.state_revision) {
          lastEvidenceRevision = latestState.state_revision;
          void workflowApi.getEvidenceReviewPackage(projectId)
            .then((reviewPackage) => {
              if (!mounted) return;
              setEvidenceReviewPackage(reviewPackage);
              const activeStream = latestState.workstreams.find(
                (item) => item.workstream_id === latestState.active_workstream_id,
              );
              if (latestState.active_gate_id && activeStream?.current_action === "claim_evidence_support") {
                setContextTab("agent-work");
              }
              // A reload used to return to the generic knowledge-library tab,
              // which made an active research project appear to have no evidence
              // even when its review package had already been created.  Preserve
              // an explicit user tab choice, but make the generated evidence
              // package the initial right-side workspace for an active workflow.
              if (latestState.active_gate_id) {
                setContextTab((current) => current === "evidence" ? "agent-work" : current);
              }
            })
            .catch(() => {
              if (mounted) setEvidenceReviewPackage(null);
            });
        }
        void workflowApi.listArtifactContents(projectId)
          .then((items) => {
            if (mounted) setOrchestrationArtifacts(items as OrchestrationArtifactContent[]);
          })
          .catch(() => {
            if (mounted) setOrchestrationArtifacts([]);
          });
        // The control-state snapshot is intentionally compact.  Use the
        // authoritative Gate record whenever one is active, otherwise a
        // blocker-updated `current_action` can masquerade as a new Gate and
        // hide route-specific controls such as the raw-data upload button.
        let latestGate = buildGateFromState(latestState);
        if (latestState.active_gate_id) {
          try {
            latestGate = await workflowApi.getOrchestrationGate(projectId, latestState.active_gate_id);
          } catch {
            // Keep the compact-state fallback during a transient refresh.
          }
        }
        setConversationControl((current) => {
          if (!current) {
            return {
              kind: "orchestration",
              message: latestGate
                ? `研究进展：${gateActionLabel(latestGate)}`
                : "已恢复当前研究流程。",
              control_state: latestState,
              route_decision: latestState.route_decision,
              gate: latestGate,
              execution_started: false,
            };
          }
          if (current.control_state.state_revision >= latestState.state_revision) return current;
          return {
            ...current,
            control_state: latestState,
            route_decision: latestState.route_decision,
            gate: current.gate && latestState.active_gate_id === current.gate.gate_id
              ? current.gate
              : latestGate,
          };
        });
        // Restoring a page must restore durable state, not manufacture a
        // "research progress" chat turn. The latter made a normal chat look
        // like it was demanding a Gate decision immediately after refresh.
        setMessages((current) => {
          const orchestrationIndex = [...current].map((item, index) => ({ item, index }))
            .reverse().find(({ item }) => item.orchestration)?.index;
          if (orchestrationIndex === undefined) return current;
          return current.map((item, index) => index === orchestrationIndex && item.orchestration
            ? {
              ...item,
              orchestration: {
                ...item.orchestration,
                control_state: latestState,
                route_decision: latestState.route_decision,
                gate: latestGate,
                message: latestGate ? `研究进展：${gateActionLabel(latestGate)}` : item.orchestration.message,
              },
            }
            : item);
        });
      } catch {
        // A transient polling failure should not hide the current card.
      }
    };
    void syncControlState();
    const timer = window.setInterval(() => void syncControlState(), 1500);
    return () => { mounted = false; window.clearInterval(timer); };
  }, [auth?.access_token, projectId, projectsReady]);

  // Research dynamics use a resumable SSE stream.  The last event id is kept
  // in a ref so reconnects and tab refreshes do not replay the whole timeline.
  useEffect(() => {
    if (!auth?.access_token || !projectId || !projectsReady) {
      orchestrationEventCursorRef.current = undefined;
      return;
    }
    let mounted = true;
    const controller = new AbortController();
    const appendEvents = (incoming: OrchestrationEvent[]) => {
      if (!incoming.length) return;
      setResearchEvents((current) => {
        const merged = new Map(current.map((event) => [event.event_id, event]));
        for (const event of incoming) {
          merged.set(event.event_id, event);
          orchestrationEventCursorRef.current = event.event_id;
        }
        return [...merged.values()]
          .sort((left, right) => left.created_at.localeCompare(right.created_at))
          .slice(-200);
      });
    };
    const wait = (milliseconds: number) => new Promise<void>((resolve) => {
      window.setTimeout(resolve, milliseconds);
    });
    void (async () => {
      try {
        const initial = await workflowApi.listOrchestrationEvents(projectId);
        if (!mounted) return;
        appendEvents(initial);
        orchestrationEventCursorRef.current = initial.at(-1)?.event_id;
      } catch {
        // The stream below can still recover after a temporary API failure.
      }
      while (mounted) {
        try {
          await workflowApi.streamOrchestrationEvents(
            projectId,
            auth.access_token,
            orchestrationEventCursorRef.current,
            (event) => {
              if (mounted) appendEvents([event]);
            },
            controller.signal,
          );
        } catch {
          if (!mounted) break;
          try {
            const fallback = await workflowApi.listOrchestrationEvents(
              projectId,
              orchestrationEventCursorRef.current,
            );
            if (mounted) appendEvents(fallback);
          } catch {
            // Keep the last known dynamics visible while the API recovers.
          }
          await wait(3000);
        }
      }
    })();
    return () => {
      mounted = false;
      controller.abort();
    };
  }, [auth?.access_token, projectId, projectsReady]);

  // Recover projects left at the durable "waiting for next candidate" marker
  // by an older page instance. This is an internal continuation, so the user
  // should not need to find a separate Agent control or click a hidden button.
  useEffect(() => {
    if (!auth?.access_token || !projectsReady || !projectId || busy || !orchestrationState) return;
    if (orchestrationState.lifecycle_status !== "ACTIVE" || orchestrationState.active_gate_id || !orchestrationState.route_decision) return;
    const stream = orchestrationState.workstreams.find(
      (item) => item.workstream_id === orchestrationState.active_workstream_id,
    );
    if (!stream || stream.current_step_index >= stream.workflow_steps.length) return;
    const waitingForCandidate = stream.execution_status === "QUEUED"
      && (stream.current_action === null || /等待编排器|等待.*候选|生成下一步/.test(stream.current_action));
    if (!waitingForCandidate) return;
    const resumeKey = `${projectId}:${orchestrationState.state_revision}:${stream.current_step_index}`;
    if (autoContinuedWorkflowRef.current === resumeKey) return;
    autoContinuedWorkflowRef.current = resumeKey;
    let mounted = true;
    void (async () => {
      try {
        let continued = await workflowApi.continueOrchestration(projectId);
        for (let step = 0; step < 32 && !continued.gate && continued.execution_started; step += 1) {
          continued = await workflowApi.continueOrchestration(projectId);
        }
        if (!mounted) return;
        setOrchestrationState(continued.control_state);
        setConversationControl((current) => current ? {
          ...current,
          control_state: continued.control_state,
          route_decision: continued.control_state.route_decision,
          gate: continued.gate,
          message: continued.gate ? "本轮内部工作已完成。请查看右侧材料，并直接说明你的研究判断或修改要求。" : current.message,
        } : current);
        if (continued.gate?.gate_type === "evidence_sufficiency_review") {
          try {
            setEvidenceReviewPackage(await workflowApi.getEvidenceReviewPackage(projectId));
            setContextTab("agent-work");
            setRightPaneVisible(true);
          } catch {
            // The control state remains actionable if the optional package
            // refresh is temporarily unavailable.
          }
        }
      } catch {
        if (mounted) autoContinuedWorkflowRef.current = null;
      }
    })();
    return () => { mounted = false; };
  }, [auth?.access_token, busy, orchestrationState, projectId, projectsReady]);

  useEffect(() => {
    let mounted = true;
    setWorkflowError("");
    if (!auth?.access_token || !projectId || !projectsReady) {
      setWorkflow(null);
      setWorkflowState(null);
      return () => { mounted = false; };
    }
    setWorkflow(null);
    setWorkflowState(null);
    void workflowApi.getProject(projectId).then((next) => {
      if (mounted) {
        setWorkflow(next);
        setWorkflowState(next);
      }
    }).catch(() => {
      if (mounted) setWorkflow(null);
    });
    return () => { mounted = false; };
  }, [auth?.access_token, projectId]);

  useEffect(() => {
    let mounted = true;
    setAnalysisError("");
    if (!auth?.access_token || !projectId || !projectsReady) {
      setRuntimeStatus(demoRuntime);
      setWorkflowSnapshot(null);
      setAnalysisStage("INTAKE");
      setAnalysisState(null);
      return () => {
        mounted = false;
      };
    }
    void Promise.all([
      workflowApi.getRuntime(),
      workflowApi.getControllerProject(projectId),
    ]).then(([runtime, controllerState]) => {
      if (!mounted) return;
      setRuntimeStatus(runtime);
      setWorkflowSnapshot(controllerState);
      setAnalysisStage(controllerState.current_stage);
      setAnalysisState(controllerState.data_pipeline);
    }).catch((error) => {
      if (!mounted) return;
      setAnalysisError(error instanceof Error ? error.message : "无法读取数据分析状态");
    });
    return () => {
      mounted = false;
    };
  }, [auth?.access_token, projectId, projectsReady]);

  useEffect(() => {
    let mounted = true;
    if (!auth?.access_token || !projectId || !projectsReady) {
      setAgentOutputs([]);
      setPageMaterials([]);
      setFormalEvidence([]);
      setAgentPlans([]);
      setAgentPlan(null);
      return () => {
        mounted = false;
      };
    }
    void Promise.allSettled([
      workflowApi.listAgentOutputs(projectId),
      workflowApi.listAgentPageMaterials(projectId),
      workflowApi.listAgentPlans(projectId),
      workflowApi.listFormalEvidence(projectId),
    ]).then(([outputResult, materialResult, planResult, formalEvidenceResult]) => {
      if (!mounted) return;
      const plans = planResult.status === "fulfilled" ? planResult.value : [];
      const fallbackOutputs = plans.flatMap(outputSummariesFromPlan);
      const outputs = outputResult.status === "fulfilled" && outputResult.value.length
        ? outputResult.value
        : fallbackOutputs;
      const materials = materialResult.status === "fulfilled" ? materialResult.value : [];
      const formal = formalEvidenceResult.status === "fulfilled" ? formalEvidenceResult.value : [];
      setAgentOutputs(outputs);
      setPageMaterials(materials);
      setFormalEvidence(formal);
      setAgentPlans(plans);
      setAgentPlan((current) => current?.project_id === projectId ? current : plans[0] ?? null);
    });
    return () => {
      mounted = false;
    };
  }, [auth?.access_token, projectId, projectsReady]);

  useEffect(() => {
    if (!draggingPane) return;
    const onPointerMove = (event: PointerEvent) => {
      if (draggingPane === "sidebar") {
        setPaneWidths((current) => ({
          ...current,
          sidebar: Math.max(190, Math.min(360, event.clientX)),
        }));
      } else {
        const nextOutput = window.innerWidth - event.clientX;
        setPaneWidths((current) => ({
          ...current,
          output: Math.max(420, Math.min(820, nextOutput)),
        }));
      }
    };
    const onPointerUp = () => setDraggingPane(null);
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    document.body.classList.add("pane-resizing");
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      document.body.classList.remove("pane-resizing");
    };
  }, [draggingPane]);

  const selectChatFiles = (files: FileList | null) => {
    if (!files?.length) return;
    const nextAttachments: ChatAttachment[] = [];
    for (const file of Array.from(files)) {
      const lowerName = file.name.toLowerCase();
      const kind = lowerName.endsWith(".pdf")
        ? "PDF"
        : lowerName.endsWith(".doc") || lowerName.endsWith(".docx")
          ? "WORD"
          : lowerName.endsWith(".csv")
            ? "CSV"
          : file.type.startsWith("image/")
            ? "IMAGE"
            : null;
      if (!kind) {
        setAttachmentError("附件仅支持 PDF、Word、CSV 和图片");
        continue;
      }
      if (file.size > 20 * 1024 * 1024) {
        setAttachmentError("单个附件不能超过 20 MB");
        continue;
      }
      nextAttachments.push({
        id: `${file.name}-${file.lastModified}-${Math.random().toString(16).slice(2)}`,
        name: file.name,
        kind,
        file,
        sizeLabel: file.size >= 1024 * 1024
          ? `${(file.size / 1024 / 1024).toFixed(1)} MB`
          : `${Math.max(1, Math.round(file.size / 1024))} KB`,
      });
    }
    setChatAttachments((current) => [...current, ...nextAttachments].slice(0, 5));
    if (nextAttachments.length && nextAttachments.length + chatAttachments.length <= 5) {
      setAttachmentError("");
    }
    if (chatAttachmentInputRef.current) chatAttachmentInputRef.current.value = "";
  };

  const removeChatAttachment = (attachmentId: string) => {
    setChatAttachments((current) => current.filter((attachment) => attachment.id !== attachmentId));
    setAttachmentError("");
  };

  const refreshWorkflow = async () => {
    const next = await workflowApi.getProject(projectId);
    setWorkflow(next);
    return next;
  };

  const refreshProjectOutputs = async (focusLatest = false) => {
    if (!auth?.access_token || !projectId) return;
    const [
      controlResult,
      artifactResult,
      outputResult,
      materialResult,
      formalEvidenceResult,
      reviewPackageResult,
    ] = await Promise.allSettled([
      workflowApi.getControlState(projectId),
      workflowApi.listArtifactContents(projectId),
      workflowApi.listAgentOutputs(projectId),
      workflowApi.listAgentPageMaterials(projectId),
      workflowApi.listFormalEvidence(projectId),
      workflowApi.getEvidenceReviewPackage(projectId),
    ]);
    if (controlResult.status === "fulfilled") {
      setOrchestrationState(controlResult.value);
      setConversationControl((current) => current
        ? {
          ...current,
          control_state: controlResult.value,
          route_decision: controlResult.value.route_decision,
          gate: current.gate && controlResult.value.active_gate_id === current.gate.gate_id
            ? current.gate
            : buildGateFromState(controlResult.value),
        }
        : current);
    }
    const artifacts = artifactResult.status === "fulfilled"
      ? artifactResult.value as OrchestrationArtifactContent[]
      : null;
    if (artifacts) setOrchestrationArtifacts(artifacts);
    if (outputResult.status === "fulfilled") setAgentOutputs(outputResult.value);
    if (materialResult.status === "fulfilled") setPageMaterials(materialResult.value);
    if (formalEvidenceResult.status === "fulfilled") setFormalEvidence(formalEvidenceResult.value);
    if (reviewPackageResult.status === "fulfilled") setEvidenceReviewPackage(reviewPackageResult.value);

    if (!focusLatest || !artifacts?.length) return;
    const latest = [...artifacts].sort((left, right) =>
      new Date(right.created_at).getTime() - new Date(left.created_at).getTime()
    )[0];
    // Do not steal the researcher's current view because an ordinary chat
    // turn refreshed an older candidate. Only focus a candidate created by
    // the current request.
    if (Date.now() - new Date(latest.created_at).getTime() > 60_000) return;
    if (latest.artifact_type === "PhysicsCodeValidationCandidate"
      || latest.artifact_type === "AnalysisCodePlanCandidate"
      || latest.artifact_type === "CodeReviewCandidate"
      || latest.artifact_type === "ManualExecutionApprovalCandidate") {
      setSelectedOutputSection("code");
      setActiveOutputWorkbench("code-review");
      setRightPaneVisible(true);
    } else if (latest.artifact_type === "ManuscriptDraftZh"
      || latest.artifact_type === "ManuscriptOutline") {
      setSelectedOutputSection("paper");
      setActiveOutputWorkbench("paper-review");
      setRightPaneVisible(true);
    } else if (latest.artifact_type === "EvidenceReviewPackage"
      || latest.artifact_type === "EvidenceMatrixCandidate"
      || latest.artifact_type === "BoundedEvidenceSynthesis"
      || latest.artifact_type === "ResearchGapReport") {
      setSelectedOutputSection("evidence");
      setActiveOutputWorkbench("evidence-review");
      setRightPaneVisible(true);
    } else if (latest.artifact_type === "ResearchQuestionTree"
      || latest.artifact_type === "StudyProtocolCandidate") {
      setSelectedOutputSection("questions");
      setActiveOutputWorkbench("research-design");
      setRightPaneVisible(true);
    }
  };

  const searchProjectEvidence = async () => {
    if (!projectId || !activeProject) return;
    setEvidenceBusy(true);
    setEvidenceError("");
    try {
      const query = activeProject.research_direction || activeProject.title;
      setEvidenceRows(await api.search(projectId, query));
    } catch (error) {
      setEvidenceError(error instanceof Error ? error.message : "无法读取项目证据");
    } finally {
      setEvidenceBusy(false);
    }
  };

  const uploadEvidenceSource = async (file: File) => {
    setEvidenceBusy(true);
    setEvidenceError("");
    try {
      if (auth?.access_token) {
        const document = await authApi.uploadDocument(auth.access_token, projectId, file);
        setDocuments((current) => [
          document,
          ...current.filter((item) => item.document_id !== document.document_id),
        ]);
      } else {
        await api.importSource(projectId, file);
      }
      await searchProjectEvidence();
      if (auth?.access_token) {
        const [reviewPackage, formal] = await Promise.all([
          workflowApi.getEvidenceReviewPackage(projectId).catch(() => null),
          workflowApi.listFormalEvidence(projectId).catch(() => null),
        ]);
        setEvidenceReviewPackage(reviewPackage);
        if (formal) setFormalEvidence(formal);
      }
    } catch (error) {
      setEvidenceError(error instanceof Error ? error.message : "证据来源上传失败");
    } finally {
      setEvidenceBusy(false);
      if (evidenceInputRef.current) evidenceInputRef.current.value = "";
    }
  };

  const findEvidenceForCitation = (rows: SearchResult[], citation: SelectedCitation) => {
    const excerpt = citation.excerpt.trim();
    const matchesExcerpt = (item: SearchResult) => {
      const candidate = item.evidence.excerpt.trim();
      return candidate === excerpt
        || (candidate.length >= 40 && excerpt.includes(candidate))
        || (excerpt.length >= 40 && candidate.includes(excerpt));
    };
    return rows.find((item) => item.evidence.chunk_id === citation.canonical_chunk_id)
      ?? rows.find(matchesExcerpt)
      ?? null;
  };

  const resolveEvidenceForCitation = async (citation: SelectedCitation) => {
    const existing = findEvidenceForCitation(evidenceRows, citation);
    if (existing) return existing.evidence;
    const searched = await api.search(projectId, citation.excerpt);
    const match = findEvidenceForCitation(searched, citation);
    if (searched.length > 0) {
      setEvidenceRows((current) => {
        const merged = new Map(current.map((item) => [item.evidence.evidence_id, item]));
        searched.forEach((item) => merged.set(item.evidence.evidence_id, item));
        return [...merged.values()];
      });
    }
    return match?.evidence ?? null;
  };

  const verifyProjectEvidence = async (evidenceId: string): Promise<boolean> => {
    setEvidenceBusy(true);
    setEvidenceError("");
    try {
      await api.verifySource(
        projectId,
        evidenceId,
        auth?.user.username ?? "researcher",
        "已人工核对上传来源与对应原文片段。",
      );
      if (auth?.access_token) {
        await workflowApi.promoteVerifiedEvidence(projectId, evidenceId);
        const [reviewPackage, formal] = await Promise.all([
          workflowApi.getEvidenceReviewPackage(projectId),
          workflowApi.listFormalEvidence(projectId),
        ]);
        setEvidenceReviewPackage(reviewPackage);
        setFormalEvidence(formal);
      }
      await searchProjectEvidence();
      return true;
    } catch (error) {
      setEvidenceError(error instanceof Error ? error.message : "证据核验失败");
      return false;
    } finally {
      setEvidenceBusy(false);
    }
  };

  const verifySelectedCitation = async () => {
    if (!selectedCitation) return;
    setCitationActionBusy(true);
    setCitationActionError("");
    try {
      const evidence = await resolveEvidenceForCitation(selectedCitation);
      if (!evidence) {
        setCitationActionError("当前回答引用还没有绑定到项目证据，无法提交核验。请先在证据审阅区刷新或上传对应来源。");
        return;
      }
      const alreadyFormal = formalEvidence.some((record) => record.evidence_id === evidence.evidence_id);
      if (!alreadyFormal) {
        const verified = await verifyProjectEvidence(evidence.evidence_id);
        if (!verified) {
          setCitationActionError("证据核验失败，请检查来源文件和定位信息后重试。");
          return;
        }
      }
      setSelectedCitation(null);
    } catch (error) {
      setCitationActionError(error instanceof Error ? error.message : "无法定位当前回答对应的项目证据");
    } finally {
      setCitationActionBusy(false);
    }
  };

  const openCitationDetails = (citation: SelectedCitation) => {
    setCitationActionError("");
    setSelectedCitation(citation);
  };

  const closeCitationDetails = () => {
    setCitationActionError("");
    setSelectedCitation(null);
  };

  const uploadRawCsv = async (file: File) => {
    setWorkflowBusy(true);
    setWorkflowError("");
    try {
      await workflowApi.uploadRawCsv(projectId, file);
      await refreshWorkflow();
    } catch (error) {
      setWorkflowError(error instanceof Error ? error.message : "CSV 上传或审查失败");
    } finally {
      setWorkflowBusy(false);
      if (rawCsvInputRef.current) rawCsvInputRef.current.value = "";
    }
  };

  const decideDataPipeline = async (decision: "approved" | "rejected") => {
    setWorkflowBusy(true);
    setWorkflowError("");
    try {
      await workflowApi.decideDataPipeline(
        projectId,
        decision,
        auth?.user.username ?? "researcher",
      );
      await refreshWorkflow();
    } catch (error) {
      setWorkflowError(error instanceof Error ? error.message : "数据 Gate 审批失败");
    } finally {
      setWorkflowBusy(false);
    }
  };

  const openAgentPlanner = (draft?: string) => {
    setRightPaneVisible(true);
    setContextTab("agent-work");
    setAgentPlanPanelOpen(true);
    setAgentPlanError("");
    if (!agentPlan && agentPlans[0]) {
      setAgentPlan(agentPlans[0]);
      setSelectedAgentTaskIds(agentPlans[0].approved_task_ids);
    }
    setAgentPlanDraft(
      draft?.trim()
      ||
      question.trim()
      || activeResponse?.question
      || "请根据当前研究问题判断需要调用哪些 Agent。",
    );
  };

  const createAgentPlan = async (requestOverride?: string): Promise<AgentExecutionPlan | null> => {
    const request = (requestOverride ?? agentPlanDraft).trim();
    if (!request || !projectId || agentPlanBusy) return null;
    if (!auth?.access_token && !demoMode) {
      setAgentPlanError("请先登录后再调用 Agent");
      return null;
    }
    setAgentPlanBusy(true);
    setAgentPlanError("");
    try {
      const next = await workflowApi.createAgentPlan({
        project_id: projectId,
        user_request: request,
        conversation_id: conversationId,
        turn_id: activeResponse?.turn_id ?? selectedTurnId ?? undefined,
        context_refs: activeResponse?.context_bundle_ref ? [activeResponse.context_bundle_ref] : [],
        conversation_context: messages
          .filter((message) => message.id !== "welcome")
          .slice(-5)
          .map((message) => `${message.role === "user" ? "研究者" : "助手"}：${message.content}`),
      });
      setAgentPlan(next);
      setAgentPlans((current) => [next, ...current.filter((item) => item.plan_id !== next.plan_id)]);
      setSelectedAgentTaskIds(
        next.tasks
          .filter((task) => task.blocked_reason === null && task.status !== "SKIPPED")
          .map((task) => task.task_id),
      );
      setAgentOutputs([]);
      setAgentExecutionMode("automatic");
      return next;
    } catch (error) {
      setAgentPlanError(error instanceof Error ? error.message : "Agent 计划生成失败");
      return null;
    } finally {
      setAgentPlanBusy(false);
    }
  };

  const toggleAgentTask = (taskId: string) => {
    setSelectedAgentTaskIds((current) => current.includes(taskId)
      ? current.filter((item) => item !== taskId)
      : [...current, taskId]);
  };

  const approveAndExecuteAgentPlan = async () => {
    if (!agentPlan || agentPlan.status !== "PENDING_APPROVAL" || agentPlanBusy) return;
    setAgentPlanBusy(true);
    setAgentPlanError("");
    try {
      const decidedBy = auth?.user.username ?? "researcher";
      const approved = await workflowApi.approveAgentPlan(
        projectId,
        agentPlan.plan_id,
        "approved",
        decidedBy,
        selectedAgentTaskIds,
        agentExecutionMode,
      );
      setAgentPlan(approved);
      setAgentPlans((current) => current.map((item) => item.plan_id === approved.plan_id ? approved : item));
      const executed = await workflowApi.executeAgentPlan(projectId, approved.plan_id);
      setAgentPlan(executed);
      setAgentPlans((current) => current.map((item) => item.plan_id === executed.plan_id ? executed : item));
      const fallbackOutputs = outputSummariesFromPlan(executed);
      setAgentOutputs(fallbackOutputs);
      setAgentOutputScope("question");
      try {
        const outputs = await workflowApi.listPlanOutputs(projectId, executed.plan_id);
        if (outputs.length) setAgentOutputs(outputs);
      } catch {
        setAgentPlanError("计划已经执行；产出预览暂时无法读取，请在任务状态中查看已生成的候选产物。");
      }
      setContextTab("agent-work");
    } catch (error) {
      setAgentPlanError(error instanceof Error ? error.message : "Agent 执行失败");
    } finally {
      setAgentPlanBusy(false);
    }
  };

  const continueStepwiseAgentPlan = async (decision: "approved" | "rework") => {
    if (!agentPlan || agentPlan.status !== "WAITING_TASK_APPROVAL" || agentPlanBusy) return;
    const task = agentPlan.tasks.find((item) => item.task_id === agentPlan.pending_review_task_id);
    const note = decision === "rework"
      ? window.prompt("说明需要修改的地方。系统会带着本轮上下文回到对话中。")?.trim()
      : undefined;
    if (decision === "rework" && note === undefined) return;
    setAgentPlanBusy(true);
    setAgentPlanError("");
    try {
      const updated = await workflowApi.continueAgentPlan(
        projectId,
        agentPlan.plan_id,
        decision,
        auth?.user.username ?? "researcher",
        note || undefined,
      );
      setAgentPlan(updated);
      setAgentPlans((current) => current.map((item) => item.plan_id === updated.plan_id ? updated : item));
      const outputs = await workflowApi.listPlanOutputs(projectId, updated.plan_id);
      setAgentOutputs(outputs);
      if (decision === "rework") {
        const agentName = task ? (agentDisplayNames[task.agent_id] ?? task.agent_id) : "当前 Agent";
        const outputRefs = task?.persisted_artifact_ids.join("、") || "当前候选产出";
        setQuestion(`请根据本轮研究需求修改 ${agentName} 的候选方案。\n原需求：${agentPlan.user_request}\n待修改产出：${outputRefs}\n修改意见：${note || "请重新审查并调整。"}`);
        setAgentPlanDraft(`基于以下研究需求与修改意见，重新生成 Agent 计划：\n${agentPlan.user_request}\n\n当前步骤：${agentName}\n修改意见：${note || "请重新审查并调整。"}`);
      }
    } catch (error) {
      setAgentPlanError(error instanceof Error ? error.message : "Agent 步骤确认失败");
    } finally {
      setAgentPlanBusy(false);
    }
  };

  const rejectAgentPlan = async () => {
    if (!agentPlan || agentPlan.status !== "PENDING_APPROVAL" || agentPlanBusy) return;
    setAgentPlanBusy(true);
    setAgentPlanError("");
    try {
      const rejected = await workflowApi.approveAgentPlan(
        projectId,
        agentPlan.plan_id,
        "rejected",
        auth?.user.username ?? "researcher",
      );
      setAgentPlan(rejected);
      setAgentPlans((current) => current.map((item) => item.plan_id === rejected.plan_id ? rejected : item));
    } catch (error) {
      setAgentPlanError(error instanceof Error ? error.message : "Agent 计划未能拒绝");
    } finally {
      setAgentPlanBusy(false);
    }
  };

  const decideAgentOutput = async (
    output: AgentOutputSummary,
    decision: "retain" | "reject" | "apply" | "promote",
    artifactIdsOverride?: string[],
  ) => {
    if (!output.artifact_ids.length || agentPlanBusy) return;
    const promotableTypes = new Set([
      "PaperCardCollection",
      "EvidenceMatrixCandidate",
      "BoundedEvidenceSynthesis",
    ]);
    const artifactIds = artifactIdsOverride?.length
      ? artifactIdsOverride
      : decision === "promote"
      ? output.output_previews
        .filter((preview) => promotableTypes.has(preview.artifact_type))
        .map((preview) => preview.artifact_id)
      : decision === "apply"
        ? (() => {
          const primary = primaryPreviewForAgent(output);
          return primary ? [primary.artifact_id] : output.artifact_ids.slice(0, 1);
        })()
      : output.artifact_ids;
    if (!artifactIds.length) {
      setAgentPlanError("当前产出不包含可正式化的来源绑定证据，请先生成并核验论文卡或证据矩阵。");
      return;
    }
    setAgentPlanBusy(true);
    setAgentPlanError("");
    try {
      let promotionBlockedReason = "";
      for (const artifactId of artifactIds) {
        const result = await workflowApi.decideAgentOutput(
          projectId,
          artifactId,
          decision,
          auth?.user.username ?? "researcher",
          agentOutputTargets[output.task_id] ?? output.target_pages[0],
        );
        if (decision === "promote" && result.formalization === "candidate_evidence_only") {
          const risks = Array.isArray(result.risk_flags)
            ? result.risk_flags.filter((item): item is string => typeof item === "string")
            : [];
          promotionBlockedReason = risks[0] ?? "FORMAL_EVIDENCE_REQUIRES_SOURCE_VERIFICATION";
        }
      }
      setAgentOutputDecisions((current) => ({ ...current, [output.task_id]: decision }));
      const [outputs, materials, formal] = await Promise.all([
        workflowApi.listAgentOutputs(projectId),
        workflowApi.listAgentPageMaterials(projectId),
        workflowApi.listFormalEvidence(projectId),
      ]);
      setAgentOutputs(outputs);
      setPageMaterials(materials);
      setFormalEvidence(formal);
      if (promotionBlockedReason) {
        setAgentPlanError(`提升被拦截：${promotionBlockedReason}。请先上传来源、完成定位并核验证据。`);
      } else if (decision === "promote") {
        setAgentPlanError("已提升为正式证据，并已按证据标识写入正式证据库。");
      }
      if (decision === "apply") {
        setRightPaneVisible(true);
        const targetView = agentOutputTargetView(output);
        setView(targetView);
        setContextTab(targetView === "knowledge" ? "evidence" : "workspace");
      }
    } catch (error) {
      setAgentPlanError(error instanceof Error ? error.message : "Agent 产出处理失败");
    } finally {
      setAgentPlanBusy(false);
    }
  };

  const applyManuscriptCandidate = async (output: AgentOutputSummary) => {
    if (agentPlanBusy) return;
    setManuscriptApplyError("");
    const manuscriptPreview = output.output_previews.find(
      (preview) => preview.artifact_type === "ManuscriptDraftZh",
    ) ?? output.output_previews.find(
      (preview) => preview.artifact_type === "ManuscriptOutline",
    );
    if (!manuscriptPreview) {
      setAgentPlanError("本轮论文写作尚未生成可送入论文草稿的候选内容。");
      return;
    }
    setAgentPlanBusy(true);
    setAgentPlanError("");
    try {
      const applied = await workflowApi.applyAgentManuscript(projectId, manuscriptPreview.artifact_id);
      if (auth?.access_token) {
        const nextDocuments = await authApi.listDocuments(auth.access_token, projectId);
        setDocuments(nextDocuments);
        const createdDocument = nextDocuments.find((document) => document.document_id === applied.document_id);
        if (createdDocument) await openDocument(createdDocument);
      }
      setAgentOutputDecisions((current) => ({ ...current, [output.task_id]: "applied" }));
      openDedicatedWorkbench("paper", "paper-review");
    } catch (error) {
      const message = error instanceof Error ? error.message : "论文草稿写入失败";
      setAgentPlanError(message);
      setManuscriptApplyError(message);
    } finally {
      setAgentPlanBusy(false);
    }
  };

  const agentOutputTargetView = (output: AgentOutputSummary): WorkspaceView => {
    if (output.agent_id === "evidence_review" || output.target_pages.some((page) => page.includes("evidence"))) {
      return "knowledge";
    }
    if (output.agent_id === "data_analysis" || output.target_pages.some((page) => page.includes("analysis") || page.includes("codex"))) {
      return "analysis";
    }
    if (output.agent_id === "independent_review" || output.target_pages.some((page) => page.includes("audit") || page.includes("validation"))) {
      return "audit";
    }
    return "codex";
  };

  const targetPageLabels: Record<string, string> = {
    workspace: "工作区",
    research_questions: "研究问题",
    knowledge_evidence: "知识库证据",
    evidence_gate: "证据核验",
    research_design: "研究设计",
    data_collection: "数据采集",
    data_analysis: "数据分析",
    codex: "Codex",
    paper_editor: "论文草稿",
    audit_validation: "审查工作区",
  };

  const targetPageLabel = (target: string) => targetPageLabels[target] ?? target;

  const outputDecision = (output: AgentOutputSummary) => (
    agentOutputDecisions[output.task_id] ?? output.decision
  );

  const activeTurnOutputs = agentOutputs.filter((output) => (
    (!conversationId || output.conversation_id === conversationId)
    && (!activeResponse?.turn_id || output.turn_id === activeResponse.turn_id)
  ));

  const selectedQuestionOutputs = agentPlan
    ? agentOutputs.filter((output) => output.plan_id === agentPlan.plan_id)
    : [];

  const visibleAgentOutputs = agentOutputScope === "project"
    ? agentOutputs
    : agentOutputScope === "question"
      ? selectedQuestionOutputs
      : activeTurnOutputs;

  const manuscriptCandidates = agentOutputs.filter((output) => (
    output.agent_id === "paper_writing"
    && output.output_previews.some((preview) => ["ManuscriptDraftZh", "ManuscriptOutline"].includes(preview.artifact_type))
  ));

  const evidenceGateOutputs = (agentPlan
    ? agentOutputs.filter((output) => output.plan_id === agentPlan.plan_id)
    : activeTurnOutputs
  ).filter((output) => output.agent_id === "evidence_review");

  const pageMaterialsFor = (targets: string[]) => pageMaterials.filter((material) => (
    targets.includes(material.target)
    // Professional pages follow the selected Agent question. This prevents
    // an applied result from an earlier round appearing beside the current one.
    && (!agentPlan || material.plan_id === agentPlan.plan_id)
  ));

  const allPageMaterialsFor = (targets: string[]) => pageMaterials.filter((material) => (
    targets.includes(material.target)
  ));

  const codeTextForArtifact = (artifact: OrchestrationArtifactContent) => {
    const body = artifact.body;
    for (const key of ["source_code", "code", "python_code", "generated_code", "script"]) {
      const value = asText(body[key]);
      if (value) return value;
    }
    const nested = [asRecord(body.code), asRecord(body.execution), asRecord(body.result)];
    for (const item of nested) {
      if (!item) continue;
      for (const key of ["source_code", "code", "python_code", "generated_code", "script"]) {
        const value = asText(item[key]);
        if (value) return value;
      }
    }
    return "";
  };

  const latestCodeSpecification = [...codeWorkbenchArtifacts]
    .reverse()
    .find((artifact) => artifact.artifact_type === "CodeSpecificationDraft" && codeTextForArtifact(artifact));

  useEffect(() => {
    if (!latestCodeSpecification) return;
    setPhysicsSource(codeTextForArtifact(latestCodeSpecification));
  }, [latestCodeSpecification]);

  const readableArtifactFields = (artifact: OrchestrationArtifactContent) => {
    const entries = Object.entries(artifact.body)
      .filter(([key, value]) => key !== "source_code" && key !== "code" && key !== "python_code" && key !== "generated_code" && key !== "script")
      .map(([key, value]) => [key, previewValueText(value)] as const)
      .filter(([, value]) => value !== "暂无内容");
    return entries.slice(0, 8);
  };

  const selectAgentQuestion = (plan: AgentExecutionPlan) => {
    setAgentPlan(plan);
    setSelectedAgentTaskIds(
      plan.approved_task_ids.length
        ? plan.approved_task_ids
        : plan.tasks
          .filter((task) => task.blocked_reason === null && task.status !== "SKIPPED")
          .map((task) => task.task_id),
    );
    setAgentOutputScope("question");
  };

  const previewValueText = (value: unknown): string => {
    if (typeof value === "string") return value;
    if (typeof value === "number" || typeof value === "boolean") return String(value);
    if (Array.isArray(value)) {
      return value.slice(0, 3).map(previewValueText).join("；") + (value.length > 3 ? "……" : "");
    }
    if (value && typeof value === "object") {
      return Object.entries(value as Record<string, unknown>)
        .slice(0, 3)
        .map(([key, item]) => `${key}：${previewValueText(item)}`)
        .join("；");
    }
    return "暂无内容";
  };

  const primaryPreviewForAgent = (output: AgentOutputSummary) => {
    if (output.primary_artifact_id) {
      const persisted = output.output_previews.find(
        (preview) => preview.artifact_id === output.primary_artifact_id,
      );
      if (persisted) return persisted;
    }
    const preferredTypes: Record<string, string[]> = {
      mentor_planning: ["ResearchQuestionTree", "FeasibilityReport"],
      evidence_review: ["EvidenceMatrixCandidate", "BoundedEvidenceSynthesis", "PaperCardCollection"],
      research_design: ["StudyProtocolCandidate", "MeasurementPlan"],
      data_analysis: ["DataProcessingPlanCandidate", "ExecutableAnalysisPlanCandidate"],
      paper_writing: ["ManuscriptDraftZh", "ManuscriptOutline"],
      independent_review: ["ReviewReport", "ReproducibilityReviewReport"],
    };
    const preferred = preferredTypes[output.agent_id] ?? [];
    return preferred
      .map((artifactType) => output.output_previews.find((preview) => preview.artifact_type === artifactType))
      .find((preview): preview is AgentOutputSummary["output_previews"][number] => Boolean(preview))
      ?? output.output_previews[0];
  };

  const outputPreviewText = (output: AgentOutputSummary) => {
    const preview = primaryPreviewForAgent(output);
    if (!preview) return output.output_types.join("、") || "候选输出引用已记录";
    const body = preview.content;
    const candidates = [
      body.title,
      body.research_question,
      body.primary_question,
      body.design_question,
      body.primary_outcome,
      body.sufficiency_judgement,
      body.corpus_coverage,
      body.summary,
      body.overall_recommendation,
      body.output_boundary,
      body.recommendation,
      body.status,
      Array.isArray(body.recommendations) ? body.recommendations[0] : null,
      Array.isArray(body.unresolved_questions) ? body.unresolved_questions[0] : null,
    ].filter((item): item is string => typeof item === "string" && item.trim().length > 0);
    return candidates[0] ?? preview.artifact_type;
  };

  const artifactPreviewSummary = (preview: AgentOutputSummary["output_previews"][number]) => {
    const body = preview.content;
    const sections = asRecord(body.sections);
    if (sections) {
      const order = ["title", "abstract", "introduction", "research_questions", "methods", "results", "discussion", "ethics_limitations"];
      const text = order
        .map((key) => asText(sections[key]))
        .filter((item): item is string => Boolean(item))
        .join("\n\n");
      if (text) return cleanResearchPresentation(text);
    }
    return cleanResearchPresentation(
      preview.researcher_summary
      || asText(body.summary)
      || asText(body.title)
      || "研究产物已生成，技术字段已移至审计详情。",
    );
  };

  const riskFlagText = (flag: string) => ({
    FORMAL_EVIDENCE_REQUIRES_SOURCE_VERIFICATION: "正式证据仍需完成来源核验和定位。",
    MANUSCRIPT_OUTPUT_REMAINS_CANDIDATE: "论文输出仍是候选草稿，需人工审查后使用。",
    PLANNER_MODEL_FALLBACK: "本次计划使用受控规则生成，未使用模型规划。",
    OUTPUT_CAPABILITY_NOT_GRANTED: "本轮仅生成计划指定的候选材料。",
  }[flag] ?? flag);

  const canPromoteEvidence = (output: AgentOutputSummary) => {
    const promotable = new Set([
      "PaperCardCollection",
      "EvidenceMatrixCandidate",
      "BoundedEvidenceSynthesis",
    ]);
    return output.agent_id === "evidence_review" && (
      output.output_types.some((type) => promotable.has(type))
      || output.output_previews.some((preview) => promotable.has(preview.artifact_type))
    );
  };

  const renderAgentOutputCard = (output: AgentOutputSummary, compact = false) => {
    const decision = outputDecision(output);
    const primaryPreview = primaryPreviewForAgent(output);
    const visibleRiskFlags = output.risk_flags.filter((flag) => flag !== "OUTPUT_CAPABILITY_NOT_GRANTED");
    return (
      <article className={compact ? "agent-output-card agent-output-card-compact" : "agent-output-card"} key={output.task_id}>
        <div className="agent-output-card-topline">
          <strong>{agentDisplayNames[output.agent_id] ?? output.agent_id}</strong>
          <span className="status-badge status-muted">{agentOutputDecisionLabels[decision] ?? decision}</span>
        </div>
        <small>
          已生成 {output.output_previews.length || output.output_types.length} 项候选材料 · 可接入：
          {output.target_pages.map(targetPageLabel).join("、") || "项目产出箱"}
        </small>
        {output.agent_run_id && <small className="agent-execution-record">已执行 · {output.agent_version || output.agent_run_id}</small>}
        {output.error && (
          <div className="agent-output-failure" role="alert">
            <strong>执行失败</strong>
            <span>{output.error}</span>
            <small>本次没有生成可审查产物。修复后请重新生成一轮 Agent 计划。</small>
          </div>
        )}
        {primaryPreview && (
          <div className="agent-output-readable-preview">
            <strong>直接回答{output.summary_mode === "llm" ? " · 模型整理" : " · 规则整理"}</strong>
            <p>{output.researcher_answer || primaryPreview.researcher_summary || outputPreviewText(output)}</p>
            {!compact && primaryPreview.review_points?.length ? (
              <div className="agent-output-brief-list">
                <span>建议审查</span>
                <ul>{primaryPreview.review_points.map((point) => <li key={point}>{point}</li>)}</ul>
              </div>
            ) : null}
            {!compact && primaryPreview.action_items?.length ? (
              <div className="agent-output-brief-list">
                <span>下一步</span>
                <ul>{primaryPreview.action_items.map((item) => <li key={item}>{item}</li>)}</ul>
              </div>
            ) : null}
          </div>
        )}
        {!compact && (
          <dl className="agent-output-metadata">
            <div><dt>输入</dt><dd>{output.input_refs.join("、") || "当前对话上下文"}</dd></div>
            <div><dt>依赖</dt><dd>{output.depends_on.map((item) => item.replace("agent:", "")).join("、") || "无"}</dd></div>
            <div><dt>风险</dt><dd>{output.risk_level}</dd></div>
          </dl>
        )}
        {visibleRiskFlags.map((flag) => <span className="agent-output-risk" key={flag}>{riskFlagText(flag)}</span>)}
        {!compact && output.output_previews.length > 0 && (
          <details className="agent-output-preview">
            <summary>查看研究产物摘要（{output.output_previews.length} 项）</summary>
            {output.output_previews.map((preview) => (
              <article className="agent-output-readable-artifact" key={preview.artifact_id}>
                <div className="agent-output-card-topline">
                  <strong>{preview.artifact_type}</strong>
                  <span className="status-badge status-muted">{preview.status}</span>
                </div>
                <p>{artifactPreviewSummary(preview)}</p>
                <TechnicalTrace title="技术详情（含内部审计标识）">
                  <pre>{JSON.stringify(preview.content, null, 2)}</pre>
                </TechnicalTrace>
              </article>
            ))}
          </details>
        )}
        {!compact && output.target_pages.length > 0 && (
          <label className="agent-output-target">
            <span>应用位置</span>
            <select
              value={agentOutputTargets[output.task_id] ?? output.target_pages[0]}
              onChange={(event) => setAgentOutputTargets((current) => ({
                ...current,
                [output.task_id]: event.target.value,
              }))}
            >
              {output.target_pages.map((target) => <option key={target} value={target}>{targetPageLabel(target)}</option>)}
            </select>
          </label>
        )}
        <div className="agent-output-actions">
          <button type="button" disabled={agentPlanBusy || !output.artifact_ids.length} onClick={() => void decideAgentOutput(output, "retain")}>保留</button>
          {output.agent_id === "paper_writing" ? (
            <button type="button" disabled={agentPlanBusy || !output.artifact_ids.length} onClick={() => void applyManuscriptCandidate(output)}>送入论文草稿</button>
          ) : (
            <button type="button" disabled={agentPlanBusy || !output.artifact_ids.length} onClick={() => void decideAgentOutput(output, "apply")}>应用主产物</button>
          )}
          {output.agent_id === "evidence_review" && (
            <>
            <button type="button" disabled={agentPlanBusy || !output.artifact_ids.length} onClick={() => {
              openOutputWorkspace("evidence", "evidence-review");
            }}>查看证据审核</button>
            <button type="button" disabled={agentPlanBusy} onClick={() => {
              openKnowledgeLibrary();
            }}>打开知识库核验</button>
            </>
          )}
          {canPromoteEvidence(output) && (
            <button type="button" disabled={agentPlanBusy || !output.artifact_ids.length} onClick={() => void decideAgentOutput(output, "promote")}>申请正式证据</button>
          )}
          <button type="button" disabled={agentPlanBusy || !output.artifact_ids.length} onClick={() => void decideAgentOutput(output, "reject")}>拒绝</button>
        </div>
      </article>
    );
  };

  const renderPageMaterials = (title: string, targets: string[], includeAll = false) => {
    const materials = includeAll ? allPageMaterialsFor(targets) : pageMaterialsFor(targets);
    return (
      <section className="output-section applied-material-section">
        <div className="output-section-heading">
          <div><h3>{title}</h3><p className="section-subtitle">仅显示研究者已应用或已提升的项目材料。</p></div>
          <span>{materials.length} 项</span>
        </div>
        {materials.length ? (
          <div className="applied-material-list">
            {materials.map((material) => (
              <article className="applied-material-card" key={material.material_id}>
                <div><strong>项目研究产出</strong><span className={material.formalization === "formal_evidence" ? "verified-tag" : "review-tag"}>{material.formalization === "formal_evidence" ? "正式证据" : "已应用"}</span></div>
                <small>{material.artifact_type} · {material.turn_id ? `轮次 ${material.turn_id}` : "项目材料"}</small>
                <p>
                  {typeof material.content.researcher_summary === "object" && material.content.researcher_summary !== null && typeof (material.content.researcher_summary as Record<string, unknown>).summary === "string"
                    ? String((material.content.researcher_summary as Record<string, unknown>).summary)
                    : typeof material.content.researcher_summary === "string"
                      ? material.content.researcher_summary
                    : typeof material.content.title === "string"
                      ? material.content.title
                      : Object.keys(material.content).slice(0, 4).join("、") || "候选内容已写入项目材料"}
                </p>
              </article>
            ))}
          </div>
        ) : <div className="empty-output"><span className="empty-symbol">□</span><p>在产出箱选择“应用到页面”后，候选材料会出现在这里。</p></div>}
      </section>
    );
  };

  const renderFormalEvidence = () => (
    <section className="output-section formal-evidence-section">
      <div className="output-section-heading">
        <div>
          <h3>正式证据库</h3>
          <p className="section-subtitle">按稳定证据标识去重汇总；每条保留来自哪个问题和研究产出的来源链。</p>
        </div>
        <span>{formalEvidence.length} 条</span>
      </div>
      {formalEvidence.length ? (
        <div className="formal-evidence-list">
          {formalEvidence.map((record) => {
            const ref = record.evidence_ref;
            const location = ref.location && typeof ref.location === "object"
              ? ref.location as Record<string, unknown>
              : null;
            const excerpt = typeof ref.excerpt === "string" ? ref.excerpt : "已核验证据片段";
            return (
              <article className="formal-evidence-card" key={record.evidence_id}>
                <div><strong>{record.evidence_id}</strong><span className="verified-tag">正式证据</span></div>
                <p>{excerpt}</p>
                <small>Chunk {String(ref.chunk_id ?? "-")} · 字符 {String(location?.char_start ?? "-")}-{String(location?.char_end ?? "-")}</small>
                <small>首次关联问题：{record.provenance[0]?.turn_id ? `轮次 ${String(record.provenance[0].turn_id)}` : "未绑定轮次"} · 已在 {record.provenance.length} 次研究产出中使用</small>
              </article>
            );
          })}
        </div>
      ) : <div className="empty-output"><span className="empty-symbol">◇</span><p>已核验的证据类产物提升成功后，会在这里按证据标识汇总。</p></div>}
    </section>
  );

  const renderKnowledgeAssetLibrary = () => {
    const groups: Array<{ kind: KnowledgeAssetKind; title: string; description: string }> = [
      { kind: "source", title: "原始来源", description: "用户上传的论文、数据和研究资料，作为项目长期检索入口。" },
      { kind: "candidate", title: "候选论文", description: "对话生成并保留的论文候选，进入正式文档前仍可继续编辑和退回。" },
      { kind: "manuscript", title: "审核后论文", description: "已经写入项目文档的可编辑论文版本，保留版本链和修改记录。" },
      { kind: "evidence", title: "证据包与正式证据", description: "候选证据包、来源定位结果和经过人工核验的正式证据。" },
      { kind: "claim", title: "主张与绑定", description: "论文中的研究主张，以及它关联的证据、结果和产物。" },
      { kind: "audit", title: "数据与审计", description: "数据质量、字段检查和分析前审计记录。" },
    ];
    return (
      <section className="output-section knowledge-library-section">
        <div className="output-section-heading">
          <div>
            <span className="chat-kicker">LONG-TERM RESEARCH ASSETS</span>
            <h3>长期研究资产</h3>
            <p className="section-subtitle">这里保存已经登记、审核或正式确认的内容；当前对话产出的候选材料仍留在产出工作区。</p>
          </div>
          <span>{knowledgeAssets.length} 项</span>
        </div>
        <div className="knowledge-asset-summary-strip">
          {groups.map((group) => (
            <div key={group.kind}>
              <strong>{knowledgeAssets.filter((asset) => asset.kind === group.kind).length}</strong>
              <span>{group.title}</span>
            </div>
          ))}
        </div>
        <div className="knowledge-asset-groups">
          {groups.map((group) => {
            const items = knowledgeAssets.filter((asset) => asset.kind === group.kind);
            return (
              <details className="knowledge-asset-group" key={group.kind} open={items.length > 0}>
                <summary>
                  <span>
                    <strong>{group.title}</strong>
                    <small>{group.description}</small>
                  </span>
                  <b>{items.length}</b>
                </summary>
                {items.length ? (
                  <div className="knowledge-asset-list">
                    {items.slice(0, 12).map((asset) => (
                      <article className="knowledge-asset-row" key={`${asset.kind}-${asset.id}`}>
                        <div className="knowledge-asset-row-main">
                          <div className="knowledge-asset-titleline">
                            <strong>{asset.title}</strong>
                            <span className={asset.status.includes("正式") || asset.status.includes("可复核") ? "verified-tag" : "review-tag"}>
                              {asset.status}
                            </span>
                          </div>
                          <p>{asset.summary}</p>
                          <small>
                            {asset.version ?? "当前版本"} · {asset.provenance ?? "项目资产"}
                            {asset.updatedAt ? ` · 更新于 ${new Date(asset.updatedAt).toLocaleDateString()}` : ""}
                          </small>
                        </div>
                        <button
                          className="plain-action"
                          type="button"
                          onClick={() => {
                            if (asset.kind === "source" || asset.kind === "manuscript") {
                              const document = activeDocuments.find((item) => item.document_id === asset.id);
                              if (document) void openDocument(document);
                              return;
                            }
                            if (asset.kind === "candidate") {
                              openDedicatedWorkbench("paper", "paper-review");
                              return;
                            }
                            if (asset.kind === "evidence") {
                              openOutputWorkspace("evidence", "evidence-review");
                              return;
                            }
                            if (asset.kind === "audit") {
                              openOutputWorkspace("data", "data-audit");
                              return;
                            }
                            openOutputWorkspace("paper", "paper-review");
                          }}
                        >
                          {asset.action ?? "查看"}
                        </button>
                      </article>
                    ))}
                  </div>
                ) : (
                  <div className="knowledge-asset-empty">当前还没有这类长期资产。</div>
                )}
              </details>
            );
          })}
        </div>
        <div className="knowledge-library-boundary">
          <strong>长期资产边界</strong>
          <span>候选产出不会自动覆盖正式版本；只有保存新文档版本、完成来源核验或人工确认后，内容才会进入对应分区。</span>
        </div>
      </section>
    );
  };

  const renderAppliedMaterials = (title: string, targets: string[]) => renderPageMaterials(title, targets, true);

  const outputSectionCards = [
    {
      id: "questions" as const,
      title: "研究问题与方案",
      tone: "blue",
      count: Number(Boolean(latestResearchQuestion)) + Number(Boolean(latestStudyProtocol)) + researchBranches.length,
      summary: compactResearchText(asText(latestResearchQuestion?.body.primary_question)
        ?? asText(latestStudyProtocol?.body.primary_outcome)
        ?? researchBranches[0]?.title, "从对话里沉淀研究问题、路线比较和方案候选。"),
      workbench: "research-design" as const,
      action: "查看方案内容",
    },
    {
      id: "evidence" as const,
      title: "证据与文献",
      tone: "green",
      count: (evidenceReviewPackage ? 1 : 0) + formalEvidence.length + citations.length,
      summary: evidenceReviewPackage?.body.synthesis?.summary
        ?? (formalEvidence.length ? `已有 ${formalEvidence.length} 条正式证据。` : "上传论文、查看证据审阅包，并把候选证据提升为正式证据。"),
      workbench: "evidence-review" as const,
      action: "查看证据内容",
    },
    {
      id: "data" as const,
      title: "数据与审计",
      tone: "amber",
      count: Number(Boolean(latestDataAudit)) + Number(Boolean(analysisState?.raw_dataset)) + Number(Boolean(analysisState?.data_audit_report)) + datasetDocuments.length,
      summary: latestDataAudit
        ? "原始数据审计已生成，可继续检查缺失、重复、字段和冻结边界。"
        : analysisState?.stage
          ? `当前数据阶段：${analysisState.stage}`
          : datasetDocuments.length
            ? `已登记 ${datasetDocuments.length} 份 CSV 数据，等待数据审计与冻结确认。`
            : "上传 CSV 后先审计，再冻结，关键动作需要人工确认。",
      workbench: "data-audit" as const,
      action: "查看数据内容",
    },
    {
      id: "code" as const,
      title: "分析与代码",
      tone: "violet",
      count: Math.max(
        codeWorkbenchArtifacts.length,
        Number(Boolean(physicsReport)) + Number(Boolean(analysisState?.code_artifact_ref)) + pageMaterialsFor(["codex", "data_analysis"]).length,
      ),
      summary: codeWorkbenchArtifacts.length
        ? `已记录 ${codeWorkbenchArtifacts.length} 项代码、执行与结果校验产物。`
        : analysisState?.code_artifact_ref
        ? "分析代码候选已生成，执行前需要代码审查和确认。"
        : "放置物理代码校验、分析代码审核和受控执行入口。",
      workbench: "code-review" as const,
      action: "查看代码内容",
    },
    {
      id: "paper" as const,
      title: "论文产出",
      tone: "rose",
      count: draftDocuments.length + manuscriptCandidates.length + Number(Boolean(latestManuscriptArtifact)) + projectClaims.length,
      summary: draftDocuments[0]?.title
        ?? (latestManuscriptArtifact ? latestManuscriptTitle : "候选论文、正文编辑、投稿格式化和 LaTeX 输出。"),
      workbench: "paper-review" as const,
      action: "查看论文内容",
    },
    {
      id: "review" as const,
      title: "最终审查",
      tone: "slate",
      count: projectClaims.length + formalEvidence.length + Number(Boolean(effectiveStatisticalResultCard)),
      summary: "集中检查研究问题、证据引用、数据版本、统计结果、结论边界和伦理治理。",
      workbench: "final-review" as const,
      action: "查看审查内容",
    },
  ];

  const selectedOutputCard = outputSectionCards.find((section) => section.id === selectedOutputSection) ?? outputSectionCards[0];

  const workbenchReviewFocus: Record<OutputSectionId, string> = {
    questions: "研究问题是否清晰，方案边界是否可执行",
    evidence: "来源是否可定位，证据是否足以支撑当前判断",
    data: "字段、缺失值、重复记录和冻结边界",
    code: "代码是否可复核，物理约束和执行风险是否明确",
    paper: "主张、引用、结果和结论边界是否一致",
    review: "研究链路是否完整，证据、数据和结论是否彼此一致",
  };

  const renderOutputWorkbenchPreview = () => (
    <section className={`output-section workbench-preview-panel workbench-${selectedOutputCard.tone}`}>
      <div className="workbench-preview-heading">
        <div>
          <span className="chat-kicker">当前选择</span>
          <h3>{selectedOutputCard.title}</h3>
        </div>
        <span className={conversationCommitGate ? "review-tag" : "verified-tag"}>
          {conversationCommitGate ? "待人工确认" : "可继续处理"}
        </span>
      </div>
      <div className="workbench-preview-scroll">
        <div className="workbench-preview-related">
          {selectedOutputSection === "questions" && (
            <>
              {latestResearchQuestion && (
                <article>
                  <span>主要研究问题</span>
                  <p>{cleanResearchPresentation(asText(latestResearchQuestion.body.primary_question) ?? asText(latestResearchQuestion.body.title) ?? "研究问题候选已生成。")}</p>
                </article>
              )}
              {latestStudyProtocol && (
                <article>
                  <span>研究方案</span>
                  <p>{cleanResearchPresentation(previewValueText(latestStudyProtocol.body.design_type))}</p>
                </article>
              )}
              {!latestResearchQuestion && !latestStudyProtocol && <p className="workbench-muted">当前还没有研究问题或方案产出。</p>}
            </>
          )}
          {selectedOutputSection === "evidence" && (
            <>
              <div className="workbench-preview-stat-row">
                <div><span>来源</span><strong>{evidenceReviewPackage?.body.coverage.source_count ?? 0}</strong></div>
                <div><span>证据片段</span><strong>{evidenceReviewPackage?.body.coverage.evidence_count ?? 0}</strong></div>
                <div><span>正式证据</span><strong>{formalEvidence.length}</strong></div>
              </div>
              <p className="workbench-preview-summary">{evidenceReviewPackage?.body.synthesis?.summary ?? "上传论文或打开证据卡片，查看原文片段和来源定位。"}</p>
            </>
          )}
          {selectedOutputSection === "data" && (
            <>
              <div className="workbench-preview-stat-row">
                <div><span>数据文件</span><strong>{datasetDocuments.length}</strong></div>
                <div><span>审计行数</span><strong>{String(dataAuditDetails?.row_count ?? dataManifest?.row_count ?? "—")}</strong></div>
                <div><span>审计状态</span><strong>{latestDataAudit ? "已记录" : "待审计"}</strong></div>
              </div>
              <p className="workbench-preview-summary">{auditColumns.length ? `字段：${auditColumns.slice(0, 5).join("、")}` : "上传 CSV 后，数据审查和字段信息会显示在这里。"}</p>
            </>
          )}
          {selectedOutputSection === "code" && (
            <>
              <div className="workbench-preview-stat-row">
                <div><span>代码产物</span><strong>{codeWorkbenchArtifacts.length}</strong></div>
                <div><span>执行结果</span><strong>{effectiveStatisticalResultCard ? "已有" : "待生成"}</strong></div>
                <div><span>物理校验</span><strong>{physicsReport?.passed ? "通过" : "待检查"}</strong></div>
              </div>
              <p className="workbench-preview-summary">{codeWorkbenchArtifacts.length ? "代码候选已进入审核区，可展开查看、编辑并统一通过。" : "代码候选生成后会在这里显示。"}</p>
            </>
          )}
          {selectedOutputSection === "paper" && (
            <>
              <div className="workbench-preview-stat-row">
                <div><span>候选论文</span><strong>{manuscriptCandidates.length}</strong></div>
                <div><span>项目草稿</span><strong>{draftDocuments.length}</strong></div>
                <div><span>主张</span><strong>{projectClaims.length}</strong></div>
              </div>
              {latestManuscriptSectionEntries.length ? renderManuscriptSectionPreview() : <p className="workbench-preview-summary">候选论文生成后，正文、引用核验和 LaTeX 操作会显示在这里。</p>}
            </>
          )}
          {selectedOutputSection === "review" && (
            <div className="workbench-preview-review-grid">
              <div><span>正式证据</span><strong>{formalEvidence.length} 条</strong></div>
              <div><span>主张绑定</span><strong>{projectClaims.length} 条</strong></div>
              <div><span>数据审计</span><strong>{latestDataAudit ? "已记录" : "待完成"}</strong></div>
              <div><span>当前阶段</span><strong>{currentStageLabel}</strong></div>
            </div>
          )}
        </div>
        <dl className="workbench-preview-meta">
          <div><dt>当前状态</dt><dd>{currentStageLabel}</dd></div>
          <div><dt>审核重点</dt><dd>{workbenchReviewFocus[selectedOutputSection]}</dd></div>
          <div><dt>关联内容</dt><dd>{selectedOutputCard.count} 项产出 · {formalEvidence.length} 条正式证据 · {projectClaims.length} 条主张</dd></div>
        </dl>
      </div>
      <div className="workbench-preview-actions">
        <button className="primary-inline-button" type="button" onClick={() => openDedicatedWorkbench(selectedOutputSection, selectedOutputCard.workbench)}>
          打开专用工作台
        </button>
        {selectedOutputSection === "paper" && (
          <button className="secondary-inline-button" type="button" onClick={() => openKnowledgeLibrary()}>查看长期论文资产</button>
        )}
        {selectedOutputSection === "evidence" && (
          <button className="secondary-inline-button" type="button" onClick={() => openKnowledgeLibrary()}>进入证据库</button>
        )}
        {selectedOutputSection === "data" && (
          <button className="secondary-inline-button" type="button" onClick={() => setAnalysisWorkbenchOpen(true)}>打开数据审查</button>
        )}
      </div>
    </section>
  );

  const renderManuscriptSectionPreview = () => {
    if (!latestManuscriptSectionEntries.length) return null;
    return (
      <div className="manuscript-section-preview">
        <div className="output-section-heading">
          <div><h3>候选论文实际内容</h3><p className="section-subtitle">这是后端生成的正文预览，写入草稿后可继续人工编辑。</p></div>
          <span>{latestManuscriptSectionEntries.length} 节</span>
        </div>
        {latestManuscriptSectionEntries.map((section) => (
          <article key={section.key}>
            <span>{section.label}</span>
            <RichMarkdown
              className="rich-markdown-compact"
              content={manuscriptSectionMarkdown(cleanResearchPresentation(section.text))}
            />
          </article>
        ))}
      </div>
    );
  };

  const renderPaperWorkbenchEditor = () => {
    const selectedManuscript = selectedDocument?.document.document_type === "manuscript"
      ? selectedDocument
      : null;
    const sectionEntries = latestManuscriptSectionEntries;
    const displayedPaperMarkdown = selectedManuscript
      ? documentContentDraft || selectedManuscript.version?.content || ""
      : sectionEntries.map((section) => section.text).join("\n\n");
    const hasInlineFigures = /!\[[^\]]*\]\([^\s)]+(?:\s+"[^"]*")?\)/.test(displayedPaperMarkdown);

    return (
      <div className="paper-workbench-layout">
        <aside className="paper-outline-panel">
          <div className="workbench-subheading"><span>章节目录</span><small>{sectionEntries.length || "—"} 节</small></div>
          {sectionEntries.length ? (
            <nav className="paper-outline-list" aria-label="论文章节目录">
              {sectionEntries.map((section) => (
                <a href={`#paper-section-${section.key}`} key={section.key}>{section.label}</a>
              ))}
            </nav>
          ) : (
            <p className="workbench-muted">生成候选论文后，章节目录会自动出现。</p>
          )}
          <div className="workbench-side-block">
            <span>版本记录</span>
            <p>{selectedManuscript ? `当前草稿 v${selectedManuscript.version?.version ?? selectedManuscript.document.current_version}` : "候选版本，尚未写入文档"}</p>
          </div>
        </aside>
        <div className="paper-editor-panel">
          <div className="workbench-subheading">
            <span>论文正文</span>
            {selectedManuscript ? (
              <div className="paper-view-switch" role="group" aria-label="论文查看模式">
                <button className={!paperSourceEditing ? "selected" : ""} type="button" onClick={() => setPaperSourceEditing(false)}>排版预览</button>
                <button className={paperSourceEditing ? "selected" : ""} type="button" onClick={() => setPaperSourceEditing(true)}>编辑源文</button>
              </div>
            ) : <small>候选内容预览</small>}
          </div>
          {selectedManuscript && paperSourceEditing ? (
            <div className="document-editor document-editor-inline">
              <label className="document-editor-label">
                论文标题
                <input
                  value={documentTitleDraft}
                  onChange={(event) => setDocumentTitleDraft(event.target.value)}
                  disabled={documentEditBusy}
                />
              </label>
              <textarea
                className="paper-main-editor"
                value={documentContentDraft}
                onChange={(event) => setDocumentContentDraft(event.target.value)}
                disabled={!selectedManuscript.version || documentEditBusy}
                placeholder="论文正文会显示在这里"
              />
              <div className="document-editor-actions">
                <button className="secondary-inline-button" type="button" onClick={() => setPaperSourceEditing(false)}>返回排版预览</button>
                <button className="primary-inline-button" type="button" disabled={documentEditBusy || !selectedManuscript.version || !documentTitleDraft.trim()} onClick={() => void saveSelectedDocument()}>
                  {documentEditBusy ? "保存中..." : "保存新版本"}
                </button>
              </div>
              {documentEditError && <p className="document-editor-error">{documentEditError}</p>}
            </div>
          ) : selectedManuscript ? (
            <div className="paper-rendered-document">
              <div className="paper-rendered-toolbar">
                <span>当前文档 v{selectedManuscript.version?.version ?? selectedManuscript.document.current_version}</span>
                <button className="plain-action" type="button" onClick={() => setSelectedDocument(null)}>关闭文档</button>
              </div>
              <RichMarkdown content={documentContentDraft || selectedManuscript.version?.content || "正文读取中..."} />
            </div>
          ) : sectionEntries.length ? (
            <div className="paper-full-preview">
              {sectionEntries.map((section) => (
                <article id={`paper-section-${section.key}`} key={section.key}>
                  <h4>{section.label}</h4>
                  <RichMarkdown content={manuscriptSectionMarkdown(cleanResearchPresentation(section.text))} />
                </article>
              ))}
            </div>
          ) : (
            <div className="empty-output"><span className="empty-symbol">□</span><p>论文候选生成后，完整正文会显示在这里。</p></div>
          )}
          {manuscriptFigureManifest.length > 0 && !hasInlineFigures && (
            <section className="paper-figure-gallery" aria-label="论文图表">
              <div className="paper-figure-gallery-heading">
                <div><strong>论文图表</strong><span>{manuscriptFigureManifest.length} 张</span></div>
                <small>图表来自当前候选论文，请在定稿前核验来源与说明。</small>
              </div>
              <div className="paper-figure-grid">
                {manuscriptFigureManifest.map((figure) => (
                  <figure key={`${figure.figure_number}-${figure.url}`}>
                    <img src={figure.url} alt={figure.alt_text} loading="lazy" />
                    <figcaption>{figure.caption}</figcaption>
                  </figure>
                ))}
              </div>
            </section>
          )}
        </div>
        <aside className="paper-review-panel">
          <div className="workbench-subheading"><span>引用与主张绑定</span><small>{projectClaims.length + formalEvidence.length} 项</small></div>
          <div className="paper-review-list">
            {projectClaims.slice(0, 8).map((claim) => {
              const relatedEvidence = formalEvidence.filter((record) => claim.support_evidence_ids.includes(record.evidence_id));
              return (
              <details className="paper-binding-detail" key={claim.claim_id}>
                <summary>
                <div><span className="review-tag">{claimSectionLabel(claim.section)}</span><small>{claimStatusLabel(claim.reviewer_status || claim.verification_status)}</small></div>
                <p>{cleanResearchPresentation(claim.claim_text)}</p>
                <small>证据 {claim.support_evidence_ids.length} · 结果 {claim.support_result_ids.length}</small>
                </summary>
                <div className="paper-binding-expanded">
                  <p><strong>主张类型：</strong>{claim.claim_type} · <strong>支持方式：</strong>{claim.support_type}</p>
                  <p><strong>验证状态：</strong>{claimStatusLabel(claim.verification_status)} · <strong>审核状态：</strong>{claimStatusLabel(claim.reviewer_status)}</p>
                  <p><strong>结果绑定：</strong>{claim.support_result_ids.join("、") || "暂无"} · <strong>产物绑定：</strong>{claim.support_artifact_ids.join("、") || "暂无"}</p>
                  {relatedEvidence.length > 0 ? (
                    <div className="paper-binding-evidence">
                      {relatedEvidence.map((record) => {
                        const ref = record.evidence_ref;
                        const location = asRecord(ref.location);
                        return (
                          <div key={record.evidence_id}>
                            <strong>{asText(ref.paper_title) ?? "正式证据"}</strong>
                            <span>{asText(ref.normalized_doi) ?? asText(ref.doi) ?? "DOI 未提供"} · 页码 {String(ref.page ?? location?.page ?? "未提供")}</span>
                            <p>{asText(ref.excerpt) ?? "已绑定正式证据片段。"}</p>
                          </div>
                        );
                      })}
                    </div>
                  ) : <p className="workbench-muted">当前主张还没有绑定正式证据。</p>}
                </div>
              </details>
              );
            })}
            {!projectClaims.length && <p className="workbench-muted">当前还没有登记论文主张绑定。</p>}
          </div>
          <div className="workbench-side-block">
            <span>审核重点</span>
            <ul className="workbench-check-list">
              <li>结论是否超出数据支持范围</li>
              <li>关键主张是否绑定正式证据</li>
              <li>引用是否可以回到原文定位</li>
            </ul>
          </div>
        </aside>
      </div>
    );
  };

  const renderOutputWorkbench = () => {
    if (activeOutputWorkbench === "research-design") {
      return (
        <section className="output-section output-workbench-panel workbench-blue">
          <div className="output-section-heading">
            <div><span className="chat-kicker">专用工作台</span><h3>研究问题与方案</h3><p className="section-subtitle">这里承接当前对话形成的研究路线、问题树和方案候选。</p></div>
            <button className="plain-action" type="button" onClick={() => { setActiveOutputWorkbench("overview"); setWorkbenchExpanded(false); }}>返回总览</button>
          </div>
          {(latestResearchQuestion || latestStudyProtocol || researchBranches.length > 0) ? (
            <div className="workbench-stack">
              {latestResearchQuestion && (
                <div className="workbench-readable-block">
                  <span>主要研究问题</span>
                  <p className="workbench-full-text">{cleanResearchPresentation(
                    asText(latestResearchQuestion.body.primary_question)
                    ?? asText(latestResearchQuestion.body.title)
                    ?? "已生成研究问题候选。",
                  )}</p>
                  {Array.isArray(latestResearchQuestion.body.research_questions)
                    && latestResearchQuestion.body.research_questions.length > 0 && (
                    <p className="workbench-full-text workbench-secondary-text">
                      {latestResearchQuestion.body.research_questions
                        .filter((item): item is string => typeof item === "string")
                        .map(cleanResearchPresentation)
                        .join("；")}
                    </p>
                  )}
                </div>
              )}
              {latestStudyProtocol && (
                <div className="workbench-two-column">
                  {[
                    ["研究设计", "design_type", "研究设计候选已生成。"],
                    ["主要成果", "primary_outcome", "主要成果指标待确认。"],
                    ["样本与分组", "sampling_approach", "样本策略待确认。"],
                    ["变量与测量", "variables", "变量和测量方案待确认。"],
                    ["分析计划", "analysis_plan", "分析计划待确认。"],
                    ["研究假设", "hypotheses", "研究假设待确认。"],
                  ].map(([label, key, fallback]) => (
                    <details className="workbench-expand-card" key={key}>
                      <summary><strong>{label}</strong><span>&gt;</span></summary>
                      <p>{cleanResearchPresentation(previewValueText(latestStudyProtocol.body[key]) === "暂无内容" ? fallback : previewValueText(latestStudyProtocol.body[key]))}</p>
                    </details>
                  ))}
                </div>
              )}
              {latestStudyProtocol && asText(latestStudyProtocol.body.raw_answer) && (
                <div className="workbench-readable-block">
                  <span>完整研究方案回答</span>
                  <p className="workbench-full-text">{cleanResearchPresentation(
                    asText(latestStudyProtocol.body.raw_answer) ?? "",
                  )}</p>
                </div>
              )}
              {researchBranches.length > 0 && (
                <div className="workbench-card-list">
                  {researchBranches.slice(0, 5).map((branch) => (
                    <article key={branch.branch_id}>
                      <div><strong>{branch.title}</strong><span className={branch.status === "selected" ? "verified-tag" : "review-tag"}>{branch.status === "selected" ? "当前选择" : "待比较"}</span></div>
                      <p>{branch.description}</p>
                    </article>
                  ))}
                </div>
              )}
            </div>
          ) : <div className="empty-output"><span className="empty-symbol">◇</span><p>在左侧对话中说明研究主题后，方案候选会自动进入这里。</p></div>}
          {allPageMaterialsFor(["research_questions", "research_design", "data_collection", "workspace"]).length > 0
            ? renderAppliedMaterials("已应用的方案材料", ["research_questions", "research_design", "data_collection", "workspace"])
            : renderPageMaterials("已应用的方案材料", ["research_questions", "research_design", "data_collection", "workspace"])}
        </section>
      );
    }

    if (activeOutputWorkbench === "evidence-review") {
      return (
        <section className="output-section output-workbench-panel workbench-green">
          <div className="output-section-heading">
            <div><span className="chat-kicker">专用工作台</span><h3>证据与文献</h3><p className="section-subtitle">当前对话产生的证据候选在这里审阅，确认后进入知识库长期保存。</p></div>
            <button className="plain-action" type="button" onClick={() => { setActiveOutputWorkbench("overview"); setWorkbenchExpanded(false); }}>返回总览</button>
          </div>
          {evidenceReviewPackage ? (
            <div className="workbench-stack">
              <div className="evidence-package-metrics">
                <div><span>来源</span><strong>{evidenceReviewPackage.body.coverage.source_count}</strong></div>
                <div><span>新增</span><strong>{evidenceReviewPackage.body.coverage.new_source_count ?? evidenceReviewPackage.body.coverage.source_count}</strong></div>
                <div><span>证据片段</span><strong>{evidenceReviewPackage.body.coverage.evidence_count}</strong></div>
                <div><span>矩阵</span><strong>{evidenceReviewPackage.body.evidence_matrix.length}</strong></div>
              </div>
              {evidenceReviewPackage.body.synthesis?.summary && <div className="workbench-readable-block"><span>证据综合</span><p>{evidenceReviewPackage.body.synthesis.summary}</p></div>}
              <div className="workbench-card-list evidence-expand-list">
                {evidenceReviewPackage.body.evidence_matrix.slice(0, 12).map((row, index) => {
                  const rowId = row.row_id ?? `${row.source_ref}-${index}`;
                  const snapshot = evidenceReviewPackage.body.evidence_snapshots.find((item) => (
                    item.evidence_id && row.evidence_refs?.includes(item.evidence_id)
                  ));
                  const sourceCard = evidenceReviewPackage.body.paper_cards.find((item) => item.source_ref === row.source_ref);
                  const expanded = expandedEvidenceRowId === rowId;
                  const evidenceCitation = citationForEvidence(sourceCard?.title, snapshot?.excerpt ?? row.finding, snapshot?.evidence_id);
                  const relatedFormalEvidence = formalEvidence.find((record) => (
                    snapshot?.evidence_id && record.evidence_id === snapshot.evidence_id
                  ));
                  return (
                    <article className={expanded ? "evidence-expand-card expanded" : "evidence-expand-card"} key={rowId}>
                      <button type="button" className="evidence-expand-trigger" onClick={() => setExpandedEvidenceRowId(expanded ? null : rowId)}>
                        <span>
                          <strong>{row.relation === "SUPPORTING" ? "支持证据" : row.relation === "CONTRASTING" ? "对照证据" : "相关证据"}</strong>
                          <small>{sourceCard?.title ?? evidenceSourceLabel(row.source_ref)}</small>
                        </span>
                        <b>{expanded ? "<" : ">"}</b>
                      </button>
                      <p>{row.finding ?? "已生成证据对应，等待人工核验。"}</p>
                      {expanded && (
                        <div className="evidence-expand-detail">
                          <dl>
                            <div><dt>研究问题</dt><dd>{row.research_question ?? "当前证据对应问题未单列。"}</dd></div>
                            <div><dt>适用边界</dt><dd>{row.applicability_boundary ?? "来源适用边界待人工补充。"}</dd></div>
                            <div><dt>DOI</dt><dd>{asText((sourceCard as Record<string, unknown> | undefined)?.doi) ?? evidenceCitation?.normalized_doi ?? evidenceDoiFallback(snapshot?.excerpt) ?? "未提供"}</dd></div>
                            <div><dt>页码</dt><dd>{snapshot?.page ?? evidenceCitation?.page_start ?? evidencePageFallback(snapshot?.excerpt) ?? "未提供"}</dd></div>
                            <div><dt>字符定位</dt><dd>{snapshot?.locator ?? (evidenceCitation?.char_start != null && evidenceCitation?.char_end != null ? `${evidenceCitation.char_start}-${evidenceCitation.char_end}` : "未提供")}</dd></div>
                            <div><dt>证据状态</dt><dd>{relatedFormalEvidence ? "已进入正式证据库" : "候选，等待人工核验"}</dd></div>
                          </dl>
                          {snapshot?.excerpt && <blockquote>{snapshot.excerpt}</blockquote>}
                          <div className="evidence-expand-actions">
                            {snapshot?.evidence_id && (
                              <button className={relatedFormalEvidence ? "verified-tag" : "primary-inline-button"} type="button" disabled={evidenceBusy || Boolean(relatedFormalEvidence)} onClick={() => void verifyProjectEvidence(snapshot.evidence_id as string)}>
                                {relatedFormalEvidence ? "已人工确认" : "人工审核确认来源"}
                              </button>
                            )}
                            {!snapshot?.evidence_id && <span className="workbench-muted">当前条目尚未绑定可核验的证据片段。</span>}
                          </div>
                        </div>
                      )}
                    </article>
                  );
                })}
              </div>
            </div>
          ) : <div className="empty-output"><span className="empty-symbol">⌕</span><p>还没有证据审阅包。你可以先上传论文，或在对话里要求系统检索并整理证据。</p></div>}
          <div className="workbench-action-row">
            <button className="secondary-inline-button" type="button" onClick={openKnowledgeLibrary}>进入知识库核验</button>
            <button className="secondary-inline-button" disabled={evidenceBusy || !projectId} type="button" onClick={() => evidenceInputRef.current?.click()}>{evidenceBusy ? "处理中..." : "上传文献来源"}</button>
          </div>
          {renderFormalEvidence()}
        </section>
      );
    }

    if (activeOutputWorkbench === "data-audit") {
      return (
        <section className="output-section output-workbench-panel workbench-amber">
          <div className="output-section-heading">
            <div><span className="chat-kicker">专用工作台</span><h3>数据与审计</h3><p className="section-subtitle">负责原始数据上传、质量审计、冻结确认和数据处理边界。</p></div>
            <button className="plain-action" type="button" onClick={() => { setActiveOutputWorkbench("overview"); setWorkbenchExpanded(false); }}>返回总览</button>
          </div>
          {latestDataAudit && (
            <div className="workbench-stack">
              <div className="evidence-package-metrics">
                <div><span>行数</span><strong>{String(dataAuditDetails?.row_count ?? dataManifest?.row_count ?? "-")}</strong></div>
                <div><span>列数</span><strong>{String(dataAuditDetails?.column_count ?? (auditColumns.length || "-"))}</strong></div>
                <div><span>重复</span><strong>{String(dataAuditDetails?.duplicate_row_count ?? "-")}</strong></div>
                <div><span>缺失字段</span><strong>{String(Object.keys(missingByColumn ?? {}).filter((key) => Number(missingByColumn?.[key] ?? 0) > 0).length)}</strong></div>
              </div>
              {auditColumns.length > 0 && <div className="workbench-readable-block"><span>字段概览</span><p>{auditColumns.join("、")}</p></div>}
            </div>
          )}
          {datasetDocuments.length > 0 && (
            <div className="workbench-card-list">
              {datasetDocuments.map((document) => (
                <article key={document.document_id}>
                  <div><strong>{document.title}</strong><span className="review-tag">CSV 数据</span></div>
                  <p>版本 {document.current_version}，已登记到当前项目，可继续做数据审计、冻结和分析审批。</p>
                </article>
              ))}
            </div>
          )}
          <div className="workbench-action-row">
            <button className="primary-inline-button" type="button" disabled={primaryDataBusy} onClick={() => primaryDataInputRef.current?.click()}>{primaryDataBusy ? "登记中..." : "上传原始数据"}</button>
            <button className="secondary-inline-button" type="button" onClick={() => setAnalysisWorkbenchOpen(true)}>打开数据审查</button>
          </div>
          {analysisState?.pending_approval && (
            <div className="analysis-approval">
              <strong>待确认：{analysisState.pending_approval.approval_type}</strong>
              <p>{analysisState.pending_approval.reason}</p>
              <div className="analysis-approval-actions">
                <button className="secondary-inline-button" type="button" disabled={analysisBusy} onClick={() => void decideAnalysisStep("rejected")}>退回修正</button>
                <button className="primary-inline-button" type="button" disabled={analysisBusy} onClick={() => void decideAnalysisStep("approved")}>确认继续</button>
              </div>
            </div>
          )}
          {renderPageMaterials("数据处理与审计材料", ["data_analysis", "audit_validation"])}
        </section>
      );
    }

    if (activeOutputWorkbench === "code-review") {
      return (
        <section className="output-section output-workbench-panel workbench-violet">
          <div className="output-section-heading">
            <div><span className="chat-kicker">专用工作台</span><h3>分析与代码</h3><p className="section-subtitle">代码候选、物理校验、执行环境和 Codex 审核入口集中在这里。</p></div>
            <button className="plain-action" type="button" onClick={() => { setActiveOutputWorkbench("overview"); setWorkbenchExpanded(false); }}>返回总览</button>
          </div>
          <div className="workbench-two-column">
            <article><strong>Codex 代码候选</strong><p>{runtimeStatus.codex_available ? "可通过对话生成并审核代码候选。" : runtimeReasonLabel(runtimeStatus.codex_reason, "可先使用受控模板，待配置 Codex 后切换。")}</p></article>
            <article><strong>SciDAVis</strong><p>{runtimeStatus.scidavis_available ? "可导出结果 CSV。" : runtimeReasonLabel(runtimeStatus.scidavis_reason, "未检测到 SciDAVis。")}</p></article>
            <article><strong>SPSS</strong><p>{runtimeStatus.spss_available ? "SPSS 可用于双引擎校验。" : runtimeReasonLabel(runtimeStatus.spss_reason, "未配置 SPSS。")}</p></article>
          </div>
          {codeWorkbenchArtifacts.length > 0 && (
            <section className="code-candidate-section">
              <div className="output-section-heading">
                <div><h3>Codex 代码候选</h3><p className="section-subtitle">代码先在这里编辑和审核，通过后再进入分析执行与结果审查。</p></div>
                <button
                  className="primary-inline-button"
                  type="button"
                  disabled={agentPlanBusy || !agentOutputs.some((output) => output.artifact_ids.some((id) => codeWorkbenchArtifacts.some((artifact) => artifact.artifact_id === id)))}
                  onClick={() => {
                    const matching = agentOutputs.filter((output) => output.artifact_ids.some((id) => codeWorkbenchArtifacts.some((artifact) => artifact.artifact_id === id)));
                    void (async () => {
                      for (const output of matching) {
                        const matchingArtifactIds = output.artifact_ids.filter((id) => codeWorkbenchArtifacts.some((artifact) => artifact.artifact_id === id));
                        await decideAgentOutput(output, "apply", matchingArtifactIds);
                      }
                    })();
                  }}
                >
                  统一通过候选
                </button>
              </div>
              <div className="code-candidate-list">
                {codeWorkbenchArtifacts.slice(-8).map((artifact) => {
                  const sourceCode = codeTextForArtifact(artifact);
                  const draft = codeArtifactDrafts[artifact.artifact_id] ?? sourceCode;
                  const expanded = expandedCodeArtifactId === artifact.artifact_id;
                  return (
                    <article className={expanded ? "code-candidate-card expanded" : "code-candidate-card"} key={artifact.artifact_id}>
                      <div className="code-candidate-heading">
                        <div><strong>{codeWorkbenchArtifactLabels[artifact.artifact_type] ?? artifact.artifact_type}</strong><small>{sourceCode ? "可编辑候选" : "结构化审查产物"}</small></div>
                        <button className="plain-action" type="button" onClick={() => setExpandedCodeArtifactId(expanded ? null : artifact.artifact_id)}>{expanded ? "< 收起详情" : "> 查看详情"}</button>
                      </div>
                      {sourceCode ? (
                        <>
                          <textarea className="code-candidate-editor" value={draft} onChange={(event) => setCodeArtifactDrafts((current) => ({ ...current, [artifact.artifact_id]: event.target.value }))} rows={10} />
                          <div className="code-candidate-actions">
                            <button
                              className="secondary-inline-button"
                              type="button"
                              disabled={codeSaveBusy === artifact.artifact_id || draft === sourceCode || !auth?.access_token}
                              onClick={() => void saveCodeArtifactVersion(artifact, draft)}
                            >
                              {codeSaveBusy === artifact.artifact_id ? "保存中..." : "保存候选版本"}
                            </button>
                          </div>
                        </>
                      ) : <p>{cleanResearchPresentation(previewValueText(artifact.body))}</p>}
                      {expanded && (
                        <div className="code-candidate-details">
                          {readableArtifactFields(artifact).map(([key, value]) => <div key={key}><strong>{key}</strong><span>{cleanResearchPresentation(value)}</span></div>)}
                        </div>
                      )}
                    </article>
                  );
                })}
              </div>
              {codeSaveError && <p className="workflow-control-error" role="alert">{codeSaveError}</p>}
              {effectiveStatisticalResultCard && (
                <div className="code-result-actions">
                  <strong>分析结果</strong>
                  <span>结果卡已生成，可导出为 SciDAVis 文件继续复核。</span>
                  <button className="secondary-inline-button" type="button" disabled={scidavisBusy} onClick={() => void exportResultForSciDAVis()}>
                    {scidavisBusy ? "导出中..." : "导出到 SciDAVis"}
                  </button>
                </div>
              )}
            </section>
          )}
          <section className="physics-validator-section">
            <h3>Physics-STEM 代码校验</h3>
            <label className="document-editor-label">Python 代码
              <textarea className="physics-code-input" value={physicsSource} onChange={(event) => setPhysicsSource(event.target.value)} rows={7} />
            </label>
            <label className="document-editor-label">物理公式
              <textarea className="physics-code-input physics-equation-input" value={physicsEquations} onChange={(event) => setPhysicsEquations(event.target.value)} rows={3} />
            </label>
            <button className="primary-inline-button" type="button" disabled={physicsBusy || !auth?.access_token} onClick={() => void validatePhysics()}>{physicsBusy ? "校验中..." : "运行物理校验"}</button>
            {physicsError && <p className="upload-error">{physicsError}</p>}
            {physicsReport && <div className={`physics-report ${physicsReport.passed ? "physics-report-pass" : "physics-report-fail"}`}><strong>{physicsReport.passed ? "校验通过" : "发现需要处理的问题"}</strong><small>{physicsReport.checks.filter((check) => check.passed).length} 项通过 · {physicsReport.finding_codes.length} 项提醒</small></div>}
          </section>
          {renderPageMaterials("代码与分析候选", ["codex", "data_analysis"])}
        </section>
      );
    }

    if (activeOutputWorkbench === "final-review") {
      const currentStudyQuestion = asText(latestResearchQuestion?.body.primary_question)
        ?? asText(latestResearchQuestion?.body.title)
        ?? "尚未登记主要研究问题";
      const studyDesign = asText(latestStudyProtocol?.body.design_type)
        ?? "尚未确认研究设计";
      const dataVersion = dataManifest
        ? `v${String(dataManifest.version ?? dataManifest.dataset_version ?? 1)} · ${String(dataManifest.row_count ?? dataAuditDetails?.row_count ?? "-")} 行`
        : datasetDocuments.length
          ? `${datasetDocuments.length} 份数据资料已登记`
          : "尚未登记分析数据";
      const statisticalResult = effectiveStatisticalResultCard;
      const reviewItems = [
        {
          title: "研究问题与方法",
          status: latestResearchQuestion && latestStudyProtocol ? "已具备" : "待补充",
          tone: latestResearchQuestion && latestStudyProtocol ? "verified" : "review",
          content: `${currentStudyQuestion}；研究设计：${studyDesign}。`,
        },
        {
          title: "证据与引用",
          status: formalEvidence.length ? `${formalEvidence.length} 条正式证据` : "待核验",
          tone: formalEvidence.length ? "verified" : "review",
          content: formalEvidence.length
            ? "正式证据已进入项目证据链，可继续展开查看来源定位和主张绑定。"
            : `${citations.length} 条本轮引用仍属于探索材料，需完成来源核验。`,
        },
        {
          title: "数据版本",
          status: dataManifest || datasetDocuments.length ? "已登记" : "待上传",
          tone: dataManifest || datasetDocuments.length ? "verified" : "review",
          content: dataVersion,
        },
        {
          title: "统计结果",
          status: statisticalResult ? "已有结果卡" : "待生成",
          tone: statisticalResult ? "verified" : "review",
          content: statisticalResult
            ? `执行状态：${statisticalResult.execution_status}；${Object.entries(statisticalResult.values).slice(0, 4).map(([key, value]) => `${key}=${formatReviewNumber(value)}`).join("，")}`
            : "完成数据冻结、代码审查和受控执行后，统计结果会显示在这里。",
        },
        {
          title: "结论边界",
          status: projectClaims.length ? `${projectClaims.length} 条主张` : "待登记",
          tone: projectClaims.length ? "verified" : "review",
          content: projectClaims.length
            ? "请逐条检查主张是否超过数据、设计和正式证据能够支持的范围。"
            : "论文主张尚未登记，暂不能进行结论边界核查。",
        },
        {
          title: "伦理与数据治理",
          status: activeProject?.abstract ? "项目说明已记录" : "待确认",
          tone: activeProject?.abstract ? "verified" : "review",
          content: "确认去标识化、数据授权、访问范围和结果发布边界；正式版本不会因审查通过而自动公开。",
        },
      ];
      return (
        <section className="output-section output-workbench-panel workbench-slate final-review-workbench">
          <div className="output-section-heading">
            <div><span className="chat-kicker">专用工作台</span><h3>最终审查</h3><p className="section-subtitle">把研究问题、证据、数据、结果和结论边界放在同一张审查清单里。</p></div>
            <button className="plain-action" type="button" onClick={() => { setActiveOutputWorkbench("overview"); setWorkbenchExpanded(false); }}>返回总览</button>
          </div>
          <div className="final-review-summary">
            <div><span>当前阶段</span><strong>{currentStageLabel}</strong></div>
            <div><span>正式证据</span><strong>{formalEvidence.length} 条</strong></div>
            <div><span>主张绑定</span><strong>{projectClaims.length} 条</strong></div>
            <div><span>数据审计</span><strong>{latestDataAudit ? "已记录" : "待完成"}</strong></div>
          </div>
          <div className="final-review-grid">
            {reviewItems.map((item) => (
              <details className="final-review-item" key={item.title}>
                <summary>
                  <span><strong>{item.title}</strong><small>{item.content}</small></span>
                  <b className={item.tone === "verified" ? "verified-tag" : "review-tag"}>{item.status}</b>
                </summary>
                <div className="final-review-item-detail">
                  <p>{item.content}</p>
                  {item.title === "证据与引用" && (
                    <button className="secondary-inline-button" type="button" onClick={() => openDedicatedWorkbench("evidence", "evidence-review")}>查看证据详情</button>
                  )}
                  {item.title === "数据版本" && (
                    <button className="secondary-inline-button" type="button" onClick={() => openDedicatedWorkbench("data", "data-audit")}>打开数据审查</button>
                  )}
                  {item.title === "统计结果" && (
                    <button className="secondary-inline-button" type="button" onClick={() => openDedicatedWorkbench("code", "code-review")}>查看代码与结果</button>
                  )}
                </div>
              </details>
            ))}
          </div>
          <div className="final-review-claims">
            <div className="workbench-subheading"><span>引用与主张绑定</span><small>{projectClaims.length} 条</small></div>
            {projectClaims.length ? projectClaims.slice(0, 12).map((claim) => (
              <details className="paper-binding-detail" key={claim.claim_id}>
                <summary>
                  <div><span className="review-tag">{claimSectionLabel(claim.section)}</span><small>{claimStatusLabel(claim.reviewer_status || claim.verification_status)}</small></div>
                  <p>{cleanResearchPresentation(claim.claim_text)}</p>
                  <small>证据 {claim.support_evidence_ids.length} · 结果 {claim.support_result_ids.length} · 产物 {claim.support_artifact_ids.length}</small>
                </summary>
                <div className="paper-binding-expanded">
                  <p><strong>主张类型：</strong>{claim.claim_type} · <strong>支持方式：</strong>{claim.support_type}</p>
                  <p><strong>验证状态：</strong>{claimStatusLabel(claim.verification_status)} · <strong>审核状态：</strong>{claimStatusLabel(claim.reviewer_status)}</p>
                  <p><strong>证据绑定：</strong>{claim.support_evidence_ids.join("、") || "暂无"}</p>
                  <p><strong>结果绑定：</strong>{claim.support_result_ids.join("、") || "暂无"}</p>
                </div>
              </details>
            )) : <p className="workbench-muted">当前还没有可供最终审查的主张绑定。</p>}
          </div>
          <div className="final-review-actions">
            <button className="secondary-inline-button" type="button" onClick={() => openDedicatedWorkbench("paper", "paper-review")}>返回论文工作台</button>
            <button className="secondary-inline-button" type="button" onClick={() => openKnowledgeLibrary()}>查看知识库资产</button>
            {conversationCommitGate && <button className="primary-inline-button" type="button" disabled={conversationGateBusy} onClick={() => void decideConversationGate("approve", conversationCommitGate)}>确认当前审查</button>}
            <button
              className="primary-inline-button"
              type="button"
              disabled={!auth?.access_token || reproducibilityBusy || !effectiveStatisticalResultCard || (!selectedDocument && !latestManuscriptArtifact && !draftDocuments.length)}
              onClick={() => void runReproducibilityReview()}
            >
              {reproducibilityBusy ? "审查中..." : "运行复现审查"}
            </button>
          </div>
          {reproducibilityError && <p className="workflow-control-error" role="alert">{reproducibilityError}</p>}
          {reproducibilityReview && (
            <div className={`reproducibility-review-result ${reproducibilityReview.outcome.report.overall_recommendation === "PASS" ? "review-pass" : "review-needs-work"}`}>
              <strong>
                复现审查：{reproducibilityReview.outcome.report.overall_recommendation === "PASS" ? "通过" : "需要修改"}
              </strong>
              <span>
                {reproducibilityReview.outcome.findings.length
                  ? `发现 ${reproducibilityReview.outcome.findings.length} 项问题。`
                  : "当前论文数字与已验证结果卡一致。"}
              </span>
              {reproducibilityReview.outcome.findings.slice(0, 4).map((finding) => (
                <p key={finding.finding_id}>{finding.category}：{finding.description}</p>
              ))}
              {reproducibilityReview.approval_request && <small>复现审查通过后，仍需人工确认才能进入下一阶段。</small>}
            </div>
          )}
        </section>
      );
    }

    if (activeOutputWorkbench === "paper-review") {
      return (
        <section className="output-section output-workbench-panel workbench-rose">
          <div className="output-section-heading">
            <div><span className="chat-kicker">专用工作台</span><h3>论文与最终审查</h3><p className="section-subtitle">候选论文、草稿编辑、投稿格式化、LaTeX、引用核验和最终确认都在这里。</p></div>
            <button className="plain-action" type="button" onClick={() => { setActiveOutputWorkbench("overview"); setWorkbenchExpanded(false); }}>返回总览</button>
          </div>
          {draftDocuments.length > 0 || manuscriptCandidates.length > 0 || latestManuscriptArtifact ? (
            <div className="paper-list">
              {draftDocuments.map((document) => (
                <button className="paper-item draft-paper-item" type="button" key={document.document_id} onClick={() => void openDocument(document)}>
                  <span className="paper-file-icon draft-file-icon">稿</span>
                  <span><strong>{document.title}</strong><small>版本 {document.current_version} · 可编辑</small></span>
                  <span className="row-arrow">&gt;</span>
                </button>
              ))}
              {manuscriptCandidates.slice(0, 3).map((output) => {
                const preview = output.output_previews.find((item) => item.artifact_type === "ManuscriptDraftZh")
                  ?? output.output_previews.find((item) => item.artifact_type === "ManuscriptOutline");
                const title = preview && typeof preview.content.title === "string" ? preview.content.title : "候选论文草稿";
                return (
                  <div className="paper-item draft-paper-item" key={output.task_id}>
                    <span className="paper-file-icon draft-file-icon">稿</span>
                    <span><strong>{title}</strong><small>等待写入草稿并人工编辑</small></span>
                    <button className="primary-inline-button" type="button" disabled={agentPlanBusy} onClick={() => void applyManuscriptCandidate(output)}>送入论文草稿</button>
                  </div>
                );
              })}
              {!draftDocuments.length && !manuscriptCandidates.length && latestManuscriptArtifact && (
                <div className="paper-item draft-paper-item">
                  <span className="paper-file-icon draft-file-icon">稿</span>
                  <span><strong>{latestManuscriptTitle}</strong><small>已生成候选稿，尚未写入项目文档</small></span>
                  <button className="primary-inline-button" type="button" disabled={agentPlanBusy} onClick={() => void applyManuscriptArtifact(latestManuscriptArtifact.artifact_id)}>打开论文</button>
                </div>
              )}
            </div>
          ) : <div className="empty-output"><span className="empty-symbol">□</span><p>论文候选生成后，会在这里打开、编辑并进入最终审查。</p></div>}
          {renderPaperWorkbenchEditor()}
          <div className="publication-target-form">
            <span>投稿目标</span>
            <select aria-label="目标期刊" value={publicationTarget} disabled={!projectId || publicationTargetBusy} onChange={(event) => {
              const journal = event.target.value;
              setPublicationTarget(journal);
              setPublicationArticleType(
                journal === "IEEE Transactions on Education" ? "Application"
                  : journal === "International Journal of Science and Mathematics Education" ? "Original Research Article"
                    : journal === "Journal of Science Education and Technology" ? "Original Paper"
                      : "Research Article",
              );
            }}>
              <option>International Journal of STEM Education</option>
              <option>IEEE Transactions on Education</option>
              <option>International Journal of Science and Mathematics Education</option>
              <option>Journal of Science Education and Technology</option>
              <option>STEM Education</option>
            </select>
            <select aria-label="文章类型" value={publicationArticleType} disabled={!projectId || publicationTargetBusy} onChange={(event) => setPublicationArticleType(event.target.value)}>
              {publicationTarget === "IEEE Transactions on Education" ? <><option>Application</option><option>Discovery</option><option>Integration</option></> : publicationTarget === "International Journal of Science and Mathematics Education" ? <><option>Original Research Article</option><option>Review Article</option></> : publicationTarget === "Journal of Science Education and Technology" ? <><option>Original Paper</option><option>Review Paper</option></> : <><option>Research Article</option><option>Review Article</option></>}
            </select>
            <button className="secondary-inline-button" type="button" disabled={!projectId || publicationTargetBusy} onClick={() => void openLatexFormatter()}>{publicationTargetBusy ? "保存中..." : "投稿格式化 / LaTeX"}</button>
            {publicationTargetError && <p className="workflow-control-error" role="alert">{publicationTargetError}</p>}
          </div>
          {renderPageMaterials("引用核验与最终审查", ["paper_editor", "audit_validation"])}
        </section>
      );
    }

    return (
      <section className="output-section output-workbench-panel">
        <div className="output-section-heading">
          <div><span className="chat-kicker">专用工作台</span><h3>{selectedOutputCard.title}</h3><p className="section-subtitle">点击上方卡片进入对应工作台；内容会随左侧对话实时填充。</p></div>
        </div>
        <div className="output-workbench-empty">
          <strong>当前选择：{selectedOutputCard.title}</strong>
          <p>{selectedOutputCard.summary}</p>
        </div>
      </section>
    );
  };

  const renderOutputWorkspace = () => (
    <div className="output-content output-workspace-content">
      {!workbenchExpanded && <section className="output-section output-board-section">
        <div className="output-section-heading">
          <div><h3>产出工作区</h3><p className="section-subtitle">点击分区查看 AI 产出预览；需要完整处理和审核时，再打开专用工作台。</p></div>
          <span>{outputSectionCards.reduce((total, section) => total + section.count, 0)} 项</span>
        </div>
        <div className="output-zone-grid">
          {outputSectionCards.map((section) => (
            <button
              className={`output-zone-card output-zone-${section.tone} ${selectedOutputSection === section.id ? "selected" : ""}`}
              type="button"
              key={section.id}
              onClick={() => {
                setSelectedOutputSection(section.id);
                setActiveOutputWorkbench(section.workbench);
                setWorkbenchExpanded(false);
                setRightPaneVisible(true);
              }}
            >
              <span className="output-zone-count">{section.count}</span>
              <strong>{section.title}</strong>
              <p>{cleanResearchPresentation(section.summary)}</p>
              <span className="output-zone-footer">
                <small>{section.action}</small>
                <span aria-hidden="true">&gt;</span>
              </span>
            </button>
          ))}
        </div>
      </section>}
      {!workbenchExpanded && conversationCommitGate && (
        <section className="output-section output-confirm-section">
          <div className="output-section-heading">
            <div><h3>待人工确认</h3><p className="section-subtitle">{gateActionLabel(conversationCommitGate)}会影响正式研究状态，确认后才继续。</p></div>
            <span className="review-tag">需要处理</span>
          </div>
          <div className="analysis-approval-actions">
            <button className="secondary-inline-button" type="button" disabled={conversationGateBusy} onClick={() => void decideConversationGate("revise", conversationCommitGate)}>退回修改</button>
            <button className="primary-inline-button" type="button" disabled={conversationGateBusy} onClick={() => void decideConversationGate("approve", conversationCommitGate)}>{conversationGateBusy ? "处理中..." : "确认继续"}</button>
          </div>
        </section>
      )}
      {workbenchExpanded ? (
        <div className="dedicated-workbench-frame">
          <div className="dedicated-workbench-grid">
            <aside className="dedicated-workbench-sidebar">
              <div className="dedicated-workbench-side-heading">
                <button className="dedicated-back-button" type="button" onClick={() => setWorkbenchExpanded(false)}>&lt; 返回目录</button>
                <small>{selectedOutputCard.count} 项</small>
              </div>
              <div className="dedicated-workbench-nav">
                {outputSectionCards.map((section) => (
                  <button
                    type="button"
                    key={section.id}
                    className={section.id === selectedOutputSection ? "selected" : ""}
                    onClick={() => {
                      setSelectedOutputSection(section.id);
                      setActiveOutputWorkbench(section.workbench);
                    }}
                  >
                    <strong>{section.title}</strong>
                    <small>{section.count} 项</small>
                  </button>
                ))}
              </div>
              <div className="dedicated-workbench-side-block">
                <span>版本记录</span>
                <p>{draftDocuments.length ? `已有 ${draftDocuments.length} 份项目文档` : "当前以候选版本为主"}</p>
                <small>正式保存前仍可退回修改</small>
              </div>
              <div className="dedicated-workbench-side-block">
                <span>相关产出</span>
                <p>{projectClaims.length} 条主张 · {formalEvidence.length} 条正式证据</p>
              </div>
            </aside>
            <main className="dedicated-workbench-center">
              {renderOutputWorkbench()}
            </main>
            <aside className="dedicated-workbench-review">
              <div className="dedicated-workbench-side-heading">
                <span>审核信息</span>
                <span className={conversationCommitGate ? "review-tag" : "verified-tag"}>{conversationCommitGate ? "待确认" : "可继续编辑"}</span>
              </div>
              <dl className="dedicated-review-list">
                <div><dt>当前状态</dt><dd>{currentStageLabel}</dd></div>
                <div><dt>内容来源</dt><dd>{selectedOutputCard.title}</dd></div>
                <div><dt>证据绑定</dt><dd>{formalEvidence.length || citations.length ? `${formalEvidence.length || citations.length} 条` : "待补充"}</dd></div>
                <div><dt>主张绑定</dt><dd>{projectClaims.length ? `${projectClaims.length} 条` : "待生成"}</dd></div>
              </dl>
              <div className="dedicated-workbench-side-block risk-block">
                <span>风险提示</span>
                {activeResponse?.risk_flags.length ? (
                  <ul>{activeResponse.risk_flags.slice(0, 4).map((flag) => <li key={flag}>{riskFlagText(flag)}</li>)}</ul>
                ) : <p>当前没有新的风险提示。</p>}
              </div>
              <div className="dedicated-workbench-side-block">
                <span>操作边界</span>
                <p>模型只生成候选修改，人工确认后才写入项目版本。</p>
              </div>
            </aside>
          </div>
          <button className="primary-inline-button floating-preview-return" type="button" onClick={() => setWorkbenchExpanded(false)}>&lt; 返回预览</button>
        </div>
      ) : renderOutputWorkbenchPreview()}
    </div>
  );

  const evidenceSearchSummary = (reviewPackage: EvidenceReviewPackage) => {
    const coverage = reviewPackage.body.coverage;
    const added = coverage.new_source_count ?? coverage.source_count;
    const duplicates = coverage.duplicate_source_count ?? 0;
    const externalCandidates = coverage.external_candidate_count ?? 0;
    const verifiedSources = coverage.verified_source_count ?? 0;
    const localSources = Math.max(0, coverage.source_count - externalCandidates);
    const gaps = (reviewPackage.body.research_gap_report?.gaps ?? [])
      .map((gap) => gap.description?.trim())
      .filter((gap): gap is string => Boolean(gap))
      .slice(0, 2);
    const limitation = reviewPackage.body.research_gap_report?.limit_text?.trim();
    const evidenceStatus = verifiedSources > 0
      ? `其中 ${verifiedSources} 个来源已具备可定位的原文证据。`
      : "当前还没有完成原文定位核验的正式证据，外部题录只能作为待核验候选。";
    const gapText = gaps.length
      ? `当前需要补足：${gaps.join("；")}。`
      : limitation
        ? `证据边界：${limitation}`
        : "请先查看右侧的来源筛选和证据覆盖。";
    const nextAction = added === 0
      ? "本轮没有新增来源。你可以直接说“继续搜索：关键词 ...”，或修改研究范围。"
      : "你可以回复“继续搜索：关键词 ...”补足证据，或回复“当前证据足够，提出研究问题候选”进入共同设计。";
    return `第一轮资料整理已完成：新增 ${added} 个来源，重复/已存在 ${duplicates} 个；当前有 ${localSources} 个项目/本地来源、${externalCandidates} 个外部候选和 ${coverage.evidence_count} 条可定位证据片段。${evidenceStatus}${gapText}${nextAction}`;
  };

  const evidenceSourceLabel = (sourceRef: string | undefined) => {
    if (!sourceRef) return "未定位来源";
    const card = evidenceReviewPackage?.body.paper_cards.find((item) => item.source_ref === sourceRef);
    return card?.title || sourceRef;
  };

  const citationForEvidence = (
    sourceTitle: string | undefined,
    excerpt: string | undefined,
    evidenceId: string | undefined,
  ) => citations.find((citation) => (
    (evidenceId && (citation.canonical_chunk_id === evidenceId || citation.canonical_paper_id === evidenceId))
    || (sourceTitle && citation.paper_title.includes(sourceTitle))
    || (excerpt && citation.excerpt.includes(excerpt.slice(0, 48)))
  )) ?? null;

  const evidencePageFallback = (excerpt: string | undefined) => {
    const match = excerpt?.match(/\bPage\s+(\d+)(?:\s+of\s+\d+)?/i);
    return match?.[1] ?? null;
  };

  const evidenceDoiFallback = (excerpt: string | undefined) => {
    const match = excerpt?.match(/\b10\.\d{4,9}\/[-._;()/:A-Z0-9]+\b/i);
    return match?.[0] ?? null;
  };

  const focusDialogueCanvas = (orchestration: ConversationCommandResult) => {
    const focus = orchestration.dialogue?.canvas_focus;
    if (!focus) return;
    if (focus === "evidence") {
      openOutputWorkspace("evidence", "evidence-review");
    } else if (["data", "execution", "results", "interpretation"].includes(focus)) {
      openOutputWorkspace("data", "data-audit");
    } else {
      openOutputWorkspace("questions", "research-design");
    }
  };

  const applyManuscriptArtifact = async (artifactId: string) => {
    if (agentPlanBusy || !projectId || !auth?.access_token) return;
    setAgentPlanBusy(true);
    setAgentPlanError("");
    try {
      const applied = await workflowApi.applyAgentManuscript(projectId, artifactId);
      const nextDocuments = await authApi.listDocuments(auth.access_token, projectId);
      setDocuments(nextDocuments);
      const createdDocument = nextDocuments.find((document) => document.document_id === applied.document_id);
      if (createdDocument) await openDocument(createdDocument);
      openDedicatedWorkbench("paper", "paper-review");
    } catch (error) {
      const message = error instanceof Error ? error.message : "论文草稿写入失败";
      setAgentPlanError(message);
      setManuscriptApplyError(message);
    } finally {
      setAgentPlanBusy(false);
    }
  };

  const chooseDialogueBranch = async (branch: DialogueBranchOption) => {
    if (!auth?.access_token || !projectId || busy) {
      await submitQuestion(branch.message);
      return;
    }
    setBusy(true);
    setConversationGateError("");
    try {
      const existing = researchBranches.find((item) => item.title === branch.title && item.status !== "rejected");
      const persisted = existing ?? await workflowApi.createResearchBranch(projectId, {
        title: branch.title,
        description: branch.description,
        benefits: branch.benefits,
        risks: branch.risks,
        constraints: branch.prerequisites,
        dependent_node_ids: [],
        chosen_reason: branch.message,
        created_turn_id: conversationId ?? undefined,
      });
      await workflowApi.activateResearchBranch(projectId, persisted.branch_id, branch.message);
      await workflowApi.listResearchBranches(projectId).then(setResearchBranches);
    } catch (error) {
      setConversationGateError(error instanceof Error ? error.message : "研究路径保存失败，本轮仍会继续对话");
    } finally {
      setBusy(false);
    }
    await submitQuestion(branch.message);
  };

  const submitQuestion = async (
    value = question,
    requestedInteractionMode: "discussion" | "workflow" = "discussion",
  ) => {
    const trimmed = value.trim();
    if (!trimmed || busy || !activeProject) return;
    const attachments = chatAttachments;
    setMessages((current) => [...current, {
      id: `user-${Date.now()}`,
      role: "user",
      content: trimmed,
      attachments,
    }]);
    setQuestion("");
    setAttachmentError("");
    setBusy(true);
    try {
      if (auth?.access_token || demoMode) {
        // The composer is the normal project-entry point.  Persist attachments
        // before interpreting the accompanying research instruction so a PDF
        // can participate in the first evidence pass instead of appearing as
        // a purely visual chat attachment.
        if (auth?.access_token && attachments.length) {
          const uploadedDocuments: ApiProjectDocument[] = [];
          for (const attachment of attachments) {
            if (attachment.kind === "CSV") {
              // Register the file as project data immediately so exploratory
              // dialogue can inspect its real schema. The control plane still
              // gates freezing and formal analysis separately.
              const receipt = await authApi.uploadPrimaryData(auth.access_token, projectId, attachment.file);
              uploadedDocuments.push(receipt.document);
              const nextState = receipt.control_state as unknown as OrchestrationControlState;
              setOrchestrationState(nextState);
              setConversationControl((current) => current ? { ...current, control_state: nextState } : current);
              continue;
            }
            if (attachment.kind === "IMAGE") {
              throw new Error("图片已保留在当前对话；请将可作为研究材料的图片先转为 PDF、Word 或文本后上传。");
            }
            uploadedDocuments.push(await authApi.uploadDocument(auth.access_token, projectId, attachment.file));
          }
          if (uploadedDocuments.length) {
            setDocuments((current) => [
              ...uploadedDocuments,
              ...current.filter((item) => !uploadedDocuments.some((uploaded) => uploaded.document_id === item.document_id)),
            ]);
          }
          setChatAttachments([]);
        }
        if (!auth?.access_token && attachments.length) setChatAttachments([]);
        // All messages use the same conversational entry point. In
        // particular, scholarly-search requests must not be diverted into a
        // deterministic `allow_llm: false` branch: that branch discarded
        // context and produced the repeated "no results" reply shown to the
        // researcher. The backend can still invoke external search as a
        // bounded tool when the model or request calls for it.
        const clientTurnId = typeof crypto.randomUUID === "function"
          ? crypto.randomUUID()
          : `turn-${Date.now()}-${Math.random().toString(16).slice(2)}`;
        let orchestration = await workflowApi.orchestrationCommand(
          projectId,
          trimmed,
          // The server's auto policy is deliberately verb-based: ordinary
          // questions stay discussion, while an explicit instruction such as
          // "start the search" can still become a research run naturally.
          requestedInteractionMode === "workflow" ? "workflow" : "auto",
          mode,
          conversationId,
          trimmed,
          "background",
          clientTurnId,
        );
        refreshConversationIndex();
        if (orchestration.answer) {
          setConversationId(orchestration.answer.conversation_id);
          setLastResponse(orchestration.answer);
        }
        // Discussion responses carry the orchestration envelope so the API
        // can return durable context, but they must render as ordinary chat
        // and must not refresh or advance the workflow canvas.
        if (orchestration.answer && (orchestration.kind === "qa" || orchestration.dialogue?.mode === "discussion")) {
          await refreshProjectOutputs(true);
          setConversationControl(null);
          setConversationGateError("");
          setConversationId(orchestration.answer.conversation_id);
          setLastResponse(orchestration.answer);
          if (auth?.access_token) {
            void workflowApi.getResearchCanvas(projectId).then(setResearchCanvas).catch(() => undefined);
            void workflowApi.listArtifactContents(projectId)
              .then((items) => setOrchestrationArtifacts(items as OrchestrationArtifactContent[]))
              .catch(() => undefined);
          }
          if (orchestration.collaboration?.belief_revisions.length) {
            setContextTab("agent-work");
            setRightPaneVisible(true);
          }
          const assistantMessageId = `assistant-${Date.now()}-${Math.random().toString(16).slice(2)}`;
          setSelectedTurnId(assistantMessageId);
          setMessages((current) => [...current, {
            id: assistantMessageId,
            role: "assistant",
            content: orchestration.message,
            response: orchestration.answer,
            orchestration,
          }]);
          return;
        }
        // A completed project is immutable. Do not call /continue on it: the
        // API correctly rejects that transition, but the user should see a
        // clear next action instead of a generic connection error.
        if (orchestration.control_state.lifecycle_status === "COMPLETED") {
          const assistantMessageId = `assistant-${Date.now()}-${Math.random().toString(16).slice(2)}`;
          const completedMessage = "当前项目的研究流程已经完成，不能在原项目上开启新的研究主题。请新建一个科研项目后继续；已完成项目的证据、结果和审计记录会保持不变。";
          setConversationControl({ ...orchestration, message: completedMessage });
          setOrchestrationState(orchestration.control_state);
          setConversationGateError("");
          setSelectedTurnId(assistantMessageId);
          setMessages((current) => [...current, {
            id: assistantMessageId,
            role: "assistant",
            content: completedMessage,
            orchestration: { ...orchestration, message: completedMessage },
          }]);
          return;
        }
        // A collaboration turn starts at most one durable research run. The
        // background worker owns internal progression; chat must not expose
        // or repeatedly drive operator steps with automatic /continue calls.
        // Evidence review is a visible research artifact, not a formal Gate.
        // Load it when the system reaches research-question deliberation;
        // older projects may still expose the legacy evidence Gate once.
        if (
          orchestration.checkpoint === "RESEARCH_QUESTION_REVIEW"
          || orchestration.gate?.gate_type === "evidence_sufficiency_review"
        ) {
          try {
            const reviewPackage = await workflowApi.getEvidenceReviewPackage(projectId);
            setEvidenceReviewPackage(reviewPackage);
            if (orchestration.gate?.gate_type === "evidence_sufficiency_review") {
              orchestration.message = evidenceSearchSummary(reviewPackage);
            }
          } catch {
            // Deliberation remains available even if the optional package fetch fails.
          }
          setContextTab("agent-work");
          setRightPaneVisible(true);
        }
        const assistantMessageId = `assistant-${Date.now()}-${Math.random().toString(16).slice(2)}`;
        setConversationControl(orchestration);
        if (auth?.access_token) {
          void workflowApi.getResearchCanvas(projectId).then(setResearchCanvas).catch(() => undefined);
        }
        focusDialogueCanvas(orchestration);
        setOrchestrationState(orchestration.control_state);
        setConversationGateError("");
        setSelectedTurnId(assistantMessageId);
        setMessages((current) => [...current, {
          id: assistantMessageId,
          role: "assistant",
          content: orchestration.message,
          response: orchestration.answer,
          orchestration,
        }]);
        await refreshProjectOutputs(true);
        return;
      }
      const response = auth?.access_token
        ? await authApi.projectChatAnswer(auth.access_token, {
          project_id: projectId,
          question: trimmed,
          mode,
          conversation_id: conversationId,
          allow_llm: true,
          top_k: 8,
          token_budget: 3000,
        })
        : await qaApi.answer({
          project_id: projectId,
          question: trimmed,
          mode,
          conversation_id: conversationId,
          allow_llm: true,
          top_k: 8,
          token_budget: 3000,
        });
      setConversationId(response.conversation_id);
      refreshConversationIndex();
      setLastResponse(response);
      const assistantMessageId = `assistant-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      setSelectedTurnId(assistantMessageId);
      void workflowApi.getProject(projectId).then(setWorkflowState).catch(() => undefined);
      setMessages((current) => [...current, {
        id: assistantMessageId,
        role: "assistant",
        content: response.answer,
        response,
      }]);
      await refreshProjectOutputs(true);
    } catch (error) {
      const message = error instanceof Error ? error.message : "对话服务暂时不可用";
      setMessages((current) => [...current, {
        id: `assistant-error-${Date.now()}`,
        role: "assistant",
        content: demoMode
          ? `暂时无法连接后端问答服务。\n\n${message}\n\n当前界面仍保留演示证据，你可以稍后重试。`
          : `暂时无法连接后端问答服务。\n\n${message}\n\n没有生成或保留任何证据，请检查服务后重试。`,
        response: demoMode ? demoQAResponse : undefined,
      }]);
    } finally {
      setBusy(false);
    }
  };

  const configurePublicationTarget = async () => {
    if (!projectId || !publicationTarget || !publicationArticleType || publicationTargetBusy) return;
    setPublicationTargetBusy(true);
    setPublicationTargetError("");
    try {
      const next = await workflowApi.setPublicationTarget(
        projectId,
        publicationTarget,
        publicationArticleType,
      );
      setOrchestrationState(next);
    } catch (error) {
      setPublicationTargetError(error instanceof Error ? error.message : "投稿目标保存失败");
    } finally {
      setPublicationTargetBusy(false);
    }
  };

  const decideConversationGate = async (decision: "approve" | "reject" | "revise" | "stop", gateOverride?: OrchestrationGate) => {
    const gate = gateOverride ?? conversationControl?.gate
      ?? [...messages].reverse().find((item) => item.orchestration?.gate?.status === "PENDING")?.orchestration?.gate;
    if (!gate || gate.status !== "PENDING" || conversationGateBusy || conversationGateActionRef.current) return;
    conversationGateActionRef.current = true;
    setConversationGateBusy(true);
    setConversationGateError("");
    try {
      const latestState = await workflowApi.getControlState(projectId);
      if (latestState.active_gate_id !== gate.gate_id) {
        const latestGate = buildGateFromState(latestState);
        setConversationControl((current) => current ? {
          ...current,
          control_state: latestState,
          route_decision: latestState.route_decision,
          gate: latestGate,
          message: latestGate
            ? "当前确认卡已更新，请确认最新的研究阶段。"
            : "当前研究流程已推进，请查看最新状态。",
        } : current);
        setConversationGateError("当前确认卡已过期，系统已刷新到最新 Gate，请重新确认。");
        return;
      }
      const next = await workflowApi.decideOrchestrationGate(
        projectId,
        gate.gate_id,
        decision,
        gate.warnings.length ? ["研究者已查看路线不确定性"] : [],
        decision === "approve" ? "研究者确认当前路线" : undefined,
      );
      setConversationControl((current) => current ? {
        ...current,
        control_state: next,
        gate: current.gate ? { ...current.gate, status: decision === "approve" ? "APPROVED" : "REJECTED" } : null,
      } : current);
      setOrchestrationState(next);
      const shouldRebuildEvidence = decision === "revise" && gate.gate_type === "evidence_sufficiency_review";
      if (decision === "approve" || shouldRebuildEvidence) {
        let continued = await workflowApi.continueOrchestration(projectId);
        // Retrieval operators are deterministic internal work. Continue through
        // them until a human-reviewable evidence candidate is ready.
        for (let automaticStep = 0; automaticStep < 32 && !continued.gate && continued.execution_started; automaticStep += 1) {
          continued = await workflowApi.continueOrchestration(projectId);
        }
        setConversationControl((current) => current ? {
          ...current,
          control_state: continued.control_state,
          message: shouldRebuildEvidence
            ? "已根据你的修改请求重新整理文献与证据，并生成新的审阅包。"
            : "证据审阅已确认，系统已进入下一阶段。",
          gate: continued.gate,
        } : current);
        setOrchestrationState(continued.control_state);
        let refreshedEvidence: EvidenceReviewPackage | null = null;
        if (continued.gate?.gate_type === "evidence_sufficiency_review") {
          try {
            refreshedEvidence = await workflowApi.getEvidenceReviewPackage(projectId);
            setEvidenceReviewPackage(refreshedEvidence);
          } catch {
            refreshedEvidence = null;
          }
        }
        setMessages((current) => {
          const index = [...current].map((item, itemIndex) => ({ item, itemIndex }))
            .reverse().find(({ item }) => item.orchestration)?.itemIndex;
          if (index === undefined) return current;
          return current.map((item, itemIndex) => itemIndex === index && item.orchestration
            ? {
              ...item,
              content: continued.gate?.gate_type === "evidence_sufficiency_review"
                ? refreshedEvidence
                  ? evidenceSearchSummary(refreshedEvidence)
                  : "文献与证据审阅包已更新，请在右侧查看后决定是否进入研究设计。"
                : continued.gate ? "本轮内部工作已完成。请查看右侧材料，并直接说明你的研究判断或修改要求。" : "当前研究流程已完成。",
              orchestration: {
                ...item.orchestration,
                control_state: continued.control_state,
                route_decision: continued.control_state.route_decision,
                gate: continued.gate,
                message: continued.gate ? "本轮内部工作已完成。请查看右侧材料，并直接说明你的研究判断或修改要求。" : "当前研究流程已完成。",
              },
            }
            : item);
        });
        if (continued.gate?.gate_type === "evidence_sufficiency_review") {
          setContextTab("agent-work");
          setRightPaneVisible(true);
        }
      }
      void workflowApi.getProject(projectId).then(setWorkflowState).catch(() => undefined);
      if (decision !== "approve") {
        setMessages((current) => [...current, {
          id: `assistant-gate-${Date.now()}`,
          role: "assistant",
          content: decision === "stop" ? "研究流程已停止。" : "当前步骤已退回修改。请在对话框补充修改要求，完成后我会重新生成候选产物。",
        }]);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "研究确认处理失败";
      setConversationGateError(message);
      if (/not active|not pending|过期|stale/i.test(message)) {
        void workflowApi.getControlState(projectId).then(async (latestState) => {
          let latestGate: OrchestrationGate | null = null;
          if (latestState.active_gate_id) {
            try {
              latestGate = await workflowApi.getOrchestrationGate(projectId, latestState.active_gate_id);
            } catch {
              latestGate = {
                gate_id: latestState.active_gate_id,
                project_id: projectId,
                workstream_id: latestState.active_workstream_id ?? "",
                gate_type: "orchestration_approval",
                level: "G2",
                status: "PENDING",
                artifact_ids: [],
                reason: "请确认当前研究阶段后继续。",
                warnings: latestState.route_decision?.uncertainties ?? [],
                risk_acceptance: [],
                requested_by: "orchestrator",
                decided_by: null,
                decision_reason: null,
                created_at: latestState.updated_at,
                decided_at: null,
              };
            }
          }
          setConversationControl((current) => current ? {
            ...current,
            control_state: latestState,
            route_decision: latestState.route_decision,
            gate: latestGate,
          } : current);
          setOrchestrationState(latestState);
        }).catch(() => undefined);
      }
    } finally {
      setConversationGateBusy(false);
      conversationGateActionRef.current = false;
    }
  };

  const retryOrchestrationTask = async (task: OrchestrationTask) => {
    if (!auth?.access_token || !projectId) return;
    const activeStream = orchestrationState?.workstreams.find(
      (stream) => stream.workstream_id === orchestrationState.active_workstream_id,
    );
    const currentAction = activeStream && activeStream.current_step_index < activeStream.workflow_steps.length
      ? activeStream.workflow_steps[activeStream.current_step_index]
      : activeStream?.current_action;
    if (!['FAILED', 'STALE', 'CANCELLED'].includes(task.status)) return;
    if (currentAction !== task.action || orchestrationState?.active_gate_id) {
      setConversationGateError("该任务已不再是当前阶段的可重试任务，请先刷新研究状态。");
      return;
    }
    setConversationGateBusy(true);
    setConversationGateError("");
    try {
      await workflowApi.retryOrchestrationTask(projectId, task.task_id);
      const [state, tasks] = await Promise.all([
        workflowApi.getControlState(projectId),
        workflowApi.listOrchestrationTasks(projectId),
      ]);
      setOrchestrationState(state);
      setOrchestrationTasks(tasks);
    } catch (error) {
      setConversationGateError(error instanceof Error ? error.message : "任务重新执行失败");
    } finally {
      setConversationGateBusy(false);
    }
  };

  const validatePhysics = async () => {
    if (!auth?.access_token || !projectId || !physicsSource.trim()) return;
    setPhysicsBusy(true);
    setPhysicsError("");
    try {
      const report = await authApi.validatePhysicsCode(auth.access_token, projectId, {
        source_code: physicsSource,
        equations: physicsEquations.split("\n").map((item) => item.trim()).filter(Boolean),
        units: {},
        bounds: {},
      });
      setPhysicsReport(report);
    } catch (error) {
      setPhysicsError(error instanceof Error ? error.message : "物理代码校验失败");
    } finally {
      setPhysicsBusy(false);
    }
  };

  const saveCodeArtifactVersion = async (
    artifact: OrchestrationArtifactContent,
    sourceCode: string,
  ) => {
    if (
      !projectId
      || !auth?.access_token
      || !sourceCode.trim()
      || codeSaveBusy === artifact.artifact_id
    ) return;
    setCodeSaveBusy(artifact.artifact_id);
    setCodeSaveError("");
    try {
      const saved = await workflowApi.saveCodeArtifactVersion(
        projectId,
        artifact.artifact_id,
        sourceCode,
        "研究者在分析与代码工作台编辑代码候选",
      );
      setCodeArtifactDrafts((current) => ({
        ...current,
        [artifact.artifact_id]: String(saved.content.body.source_code ?? sourceCode),
      }));
      const contents = await workflowApi.listArtifactContents(projectId);
      setOrchestrationArtifacts(contents as OrchestrationArtifactContent[]);
    } catch (error) {
      setCodeSaveError(error instanceof Error ? error.message : "代码候选保存失败");
    } finally {
      setCodeSaveBusy(null);
    }
  };

  const extractManuscriptNumbers = (content: string) => {
    const matches = content.match(/-?(?:\d+(?:\.\d+)?|\.\d+)(?:e[+-]?\d+)?/gi) ?? [];
    return matches
      .map((item) => Number(item))
      .filter((item) => Number.isFinite(item));
  };

  const runReproducibilityReview = async () => {
    const statisticalResult = effectiveStatisticalResultCard;
    const selectedManuscript = selectedDocument?.document.document_type === "manuscript"
      ? selectedDocument
      : null;
    const manuscriptDocument = selectedManuscript?.document ?? draftDocuments[0] ?? null;
    const manuscriptArtifact = latestManuscriptArtifact;
    if (!projectId || !statisticalResult || (!manuscriptDocument && !manuscriptArtifact)) return;
    setReproducibilityBusy(true);
    setReproducibilityError("");
    try {
      const manuscript = selectedManuscript ?? (
        manuscriptDocument && auth?.access_token
          ? {
            document: manuscriptDocument,
            version: await authApi.getDocumentVersion(
              auth.access_token,
              projectId,
              manuscriptDocument.document_id,
              manuscriptDocument.current_version,
            ),
          }
          : null
      );
      const manuscriptContent = manuscript
        ? manuscript === selectedManuscript
          ? documentContentDraft
          : manuscript.version?.content ?? ""
        : JSON.stringify(manuscriptArtifact?.body ?? {});
      const numbers = extractManuscriptNumbers(manuscriptContent);
      const numericClaims = Object.entries(statisticalResult.values)
        .map(([resultKey, expected], index) => {
          const reportedValue = numbers.find((value) => Math.abs(value - expected) <= 1e-8);
          if (reportedValue === undefined) return null;
          return {
          claim_ref: `claim://${projectId}/workbench-${index + 1}`,
          result_card_ref: `result-card://${statisticalResult.result_id}`,
          result_key: resultKey,
            reported_value: reportedValue,
          };
        })
        .filter((claim): claim is {
          claim_ref: string;
          result_card_ref: string;
          result_key: string;
          reported_value: number;
        } => claim !== null);
      if (!numericClaims.length) {
        setReproducibilityError("未在当前论文正文中识别到与已验证结果卡对应的数字，请先保存正文后再审查。");
        return;
      }
      const result = await workflowApi.runReproducibilityReview(projectId, {
        manuscriptRef: manuscript
          ? `document://${manuscript.document.document_id}/v${manuscript.version?.version ?? manuscript.document.current_version}`
          : manuscriptArtifact?.artifact_id ?? "manuscript-candidate",
        numericClaims,
      });
      setReproducibilityReview(result);
      setWorkflowState(result.workflow_state as WorkflowState);
      setWorkflowSnapshot(result.workflow_state);
      setAnalysisState(result.workflow_state.data_pipeline);
      setAnalysisStage(result.workflow_state.current_stage);
      setOrchestrationArtifacts(
        await workflowApi.listArtifactContents(projectId) as OrchestrationArtifactContent[],
      );
    } catch (error) {
      setReproducibilityError(error instanceof Error ? error.message : "复现审查失败");
    } finally {
      setReproducibilityBusy(false);
    }
  };

  const selectWorkspaceMode = (nextMode: Exclude<WorkspaceMode, null>) => {
    setWorkspaceMode(nextMode);
    window.history.pushState({}, "", `/workspace/${nextMode}`);
  };

  const openWorkspaceSelector = () => {
    setWorkspaceMode(null);
    window.history.pushState({}, "", "/workspace/select");
  };

  const signIn = async () => {
    if (!loginValue.trim() || !passwordValue.trim()) return;
    setAuthBusy(true);
    setAuthError("");
    try {
      const next = await authApi.login({ login: loginValue.trim(), password: passwordValue });
      saveAuth(next);
      setAuth(next);
      setWorkspaceMode(null);
      window.history.replaceState({}, "", "/workspace/select");
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "登录失败");
    } finally {
      setAuthBusy(false);
    }
  };

  const openLatexFormatter = async () => {
    if (projectId && publicationTarget && publicationArticleType) {
      await configurePublicationTarget();
    }
    window.dispatchEvent(new CustomEvent("stem-sci:open-latex"));
  };

  const signUp = async () => {
    if (!registerUsername.trim() || !registerEmail.trim() || !passwordValue.trim()) {
      setAuthError("请填写用户名、邮箱和密码");
      return;
    }
    setAuthBusy(true);
    setAuthError("");
    try {
      const next = await authApi.register({
        username: registerUsername.trim(),
        email: registerEmail.trim(),
        password: passwordValue,
        display_name: registerDisplayName.trim() || null,
      });
      saveAuth(next);
      setAuth(next);
      setWorkspaceMode(null);
      window.history.replaceState({}, "", "/workspace/select");
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "注册失败");
    } finally {
      setAuthBusy(false);
    }
  };

  const signOut = async () => {
    try {
      if (auth?.access_token) await authApi.logout(auth.access_token);
    } catch {
      // Local session is still cleared when the API is unavailable.
    }
    clearAuth();
    setAuth(null);
    setWorkspaceMode(null);
    window.history.replaceState({}, "", "/");
  };

  const switchProject = (nextProjectId: string) => {
    setProjectId(nextProjectId);
    setProjectMenuOpen(false);
    setConversationId(undefined);
    setConversations([]);
    setSelectedTurnId(null);
    setConversationControl(null);
    setOrchestrationState(null);
    setProjectBlockers([]);
    setOrchestrationTasks([]);
    setEvidenceReviewPackage(null);
    setProjectClaims([]);
    setReproducibilityReview(null);
    setReproducibilityError("");
    setConversationGateError("");
    setLastResponse(demoMode ? demoQAResponse : null);
    const project = projects.find((item) => item.project_id === nextProjectId);
    setMessages([makeWelcome(project?.title ?? "科研项目")]);
  };

  const openCreateProject = () => {
    setProjectForm({
      project_id: "",
      title: "",
      research_direction: "",
      abstract: "",
    });
    setProjectError("");
    setCreateProjectOpen(true);
  };

  const createProject = async () => {
    if (!auth?.access_token) {
      setProjectError("请先登录后再创建项目");
      return;
    }
    if (!projectForm.title.trim() || !projectForm.research_direction.trim()) {
      setProjectError("请填写项目名称和研究方向");
      return;
    }
    setProjectBusy(true);
    setProjectError("");
    try {
      const created = await authApi.createProject(auth.access_token, {
        project_id: projectForm.project_id.trim() || undefined,
        title: projectForm.title.trim(),
        research_direction: projectForm.research_direction.trim(),
        abstract: projectForm.abstract.trim() || null,
      });
      setProjects((current) => [created, ...current.filter((item) => item.project_id !== created.project_id)]);
      setProjectId(created.project_id);
      setDocuments([]);
      setConversations([]);
      setConversationId(undefined);
      setMessages([makeWelcome(created.title)]);
      const initialWorkflow = intakeWorkflowState(created.project_id);
      setLastResponse(null);
      setConversationControl(null);
      setOrchestrationState(null);
      setProjectBlockers([]);
      setOrchestrationTasks([]);
      setConversationGateError("");
      setWorkflow(initialWorkflow);
      setWorkflowState(initialWorkflow);
      setWorkflowSnapshot({ ...initialWorkflow, data_pipeline: null });
      setAnalysisStage("INTAKE");
      setAnalysisState(null);
      setEvidenceRows([]);
      setAgentPlan(null);
      setAgentPlans([]);
      setAgentOutputs([]);
      setPageMaterials([]);
      setFormalEvidence([]);
      setEvidenceReviewPackage(null);
      setProjectClaims([]);
      setSelectedTurnId(null);
      setCreateProjectOpen(false);
      void workflowApi.getProject(created.project_id).then((state) => {
        setWorkflow(state);
        setWorkflowState(state);
      }).catch(() => undefined);
    } catch (error) {
      setProjectError(error instanceof Error ? error.message : "创建项目失败");
    } finally {
      setProjectBusy(false);
    }
  };

  const uploadDocument = async (file: File) => {
    if (!auth?.access_token || !projectId) {
      setUploadError("请先登录并选择一个项目");
      return;
    }
    const lowerName = file.name.toLowerCase();
    if (!lowerName.endsWith(".pdf") && !lowerName.endsWith(".docx")) {
      setUploadError("目前支持 PDF 和 DOCX 文件");
      return;
    }
    setUploadBusy(true);
    setUploadError("");
    try {
      const created = await authApi.uploadDocument(auth.access_token, projectId, file);
      setDocuments((current) => [created, ...current.filter((item) => item.document_id !== created.document_id)]);
      const [reviewPackage, formal] = await Promise.all([
        workflowApi.getEvidenceReviewPackage(projectId).catch(() => null),
        workflowApi.listFormalEvidence(projectId).catch(() => null),
      ]);
      setEvidenceReviewPackage(reviewPackage);
      if (formal) setFormalEvidence(formal);
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : "上传文档失败");
    } finally {
      setUploadBusy(false);
      if (uploadInputRef.current) uploadInputRef.current.value = "";
    }
  };

  const refreshAnalysisState = async () => {
    if (!projectId) return;
    const controllerState = await workflowApi.getControllerProject(projectId);
    setWorkflowSnapshot(controllerState);
    setAnalysisStage(controllerState.current_stage);
    setAnalysisState(controllerState.data_pipeline);
  };

  const uploadAnalysisDataset = async (file: File) => {
    if (!projectId) return;
    if (!file.name.toLowerCase().endsWith(".csv")) {
      setAnalysisError("数据分析目前只接受 CSV 文件，避免把未结构化文档直接送入统计执行链。");
      return;
    }
    if (file.size > 50 * 1024 * 1024) {
      setAnalysisError("CSV 文件不能超过 50 MB。");
      return;
    }
    setAnalysisBusy(true);
    setAnalysisError("");
    try {
      const next = await workflowApi.uploadControllerRawCsv(projectId, file);
      setAnalysisState(next);
      setAnalysisStage(next.stage);
      setWorkflowSnapshot((current) => current ? {
        ...current,
        current_stage: next.stage,
        data_pipeline: next,
      } : current);
      if (auth?.access_token) {
        setDocuments(await authApi.listDocuments(auth.access_token, projectId));
      }
    } catch (error) {
      setAnalysisError(error instanceof Error ? error.message : "实验数据上传失败");
    } finally {
      setAnalysisBusy(false);
      if (analysisInputRef.current) analysisInputRef.current.value = "";
    }
  };

  const decideAnalysisStep = async (decision: "approved" | "rejected") => {
    if (!projectId || !analysisState?.pending_approval) return;
    setAnalysisBusy(true);
    setAnalysisError("");
    try {
      const decidedBy = auth?.user.username ?? "researcher";
      const next = await workflowApi.decideControllerDataPipeline(projectId, decision, decidedBy);
      setAnalysisState(next);
      setAnalysisStage(next.stage);
      setWorkflowSnapshot((current) => current ? {
        ...current,
        current_stage: next.stage,
        data_pipeline: next,
      } : current);
      await refreshWorkflow();
      if (auth?.access_token) {
        setDocuments(await authApi.listDocuments(auth.access_token, projectId));
      }
    } catch (error) {
      setAnalysisError(error instanceof Error ? error.message : "数据分析审批失败");
    } finally {
      setAnalysisBusy(false);
    }
  };

  const openDataAnalysisAgentPlan = () => {
    setAnalysisError("");
    openAgentPlanner(
      "请根据当前已批准的研究方案，判断是否需要调用数据分析 Agent，并生成数据审查、处理计划、分析规格和代码草案的任务计划。",
    );
  };

  const createDraft = async () => {
    if (!auth?.access_token || !projectId) {
      setUploadError("请先登录并选择一个项目");
      return;
    }
    setDocumentEditBusy(true);
    setDocumentEditError("");
    try {
      const created = await authApi.createDocument(auth.access_token, projectId, {
        title: "论文草稿",
        document_type: "manuscript",
        format: "markdown",
        content: "# 论文草稿\n\n## 研究问题\n\n## 研究设计\n\n## 结果与讨论\n",
        change_note: "创建论文草稿",
      });
      setDocuments((current) => [
        created,
        ...current.filter((item) => item.document_id !== created.document_id),
      ]);
      await openDocument(created);
    } catch (error) {
      setDocumentEditError(error instanceof Error ? error.message : "创建论文草稿失败");
    } finally {
      setDocumentEditBusy(false);
    }
  };

  const openDocument = async (document: ApiProjectDocument) => {
    setSelectedDocument({ document, version: null });
    setPaperSourceEditing(false);
    setDocumentTitleDraft(document.title);
    setDocumentContentDraft("");
    setDocumentEditError("");
    if (!auth?.access_token) {
      const content = demoDocumentContents[document.document_id] ?? "演示文档暂无正文。";
      setSelectedDocument({
        document,
        version: {
          document_id: document.document_id,
          project_id: document.project_id,
          version: document.current_version,
          format: document.format,
          content,
          sha256: document.current_sha256,
          size_bytes: document.size_bytes,
          storage_ref: `demo://${document.document_id}`,
          change_note: null,
          created_by: document.created_by,
          created_at: document.updated_at,
        },
      });
      setDocumentContentDraft(cleanResearchPresentation(content));
      return;
    }
    try {
      const version = await authApi.getDocumentVersion(
        auth.access_token,
        projectId,
        document.document_id,
        document.current_version,
      );
      setSelectedDocument({ document, version });
      setDocumentTitleDraft(document.title);
      setDocumentContentDraft(cleanResearchPresentation(version.content));
    } catch {
      setSelectedDocument({ document, version: null });
      setDocumentEditError("无法读取文档正文");
    }
  };

  useEffect(() => {
    if (!selectedDocument || selectedDocument.document.document_type !== "manuscript" || !selectedDocument.version || !projectId) return;
    window.dispatchEvent(new CustomEvent("stem-sci:manuscript-context", {
      detail: {
        projectId,
        title: documentTitleDraft || selectedDocument.document.title,
        content: documentContentDraft || selectedDocument.version.content,
      },
    }));
  }, [documentContentDraft, documentTitleDraft, projectId, selectedDocument]);

  const saveSelectedDocument = async () => {
    if (!auth?.access_token || !selectedDocument?.version) return;
    setDocumentEditBusy(true);
    setDocumentEditError("");
    try {
      let nextDocument = selectedDocument.document;
      let nextVersion = selectedDocument.version;
      const nextTitle = documentTitleDraft.trim();
      if (nextTitle && nextTitle !== nextDocument.title) {
        nextDocument = await authApi.updateDocument(
          auth.access_token,
          projectId,
          nextDocument.document_id,
          { title: nextTitle },
        );
      }
      if (documentContentDraft !== selectedDocument.version.content) {
        nextVersion = await authApi.saveDocumentVersion(
          auth.access_token,
          projectId,
          nextDocument.document_id,
          documentContentDraft,
          "在平台编辑论文草稿",
        );
        nextDocument = {
          ...nextDocument,
          current_version: nextVersion.version,
          current_sha256: nextVersion.sha256,
          size_bytes: nextVersion.size_bytes,
          updated_by: nextVersion.created_by,
          updated_at: nextVersion.created_at,
        };
      }
      setDocuments((current) =>
        current.map((item) => item.document_id === nextDocument.document_id ? nextDocument : item),
      );
      setSelectedDocument({ document: nextDocument, version: nextVersion });
      setDocumentTitleDraft(nextDocument.title);
      setDocumentContentDraft(cleanResearchPresentation(nextVersion.content));
    } catch (error) {
      setDocumentEditError(error instanceof Error ? error.message : "保存论文草稿失败");
    } finally {
      setDocumentEditBusy(false);
    }
  };

  const deleteSelectedDocument = async () => {
    if (!auth?.access_token || !selectedDocument) return;
    if (selectedDocument.document.document_type !== "manuscript") return;
    if (!window.confirm(`确定删除“${selectedDocument.document.title}”吗？`)) return;
    setDocumentEditBusy(true);
    setDocumentEditError("");
    try {
      await authApi.deleteDocument(
        auth.access_token,
        projectId,
        selectedDocument.document.document_id,
      );
      setDocuments((current) =>
        current.filter((item) => item.document_id !== selectedDocument.document.document_id),
      );
      setSelectedDocument(null);
    } catch (error) {
      setDocumentEditError(error instanceof Error ? error.message : "删除论文草稿失败");
    } finally {
      setDocumentEditBusy(false);
    }
  };

  const openConversation = async (conversation: ApiConversationSummary) => {
    setConversationId(conversation.conversation_id);
    if (!auth?.access_token) return;
    try {
      // Project-level orchestration history is not chat history.  It may
      // contain old "accepted / task queued" records from another thread;
      // restoring those as bubbles makes a normal question appear to have
      // triggered a workflow.  Keep that history in the research panel only.
      const turns = await authApi.listConversationTurns(
        auth.access_token,
        projectId,
        conversation.conversation_id,
      );
      const restoredGroups: Array<{ createdAt: string; messages: ChatMessage[] }> = [];
      turns.forEach((turn) => {
        restoredGroups.push({
          createdAt: turn.created_at,
          messages: [
            {
              id: `${turn.memory_id}-question`,
              role: "user",
              content: turn.question,
            },
            {
              id: `${turn.memory_id}-answer`,
              role: "assistant",
              content: turn.answer,
              response: {
                project_id: turn.project_id,
                conversation_id: turn.conversation_id,
                question: turn.question,
                turn_id: turn.turn_id ?? turn.memory_id,
                mode: turn.mode ?? "discovery",
                rewritten_query: turn.rewritten_query,
                route: {
                  route: turn.route,
                  reason: "从已保存的对话记录恢复",
                  recommended_agent: null,
                },
                answer: turn.answer,
                citations: turn.citations,
                retrieval_status: "RESTORED",
                retrieval_trace_ref: turn.retrieval_trace_ref,
                context_bundle_ref: null,
                memory_ref: turn.memory_id,
                risk_flags: [],
                answer_mode: "fallback",
                confidence: 0,
                needs_follow_up: false,
                follow_up_question: null,
                tool_calls: [],
                workflow_action: null,
              },
            },
          ],
        });
      });
      restoredGroups.sort((left, right) => left.createdAt.localeCompare(right.createdAt));
      const nextMessages = restoredGroups.flatMap((group) => group.messages);
      if (nextMessages.length) {
        setMessages(nextMessages);
        setSelectedTurnId(nextMessages[nextMessages.length - 1]?.id ?? null);
        const last = turns[turns.length - 1];
        setLastResponse({
          project_id: last.project_id,
          conversation_id: last.conversation_id,
          question: last.question,
          turn_id: last.turn_id ?? last.memory_id,
          mode: last.mode ?? "discovery",
          rewritten_query: last.rewritten_query,
          route: {
            route: last.route,
            reason: "从已保存的对话记录恢复",
            recommended_agent: null,
          },
          answer: last.answer,
          citations: last.citations,
          retrieval_status: "RESTORED",
          retrieval_trace_ref: last.retrieval_trace_ref,
          context_bundle_ref: null,
          memory_ref: last.memory_id,
          risk_flags: [],
          answer_mode: "fallback",
          confidence: 0,
          needs_follow_up: false,
          follow_up_question: null,
          tool_calls: [],
          workflow_action: null,
        });
      }
    } catch {
      // Keep the current view if a stored conversation cannot be restored.
    }
  };

  const restoreOrchestrationConversation = (history: ConversationalHistoryEntry[]) => {
    const restored = history.flatMap((turn) => {
      const response = turn.response;
      const content = response?.message
        ?? (turn.status === "failed" ? "这一轮没有完成，原始研究请求已保留，尚未生成可用结论。" : "这一轮研究请求已保留，等待后台结果。");
      return [
        {
          id: `${turn.turn_id}-question`,
          role: "user" as const,
          content: turn.message,
        },
        {
          id: `${turn.turn_id}-answer`,
          role: "assistant" as const,
          content,
          orchestration: response ?? undefined,
          response: response?.answer,
        },
      ];
    });
    if (!restored.length) return;
    suppressConversationRestoreRef.current = true;
    setMessages(restored);
    const latest = [...history].reverse().find((turn) => turn.response);
    if (latest?.response) {
      setConversationControl(latest.response);
      setOrchestrationState(latest.response.control_state);
      setLastResponse(latest.response.answer ?? null);
      if (latest.response.answer?.conversation_id) {
        setConversationId(latest.response.answer.conversation_id);
      }
      setSelectedTurnId(`${latest.turn_id}-answer`);
    }
  };

  const refreshConversationIndex = () => {
    if (!auth?.access_token || !projectId) return;
    void authApi.listConversations(auth.access_token, projectId)
      .then(setConversations)
      .catch(() => undefined);
  };

  // Conversations are persisted server-side, but the message list is local
  // React state. Rehydrate the most recent conversation after a refresh or a
  // project switch once the project conversation index has loaded.
  useEffect(() => {
    if (!auth?.access_token || !projectId || !conversations.length || conversationId) return;
    if (suppressConversationRestoreRef.current) return;
    void openConversation(conversations[0]);
  }, [auth?.access_token, projectId, conversations, conversationId]);

  // The orchestration journal is the authoritative record for research
  // dialogue. Restore it into the main chat when a project has no locally
  // loaded messages yet; otherwise it remains available in the full journal.
  // This prevents refresh from hiding the actual research reasoning in the
  // right pane while preserving an explicitly opened ordinary QA thread.
  useEffect(() => {
    if (!auth?.access_token || !projectId || !orchestrationHistory.length) return;
    if (suppressConversationRestoreRef.current) return;
    if (messages.length !== 1 || messages[0]?.id !== "welcome") return;
    restoreOrchestrationConversation(orchestrationHistory);
  }, [auth?.access_token, projectId, orchestrationHistory, messages.length, messages[0]?.id]);

  const resetConversation = () => {
    suppressConversationRestoreRef.current = true;
    setConversationId(undefined);
    setMessages([makeWelcome(activeProject?.title ?? "科研项目", true)]);
    setLastResponse(demoMode ? demoQAResponse : null);
    setSelectedTurnId(null);
    setConversationControl(null);
    setOrchestrationState(null);
    setEvidenceReviewPackage(null);
    setConversationGateError("");
  };

  const uploadPrimaryData = async (file: File) => {
    if (!auth?.access_token || !projectId) {
      setConversationGateError("请先登录并选择一个项目");
      return;
    }
    const filename = file.name.toLowerCase();
    if (!/\.(pdf|docx|txt|csv)$/.test(filename)) {
      setConversationGateError("原始资料支持 PDF、DOCX、TXT 或 CSV 文件");
      return;
    }
    setPrimaryDataBusy(true);
    setConversationGateError("");
    try {
      const receipt = await authApi.uploadPrimaryData(auth.access_token, projectId, file);
      setDocuments((current) => [receipt.document, ...current.filter((item) => item.document_id !== receipt.document.document_id)]);
      const nextState = receipt.control_state as unknown as OrchestrationControlState;
      setOrchestrationState(nextState);
      setConversationControl((current) => current ? { ...current, control_state: nextState } : current);
      setMessages((current) => [...current, {
        id: `assistant-data-upload-${Date.now()}`,
        role: "assistant",
        content: "原始资料已登记。请直接说“审计这份原始数据，检查字段、缺失值、重复记录和异常值”，我会开始数据审计。",
      }]);
    } catch (error) {
      setConversationGateError(error instanceof Error ? error.message : "原始资料上传失败");
    } finally {
      setPrimaryDataBusy(false);
      if (primaryDataInputRef.current) primaryDataInputRef.current.value = "";
    }
  };

  const exportResultForSciDAVis = async () => {
    if (!projectId || !effectiveStatisticalResultCard) return;
    setScidavisBusy(true);
    setAnalysisError("");
    try {
      setScidavisExport(await workflowApi.exportResultForSciDAVis(projectId));
    } catch (error) {
      setAnalysisError(error instanceof Error ? error.message : "SciDAVis 导出失败");
    } finally {
      setScidavisBusy(false);
    }
  };

  const workspaceStyle = {
    gridTemplateColumns: workbenchExpanded
      ? `${sidebarVisible ? `${paneWidths.sidebar}px` : "0px"} minmax(0, 1fr)`
      : [
        sidebarVisible ? `${paneWidths.sidebar}px 8px` : "0px 0px",
        rightPaneVisible
          ? "minmax(420px, 1fr) 8px"
          : "minmax(0, 1fr)",
        rightPaneVisible ? `${paneWidths.output}px` : "",
      ].filter(Boolean).join(" "),
  };
  const activeStage = workflowState?.current_stage ?? orchestrationState?.route_decision?.primary_route ?? "INTAKE";
  const activeStageLabel: Record<string, string> = {
    INTAKE: "研究接入",
    SCOPED: "范围确认",
    EVIDENCE_READY: "证据综述",
    STUDY_PROTOCOL_APPROVED: "研究设计",
    DATA_READY: "数据准备",
    ANALYZED: "分析执行",
    DRAFTED: "论文草稿",
    VERIFIED: "独立审查",
    RELEASED: "发布准备",
    WAITING_HUMAN: "等待研究确认",
    REWORK: "需要返工",
    BLOCKED: "流程已阻断",
  };
  const currentStageLabel = activeStageLabel[activeStage] ?? activeStage;
  const evidenceCount = evidenceReviewPackage?.body.coverage.evidence_count ?? citations.length;
  const projectDocumentCount = activeDocuments.length;
  const currentGateLabel = conversationControl?.gate ? gateActionLabel(conversationControl.gate) : "暂无待确认事项";
  const backendStatusLabel = backendStatus === "online"
    ? backendHealth?.service === "stem-sci-demo" ? "演示数据已就绪" : "后端服务已连接"
    : backendStatus === "checking" ? "正在检测后端" : "后端暂不可用";

  if (auth && workspaceMode === null) {
    return (
      <WorkspaceModeSelector
        user={auth.user}
        onSelect={selectWorkspaceMode}
        onSignOut={() => void signOut()}
      />
    );
  }

  if (auth && workspaceMode === "teaching") {
    return (
      <TeachingWorkspaceFrame
        url={starMapWebUrl}
        userLabel={auth.user.display_name ?? auth.user.username}
        onBack={openWorkspaceSelector}
        onSignOut={() => void signOut()}
      />
    );
  }

  return (
    <div className={`research-app ${rightPaneVisible ? "" : "research-app-two-pane"}${workbenchExpanded ? " research-app-workbench-expanded" : ""}`} style={workspaceStyle}>
      <aside className={`research-sidebar ${sidebarVisible ? "" : "research-sidebar-hidden"}`}>
        <div className="research-brand">
          <div className="research-logo">S</div>
          <div>
            <strong>STEM-SSCI/SCI</strong>
            <span>智研育航 · 科研智能工作台</span>
          </div>
          <button
            className="header-icon-button workspace-collapse-button"
            type="button"
            title="隐藏工作区"
            onClick={() => setSidebarVisible(false)}
          >
            &lt;
          </button>
        </div>

        <button className="new-conversation" type="button" onClick={resetConversation}>
          <span className="ui-icon">＋</span>
          新建对话
        </button>

        <div className="sidebar-section">
          <span className="sidebar-label">工作区</span>
          <button
            className={!rightPaneVisible ? "sidebar-link sidebar-link-active" : "sidebar-link"}
            type="button"
            onClick={focusResearchDialogue}
          >
            <span className="ui-icon">◌</span>
            研究对话
          </button>
          <button className={view === "audit" && rightPaneVisible ? "sidebar-link sidebar-link-active" : "sidebar-link"} type="button" onClick={() => openOutputWorkspace(selectedOutputSection, activeOutputWorkbench)}>
            <span className="ui-icon">✦</span>
            产出工作区
          </button>
          <button className={view === "knowledge" && rightPaneVisible ? "sidebar-link sidebar-link-active" : "sidebar-link"} type="button" onClick={openKnowledgeLibrary}>
            <span className="ui-icon">▱</span>
            知识库
          </button>
        </div>

        <div className="sidebar-section project-section">
          <div className="sidebar-section-heading">
            <span className="sidebar-label">项目</span>
            <button className="plain-icon-button" type="button" title="新建项目" onClick={openCreateProject}>＋</button>
          </div>
          <button className="project-select" type="button" onClick={() => setProjectMenuOpen((open) => !open)}>
            <span className="project-avatar">{(activeProject?.title ?? "研").slice(0, 1)}</span>
            <span className="project-select-copy">
              <strong>{activeProject?.title ?? "选择项目"}</strong>
              <small>{activeProject?.research_direction ?? "开始一个研究项目"}</small>
            </span>
            <span className="chevron">{projectMenuOpen ? "<" : ">"}</span>
          </button>
          {projectMenuOpen && (
            <div className="project-menu">
              {projects.map((project) => (
                <button
                  className={project.project_id === projectId ? "project-menu-item selected" : "project-menu-item"}
                  key={project.project_id}
                  type="button"
                  onClick={() => switchProject(project.project_id)}
                >
                  <strong>{project.title}</strong>
                  <small>{project.status === "active" ? "进行中" : "已归档"}</small>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="sidebar-section recent-section">
          <span className="sidebar-label">最近对话</span>
          {conversations.length ? conversations.slice(0, 4).map((conversation) => (
            <button
              className={conversation.conversation_id === conversationId ? "recent-chat selected" : "recent-chat"}
              type="button"
              key={conversation.conversation_id}
              onClick={() => void openConversation(conversation)}
            >
              <strong>{conversation.title || conversation.last_question}</strong>
              <small>{conversation.turn_count} 轮 · {conversation.last_answer_preview.slice(0, 16)}</small>
            </button>
          )) : (
            <button className="recent-chat selected" type="button">
              <strong>{conversationId ? "当前研究讨论" : "研究设计与文献证据"}</strong>
              <small>刚刚 · {(activeProject?.title ?? "科研项目").slice(0, 12)}</small>
            </button>
          )}
          <button className="recent-chat" type="button" onClick={resetConversation}>
            <strong>新建研究问题</strong>
            <small>开始新的研究对话</small>
          </button>
        </div>

        <div className="sidebar-bottom">
          {auth && (
            <button className="workspace-switch-button" type="button" onClick={openWorkspaceSelector}>
              切换助研 / 助学
            </button>
          )}
          <div className={`service-status service-status-${backendStatus}`}>
            <span className="status-pulse" />
            {backendStatusLabel}
          </div>
          {auth ? (
            <button className="account-row" type="button" onClick={() => void signOut()}>
              <span className="account-avatar">{(auth.user.display_name ?? auth.user.username).slice(0, 1)}</span>
              <span><strong>{auth.user.display_name ?? auth.user.username}</strong><small>退出登录</small></span>
              <span className="more-icon">···</span>
            </button>
          ) : (
            <div className="account-row account-row-demo">
              <span className="account-avatar">D</span>
              <span><strong>演示访客</strong><small>登录以保存项目</small></span>
            </div>
          )}
        </div>
      </aside>
      <div className="pane-resizer pane-resizer-sidebar" role="separator" aria-label="调整左侧栏宽度" onPointerDown={() => setDraggingPane("sidebar")} />
      {!sidebarVisible && (
        <button
          className="restore-sidebar-button"
          type="button"
          title="显示工作区"
          onClick={() => setSidebarVisible(true)}
        >
          &gt; <span>显示工作区</span>
        </button>
      )}

      <main className={topResearchInfoOpen ? "chat-pane chat-pane-with-progress" : "chat-pane"}>
        <section className={topResearchInfoOpen ? "research-overview" : "research-overview research-overview-collapsed"} aria-label="当前研究概览">
          <div className="overview-lead">
            <span className="overview-kicker">当前研究概览</span>
            <strong>{currentGateLabel}</strong>
            {topResearchInfoOpen && (
              <p>
                {conversationControl?.gate
                  ? "右侧已准备好需要你确认的研究材料。"
                  : "从一个问题开始，系统会把回答、证据和后续研究动作连起来。"}
              </p>
            )}
          </div>
          {topResearchInfoOpen ? (
            <>
              <div className="overview-stats">
                <div><span>项目资料</span><strong>{projectDocumentCount}</strong><small>份</small></div>
                <div><span>本轮证据</span><strong>{evidenceCount}</strong><small>条</small></div>
                <div><span>研究阶段</span><strong>{currentStageLabel}</strong><small>{auth ? "已同步" : "本地预览"}</small></div>
              </div>
              <div className="overview-actions">
                <button type="button" onClick={openKnowledgeLibrary}><span aria-hidden="true">⌕</span> 查证据</button>
                <button type="button" onClick={() => openOutputWorkspace("data", "data-audit")}><span aria-hidden="true">◫</span> 做分析</button>
                <button type="button" onClick={() => openOutputWorkspace("paper", "paper-review")}><span aria-hidden="true">✦</span> 看产出</button>
              </div>
            </>
          ) : (
            <button className="overview-expand-inline" type="button" onClick={() => setTopResearchInfoOpen(true)}>
              {currentStageLabel} · {projectDocumentCount} 份资料 · {evidenceCount} 条证据
            </button>
          )}
          <button
            className="header-icon-button research-info-toggle"
            type="button"
            title={topResearchInfoOpen ? "收起研究信息" : "展开研究信息"}
            aria-label={topResearchInfoOpen ? "收起研究信息" : "展开研究信息"}
            onClick={() => setTopResearchInfoOpen((open) => !open)}
          >
            {topResearchInfoOpen ? "<" : ">"}
          </button>
        </section>

        {topResearchInfoOpen && (
          <ResearchProgressBoard
            response={lastResponse}
            workflow={workflowState}
            orchestration={orchestrationState}
            evidenceReview={evidenceReviewPackage}
            blockers={projectBlockers}
            tasks={orchestrationTasks}
            onRetryTask={retryOrchestrationTask}
            busy={busy}
          />
        )}

        <div className="chat-dialogue-bar">
          <div>
            <span className="chat-kicker">RESEARCH DIALOGUE</span>
            <strong>研究对话</strong>
          </div>
          <span>{messages.filter((message) => message.role === "user").length} 轮</span>
        </div>

        <section className="chat-thread" aria-live="polite">
          {messages.length === 1 && messages[0].id === "welcome" && (
            <section className="capability-section">
              <div className="capability-panel-heading">
                <div>
                  <span className="chat-kicker">你可以这样开始</span>
                  <h2>把研究问题交给工作台</h2>
                </div>
                <span className="capability-count">4 项能力</span>
              </div>
              <div className="capability-grid">
                {capabilityCards.map((card) => (
                  <button
                    className="capability-card"
                    key={card.title}
                    type="button"
                    onClick={() => void submitQuestion(card.prompt)}
                  >
                    <span className="capability-icon">{card.icon}</span>
                    <strong>{card.title}</strong>
                    <p>{card.description}</p>
                    <span className="capability-arrow">开始使用 &gt;</span>
                  </button>
                ))}
              </div>
            </section>
          )}
          {messages.map((message) => {
            const dialogue = message.orchestration?.dialogue;
            const turnRole = dialogue?.turn_role ?? "answer";
            const isGuidedQuestion = turnRole === "ask_novel";
            const isDecision = turnRole === "decide";
            const showReflection = turnRole === "summarize" || turnRole === "challenge" || turnRole === "wait";
            const showSuggestions = Boolean(
              dialogue?.suggestions.length
              && (isDecision || (!dialogue.turn_role && dialogue.mode !== "co_think")),
            );
            return (
              <article
              className={`${message.role === "user" ? "chat-message user-message" : "chat-message assistant-message"}${message.id === selectedTurnId ? " message-selected" : ""}`}
              key={message.id}
              onClick={() => {
                if (message.role === "assistant" && message.response) setSelectedTurnId(message.id);
              }}
              onKeyDown={(event) => {
                if ((event.key === "Enter" || event.key === " ") && message.role === "assistant" && message.response) {
                  event.preventDefault();
                  setSelectedTurnId(message.id);
                }
              }}
              role={undefined}
              tabIndex={undefined}
            >
              {message.role === "assistant" && <div className="assistant-mark">S</div>}
              <div className="message-body">
                <div className="message-meta">{message.role === "user" ? "你" : "STEM-SCI"} <span>·</span> {message.role === "user" ? "研究问题" : "研究助手"}</div>
                <p>{cleanResearchPresentation(message.content)}</p>
                {message.role === "assistant" && dialogue && (
                  <div className={`dialogue-turn dialogue-turn-${turnRole}`} onClick={(event) => event.stopPropagation()}>
                    {showReflection && (
                      <p className="dialogue-summary">{cleanResearchPresentation(dialogue.summary)}</p>
                    )}
                    {dialogue.question && (isGuidedQuestion || isDecision || dialogue.user_action_required) && (
                      <div className="dialogue-prompt">
                        <span>{isDecision ? "这里需要你来定" : "我想接着确认一个细节"}</span>
                        <p className="dialogue-question">{cleanResearchPresentation(dialogue.question)}</p>
                        {dialogue.why_now && isDecision && (
                          <small>{cleanResearchPresentation(dialogue.why_now)}</small>
                        )}
                      </div>
                    )}
                    {dialogue.evidence && dialogue.evidence.length > 0 && (
                      <div className="dialogue-evidence" aria-label="本轮判断依据">
                        <strong>本轮依据</strong>
                        {dialogue.evidence.map((item, index) => (
                          <button
                            className="dialogue-evidence-card"
                            type="button"
                            key={`${item.title}-${index}`}
                            onClick={() => {
                              const citation = message.response?.citations.find((candidate) =>
                                item.evidence_id && (candidate.canonical_chunk_id === item.evidence_id || candidate.canonical_paper_id === item.evidence_id),
                              );
                              if (citation) openCitationDetails(citation);
                            }}
                            disabled={!message.response?.citations.some((candidate) => item.evidence_id && (candidate.canonical_chunk_id === item.evidence_id || candidate.canonical_paper_id === item.evidence_id))}
                            title="打开来源定位"
                          >
                            <span>{item.title}</span>
                            <p>{cleanResearchPresentation(item.excerpt)}</p>
                            <small>{item.role ?? "依据"} · {item.verification_status} · {item.locator_status}</small>
                          </button>
                        ))}
                      </div>
                    )}
                    {isDecision && dialogue.tradeoffs && dialogue.tradeoffs.length > 0 && (
                      <div className="dialogue-tradeoffs">
                        <strong>取舍与边界</strong>
                        {dialogue.tradeoffs.map((item, index) => <p key={`${item}-${index}`}>{cleanResearchPresentation(item)}</p>)}
                      </div>
                    )}
                    {dialogue.branches && dialogue.branches.length > 0 && isDecision && (
                      <div className="dialogue-branches" aria-label="研究路径比较">
                        <strong>研究路径比较</strong>
                        <div className="dialogue-branch-grid">
                          {dialogue.branches.map((branch) => (
                            <article className="dialogue-branch" key={branch.id}>
                              <h4>{branch.title}</h4>
                              <p>{cleanResearchPresentation(branch.description)}</p>
                              <div><b>收益：</b>{branch.benefits.join("；")}</div>
                              <div><b>风险：</b>{branch.risks.join("；")}</div>
                              <div><b>前置：</b>{branch.prerequisites.join("；")}</div>
                              <button type="button" disabled={busy} onClick={() => void chooseDialogueBranch(branch)}>选择这条路径</button>
                            </article>
                          ))}
                        </div>
                      </div>
                    )}
                    {dialogue.version_change && (turnRole === "summarize" || isDecision) && (
                      <div className="dialogue-version-change" aria-label="共享研究地图版本变化">
                        <strong>这次选择改变了什么</strong>
                        <span>研究地图 v{dialogue.version_change.from_version} → v{dialogue.version_change.to_version}</span>
                        {dialogue.version_change.added.length > 0 && (
                          <p><b>新增：</b>{dialogue.version_change.added.join("；")}</p>
                        )}
                        {dialogue.version_change.changed.length > 0 && (
                          <p><b>变化：</b>{dialogue.version_change.changed.join("；")}</p>
                        )}
                        {dialogue.version_change.implications.length > 0 && (
                          <p><b>研究影响：</b>{dialogue.version_change.implications.join("；")}</p>
                        )}
                      </div>
                    )}
                    {showSuggestions && (
                      <div className="dialogue-suggestions" aria-label="研究协作选项">
                        {dialogue.suggestions.map((suggestion) => (
                          <button
                            key={suggestion.id}
                            type="button"
                            disabled={busy}
                            onClick={() => void submitQuestion(suggestion.message)}
                            title={suggestion.message}
                          >
                            {suggestion.label}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}
                {message.attachments && message.attachments.length > 0 && (
                  <div className="message-attachments" aria-label="本条消息的附件">
                    {message.attachments.map((attachment) => (
                      <span className="message-attachment" key={attachment.id}>
                        <strong>{attachment.kind}</strong>
                        <span>{attachment.name}</span>
                        <small>{attachment.sizeLabel}</small>
                      </span>
                    ))}
                  </div>
                )}
              </div>
              </article>
            );
          })}
          {busy && (
            <article className="chat-message assistant-message">
              <div className="assistant-mark">S</div>
              <div className="message-body typing-state"><span /><span /><span /><small>正在结合当前研究上下文回答…</small></div>
            </article>
          )}
        </section>

        <section className="composer-area">
          <div className="composer-box">
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void submitQuestion();
                }
              }}
              placeholder="直接提问、比较方案、补充条件或修改想法..."
              rows={3}
            />
            {chatAttachments.length > 0 && (
              <div className="attachment-preview" aria-label="待发送附件">
                {chatAttachments.map((attachment) => (
                  <div className="attachment-chip" key={attachment.id}>
                    <span className="attachment-chip-kind">{attachment.kind}</span>
                    <span className="attachment-chip-copy">
                      <strong>{attachment.name}</strong>
                      <small>{attachment.sizeLabel}</small>
                    </span>
                    <button
                      className="attachment-remove"
                      type="button"
                      title={`移除 ${attachment.name}`}
                      onClick={() => removeChatAttachment(attachment.id)}
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            )}
            {attachmentError && <p className="attachment-error">{attachmentError}</p>}
            {conversationGateError && <p className="attachment-error" role="alert">{conversationGateError}</p>}
            <div className="composer-toolbar">
              <div className="composer-tools">
                {conversationControl?.gate?.status === "PENDING" && conversationControl.gate.gate_type === "raw_data_import_approval" && (
                  <>
                    <button
                      className="composer-tool"
                      type="button"
                      disabled={primaryDataBusy}
                      title="上传去标识化原始数据"
                      onClick={() => primaryDataInputRef.current?.click()}
                    >
                      ↥ <span>{primaryDataBusy ? "登记中" : "上传数据"}</span>
                    </button>
                  </>
                )}
                <button
                  className="composer-tool composer-attach-tool"
                  type="button"
                  title="添加研究材料或 CSV 数据"
                  onClick={() => chatAttachmentInputRef.current?.click()}
                >
                  ＋
                </button>
                <input
                  ref={chatAttachmentInputRef}
                  className="visually-hidden"
                  type="file"
                  multiple
                  accept=".pdf,.doc,.docx,.csv,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/csv,image/*"
                  onChange={(event) => selectChatFiles(event.target.files)}
                />
                <button
                  className="composer-tool"
                  type="button"
                  title="打开知识库证据"
                  onClick={openKnowledgeLibrary}
                >
                  ▱ <span>知识库</span>
                </button>
                <button
                  className="composer-tool"
                  type="button"
                  title="打开产出工作区"
                  onClick={() => openOutputWorkspace(selectedOutputSection, activeOutputWorkbench)}
                >
                  ✦ <span>产出</span>
                </button>
                <button
                  className="composer-tool"
                  type="button"
                  disabled={mode === "discovery" && !corpusSummary?.formal_evidence_ready}
                  title={corpusSummary?.formal_evidence_ready ? "切换正式证据或探索模式" : "正式证据尚未满足来源定位和核验条件"}
                  onClick={() => {
                    if (mode === "discovery" && !corpusSummary?.formal_evidence_ready) return;
                    setMode((current) => current === "discovery" ? "formal" : "discovery");
                  }}
                >
                  ◈ <span>{mode === "formal" ? "正式" : "探索"}</span>
                </button>
              </div>
              <button className="send-button" type="button" disabled={busy || !question.trim() || !activeProject} onClick={() => void submitQuestion()} title={activeProject ? "发送消息" : "请先选择项目"}>↑</button>
            </div>
          </div>
          <input
            ref={primaryDataInputRef}
            className="visually-hidden"
            type="file"
            accept=".pdf,.docx,.txt,.csv,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/csv"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void uploadPrimaryData(file);
            }}
          />
          <input
            ref={evidenceInputRef}
            className="visually-hidden"
            type="file"
            accept=".pdf,.txt,.md,.json,application/pdf,text/plain,application/json"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void uploadEvidenceSource(file);
            }}
          />
          <p className="composer-note">研究状态会在后台随对话更新；数据冻结、执行和发布等高风险动作仍会单独向你确认。</p>
        </section>
      </main>

      <div className="pane-resizer pane-resizer-output" role="separator" aria-label="调整右侧栏宽度" onPointerDown={() => setDraggingPane("output")} />
      <aside className={`output-pane ${view === "knowledge" ? "output-pane-knowledge" : ""} ${rightPaneVisible ? "" : "output-pane-hidden"}`}>
        <div className="output-header">
          <div>
            <span className="chat-kicker">{view === "knowledge" ? "长期知识库" : "当前对话产出"}</span>
          <h2>{view === "knowledge" ? "知识库" : selectedOutputCard.title}</h2>
          </div>
          <button className="header-icon-button" type="button" title="隐藏右侧面板，进入双栏模式" onClick={focusResearchDialogue}>&gt;</button>
        </div>
        {contextTab === "agent-work" && (
          <div className="output-content">
            {researchCanvas && researchCanvas.nodes.length > 0 && (
              <section className="output-section evidence-review-package">
                <div className="output-section-heading">
                  <div>
                    <span className="chat-kicker">RESEARCH CANVAS</span>
                    <h3>共享研究画布</h3>
                    <p className="section-subtitle">记录当前研究目的、假设、约束、证据和争议；所有判断都可以追溯并继续修订。</p>
                  </div>
                  <span>版本 {researchCanvas.version}</span>
                </div>
                <div className="evidence-package-matrix">
                  {researchCanvas.nodes
                    .filter((node) => node.node_type !== "evidence")
                    .slice(-10)
                    .map((node) => {
                      const nodeLabels: Record<string, string> = {
                        objective: "研究目的",
                        question: "研究问题",
                        concept: "核心概念",
                        hypothesis: "假设",
                        assumption: "待检验假设",
                        design: "研究设计",
                        constraint: "现实约束",
                        decision: "当前决定",
                        uncertainty: "关键未知",
                      };
                      const statusLabels: Record<string, string> = {
                        established: "已有支持",
                        tentative: "暂定",
                        disputed: "存在争议",
                        rejected: "已否定",
                        frozen: "已冻结",
                      };
                      return (
                        <article key={node.node_id}>
                          <div>
                            <strong>{nodeLabels[node.node_type] ?? node.node_type}</strong>
                            <span className={node.status === "established" ? "verified-tag" : "review-tag"}>
                              {statusLabels[node.status] ?? node.status}
                            </span>
                          </div>
                          <p>{node.content}</p>
                          <small>置信度：{node.confidence === "high" ? "高" : node.confidence === "medium" ? "中" : "低"}</small>
                        </article>
                      );
                    })}
                </div>
                {researchCanvas.nodes.some((node) => node.node_type === "evidence") && (
                  <div className="evidence-package-block">
                    <div className="evidence-package-block-heading">
                      <strong>关联证据</strong>
                      <span>{researchCanvas.nodes.filter((node) => node.node_type === "evidence").length} 条</span>
                    </div>
                    <div className="evidence-package-matrix">
                      {researchCanvas.nodes
                        .filter((node) => node.node_type === "evidence")
                        .slice(-6)
                        .map((node) => (
                          <article key={node.node_id}>
                            <div>
                              <strong>{node.status === "established" ? "已核验证据" : "待核验候选"}</strong>
                              <span className={node.status === "established" ? "verified-tag" : "review-tag"}>{node.confidence}</span>
                            </div>
                            <p>{node.content}</p>
                          </article>
                        ))}
                    </div>
                  </div>
                )}
                {researchCanvas.edges.length > 0 && (
                  <div className="evidence-package-block">
                    <div className="evidence-package-block-heading">
                      <strong>主张—证据关系</strong>
                      <span>{researchCanvas.edges.length} 条关系</span>
                    </div>
                    <div className="claim-evidence-links">
                      {researchCanvas.edges.slice(-10).reverse().map((edge, index) => {
                        const source = researchCanvas.nodes.find((node) => node.node_id === edge.source_id);
                        const target = researchCanvas.nodes.find((node) => node.node_id === edge.target_id);
                        const relationLabel = edge.relation === "supports" ? "支持" : edge.relation === "contradicts" ? "反驳" : edge.relation === "chosen_over" ? "优先于" : edge.relation;
                        return (
                          <div className={`claim-evidence-link ${edge.relation === "contradicts" ? "claim-evidence-link-challenge" : ""}`} key={`${edge.source_id}-${edge.target_id}-${index}`}>
                            <span>{source?.node_type === "evidence" ? "证据" : "研究判断"}</span>
                            <p>{source?.content ?? edge.source_id}</p>
                            <b>{relationLabel}</b>
                            <span>{target?.node_type === "evidence" ? "证据" : "研究判断"}</span>
                            <p>{target?.content ?? edge.target_id}</p>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
                {researchCanvas.revisions.length > 0 && (
                  <div className="evidence-package-warning">
                    <strong>新证据改变了什么</strong>
                    {researchCanvas.revisions.slice(-3).reverse().map((revision, index) => (
                      <p key={`${String(revision.node_id ?? "revision")}-${index}`}>
                        {String(revision.previous_status ?? "-")} → {String(revision.new_status ?? "-")}：{String(revision.reason ?? "研究判断已更新")}
                        {Array.isArray(revision.research_consequences) && revision.research_consequences.length > 0 ? ` 研究影响：${revision.research_consequences.join("；")}` : ""}
                      </p>
                    ))}
                  </div>
                )}
              </section>
            )}
            {researchBranches.length > 0 && (
              <section className="output-section evidence-review-package">
                <div className="output-section-heading">
                  <div>
                    <span className="chat-kicker">RESEARCH BRANCHES</span>
                    <h3>研究路线分支</h3>
                    <p className="section-subtitle">路线可以先比较、搁置或重新激活；选择路线不会替代正式研究确认。</p>
                  </div>
                  <span>{researchBranches.length} 条</span>
                </div>
                <div className="evidence-package-matrix">
                  {researchBranches.map((branch) => (
                    <article key={branch.branch_id}>
                      <div>
                        <strong>{branch.title}</strong>
                        <span className={branch.status === "selected" ? "verified-tag" : branch.status === "parked" ? "review-tag" : "review-tag"}>
                          {branch.status === "selected" ? "当前选择" : branch.status === "parked" ? "已搁置" : branch.status === "rejected" ? "已排除" : "待比较"}
                        </span>
                      </div>
                      <p>{branch.description}</p>
                      {branch.risks.length > 0 && <small>主要风险：{branch.risks.slice(0, 2).join("；")}</small>}
                    </article>
                  ))}
                </div>
              </section>
            )}
            {(latestResearchQuestion || latestStudyProtocol) && (
              <section className="output-section evidence-review-package">
                <div className="output-section-heading">
                  <div>
                    <span className="chat-kicker">RESEARCH DESIGN</span>
                    <h3>研究设计候选</h3>
                    <p className="section-subtitle">以下内容来自当前证据和研究澄清记录；确认预注册前仍可在左侧对话修改。</p>
                  </div>
                  <span className="review-tag">待确认</span>
                </div>
                {asText(latestResearchQuestion?.body.primary_question) && (
                  <div className="evidence-package-synthesis">
                    <span>主要研究问题</span>
                    <p>{asText(latestResearchQuestion?.body.primary_question)}</p>
                  </div>
                )}
                <div className="evidence-package-matrix">
                  {asText(latestStudyProtocol?.body.primary_outcome) && <article><div><strong>主要结果</strong></div><p>{asText(latestStudyProtocol?.body.primary_outcome)}</p></article>}
                  {asText(latestStudyProtocol?.body.design_type) && <article><div><strong>研究设计</strong></div><p>{asText(latestStudyProtocol?.body.design_type)}</p></article>}
                  {asText(latestStudyProtocol?.body.sampling_approach) && <article><div><strong>样本与分组</strong></div><p>{asText(latestStudyProtocol?.body.sampling_approach)}</p></article>}
                </div>
              </section>
            )}
            {latestDataAudit && (
              <section className="output-section evidence-review-package">
                <div className="output-section-heading">
                  <div>
                    <span className="chat-kicker">DATA AUDIT</span>
                    <h3>原始数据审计</h3>
                    <p className="section-subtitle">这是原始数据的只读审计结果；冻结前请确认字段、缺失和处理边界。</p>
                  </div>
                  <span className={dataAuditDetails?.passed === true ? "verified-tag" : "review-tag"}>{dataAuditDetails?.passed === true ? "已完成" : "需复核"}</span>
                </div>
                <div className="evidence-package-metrics">
                  <div><span>行数</span><strong>{String(dataAuditDetails?.row_count ?? dataManifest?.row_count ?? "-")}</strong></div>
                  <div><span>列数</span><strong>{String(dataAuditDetails?.column_count ?? (auditColumns.length || "-"))}</strong></div>
                  <div><span>重复记录</span><strong>{String(dataAuditDetails?.duplicate_row_count ?? "-")}</strong></div>
                  <div><span>缺失字段</span><strong>{String(Object.keys(missingByColumn ?? {}).filter((key) => Number(missingByColumn?.[key] ?? 0) > 0).length)}</strong></div>
                </div>
                {auditColumns.length > 0 && <div className="evidence-package-synthesis"><span>字段概览</span><p>{auditColumns.join("、")}</p></div>}
                <div className="evidence-package-matrix">
                  <article><div><strong>缺失值检查</strong></div><p>{missingByColumn && Object.keys(missingByColumn).length ? Object.entries(missingByColumn).map(([column, count]) => `${column}: ${count}`).join("；") : "未发现缺失值"}</p></article>
                  <article><div><strong>数据质量提示</strong></div><p>{Array.isArray(dataAuditDetails?.risk_flags) && dataAuditDetails.risk_flags.length ? dataAuditDetails.risk_flags.filter((item): item is string => typeof item === "string").join("；") : "未发现需要阻断后续分析的数据质量问题"}</p></article>
                </div>
              </section>
            )}
            {evidenceReviewPackage && (
              <section className="output-section evidence-review-package">
                <div className="output-section-heading">
                  <div>
                    <span className="chat-kicker">AI RESEARCH OUTPUT</span>
                    <h3>文献与证据审阅包</h3>
                    <p className="section-subtitle">{evidenceReviewPackage.body.research_scope}</p>
                  </div>
                  <span className={evidenceReviewPackage.body.status === "READY" ? "verified-tag" : "review-tag"}>
                    {evidenceReviewPackage.body.status === "READY" ? "可审阅" : "待补充"}
                  </span>
                </div>
                <div className="evidence-package-metrics">
                  <div><span>来源</span><strong>{evidenceReviewPackage.body.coverage.source_count}</strong></div>
                  <div><span>本轮新增来源</span><strong>{evidenceReviewPackage.body.coverage.new_source_count ?? evidenceReviewPackage.body.coverage.source_count}</strong></div>
                  <div><span>重复/已存在</span><strong>{evidenceReviewPackage.body.coverage.duplicate_source_count ?? 0}</strong></div>
                  <div><span>证据片段</span><strong>{evidenceReviewPackage.body.coverage.evidence_count}</strong></div>
                  <div><span>证据对应</span><strong>{evidenceReviewPackage.body.evidence_matrix.length}</strong></div>
                </div>
                <p className="evidence-package-limit">联网候选仅供筛选；导入原文并核验页码后，才能作为正式引用。</p>
                {(evidenceReviewPackage.body.coverage.external_candidate_count ?? 0) > 0 && (
                  <p className="evidence-package-limit">本轮联网候选：{evidenceReviewPackage.body.coverage.external_candidate_count} 篇，尚未计入正式证据。</p>
                )}
                {evidenceReviewPackage.body.synthesis?.summary && (
                  <div className="evidence-package-synthesis">
                    <span>当前综合</span>
                    <p>{evidenceReviewPackage.body.synthesis.summary}</p>
                    {evidenceReviewPackage.body.synthesis.corpus_limit && <small>{evidenceReviewPackage.body.synthesis.corpus_limit}</small>}
                  </div>
                )}
                {evidenceReviewPackage.body.coverage.missing_requirements.length > 0 && (
                  <div className="evidence-package-warning">
                    <strong>仍需补充</strong>
                    {evidenceReviewPackage.body.coverage.missing_requirements.map((item) => <p key={item}>{item}</p>)}
                  </div>
                )}
                <div className="evidence-package-block">
                  <div className="evidence-package-block-heading"><strong>主张—证据矩阵</strong><span>{evidenceReviewPackage.body.evidence_matrix.length} 条</span></div>
                  {evidenceReviewPackage.body.evidence_matrix.length ? (
                    <div className="evidence-package-matrix">
                      {evidenceReviewPackage.body.evidence_matrix.slice(0, 8).map((row, index) => (
                        <article key={row.row_id ?? `${row.source_ref}-${index}`}>
                          <div><span className={`evidence-relation evidence-relation-${(row.relation ?? "MENTIONING").toLowerCase()}`}>{row.relation === "SUPPORTING" ? "支持" : row.relation === "CONTRASTING" ? "冲突" : "相关"}</span><small>{evidenceSourceLabel(row.source_ref)}</small></div>
                          <p>{row.finding ?? "未提供可读摘录"}</p>
                          {row.applicability_boundary && <small>{row.applicability_boundary}</small>}
                        </article>
                      ))}
                    </div>
                  ) : <p className="evidence-package-empty">当前还没有可供审阅的主张—证据对应。请补充材料后重新整理。</p>}
                </div>
                {evidenceReviewPackage.body.research_gap_report?.gaps?.length ? (
                  <div className="evidence-package-block">
                    <div className="evidence-package-block-heading"><strong>证据缺口</strong><span>{evidenceReviewPackage.body.research_gap_report.gaps.length} 项</span></div>
                    <ul className="evidence-gap-list">
                      {evidenceReviewPackage.body.research_gap_report.gaps.map((gap, index) => <li key={gap.gap_id ?? index}>{gap.description ?? "未命名证据缺口"}</li>)}
                    </ul>
                    {evidenceReviewPackage.body.research_gap_report.limit_text && <small className="evidence-package-limit">{evidenceReviewPackage.body.research_gap_report.limit_text}</small>}
                  </div>
                ) : null}
                {evidenceReviewPackage.body.retrieval_trace.length > 0 && (
                  <div className="evidence-package-trace" aria-label="已完成的内部证据步骤">
                    {Array.from(new Map(evidenceReviewPackage.body.retrieval_trace.map((item) => [item.step || item.label, item])).values())
                      .map((item) => <span key={item.step || item.label}>✓ {item.label}</span>)}
                  </div>
                )}
              </section>
            )}
            {projectClaims.length > 0 && (
              <section className="output-section evidence-review-package">
                <div className="output-section-heading">
                  <div>
                    <span className="chat-kicker">MANUSCRIPT TRACE</span>
                    <h3>论文主张链</h3>
                    <p className="section-subtitle">每条主张都显示其已登记的证据、结果卡或冻结资料引用。</p>
                  </div>
                  <span>{projectClaims.length} 条</span>
                </div>
                <div className="evidence-package-matrix">
                  {projectClaims.slice(0, 12).map((claim) => {
                    const refs = [
                      ...claim.support_evidence_ids,
                      ...claim.support_result_ids,
                      ...claim.support_artifact_ids,
                    ];
                    return (
                      <article key={claim.claim_id}>
                        <div><span className="review-tag">{claim.claim_type}</span><small>{claim.section}</small></div>
                        <p>{claim.claim_text}</p>
                        <small>{refs.length ? `关联：${refs.join("、")}` : `依据：${claim.support_type}`}</small>
                      </article>
                    );
                  })}
                </div>
              </section>
            )}
            <section className="output-section agent-workbench">
              <div className="output-section-heading">
                <div>
                  <span className="chat-kicker">PUBLICATION SETTINGS</span>
                  <h3>投稿设置</h3>
                  <p className="section-subtitle">仅在写作阶段需要时配置目标期刊；研究推进和后台处理均由对话自动完成。</p>
                </div>
              </div>
              <div className="publication-target-form">
                <span>投稿目标</span>
                <select
                  aria-label="目标期刊"
                  value={publicationTarget}
                  disabled={!projectId || publicationTargetBusy}
                  onChange={(event) => {
                    const journal = event.target.value;
                    setPublicationTarget(journal);
                    setPublicationArticleType(
                      journal === "IEEE Transactions on Education" ? "Application"
                        : journal === "International Journal of Science and Mathematics Education" ? "Original Research Article"
                          : journal === "Journal of Science Education and Technology" ? "Original Paper"
                            : "Research Article",
                    );
                  }}
                >
                  <option>International Journal of STEM Education</option>
                  <option>IEEE Transactions on Education</option>
                  <option>International Journal of Science and Mathematics Education</option>
                  <option>Journal of Science Education and Technology</option>
                  <option>STEM Education</option>
                </select>
                <select
                  aria-label="文章类型"
                  value={publicationArticleType}
                  disabled={!projectId || publicationTargetBusy}
                  onChange={(event) => setPublicationArticleType(event.target.value)}
                >
                  {publicationTarget === "IEEE Transactions on Education" ? <>
                    <option>Application</option><option>Discovery</option><option>Integration</option>
                  </> : publicationTarget === "International Journal of Science and Mathematics Education" ? <>
                    <option>Original Research Article</option><option>Review Article</option>
                  </> : publicationTarget === "Journal of Science Education and Technology" ? <>
                    <option>Original Paper</option><option>Review Paper</option>
                  </> : <><option>Research Article</option><option>Review Article</option></>}
                </select>
                <button
                  className="secondary-inline-button"
                  type="button"
                  disabled={!projectId || publicationTargetBusy}
                  onClick={() => void configurePublicationTarget()}
                >{publicationTargetBusy ? "保存中..." : "启用投稿格式化"}</button>
                {orchestrationState?.target_journal && <small>当前：{orchestrationState.target_journal} · {orchestrationState.article_type}</small>}
                {publicationTargetError && <p className="workflow-control-error" role="alert">{publicationTargetError}</p>}
              </div>
              {conversationCommitGate ? (
                <p className="workflow-control-note">
                  这一步会{gateActionLabel(conversationCommitGate)}，属于正式研究提交。我会在执行前说明影响；你可以直接确认，也可以先继续讨论。
                </p>
              ) : conversationControl?.gate ? (
                <p className="workflow-control-note">我已经整理好相关研究材料。你可以直接提出疑问、修改范围或选择一个方向，不需要记住内部阶段；我会根据你的判断继续整理。</p>
              ) : conversationControl?.checkpoint ? (
                <p className="workflow-control-note">我们正在共同讨论{conversationControl.checkpoint === "RESEARCH_QUESTION_REVIEW" ? "研究问题" : conversationControl.checkpoint === "RESEARCH_DESIGN_REVIEW" ? "研究方案" : conversationControl.checkpoint === "RESULT_INTERPRETATION_REVIEW" ? "结果解释边界" : "论文大纲"}。你可以选择、质疑、改写，或先问我为什么这样建议。</p>
              ) : (
                <p className="workflow-control-note">系统会在后台整理证据、方案、代码和论文候选；你可以随时插入新的问题或改变方向。</p>
              )}
              {conversationControl?.gate?.gate_type === "reviewer_final_confirmation_approval" && activeProject?.role === "owner" && (
                <div className="reviewer-assignment-control">
                  <input
                    value={reviewerUsername}
                    onChange={(event) => setReviewerUsername(event.target.value)}
                    placeholder="已注册审稿人用户名"
                    aria-label="独立审稿人用户名"
                  />
                  <button type="button" className="secondary-inline-button" disabled={reviewerBusy || !reviewerUsername.trim()} onClick={() => void addIndependentReviewer()}>
                    {reviewerBusy ? "添加中..." : "添加独立审稿人"}
                  </button>
                </div>
              )}
            </section>
            {legacyAgentPlannerEnabled && (<section className="output-section agent-workbench">
              <div className="output-section-heading">
                <div>
                  <span className="chat-kicker">WORK TASKS</span>
                  <h3>Agent 工作台</h3>
                  <p className="section-subtitle">先生成计划，批准后执行；所有输出先进入产出箱。</p>
                </div>
              </div>
              {agentPlan?.user_request && (
                <div className="agent-current-question">
                  <span>本轮研究问题</span>
                  <p>{agentPlan.user_request}</p>
                </div>
              )}
              <label className="agent-plan-input">
                <span>研究需求</span>
                <textarea rows={4} value={agentPlanDraft} onChange={(event) => setAgentPlanDraft(event.target.value)} placeholder="描述本轮需要完成的研究任务..." />
              </label>
              <button className="primary-inline-button full-width" type="button" disabled={agentPlanBusy || !agentPlanDraft.trim()} onClick={() => void createAgentPlan()}>
                {agentPlanBusy ? "处理中..." : "生成 Agent 计划"}
              </button>
              {agentPlans.length > 0 && (
                <div className="agent-question-history" aria-label="Agent 使用问题记录">
                  <span>Agent 使用记录</span>
                  {agentPlans.slice(0, 8).map((plan) => (
                    <button
                      key={plan.plan_id}
                      className={agentPlan?.plan_id === plan.plan_id ? "selected" : ""}
                      type="button"
                      onClick={() => selectAgentQuestion(plan)}
                    >
                      <strong>{plan.user_request}</strong>
                      <small>{plan.tasks.filter((task) => task.status === "COMPLETED").length}/{plan.tasks.length} 已完成 · {agentPlanStatusLabels[plan.status] ?? plan.status}</small>
                    </button>
                  ))}
                </div>
              )}
              {agentPlan && (
                <>
                  <div className="agent-work-plan-head">
                    <div><strong>{agentPlan.user_request}</strong><small>{agentPlan.intent_summary} · {agentPlan.planner_mode === "llm" ? "模型规划" : "受控规则规划"} · {agentPlanStatusLabels[agentPlan.status] ?? agentPlan.status}</small></div>
                    <span>{agentPlan.tasks.filter((task) => task.status === "COMPLETED").length}/{agentPlan.tasks.length} 完成</span>
                  </div>
                  <div className="agent-progress-track" aria-label="Agent 计划进度">
                    <i style={{ width: `${agentPlan.tasks.length ? Math.round(agentPlan.tasks.filter((task) => task.status === "COMPLETED").length / agentPlan.tasks.length * 100) : 0}%` }} />
                  </div>
                  <div className="agent-work-task-list">
                    {agentPlan.tasks.map((task) => {
                      const selected = selectedAgentTaskIds.includes(task.task_id);
                      const disabled = task.blocked_reason !== null || task.status === "SKIPPED";
                      return (
                        <label className={`agent-work-task ${disabled ? "agent-plan-task-disabled" : ""}`} key={task.task_id}>
                          <input type="checkbox" checked={selected} disabled={disabled || agentPlan.status !== "PENDING_APPROVAL"} onChange={() => toggleAgentTask(task.task_id)} />
                          <span><strong>{agentDisplayNames[task.agent_id] ?? task.agent_id}</strong><small>{task.reason}</small>{task.persisted_artifact_ids.length > 0 && <small>已生成 {task.persisted_artifact_ids.length} 项候选产出</small>}{task.review_note && <small>审核意见：{task.review_note}</small>}{task.error && <em>{task.error}</em>}{task.blocked_reason && <em>{task.blocked_reason}</em>}</span>
                          <b className={`agent-task-status agent-task-status-${task.status.toLowerCase()}`}>{agentTaskStatusLabels[task.status] ?? task.status}</b>
                        </label>
                      );
                    })}
                  </div>
                  {agentPlan.status === "PENDING_APPROVAL" ? (
                    <>
                      <div className="agent-execution-mode" role="group" aria-label="Agent 执行方式">
                        <button className={agentExecutionMode === "automatic" ? "selected" : ""} type="button" onClick={() => setAgentExecutionMode("automatic")}>全自动</button>
                        <button className={agentExecutionMode === "stepwise" ? "selected" : ""} type="button" onClick={() => setAgentExecutionMode("stepwise")}>逐步人工</button>
                        <small>{agentExecutionMode === "automatic" ? "按任务依赖自动执行，完成后统一审查。" : "每个 Agent 产出后暂停，确认后才继续下一步。"}</small>
                      </div>
                      <div className="agent-plan-actions">
                        <button className="secondary-inline-button" type="button" disabled={agentPlanBusy} onClick={() => void rejectAgentPlan()}>拒绝计划</button>
                        <button className="primary-inline-button" type="button" disabled={agentPlanBusy || selectedAgentTaskIds.length === 0} onClick={() => void approveAndExecuteAgentPlan()}>{agentPlanBusy ? "执行中..." : agentExecutionMode === "automatic" ? "批准并全自动执行" : "批准并执行第一项"}</button>
                      </div>
                    </>
                  ) : agentPlan.status === "WAITING_TASK_APPROVAL" ? (
                    <div className="agent-step-review">
                      <p>当前候选产出等待人工确认。确认后才会执行下一项 Agent。</p>
                      <div className="agent-plan-actions">
                        <button className="secondary-inline-button" type="button" disabled={agentPlanBusy} onClick={() => void continueStepwiseAgentPlan("rework")}>退回到对话修改</button>
                        <button className="primary-inline-button" type="button" disabled={agentPlanBusy} onClick={() => void continueStepwiseAgentPlan("approved")}>{agentPlanBusy ? "处理中..." : "确认并继续"}</button>
                      </div>
                    </div>
                  ) : agentPlan.status === "REWORK_REQUIRED" ? (
                    <div className="agent-step-review agent-step-rework">
                      <p>{agentPlan.rework_note || "当前步骤已退回。请在对话框补充修改要求，再生成新的 Agent 计划。"}</p>
                      <button className="secondary-inline-button" type="button" onClick={() => document.querySelector<HTMLTextAreaElement>(".composer-box textarea")?.focus()}>继续在对话中修改</button>
                    </div>
                  ) : null}
                  {agentPlan.risk_flags.map((flag) => <p className="workflow-control-error" key={flag}>{riskFlagText(flag)}</p>)}
                </>
              )}
              {agentPlanError && <p className="workflow-control-error" role="alert">{agentPlanError}</p>}
            </section>)}
            {legacyAgentPlannerEnabled && (agentOutputs.length > 0) && <section className="output-section agent-workbench-output">
              <div className="output-section-heading">
                <div><h3>Agent 产出</h3><p className="section-subtitle">候选输出需要人工保留或应用；证据通过核验后才可提升为正式证据。</p></div>
                <button className="plain-action" type="button" onClick={() => setAgentOutputBoxOpen((open) => !open)}>{agentOutputBoxOpen ? "收起产出" : "展开产出"}</button>
              </div>
              <div className="agent-output-scope" role="tablist" aria-label="Agent 产出范围">
                <button className={agentOutputScope === "turn" ? "selected" : ""} type="button" onClick={() => setAgentOutputScope("turn")}>当前对话轮次 {activeTurnOutputs.length}</button>
                <button className={agentOutputScope === "question" ? "selected" : ""} type="button" disabled={!agentPlan} onClick={() => setAgentOutputScope("question")}>所选问题 {selectedQuestionOutputs.length}</button>
                <button className={agentOutputScope === "project" ? "selected" : ""} type="button" onClick={() => setAgentOutputScope("project")}>项目全部 {agentOutputs.length}</button>
              </div>
              {visibleAgentOutputs.length ? (
                <div className="agent-output-list">{visibleAgentOutputs.map((output) => renderAgentOutputCard(output, !agentOutputBoxOpen))}</div>
              ) : <div className="empty-output"><span className="empty-symbol">✦</span><p>系统自动生成的候选产物会在这里显示，供你审阅和确认。</p></div>}
            </section>
            }
            {renderPageMaterials("审查结论与修改请求", ["audit_validation"])}
            {agentOutputs.some((output) => output.agent_id === "evidence_review") && (
              <section className="output-section evidence-gate-link-section">
                <div className="output-section-heading">
                  <div>
                    <h3>证据核验与正式化</h3>
                    <p className="section-subtitle">证据 Agent 的结果先在这里审核；完成来源核验后，才能申请进入正式证据库。</p>
                  </div>
                  <span>{formalEvidence.length} 条正式证据</span>
                </div>
                <div className="workflow-control-actions">
                  <button className="secondary-inline-button" type="button" onClick={() => {
                    setView("audit");
                    setContextTab("workspace");
                    setRightPaneVisible(true);
                  }}>打开证据审阅</button>
                  <button className="secondary-inline-button" type="button" onClick={() => {
                    setView("knowledge");
                    setContextTab("evidence");
                    setRightPaneVisible(true);
                  }}>查看正式证据库</button>
                </div>
              </section>
            )}
            {formalEvidence.length > 0 && renderFormalEvidence()}
          </div>
        )}

        {legacyAgentPlannerEnabled && contextTab === "agent-plan" && (
          <div className="output-content">
            <section className="output-section agent-plan-section">
              <div className="output-section-heading">
                <div>
                  <h3>本轮调用计划</h3>
                  <p className="section-subtitle">模型只提出必要任务；勾选并批准前不会调用任何 Agent。</p>
                </div>
                <button className="plain-action" type="button" onClick={() => setAgentPlanPanelOpen((open) => !open)}>
                  {agentPlanPanelOpen ? "收起" : "展开"} · {agentPlan?.status ?? "未生成"}
                </button>
              </div>
              {agentPlanPanelOpen && (
                <>
                  <label className="agent-plan-input">
                    <span>研究需求</span>
                    <textarea rows={4} value={agentPlanDraft} onChange={(event) => setAgentPlanDraft(event.target.value)} placeholder="描述本轮希望完成的研究任务..." />
                  </label>
                  <button className="primary-inline-button full-width" type="button" disabled={agentPlanBusy || !agentPlanDraft.trim()} onClick={() => void createAgentPlan()}>
                    {agentPlanBusy ? "处理中..." : "生成调用计划"}
                  </button>
                  {agentPlans.length > 1 && (
                    <div className="agent-plan-history">
                      <span>历史计划</span>
                      {agentPlans.slice(0, 4).map((plan) => (
                        <button key={plan.plan_id} className={agentPlan?.plan_id === plan.plan_id ? "selected" : ""} type="button" onClick={() => {
                          setAgentPlan(plan);
                          setSelectedAgentTaskIds(plan.approved_task_ids.length ? plan.approved_task_ids : plan.tasks.filter((task) => task.blocked_reason === null && task.status !== "SKIPPED").map((task) => task.task_id));
                        }}>{plan.intent_summary}</button>
                      ))}
                    </div>
                  )}
                  {agentPlan && (
                    <div className="agent-plan-card">
                      <div className="agent-plan-summary">
                        <strong>{agentPlan.intent_summary}</strong>
                        <small>{agentPlan.planner_mode === "llm" ? "模型规划" : "受控规则规划"} · {agentPlan.tasks.length} 个任务</small>
                      </div>
                      {agentPlan.status === "PENDING_APPROVAL" && (
                        <div className="agent-selection-actions">
                          <button type="button" onClick={() => setSelectedAgentTaskIds(agentPlan.tasks.filter((task) => task.blocked_reason === null && task.status !== "SKIPPED").map((task) => task.task_id))}>全选可执行项</button>
                          <button type="button" onClick={() => setSelectedAgentTaskIds([])}>清空选择</button>
                        </div>
                      )}
                      <div className="agent-plan-task-list">
                        {agentPlan.tasks.map((task) => {
                          const selected = selectedAgentTaskIds.includes(task.task_id);
                          const disabled = task.blocked_reason !== null || task.status === "SKIPPED";
                          return (
                            <label className={`agent-plan-task ${disabled ? "agent-plan-task-disabled" : ""}`} key={task.task_id}>
                              <input type="checkbox" checked={selected} disabled={disabled || agentPlan.status !== "PENDING_APPROVAL"} onChange={() => toggleAgentTask(task.task_id)} />
                              <span className="agent-plan-task-copy">
                                <strong>{agentDisplayNames[task.agent_id] ?? task.agent_id}</strong>
                                <small>{task.reason}</small>
                                <span>输入：{task.input_refs.join("、") || "当前对话"}</span>
                                <span>输出：{task.expected_output_types.slice(0, 3).join("、")}</span>
                        <span>风险：{task.risk_level} · 依赖：{task.depends_on.map((item) => item.replace("agent:", "")).join("、") || "无"}</span>
                                {task.blocked_reason && <span className="workflow-control-error">{task.blocked_reason}</span>}
                              </span>
                              <span className={`agent-task-status agent-task-status-${task.status.toLowerCase()}`}>{task.status}</span>
                            </label>
                          );
                        })}
                      </div>
                      {agentPlan.status === "PENDING_APPROVAL" ? (
                        <div className="agent-plan-actions">
                          <button className="secondary-inline-button" type="button" disabled={agentPlanBusy} onClick={() => void rejectAgentPlan()}>拒绝本次计划</button>
                          <button className="primary-inline-button" type="button" disabled={agentPlanBusy || selectedAgentTaskIds.length === 0} onClick={() => void approveAndExecuteAgentPlan()}>{agentPlanBusy ? "执行中..." : "批准选中项并执行"}</button>
                        </div>
                      ) : <div className="agent-plan-status-note"><span>计划状态</span><strong>{agentPlanStatusLabels[agentPlan.status] ?? agentPlan.status}</strong></div>}
                      {agentPlan.risk_flags.map((flag) => <p className="workflow-control-error" key={flag}>{riskFlagText(flag)}</p>)}
                    </div>
                  )}
                  {agentPlanError && <p className="workflow-control-error" role="alert">{agentPlanError}</p>}
                </>
              )}
            </section>
          </div>
        )}

        {legacyAgentPlannerEnabled && contextTab === "agent-outputs" && (
          <div className="output-content">
            <section className="output-section agent-output-section">
              <div className="output-section-heading">
                <div><h3>Agent 产出箱</h3><p className="section-subtitle">候选材料不会自动进入正式证据或专业页面。</p></div>
                <button className="plain-action" type="button" onClick={() => setAgentOutputBoxOpen((open) => !open)}>{agentOutputBoxOpen ? "收起" : "展开"}</button>
              </div>
              <div className="agent-output-scope" role="tablist" aria-label="产出范围">
                <button className={agentOutputScope === "turn" ? "selected" : ""} type="button" onClick={() => setAgentOutputScope("turn")}>当前轮次 {activeTurnOutputs.length}</button>
                <button className={agentOutputScope === "project" ? "selected" : ""} type="button" onClick={() => setAgentOutputScope("project")}>项目全部 {agentOutputs.length}</button>
              </div>
              {agentOutputBoxOpen && (agentOutputScope === "turn" ? activeTurnOutputs : agentOutputs).length ? (
                <div className="agent-output-list">{(agentOutputScope === "turn" ? activeTurnOutputs : agentOutputs).map((output) => renderAgentOutputCard(output))}</div>
              ) : agentOutputBoxOpen ? <div className="empty-output"><span className="empty-symbol">✦</span><p>系统完成内部步骤后，本轮的候选产物会出现在这里供审阅。</p></div> : null}
            </section>
          </div>
        )}

        {view === "knowledge" && contextTab === "evidence" && (
          <div className="output-content">
            <section className="output-section knowledge-project-materials-section">
              <div className="output-section-heading">
                  <h3>当前项目资料</h3>
                <div className="output-heading-actions">
                  <span>{documentsBusy ? "加载中..." : `${activeDocuments.length} 篇`}</span>
                  <button
                    className="upload-doc-button"
                    type="button"
                    title="上传 PDF 或 DOCX"
                    disabled={uploadBusy || !auth?.access_token || !projectId}
                    onClick={() => uploadInputRef.current?.click()}
                  >
                    {uploadBusy ? "上传中..." : "上传"}
                  </button>
                  <input
                    ref={uploadInputRef}
                    className="visually-hidden"
                    type="file"
                    accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) void uploadDocument(file);
                    }}
                  />
                </div>
              </div>
              <div className="paper-list knowledge-project-materials-list">
                {projectPapers.map((document) => (
                  <button className="paper-item" type="button" key={document.document_id} onClick={() => void openDocument(document)}>
                    <span className="paper-file-icon">{document.format.toUpperCase()}</span>
                    <span><strong>{document.title}</strong><small>版本 {document.current_version} · {document.document_type}</small></span>
                    <span className="row-arrow">&gt;</span>
                  </button>
                ))}
                {!documentsBusy && !projectPapers.length && (
                  <div className="empty-documents">
                    <strong>还没有项目论文</strong>
                    <span>上传 PDF 或 DOCX 后，论文会出现在这里并可供对话检索。</span>
                  </div>
                )}
                {uploadError && <p className="upload-error">{uploadError}</p>}
              </div>
            </section>
            {renderKnowledgeAssetLibrary()}
            {writingSurfaceVisible && <section className="output-section draft-section">
              <div className="output-section-heading">
                <div>
                  <h3>论文草稿</h3>
                  <p className="section-subtitle">可直接编辑，保存后自动生成新版本</p>
                </div>
                <button
                  className="draft-create-button"
                  type="button"
                  disabled={documentEditBusy || !auth?.access_token || !projectId}
                  onClick={() => void createDraft()}
                >
                  ＋ 新建
                </button>
              </div>
              <div className="paper-list">
                {draftDocuments.map((document) => (
                  <button className="paper-item draft-paper-item" type="button" key={document.document_id} onClick={() => void openDocument(document)}>
                    <span className="paper-file-icon draft-file-icon">稿</span>
                    <span>
                      <strong>{document.title}</strong>
                      <small>版本 {document.current_version} · 可编辑</small>
                    </span>
                    <span className="row-arrow">&gt;</span>
                  </button>
                ))}
                {!documentsBusy && !draftDocuments.length && (
                  <div className="empty-documents draft-empty">
                    <strong>还没有论文草稿</strong>
                    <span>创建草稿后，可以在平台内直接编辑、保存版本或删除。</span>
                  </div>
                )}
                {documentEditError && <p className="upload-error">{documentEditError}</p>}
              </div>
            </section>}
            <section className="output-section">
              <div className="output-section-heading">
                <div>
                  <h3>{activeResponse?.mode === "formal" ? "本轮正式证据" : "本轮探索证据"}</h3>
                  <p className="section-subtitle">
                    {selectedTurnResponse ? "当前显示所选回答轮次的证据" : "当前回答轮次的证据"}
                  </p>
                </div>
                <span>{citations.length} 条</span>
              </div>
              <div className="evidence-list">
                {citations.map((citation, index) => (
                  <button
                    className="evidence-item"
                    type="button"
                    key={`${activeResponse?.turn_id ?? activeResponse?.memory_ref ?? "turn"}-${index}-${citation.canonical_chunk_id}`}
                    onClick={() => openCitationDetails(citation)}
                  >
                    <div className="evidence-item-topline">
                      <span className="citation-number">{citation.citation_index || index + 1}</span>
                      <span className={isFormalCitation(citation) ? "verified-tag" : "review-tag"}>
                        {citationStatusLabel(citation)}
                      </span>
                    </div>
                    <strong>{citation.paper_title}</strong>
                    <p>{citation.excerpt}</p>
                    <small>
                      {citation.source_filename} · Chunk {citation.chunk_index} · {citationPageLabel(citation)}
                    </small>
                  </button>
                ))}
              </div>
            </section>
            {renderFormalEvidence()}
            {renderPageMaterials("候选证据与证据矩阵", ["knowledge_evidence", "evidence_gate"])}
            <section className="output-section compact-section">
              <div className="output-section-heading">
                <h3>知识库状态</h3>
                <span className={corpusSummary?.discovery_ready ? "ready-text" : "review-tag"}>
                  {corpusStatusLabel(corpusSummary)}
                </span>
              </div>
              <div className="corpus-stats">
                <div><strong>1211</strong><small>篇论文</small></div>
                <div><strong>17885</strong><small>文本块</small></div>
                <div><strong>{citations.length}</strong><small>本轮证据</small></div>
              </div>
              {corpusSummary?.risk_flags.length ? (
                <p className="workflow-control-error">{corpusSummary.risk_flags.map(corpusRiskFlagLabel).join("；")}</p>
              ) : null}
            </section>
            {knowledgeAssetSummary && (
              <section className="output-section compact-section knowledge-assets-section">
                <div className="output-section-heading">
                  <div>
                    <h3>研究助研资产扩展</h3>
                    <p className="section-subtitle">把文献检索连接到筛选、设计、测量、写作和复现工作流</p>
                  </div>
                  <span className="review-tag">结构化目录</span>
                </div>
                <div className="asset-stat-grid">
                  <div><strong>{knowledgeAssetSummary.structured_assets.research_method_and_workflow_records}</strong><small>方法与规范资源</small></div>
                  <div><strong>{knowledgeAssetSummary.structured_assets.research_assistant_tasks}</strong><small>助研任务模板</small></div>
                  <div><strong>{knowledgeAssetSummary.structured_assets.discovery_candidates}</strong><small>发现候选</small></div>
                  <div><strong>{knowledgeAssetSummary.structured_assets.discovery_fulltext_chunks}</strong><small>全文发现块</small></div>
                </div>
                {discoveryAssets && (
                  <>
                    <div className="asset-discovery-heading">
                      <span>已下载全文发现集</span>
                      <small>{discoveryAssets.downloaded_count} 篇 · {discoveryAssets.chunk_count} 个页码块 · 不进入正式证据</small>
                    </div>
                    <div className="asset-discovery-list">
                      {discoveryAssets.records.map((record) => (
                        <div className="asset-discovery-row" key={record.candidate_id}>
                          <span className="asset-discovery-year">{record.year ?? "—"}</span>
                          <span><strong>{record.title}</strong><small>{record.doi ?? record.candidate_id} · {record.detail ?? "页码已记录"}</small></span>
                          <span className="review-tag">发现</span>
                        </div>
                      ))}
                    </div>
                  </>
                )}
                <p className="asset-boundary-note">边界：PaperCard、图谱关系和 OpenAlex 候选均为未核验导航材料；只有通过身份、授权、定位和来源检查后，才可提升为正式证据。</p>
              </section>
            )}
          </div>
        )}

        {view === "codex" && contextTab === "workspace" && (
          <div className="output-content">
            <section className="codex-hero">
              <span className="codex-symbol">⌘</span>
              <h3>研究代码与审查</h3>
              <p>在对话中提出研究需求后，系统会自动生成受控代码候选并在执行前完成审查。输出会保留在项目产出箱中。</p>
              <button
                className="primary-inline-button"
                type="button"
                onClick={() => document.querySelector<HTMLTextAreaElement>(".composer-box textarea")?.focus()}
              >
                在对话中提出研究需求 <span>&gt;</span>
              </button>
            </section>
            <section className="output-section physics-validator-section">
              <h3>Physics-STEM 代码校验</h3>
              <p>先检查公式和代码安全，再进入后续执行流程。</p>
              <label className="document-editor-label">Python 代码
                <textarea className="physics-code-input" value={physicsSource} onChange={(event) => setPhysicsSource(event.target.value)} rows={9} />
              </label>
              <label className="document-editor-label">物理公式（每行一个）
                <textarea className="physics-code-input physics-equation-input" value={physicsEquations} onChange={(event) => setPhysicsEquations(event.target.value)} rows={3} />
              </label>
              <button className="primary-inline-button" type="button" disabled={physicsBusy || !auth?.access_token} onClick={() => void validatePhysics()}>
                {physicsBusy ? "校验中..." : "运行物理校验"} <span>&gt;</span>
              </button>
              {physicsError && <p className="upload-error">{physicsError}</p>}
              {physicsReport && <div className={`physics-report ${physicsReport.passed ? "physics-report-pass" : "physics-report-fail"}`}>
                <strong>{physicsReport.passed ? "校验通过" : "发现需要处理的问题"}</strong>
                <small>{physicsReport.checks.filter((check) => check.passed).length} 项通过 · {physicsReport.finding_codes.length} 项提醒</small>
                {physicsReport.finding_codes.map((code) => <span className="review-item" key={code}>! {code}</span>)}
              </div>}
            </section>
            {renderPageMaterials("研究方案、写作与代码候选", ["workspace", "research_questions", "research_design", "data_collection", "codex", "paper_editor"])}
            <section className="output-section">
              <div className="output-section-heading"><h3>运行环境</h3><span className="review-tag">开发模式</span></div>
              <div className="runtime-list">
                <div><span>代码提供方</span><strong>{runtimeStatus.coding_provider}</strong></div>
                <div><span>Codex CLI</span><strong>{runtimeStatus.codex_available ? "生成已确认" : runtimeStatus.codex_cli_detected ? "已检测，网络待确认" : runtimeStatus.codex_reason ?? "未配置"}</strong></div>
                <div><span>SPSS</span><strong>{runtimeStatus.spss_available ? "可用" : runtimeStatus.spss_reason ?? "未配置"}</strong></div>
                <div><span>SciDAVis</span><strong>{runtimeStatus.scidavis_available ? "可用" : runtimeStatus.scidavis_reason ?? "未配置"}</strong></div>
              </div>
            </section>
            <section className="output-section">
              <div className="output-section-heading"><h3>最近代码任务</h3><span>0</span></div>
              <div className="empty-output"><span className="empty-symbol">⌘</span><p>在对话中描述你的分析需求，Codex 会先生成代码草案。</p></div>
            </section>
          </div>
        )}

        {view === "analysis" && contextTab === "workspace" && (
          <div className="output-content">
            <section className="analysis-summary">
              <div className="analysis-summary-icon">◫</div>
              <div>
                <strong>实验数据进入受控分析链</strong>
                <p>上传 CSV 后先做数据审查，再逐步审批处理、冻结和执行。Codex 只生成候选代码，SPSS 未配置时不会伪装成已完成。</p>
              </div>
            </section>

            <section className="output-section">
              <div className="output-section-heading">
                <h3>当前链路</h3>
                <button
                  className="plain-action"
                  type="button"
                  disabled={analysisBusy || !projectId}
                  onClick={() => void refreshAnalysisState()}
                >
                  刷新
                </button>
              </div>
              <div className="analysis-stage">
                <div className={analysisStage === "STUDY_PROTOCOL_APPROVED" ? "analysis-stage-item active" : "analysis-stage-item"}>
                  <span>1</span><strong>研究方案</strong><small>{analysisStage === "INTAKE" ? "请先从研究问题界定开始" : analysisStage === "STUDY_PROTOCOL_APPROVED" ? "等待生成分析方案" : "已完成或已进入数据阶段"}</small>
                </div>
                <div className={analysisState || latestDataAudit ? "analysis-stage-item active" : "analysis-stage-item"}>
                  <span>2</span><strong>数据管道</strong><small>{analysisState?.stage ?? (latestDataAudit ? "演示数据审查已记录" : "尚未建立分析计划")}</small>
                </div>
                <div className={effectiveStatisticalResultCard ? "analysis-stage-item active" : "analysis-stage-item"}>
                  <span>3</span><strong>结果验证</strong><small>{effectiveStatisticalResultCard ? "已有结果卡" : "等待受控执行"}</small>
                </div>
              </div>
              {!analysisState && (
                <div className="analysis-inline-note">
                  <strong>还没有分析管道</strong>
                  <span>请在对话框中说“开始数据分析”或“生成分析方案”，系统会自动准备下一步。</span>
                </div>
              )}
            </section>

            {analysisState && (
              <>
                <section className="output-section">
                  <div className="output-section-heading">
                    <div>
                      <h3>实验数据</h3>
                      <p className="section-subtitle">只接受 CSV，原始文件会先经过确定性审查</p>
                    </div>
                    <div className="output-heading-actions">
                      <span className={analysisState.data_audit_report?.passed ? "ready-text" : ""}>
                        {analysisState.data_audit_report ? (analysisState.data_audit_report.passed ? "审查通过" : "需要修正") : "等待上传"}
                      </span>
                      <button
                        className="upload-doc-button"
                        type="button"
                        disabled={analysisBusy || analysisState.stage !== "WAITING_RAW_DATA"}
                        onClick={() => analysisInputRef.current?.click()}
                      >
                        {analysisBusy ? "处理中..." : "上传 CSV"}
                      </button>
                      <input
                        ref={analysisInputRef}
                        className="visually-hidden"
                        type="file"
                        accept=".csv,text/csv"
                        onChange={(event) => {
                          const file = event.target.files?.[0];
                          if (file) void uploadAnalysisDataset(file);
                        }}
                      />
                    </div>
                  </div>
                  {analysisState.raw_dataset ? (
                    <div className="analysis-dataset-row">
                      <span className="paper-file-icon">CSV</span>
                      <div>
                        <strong>{String(analysisState.raw_dataset.dataset_id ?? "原始实验数据")}</strong>
                        <small>数据集已登记 · {analysisState.data_audit_report?.passed ? "通过基础字段审查" : "存在审查问题"}</small>
                      </div>
                      <span className="analysis-dataset-status">{analysisState.stage}</span>
                    </div>
                  ) : (
                    <div className="analysis-file-drop">
                      <strong>上传实验数据 CSV</strong>
                      <span>建议包含清晰的分组、结果变量和必要的受试者标识；系统会先检查列名、类型、缺失和隐私风险。</span>
                    </div>
                  )}
                  {analysisState.data_audit_report?.risk_flags.length ? (
                    <div className="analysis-risk-list">
                      {analysisState.data_audit_report.risk_flags.map((flag) => <span key={flag}>! {flag}</span>)}
                    </div>
                  ) : null}
                </section>

                <section className="output-section">
                  <div className="output-section-heading"><h3>代码与统计引擎</h3><span>{analysisState.executable_plan?.analysis_mode ?? "等待分析计划"}</span></div>
                  <div className="analysis-engine-grid">
                    <div className="analysis-engine-row">
                      <span>Python 受控执行</span>
                      <strong>{analysisState.code_artifact_ref ? (analysisState.code_generation_provider === "deterministic_research_template" ? "受控模板已生成" : "Codex 候选代码已生成") : runtimeStatus.codex_available ? "可生成候选代码" : "使用受控模板或待配置"}</strong>
                      <small>{analysisState.code_generation_fallback_reason ?? (analysisState.code_review_ref ? "已记录代码审查" : "执行前需要代码审查和人工确认")}</small>
                    </div>
                    <div className="analysis-engine-row">
                      <span>SPSS</span>
                      <strong>{runtimeStatus.spss_available ? "SPSS 可用" : "SPSS 未配置"}</strong>
                      <small>{runtimeStatus.spss_available ? "双引擎模式可在审批后执行" : runtimeStatus.spss_reason ?? "需要配置 SPSS 批处理程序"}</small>
                    </div>
                  </div>
                  <div className="analysis-code-ref">
                    <span>代码工件</span>
                    <code>{analysisState.code_artifact_ref ?? "尚未生成，需先完成数据冻结和执行审批"}</code>
                  </div>
                </section>

                {analysisState.pending_approval && (
                  <section className="output-section analysis-approval">
                    <div className="output-section-heading"><h3>待人工确认</h3><span>{analysisState.pending_approval.approval_type}</span></div>
                    <p>{analysisState.pending_approval.reason}</p>
                    <div className="analysis-approval-actions">
                      <button className="secondary-inline-button" type="button" disabled={analysisBusy} onClick={() => void decideAnalysisStep("rejected")}>退回修正<span>↩</span></button>
                      <button className="primary-inline-button" type="button" disabled={analysisBusy} onClick={() => void decideAnalysisStep("approved")}>{analysisBusy ? "处理中..." : "确认并继续"}<span>&gt;</span></button>
                    </div>
                  </section>
                )}

                <section className="output-section compact-section">
                  <div className="output-section-heading">
                    <h3>分析结果</h3>
                    <div className="output-heading-actions">
                      <span>{effectiveStatisticalResultCard ? "已生成" : "等待执行"}</span>
                      {effectiveStatisticalResultCard && (
                        <button className="secondary-inline-button" type="button" disabled={scidavisBusy} onClick={() => void exportResultForSciDAVis()}>
                          {scidavisBusy ? "导出中..." : "导出到 SciDAVis"}
                        </button>
                      )}
                    </div>
                  </div>
                  {effectiveStatisticalResultCard ? (
                    <div className="analysis-result-grid">
                      {Object.entries(effectiveStatisticalResultCard.values).map(([key, value]) => (
                        <div key={key}><strong>{String(value)}</strong><small>{statisticalResultLabel(key)}</small></div>
                      ))}
                      <p className="analysis-result-note">结果状态：{effectiveStatisticalResultCard.execution_status}。正式解释仍需遵守结果卡和人工审查边界。</p>
                      {scidavisExport && <p className="analysis-result-note">已生成 SciDAVis CSV：{scidavisExport.file_path}（{scidavisExport.row_count} 项）</p>}
                    </div>
                  ) : (
                    <div className="empty-output"><span className="empty-symbol">∿</span><p>完成数据审查、冻结和执行审批后，结果卡会出现在这里。</p></div>
                  )}
                </section>
              </>
            )}
            {renderPageMaterials("数据处理与分析计划", ["data_analysis", "codex"])}
            {analysisError && <p className="upload-error" role="alert">{analysisError}</p>}
          </div>
        )}

        {view === "audit" && contextTab === "workspace" && renderOutputWorkspace()}

        {false && view === "audit" && contextTab === "workspace" && (
          <div className="output-content">
            <section className="output-section workflow-control-section">
              <div className="output-section-heading">
                <div>
                  <h3>已生成结果</h3>
                  <p className="section-subtitle">按结果类型查看，不需要在对话记录里翻找。</p>
                </div>
                <span className="ready-text">研究链路 {orchestrationProgress ?? "—"}</span>
              </div>
              <div className="workflow-control-actions">
                <button className="primary-inline-button" type="button" onClick={() => { setView("analysis"); setContextTab("workspace"); }}>
                  统计结果
                </button>
                <button className="secondary-inline-button" type="button" onClick={() => document.querySelector<HTMLElement>(".manuscript-result-section")?.scrollIntoView({ behavior: "smooth", block: "start" })}>
                  论文正文
                </button>
                <button className="secondary-inline-button" type="button" onClick={() => { setView("audit"); setContextTab("workspace"); }}>
                  引用与审查
                </button>
              </div>
            </section>
            <section className="output-section manuscript-result-section">
              <div className="output-section-heading">
                <div>
                  <h3>论文正文</h3>
                  <p className="section-subtitle">已生成的论文草稿和候选稿都从这里打开，不需要继续翻研究日志。</p>
                </div>
                <span>{draftDocuments.length ? `${draftDocuments.length} 份草稿` : manuscriptCandidates.length || latestManuscriptArtifact ? "候选稿待应用" : "待生成"}</span>
              </div>
              {draftDocuments.length > 0 ? (
                <div className="paper-list">
                  {draftDocuments.map((document) => (
                    <button className="paper-item draft-paper-item" type="button" key={document.document_id} onClick={() => void openDocument(document)}>
                      <span className="paper-file-icon draft-file-icon">稿</span>
                      <span>
                        <strong>{document.title}</strong>
                        <small>版本 {document.current_version} · {new Date(document.updated_at).toLocaleString()}</small>
                      </span>
                      <span className="row-arrow">&gt;</span>
                    </button>
                  ))}
                </div>
              ) : manuscriptCandidates.length > 0 ? (
                <div className="paper-list">
                  {manuscriptCandidates.slice(0, 3).map((output) => {
                    const preview = output.output_previews.find((item) => item.artifact_type === "ManuscriptDraftZh")
                      ?? output.output_previews.find((item) => item.artifact_type === "ManuscriptOutline");
                    const title = preview && typeof preview.content.title === "string" ? preview.content.title : "候选论文草稿";
                    return (
                      <div className="paper-item draft-paper-item" key={output.task_id}>
                        <span className="paper-file-icon draft-file-icon">稿</span>
                        <span>
                          <strong>{title}</strong>
                          <small>{preview?.artifact_type === "ManuscriptDraftZh" ? "完整候选稿" : "论文大纲"} · 等待写入草稿</small>
                        </span>
                        <button className="primary-inline-button" type="button" disabled={agentPlanBusy} onClick={() => void applyManuscriptCandidate(output)}>
                          {agentPlanBusy ? "处理中..." : "打开论文"}
                        </button>
                      </div>
                    );
                  })}
                </div>
              ) : latestManuscriptArtifact ? (
                <div className="paper-list">
                  <div className="paper-item draft-paper-item">
                    <span className="paper-file-icon draft-file-icon">稿</span>
                    <span>
                      <strong>{latestManuscriptTitle}</strong>
                      <small>{latestManuscriptArtifact?.artifact_type === "ManuscriptDraftZh" ? "完整候选稿" : "论文大纲"} · 已生成，尚未写入项目文档</small>
                    </span>
                    <button className="primary-inline-button" type="button" disabled={agentPlanBusy || !latestManuscriptArtifact} onClick={() => {
                      if (latestManuscriptArtifact) void applyManuscriptArtifact(latestManuscriptArtifact.artifact_id);
                    }}>
                      {agentPlanBusy ? "处理中..." : "打开论文"}
                    </button>
                  </div>
                </div>
              ) : (
                <div className="empty-documents draft-empty">
                  <strong>论文尚未写入项目文档</strong>
                  <span>完成论文写作 Agent 后，候选稿会在这里出现。</span>
                </div>
              )}
              {manuscriptApplyError && <p className="workflow-control-error" role="alert">{manuscriptApplyError}</p>}
            </section>
            <section className="output-section evidence-control-section">
              <div className="output-section-heading">
                <div>
                  <h3>证据审阅</h3>
                  <p className="section-subtitle">上传来源并逐条核验后，才能通过证据审查。</p>
                </div>
                <span>{evidenceRows.filter((item) => item.evidence.verification_status === "source_verified" || item.evidence.verification_status === "human_verified").length} 条已核验</span>
              </div>
              <div className="workflow-control-actions">
                <button className="secondary-inline-button" disabled={evidenceBusy || !projectId} type="button" onClick={() => evidenceInputRef.current?.click()}>
                  {evidenceBusy ? "处理中..." : "上传 PDF / TXT"}
                </button>
                <button className="secondary-inline-button" disabled={evidenceBusy || !projectId} type="button" onClick={() => void searchProjectEvidence()}>
                  刷新证据
                </button>
                <input
                  ref={evidenceInputRef}
                  className="visually-hidden"
                  type="file"
                  accept=".pdf,.txt,.md,.json,application/pdf,text/plain,application/json"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) void uploadEvidenceSource(file);
                  }}
                />
              </div>
              {evidenceRows.length > 0 && (
                <div className="evidence-control-list">
                  {evidenceRows.map((item) => {
                    const verified = item.evidence.verification_status === "source_verified" || item.evidence.verification_status === "human_verified";
                    return (
                      <div className="evidence-control-row" key={item.evidence.evidence_id}>
                        <div>
                          <strong>{item.evidence.excerpt.slice(0, 90)}{item.evidence.excerpt.length > 90 ? "..." : ""}</strong>
                          <small>{item.evidence.verification_status}</small>
                        </div>
                        <button className={verified ? "verified-tag" : "review-tag"} disabled={verified || evidenceBusy} type="button" onClick={() => void verifyProjectEvidence(item.evidence.evidence_id)}>
                          {verified ? "已核验" : "核验来源"}
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
              {evidenceError && <p className="workflow-control-error" role="alert">{evidenceError}</p>}
            </section>
            {false && evidenceGateOutputs.length > 0 && (
              <section className="output-section evidence-control-section">
                <div className="output-section-heading">
                  <div>
                    <h3>本轮证据候选</h3>
                    <p className="section-subtitle">这里显示本轮研究产出；核验通过后可申请写入正式证据库。</p>
                  </div>
                  <span>{evidenceGateOutputs.length} 个 Agent 结果</span>
                </div>
                <div className="agent-output-list">
                  {evidenceGateOutputs.map((output) => renderAgentOutputCard(output))}
                </div>
              </section>
            )}
            <section className="output-section workflow-control-section">
              <div className="output-section-heading">
                <h3>科研工作流</h3>
                <span className="workflow-stage-code">
                  {orchestrationState?.active_workstream_id
                    ? orchestrationPhaseLabels[String(activeOrchestrationStream?.phase ?? "")] ?? activeOrchestrationStream?.phase
                    : workflow?.current_stage ?? "未启动"}
                </span>
              </div>
              {!auth?.access_token ? (
                  <p className="workflow-control-note">登录后可以继续数据审批和研究流程。</p>
              ) : (
                <div className="workflow-control-body">
                  <div className="workflow-state-row">
                    <span>当前阶段</span>
                    <strong>
                      {orchestrationState?.active_workstream_id
                        ? orchestrationPhaseLabels[String(activeOrchestrationStream?.phase ?? "")] ?? activeOrchestrationStream?.phase
                        : workflow?.current_stage ?? "等待研究主题"}
                    </strong>
                  </div>
                  {activeOrchestrationStep && (
                    <div className="workflow-state-row">
                      <span>当前动作</span>
                      <strong>{orchestrationActionLabels[String(activeOrchestrationStep)] ?? activeOrchestrationStep}</strong>
                    </div>
                  )}
                  {orchestrationState?.active_gate_id && activeOrchestrationStep && (
                    <p className="workflow-control-note">
                      当前停在“{orchestrationActionLabels[String(activeOrchestrationStep)] ?? activeOrchestrationStep}”审查点；你可以在对话中确认、提出修改，或查看右侧对应产物。
                    </p>
                  )}
                  <p className="workflow-control-note workflow-control-agent-note">
                    在对话中提出研究主题或修改意见后，系统会自动调度内部工作；只有正式证据、数据、结果和发布等关键确认点需要你确认。
                  </p>
                  {workflow?.data_pipeline && (
                    <div className="workflow-state-row">
                      <span>数据管线</span>
                      <strong>{workflow?.data_pipeline?.stage ? dataPipelineLabels[String(workflow?.data_pipeline?.stage)] ?? workflow?.data_pipeline?.stage : "未启动"}</strong>
                    </div>
                  )}

                  {workflow?.data_pipeline?.stage === "WAITING_RAW_DATA" ? (
                    <div className="workflow-control-actions">
                      <button className="primary-inline-button" disabled={workflowBusy} type="button" onClick={() => rawCsvInputRef.current?.click()}>
                        {workflowBusy ? "审查中..." : "上传原始 CSV"}
                      </button>
                      <input
                        ref={rawCsvInputRef}
                        className="visually-hidden"
                        type="file"
                        accept=".csv,text/csv"
                        onChange={(event) => {
                          const file = event.target.files?.[0];
                          if (file) void uploadRawCsv(file);
                        }}
                      />
                    </div>
                  ) : workflow?.data_pipeline?.pending_approval ? (
                    <div className="workflow-control-actions">
                      <button className="primary-inline-button" disabled={workflowBusy} type="button" onClick={() => void decideDataPipeline("approved")}>确认数据处理</button>
                      <button className="secondary-inline-button" disabled={workflowBusy} type="button" onClick={() => void decideDataPipeline("rejected")}>退回</button>
                    </div>
                  ) : workflow?.pending_approval_ref ? (
                    <p className="workflow-control-note">这是历史固定流程遗留的审批记录；新的研究任务请直接在对话中提出。</p>
                  ) : null}
                  {workflow?.data_pipeline?.rework_reason && <p className="workflow-control-error">{workflow?.data_pipeline?.rework_reason}</p>}
                </div>
              )}
              {workflowError && <p className="workflow-control-error" role="alert">{workflowError}</p>}
            </section>
            <section className="audit-summary">
              <div className="audit-summary-icon">✓</div>
              <div><strong>研究链路正在审查</strong><p>当前回答已关联证据，正式发布前仍需检查数据和引用。</p></div>
            </section>
            <section className="output-section research-analysis-launcher">
              <div className="output-section-heading"><h3>研究数据审查</h3><span className="review-tag">人工复核</span></div>
              <p>运行 Schema、异常值、多重比较、因果识别、敏感性、预测区间和元分析，并查看每一步的可审计报告。</p>
              <button className="primary-inline-button" type="button" onClick={() => setAnalysisWorkbenchOpen(true)}>打开审查工作台 <span>&gt;</span></button>
            </section>
            {renderPageMaterials("审查结论与修改请求", ["audit_validation"])}
            <section className="output-section">
              <div className="output-section-heading"><h3>本轮审查</h3><span>{activeResponse?.risk_flags.length ?? 0} 项提醒</span></div>
              <div className="review-list">
                {(activeResponse?.risk_flags ?? []).map((flag) => <div className="review-item" key={flag}><span>!</span><p>{flag}</p></div>)}
              </div>
              {workflowSnapshot?.pending_approval_ref && (
                <div className="audit-pending-note">
                  <strong>当前有一项待确认事项</strong>
                  <p>
                    当前研究路径已生成候选结果，需要你在研究流程中确认后才能继续。
                  </p>
                </div>
              )}
              <button
                className="secondary-inline-button"
                type="button"
                onClick={() => {
                  setView("audit");
                  setContextTab("workspace");
                  setRightPaneVisible(true);
                }}
              >
                查看完整审查记录 <span>&gt;</span>
              </button>
            </section>
          </div>
        )}
      </aside>

      {!rightPaneVisible && (
        <button className="restore-output-button" type="button" title="显示右侧输出面板" onClick={() => setRightPaneVisible(true)}>
          &lt; <span>显示输出</span>
        </button>
      )}

      {selectedDocument && (
        <div className="workspace-drawer-backdrop" role="presentation" onClick={() => setSelectedDocument(null)}>
          <section className="workspace-drawer document-drawer" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <div className="workspace-drawer-header">
              <div>
                <span className="chat-kicker">
                  {selectedDocument.document.document_type === "manuscript" ? "论文草稿编辑器" : "项目文档"}
                </span>
                <h2>{selectedDocument.document.title}</h2>
                <small>版本 {selectedDocument.version?.version ?? selectedDocument.document.current_version} · {selectedDocument.document.format}</small>
              </div>
              <button className="header-icon-button" type="button" title="关闭" onClick={() => setSelectedDocument(null)}>×</button>
            </div>
            {selectedDocument.document.document_type === "manuscript" ? (
              <div className="document-editor">
                <label className="document-editor-label">
                  草稿标题
                  <input
                    value={documentTitleDraft}
                    onChange={(event) => setDocumentTitleDraft(event.target.value)}
                    placeholder="输入论文标题"
                  />
                </label>
                <label className="document-editor-label">
                  草稿正文
                  <textarea
                    value={documentContentDraft}
                    onChange={(event) => setDocumentContentDraft(event.target.value)}
                    placeholder="在这里编辑论文草稿..."
                    disabled={!selectedDocument.version || documentEditBusy}
                  />
                </label>
                {documentEditError && <p className="document-editor-error">{documentEditError}</p>}
                <div className="document-editor-actions">
                  <button
                    className="delete-draft-button"
                    type="button"
                    disabled={documentEditBusy}
                    onClick={() => void deleteSelectedDocument()}
                  >
                    删除草稿
                  </button>
                  <button
                    className="primary-inline-button"
                    type="button"
                    disabled={
                      documentEditBusy
                      || !selectedDocument.version
                      || !documentTitleDraft.trim()
                    }
                    onClick={() => void saveSelectedDocument()}
                  >
                    {documentEditBusy ? "保存中..." : "保存新版本"}
                  </button>
                </div>
              </div>
            ) : (
              <div className="document-content">
                {selectedDocument.version?.content ?? "正在读取文档内容..."}
              </div>
            )}
            <div className="document-meta">
              <span>项目隔离：{selectedDocument.document.project_id}</span>
              <span>SHA256：{selectedDocument.document.current_sha256.slice(0, 12)}...</span>
            </div>
          </section>
        </div>
      )}

      {selectedCitation && (
        <div className="workspace-drawer-backdrop" role="presentation" onClick={closeCitationDetails}>
          <section className="workspace-drawer citation-drawer-new" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <div className="workspace-drawer-header">
              <div>
                <span className="chat-kicker">检索证据</span>
                <h2>{selectedCitation.paper_title}</h2>
              </div>
              <button className="header-icon-button" type="button" title="关闭" onClick={closeCitationDetails}>×</button>
            </div>
            <blockquote>{selectedCitation.excerpt}</blockquote>
            <dl className="citation-meta-list">
              <div><dt>来源文件</dt><dd>{selectedCitation.source_filename}</dd></div>
              <div><dt>回答引用序号</dt><dd>{selectedCitation.citation_index || "未提供"}</dd></div>
              <div><dt>Chunk</dt><dd>{selectedCitation.canonical_chunk_id}</dd></div>
              <div><dt>论文标识</dt><dd>{selectedCitation.canonical_paper_id}</dd></div>
              <div><dt>DOI</dt><dd>{selectedCitation.normalized_doi ?? "未提供"}</dd></div>
              <div><dt>证据状态</dt><dd>{citationStatusLabel(selectedCitation)}</dd></div>
              <div><dt>来源定位</dt><dd>{selectedCitation.source_locator_method ?? "UNRESOLVED"}</dd></div>
              <div><dt>PDF 页码</dt><dd>{citationPageLabel(selectedCitation)}</dd></div>
              <div><dt>字符范围</dt><dd>{selectedCitation.char_start != null && selectedCitation.char_end != null ? `${selectedCitation.char_start}-${selectedCitation.char_end}` : "待补充"}</dd></div>
            </dl>
            <p className="drawer-note">
              {isFormalCitation(selectedCitation)
                ? "这条材料已通过来源定位和核验，可以进入正式证据链。"
                : "这条材料目前只能用于探索，正式模式下还需要来源定位和核验。"}
            </p>
            <div className="citation-drawer-actions">
              {isFormalCitation(selectedCitation) ? (
                <span className="verified-tag">已进入正式证据链</span>
              ) : (
                <button
                  className="primary-inline-button"
                  type="button"
                  disabled={citationActionBusy || evidenceBusy}
                  onClick={() => void verifySelectedCitation()}
                >
                  {citationActionBusy ? "核验并提取中..." : "核验来源并提取正式证据"}
                </button>
              )}
              <span className="citation-action-hint">核验通过后，这条材料会同步到正式证据库。</span>
            </div>
            {citationActionError && <p className="citation-action-error" role="alert">{citationActionError}</p>}
          </section>
        </div>
      )}

      {createProjectOpen && (
        <div className="workspace-drawer-backdrop" role="presentation" onClick={() => setCreateProjectOpen(false)}>
          <section className="workspace-modal create-project-modal" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <div className="workspace-drawer-header">
              <div>
                <span className="chat-kicker">项目管理</span>
                <h2>新建研究项目</h2>
                <small>创建后会自动切换到新项目，不会清空已有项目。</small>
              </div>
              <button className="header-icon-button" type="button" title="关闭" onClick={() => setCreateProjectOpen(false)}>×</button>
            </div>
            <div className="create-project-form">
              <label>
                项目名称
                <input
                  value={projectForm.title}
                  onChange={(event) => setProjectForm((current) => ({ ...current, title: event.target.value }))}
                  placeholder="例如：生成式 AI 物理建模研究"
                />
              </label>
              <label>
                研究方向
                <input
                  value={projectForm.research_direction}
                  onChange={(event) => setProjectForm((current) => ({ ...current, research_direction: event.target.value }))}
                  placeholder="例如：师范生 Python 物理建模与生成式 AI 支架"
                />
              </label>
              <label>
                项目标识（可选）
                <input
                  value={projectForm.project_id}
                  onChange={(event) => setProjectForm((current) => ({ ...current, project_id: event.target.value }))}
                  placeholder="留空则由后端自动生成"
                />
              </label>
              <label>
                项目简介（可选）
                <textarea
                  value={projectForm.abstract}
                  onChange={(event) => setProjectForm((current) => ({ ...current, abstract: event.target.value }))}
                  placeholder="描述这个项目要解决的问题和计划产出"
                  rows={4}
                />
              </label>
              {projectError && <p className="project-form-error">{projectError}</p>}
              <div className="modal-actions">
                <button className="secondary-inline-button" type="button" onClick={() => setCreateProjectOpen(false)}>取消</button>
                <button className="primary-inline-button" type="button" disabled={projectBusy} onClick={() => void createProject()}>
                  {projectBusy ? "创建中..." : "创建项目"}
                </button>
              </div>
            </div>
          </section>
        </div>
      )}

      {analysisWorkbenchOpen && (
        <ResearchAnalysisWorkbench
          projectId={projectId}
          accessToken={auth?.access_token}
          onClose={() => setAnalysisWorkbenchOpen(false)}
        />
      )}

      {!auth && !demoMode && (
        <div className="login-overlay">
          <div className="login-card">
            <div className="research-logo large">S</div>
            <span className="chat-kicker">智研育航 · STEM-SSCI/SCI</span>
            <div className="auth-heading-row">
              <div>
                <h2>{authMode === "login" ? "登录你的科研工作台" : "创建科研工作台账号"}</h2>
                <p>
                  {authMode === "login"
                    ? "登录后可以保存项目、对话、论文和长期研究记忆。这里使用智研育航本地账号，不是 GitHub 账号。"
                    : "注册后即可创建项目，并把对话、证据和研究产出保存到本地后端。"}
                </p>
              </div>
              <span className="auth-mode-label">{authMode === "login" ? "已有账号" : "首次使用"}</span>
            </div>
            <div className="auth-mode-switch" role="tablist" aria-label="账号操作">
              <button
                className={authMode === "login" ? "auth-mode-button active" : "auth-mode-button"}
                type="button"
                role="tab"
                aria-selected={authMode === "login"}
                onClick={() => {
                  setAuthMode("login");
                  setAuthError("");
                }}
              >
                登录
              </button>
              <button
                className={authMode === "register" ? "auth-mode-button active" : "auth-mode-button"}
                type="button"
                role="tab"
                aria-selected={authMode === "register"}
                onClick={() => {
                  setAuthMode("register");
                  setAuthError("");
                }}
              >
                注册
              </button>
            </div>
            {authMode === "register" && (
              <>
                <label>用户名<input value={registerUsername} onChange={(event) => setRegisterUsername(event.target.value)} placeholder="例如 researcher01" autoComplete="username" /></label>
                <label>邮箱<input type="email" value={registerEmail} onChange={(event) => setRegisterEmail(event.target.value)} placeholder="name@university.edu.cn" autoComplete="email" /></label>
                <label>显示名称（可选）<input value={registerDisplayName} onChange={(event) => setRegisterDisplayName(event.target.value)} placeholder="例如 张同学" autoComplete="name" /></label>
              </>
            )}
            {authMode === "login" && (
              <label>邮箱或用户名<input value={loginValue} onChange={(event) => setLoginValue(event.target.value)} placeholder="researcher" autoComplete="username" /></label>
            )}
            <label>密码<input type="password" value={passwordValue} onChange={(event) => setPasswordValue(event.target.value)} placeholder="••••••••" /></label>
            <button className="login-submit" type="button" disabled={authBusy} onClick={() => void (authMode === "login" ? signIn() : signUp())}>
              {authBusy ? (authMode === "login" ? "正在登录..." : "正在创建账号...") : (authMode === "login" ? "登录并进入工作台" : "注册并进入工作台")}
            </button>
            {authError && <p className="login-error">{authError}</p>}
            {demoMode && <small className="login-demo-note">当前为演示模式，可先直接浏览界面和示例证据。</small>}
          </div>
        </div>
      )}
    </div>
  );
}
