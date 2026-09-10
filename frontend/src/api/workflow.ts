export type ProjectStage =
  | "INTAKE"
  | "SCOPED"
  | "SEARCH_PROTOCOL_APPROVED"
  | "EVIDENCE_READY"
  | "RESEARCH_QUESTION_APPROVED"
  | "STUDY_PROTOCOL_APPROVED"
  | "DATA_READY"
  | "ANALYZED"
  | "DRAFTED"
  | "VERIFIED"
  | "RELEASED"
  | "REWORK"
  | "BLOCKED"
  | "WAITING_HUMAN"
  | "FAILED";

export interface AgentCapability {
  agent_id: string;
  supported_task_types: string[];
  allowed_tool_capabilities: string[];
  allowed_output_types: string[];
  forbidden_actions: string[];
  read_only_global_state: boolean;
}

export type AgentPlanStatus =
  | "PENDING_APPROVAL"
  | "APPROVED"
  | "RUNNING"
  | "COMPLETED"
  | "PARTIAL"
  | "REJECTED"
  | "BLOCKED"
  | "WAITING_TASK_APPROVAL"
  | "REWORK_REQUIRED";

export type AgentExecutionMode = "automatic" | "stepwise";

export type AgentTaskStatus =
  | "PLANNED"
  | "WAITING_DEPENDENCY"
  | "SKIPPED"
  | "RUNNING"
  | "COMPLETED"
  | "FAILED"
  | "BLOCKED";

export interface AgentTaskPlan {
  task_id: string;
  agent_id: string;
  task_type: string;
  reason: string;
  input_refs: string[];
  required_context: string[];
  depends_on: string[];
  expected_output_types: string[];
  risk_level: string;
  approval_required: boolean;
  status: AgentTaskStatus;
  blocked_reason: string | null;
  agent_run_id: string | null;
  output_refs: string[];
  persisted_artifact_ids: string[];
  evidence_refs: string[];
  risk_flags: string[];
  unresolved_questions: string[];
  error: string | null;
  review_note: string | null;
}

export interface AgentExecutionPlan {
  plan_id: string;
  project_id: string;
  conversation_id: string | null;
  turn_id: string | null;
  user_request: string;
  conversation_context: string[];
  intent_summary: string;
  status: AgentPlanStatus;
  tasks: AgentTaskPlan[];
  source_context_refs: string[];
  risk_flags: string[];
  unresolved_questions: string[];
  planner_mode: string;
  execution_mode: AgentExecutionMode;
  pending_review_task_id: string | null;
  rework_note: string | null;
  approved_task_ids: string[];
  approved_by: string | null;
  approved_at: string | null;
  executed_at: string | null;
  created_at: string;
}

export interface AgentOutputSummary {
  plan_id: string;
  task_id: string;
  project_id: string;
  user_request: string | null;
  conversation_id: string | null;
  turn_id: string | null;
  agent_id: string;
  task_type: string;
  status: AgentTaskStatus;
  input_refs: string[];
  depends_on: string[];
  risk_level: string;
  output_types: string[];
  artifact_ids: string[];
  artifact_refs: string[];
  evidence_refs: string[];
  output_previews: AgentOutputPreview[];
  risk_flags: string[];
  unresolved_questions: string[];
  decision: string;
  target_pages: string[];
  error: string | null;
  agent_run_id?: string | null;
  agent_version?: string | null;
  primary_artifact_id?: string | null;
  researcher_answer?: string;
  summary_mode?: "llm" | "deterministic" | string;
}

export interface AgentOutputPreview {
  artifact_id: string;
  artifact_type: string;
  status: string;
  content: Record<string, unknown>;
  researcher_summary?: string;
  review_points?: string[];
  action_items?: string[];
  summary_mode?: "llm" | "deterministic" | string;
}

export interface AgentPageMaterial {
  material_id: string;
  project_id: string;
  plan_id: string;
  task_id: string;
  agent_id: string;
  artifact_id: string;
  artifact_type: string;
  target: string;
  conversation_id: string | null;
  turn_id: string | null;
  formalization: string;
  applied_by: string;
  applied_at: string;
  content: Record<string, unknown>;
}

export interface FormalEvidenceRecord {
  project_id: string;
  evidence_id: string;
  artifact_id: string;
  plan_id: string;
  task_id: string;
  agent_id: string;
  conversation_id: string | null;
  turn_id: string | null;
  promoted_by: string;
  promoted_at: string;
  evidence_ref: Record<string, unknown>;
  provenance: Array<Record<string, unknown>>;
}

export interface ApprovalRequest {
  request_id: string;
  artifact_ref: string;
  approval_type: string;
  reason: string;
  risk_summary: string;
}

export interface RouteDecision {
  decision_id: string;
  project_id: string;
  current_stage: ProjectStage;
  selected_route: string;
  reason: string;
  required_context: string[];
  required_tools: string[];
  decision_scope: string;
  risk_level: string;
  triggered_rules: string[];
  final_decider: string;
  policy_version: string;
  created_at: string;
}

export interface AgentResult {
  agent_run_id: string;
  agent_id: string;
  agent_version: string;
  candidate_artifact_refs: string[];
  evidence_refs: string[];
  tool_requests: ToolRequest[];
  approval_requests: string[];
  risk_flags: string[];
  unresolved_questions: string[];
  recommendations: string[];
  confidence: number | null;
  created_at: string;
}

export interface ToolRequest {
  request_id: string;
  capability: string;
  input_refs: string[];
  required_output_types: string[];
  reason: string;
}

export interface ResearchState {
  project_id: string;
  current_stage: ProjectStage;
  rework_target_agent: string | null;
  rework_reason: string | null;
  rework_trigger_refs: string[];
  task_status: Record<string, string>;
  task_ledger: string[];
  progress_ledger: string[];
  evidence_refs: string[];
  context_bundle_refs: string[];
  execution_run_refs: string[];
  artifact_refs: string[];
  data_asset_refs: string[];
  protocol_refs: string[];
  research_test_result_refs: string[];
  risk_profile_refs: string[];
  route_decision_refs: string[];
  agent_run_refs: string[];
  approval_request_refs: string[];
  budget_state_ref: string | null;
  recent_rounds: string[];
  short_memory_summary: string | null;
  long_memory_refs: string[];
  risk_flags: string[];
  unresolved_questions: string[];
  error_log: string[];
}

export interface WorkflowState {
  project_id: string;
  current_stage: ProjectStage;
  pending_approval_ref: string | null;
  last_agent_run_id: string | null;
  last_route_decision: RouteDecision | null;
  research_state: ResearchState | null;
  data_pipeline?: DataPipelineState | null;
  data_pipeline_package_ref?: string | null;
}

export interface PlanningRun {
  workflow_state: WorkflowState;
  agent_result: AgentResult;
  approval_request: ApprovalRequest;
  route_decision: RouteDecision | null;
}

export interface WorkflowRun {
  workflow_state: WorkflowState;
  agent_result: AgentResult;
  approval_request: ApprovalRequest;
  route_decision: RouteDecision;
}

export interface RuntimeStatus {
  coding_provider: string;
  codex_available: boolean;
  codex_cli_detected?: boolean;
  codex_generation_confirmed?: boolean;
  codex_reason: string | null;
  spss_available: boolean;
  spss_reason: string | null;
  scidavis_available?: boolean;
  scidavis_reason?: string | null;
}

export interface SciDAVisExport {
  project_id: string;
  result_id: string;
  filename: string;
  file_path: string;
  row_count: number;
  format: string;
}

export type DataPipelineStage =
  | "WAITING_RAW_DATA"
  | "WAITING_PROCESSING_APPROVAL"
  | "REWORK"
  | "WAITING_FREEZE_APPROVAL"
  | "WAITING_EXECUTION_APPROVAL"
  | "ANALYZED"
  | "BLOCKED";

export interface DataPipelineApproval {
  request_id: string;
  approval_type: string;
  artifact_ref: string;
  reason: string;
}

export interface DataPipelineState {
  project_id: string;
  stage: DataPipelineStage;
  preregistered_plan_ref: string;
  preregistration_approval_ref: string;
  code_artifact_ref: string | null;
  code_specification_ref: string | null;
  code_review_ref: string | null;
  code_generation_provider: string | null;
  code_generation_fallback_reason: string | null;
  spss_code_artifact_ref: string | null;
  spss_execution_run_ref: string | null;
  result_consistency_report_ref: string | null;
  raw_dataset: Record<string, unknown> | null;
  data_audit_report: {
    passed: boolean;
    missing_required_variables: string[];
    risk_flags: string[];
  } | null;
  processed_dataset: Record<string, unknown> | null;
  frozen_dataset: Record<string, unknown> | null;
  executable_plan: {
    analysis_mode: "PYTHON_ONLY" | "SPSS_PYTHON_DUAL";
    executable_plan_id: string;
  } | null;
  validation_report: {
    passed: boolean;
    execution_run_refs: string[];
  } | null;
  statistical_result_card: {
    result_id: string;
    execution_status: string;
    values: Record<string, number>;
  } | null;
  pending_approval: DataPipelineApproval | null;
  rework_reason: string | null;
  blocked_target_ids: string[];
}

export interface ControllerWorkflowState {
  project_id: string;
  current_stage: string;
  pending_approval_ref: string | null;
  last_route_decision: RouteDecision | null;
  data_pipeline: DataPipelineState | null;
  research_state: ResearchState | null;
}

export interface OrchestrationControlState {
  project_id: string;
  lifecycle_status: "ACTIVE" | "PAUSED" | "TERMINATED" | "ARCHIVED" | "COMPLETED";
  review_policy: string;
  state_revision: number;
  target_journal: string | null;
  article_type: string | null;
  workstreams: Array<{
    workstream_id: string;
    name: string;
    route: string;
    status: string;
    phase: string;
    execution_status: string;
    current_action: string | null;
    artifact_ids: string[];
    gate_ids: string[];
    blocker_ids: string[];
    state_revision: number;
    workflow_steps: string[];
    current_step_index: number;
    completed_step_ids: string[];
    skipped_step_ids: string[];
    conversation_checkpoint?: string | null;
  }>;
  route_decision: OrchestrationRouteDecision | null;
  active_workstream_id: string | null;
  active_gate_id: string | null;
  active_blocking_issue_id: string | null;
  updated_at: string;
}

export interface OrchestrationRouteDecision {
  decision_id: string;
  project_id: string;
  primary_route: string;
  research_scope: string;
  confidence: number;
  evidence: string[];
  applicable_modules: string[];
  skipped_modules: string[];
  skip_reasons: string[];
  uncertainties: string[];
  requires_user_confirmation: boolean;
  policy_version: string;
  created_at: string;
}

export interface OrchestrationGate {
  gate_id: string;
  project_id: string;
  workstream_id: string;
  gate_type: string;
  level: "G0" | "G1" | "G2" | "G3";
  status: "NOT_REQUIRED" | "PENDING" | "APPROVED" | "REJECTED" | "SUPERSEDED";
  artifact_ids: string[];
  reason: string;
  warnings: string[];
  risk_acceptance: string[];
  requested_by: string;
  decided_by: string | null;
  decision_reason: string | null;
  created_at: string;
  decided_at: string | null;
}

export interface OrchestrationBlocker {
  issue_id: string;
  project_id: string;
  workstream_id: string;
  code: string;
  message: string;
  priority: number;
  status: string;
  created_at: string;
  resolved_at: string | null;
  resolution_ref: string | null;
}

export interface OrchestrationTask {
  task_id: string;
  project_id: string;
  workstream_id: string;
  action: string;
  status: string;
  claimed_by: string | null;
  lease_until: string | null;
  heartbeat_at: string | null;
  attempt: number;
  max_attempts: number;
  idempotency_key: string;
  input_hash: string;
  expected_state_revision: number;
  output_artifact_ids: string[];
  error: string | null;
  created_at: string;
}

export interface ResearchRun {
  run_id: string;
  project_id: string;
  run_type: "literature" | "analysis" | "writing" | "workflow";
  action: string;
  status: string;
  output_artifact_ids: string[];
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface OrchestrationEvent {
  event_id: string;
  project_id: string;
  event_type: string;
  actor: string;
  state_revision: number;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface ProjectClaim {
  claim_id: string;
  project_id: string;
  manuscript_artifact_id: string;
  section: string;
  claim_text: string;
  claim_type: string;
  support_type: string;
  support_evidence_ids: string[];
  support_result_ids: string[];
  support_artifact_ids: string[];
  confidence: number | null;
  verification_status: string;
  reviewer_status: string;
}

export interface EvidenceReviewPackage {
  project_id: string;
  artifact_id: string;
  version: number;
  artifact_type: "EvidenceReviewPackage";
  schema_version: string;
  body: {
    schema: string;
    research_scope: string;
    status: "READY" | "INCOMPLETE" | string;
    retrieval_trace: Array<{ step: string; label: string; artifact_id: string }>;
    coverage: {
      source_count: number;
      evidence_count: number;
      new_source_count?: number;
      duplicate_source_count?: number;
      external_candidate_count?: number;
      verified_source_count?: number;
      missing_requirements: string[];
    };
    paper_cards: Array<{
      paper_card_id?: string;
      title?: string;
      source_ref?: string;
      main_findings?: string[];
      limitations?: string[];
      evidence_refs?: string[];
    }>;
    evidence_matrix: Array<{
      row_id?: string;
      research_question?: string;
      source_ref?: string;
      relation?: "SUPPORTING" | "CONTRASTING" | "MENTIONING" | string;
      finding?: string;
      applicability_boundary?: string;
      evidence_refs?: string[];
    }>;
    evidence_snapshots: Array<{
      evidence_id?: string;
      source_id?: string;
      excerpt?: string;
      page?: number | null;
      locator?: string;
    }>;
    synthesis?: { summary?: string; corpus_limit?: string } | null;
    research_gap_report?: {
      gaps?: Array<{ gap_id?: string; description?: string; evidence_refs?: string[] }>;
      limit_text?: string;
    };
    used_evidence_refs: string[];
    source_artifact_ids: string[];
  };
}

export interface ConversationCommandResult {
  kind?: "qa" | "orchestration";
  message: string;
  control_state: OrchestrationControlState;
  route_decision: OrchestrationRouteDecision | null;
  gate: OrchestrationGate | null;
  execution_started: boolean;
  waiting_for_user?: boolean;
  checkpoint?: string | null;
  answer?: QAAnswerResponse;
  collaboration?: CollaborationDecision | null;
  dialogue?: {
    mode: string;
    summary: string;
    question?: string | null;
    suggestions: Array<{
      id: string;
      label: string;
      message: string;
    }>;
    evidence?: Array<{
      title: string;
      evidence_id?: string | null;
      excerpt: string;
      verification_status: string;
      locator_status: string;
      role?: string;
    }>;
    tradeoffs?: string[];
    branches?: Array<{
      id: string;
      title: string;
      description: string;
      benefits: string[];
      risks: string[];
      prerequisites: string[];
      message: string;
    }>;
    version_change?: {
      from_version: number;
      to_version: number;
      added: string[];
      changed: string[];
      implications: string[];
    } | null;
    next_action?: string | null;
    canvas_focus: string;
    turn_role?: "answer" | "ask_novel" | "challenge" | "summarize" | "decide" | "wait" | string;
    why_now?: string | null;
    novelty?: string[];
    user_action_required?: boolean;
  } | null;
}

export type CollaborationTurnMode = "teach" | "co_think" | "execute" | "review" | "synthesize" | "decide";
export type ResearchDialogueAct =
  | "clarify"
  | "reframe"
  | "explore"
  | "compare"
  | "challenge"
  | "evidence_seek"
  | "execute"
  | "reflect"
  | "commit";

export interface ResearchBeliefNode {
  node_id: string;
  node_type: "objective" | "question" | "concept" | "hypothesis" | "assumption" | "evidence" | "design" | "constraint" | "decision" | "uncertainty";
  content: string;
  status: "established" | "tentative" | "disputed" | "rejected" | "frozen";
  confidence: "low" | "medium" | "high";
  source_type: "user" | "literature" | "analysis" | "assumption" | "reviewer";
  source_turn_ids: string[];
  source_evidence_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface ResearchBeliefGraph {
  project_id: string;
  version: number;
  nodes: ResearchBeliefNode[];
  edges: Array<{ source_id: string; target_id: string; relation: string }>;
  revisions: Array<Record<string, unknown>>;
  created_at: string;
  updated_at: string;
}

export interface ResearchBranch {
  branch_id: string;
  project_id: string;
  title: string;
  description: string;
  status: "active" | "parked" | "selected" | "rejected";
  benefits: string[];
  risks: string[];
  constraints: string[];
  dependent_node_ids: string[];
  chosen_reason?: string | null;
  created_turn_id?: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface CollaborationDecision {
  profile: {
    default_mode: CollaborationTurnMode;
    explanation_depth: "brief" | "balanced" | "detailed";
    autonomy_level: "confirm_often" | "balanced" | "proactive";
  };
  plan: {
    current_mode: CollaborationTurnMode;
    research_acts: ResearchDialogueAct[];
    decision_relevance: {
      focal_unknown?: string | null;
      owner: "context" | "system_retrieval" | "system_analysis" | "user" | "defer";
      route_impact: "low" | "medium" | "high";
      can_proceed_provisionally: boolean;
      rationale: string;
    };
    provisional_assumptions: string[];
    question_to_user?: string | null;
    tool_plan: Array<{ capability: string; reason: string; bounded: boolean }>;
    should_start_workflow: boolean;
    exploration_sufficient: boolean;
    sufficiency_reason?: string | null;
    formal_gate_required: boolean;
  };
  graph_version: number;
  graph_patch: {
    base_version: number;
    new_version: number;
    upserted_nodes: ResearchBeliefNode[];
    upserted_edges: Array<Record<string, unknown>>;
    revisions: Array<Record<string, unknown>>;
  };
  belief_revisions: Array<Record<string, unknown>>;
  waiting_reason: "none" | "high_value_user_input" | "background_research" | "formal_confirmation";
}
const demoMode = import.meta.env.VITE_DEMO_MODE === "true";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  try {
    return await authenticatedRequest<T>(path, {
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      ...init,
    });
  } catch (error) {
    if (!demoMode) throw error;
    return demoWorkflowFallback<T>(path, init);
  }
}

function demoWorkflowFallback<T>(path: string, init?: RequestInit): T {
  if (path === "/workflow/runtime") return demoRuntime as T;
  if (path === "/workflow/agents") return demoAgents as T;
  if (path.endsWith("/research-branches")) return [] as T;
  if ((path.endsWith("/conversation/command") || path.endsWith("/collaboration/turn")) && init?.method === "POST") {
    const body = typeof init.body === "string" ? JSON.parse(init.body) as { project_id?: string; message?: string } : {};
    const projectId = body.project_id ?? "physics-ai-demo";
    const message = (body.message ?? "").trim().toLowerCase();
    const negatedTransition = /不要|别|暂不|先不|不确认|not|don't|do not/.test(message);
    const gateCommand = !negatedTransition && /证据足够|确认并继续|进入研究设计|继续下一步|可以继续|同意|approve|approved/.test(message);
    const reviseCommand = /继续搜索|补充文献|扩大检索|重新整理|证据不足|证据不够|还不够|再搜|退回修改|退回|revise|search more/.test(message);
    const stopCommand = /停止|终止|暂停|stop|cancel/.test(message);
    const conversationalDecision = gateCommand || reviseCommand || stopCommand;
    const nextGate = conversationalDecision && !stopCommand ? null : {
      gate_id: "gate-demo-route", project_id: projectId, workstream_id: `ws-${projectId}-main`, gate_type: "research_route",
      level: "G2", status: "PENDING", artifact_ids: [], reason: "确认研究路线与证据范围后，系统才会继续。",
      warnings: ["路线判断来自当前研究上下文，需研究者确认。"], risk_acceptance: [], requested_by: "orchestrator",
      decided_by: null, decision_reason: null, created_at: new Date().toISOString(), decided_at: null,
    };
    return {
      message: stopCommand
        ? "研究流程已停止。你可以在对话中重新描述研究主题。"
        : reviseCommand
          ? "已按你的要求重新整理检索范围，右侧结果会随研究动态更新。"
          : gateCommand
            ? "已确认，系统会继续推进下一阶段。"
            : "已识别研究主题，系统正在整理文献和证据；你可以继续补充问题或限制。",
      control_state: {
        project_id: projectId,
        lifecycle_status: "ACTIVE",
        review_policy: "REHEARSAL_ONLY",
        state_revision: conversationalDecision ? 2 : 1,
        workstreams: [{
          workstream_id: `ws-${projectId}-main`, name: "主研究线", route: "QUALITATIVE", status: "ACTIVE",
          phase: "EVIDENCE_PREPARATION", execution_status: "WAITING_USER", current_action: "准备证据",
          artifact_ids: [], gate_ids: ["gate-demo-route"], blocker_ids: [], state_revision: 1,
        }],
        route_decision: {
          decision_id: "route-demo", project_id: projectId, primary_route: "QUALITATIVE", confidence: 0.85,
          evidence: ["conversation_intent"], applicable_modules: ["literature_evidence", "qualitative_design", "writing"],
          skipped_modules: ["causal_DAG", "power_analysis", "bootstrap_hypothesis_test", "permutation_test"],
          skip_reasons: ["研究目标是解释性主题归纳，没有待估计的因果或组间效应。"],
          uncertainties: ["路线判断来自用户描述，需研究者确认。"], requires_user_confirmation: true,
          policy_version: "route-policy-v1", created_at: new Date().toISOString(),
        },
        active_workstream_id: `ws-${projectId}-main`, active_gate_id: nextGate?.gate_id ?? null, active_blocking_issue_id: null,
        updated_at: new Date().toISOString(),
      },
      route_decision: {
        decision_id: "route-demo", project_id: projectId, primary_route: "QUALITATIVE", confidence: 0.85,
        evidence: ["conversation_intent"], applicable_modules: ["literature_evidence", "qualitative_design", "writing"],
        skipped_modules: ["causal_DAG", "power_analysis", "bootstrap_hypothesis_test", "permutation_test"],
        skip_reasons: ["研究目标是解释性主题归纳，没有待估计的因果或组间效应。"], uncertainties: ["路线判断来自用户描述，需研究者确认。"],
        requires_user_confirmation: true, policy_version: "route-policy-v1", created_at: new Date().toISOString(),
      },
      gate: nextGate,
      execution_started: conversationalDecision && !stopCommand,
    } as T;
  }
  if (path.endsWith("/orchestration/continue") && init?.method === "POST") {
    const projectId = path.split("/")[3] || "physics-ai-demo";
    return {
      task: null,
      control_state: {
        project_id: projectId, lifecycle_status: "ACTIVE", review_policy: "REHEARSAL_ONLY", state_revision: 3,
        workstreams: [{
          workstream_id: `ws-${projectId}-main`, name: "主研究线", route: "QUALITATIVE", status: "ACTIVE",
          phase: "EVIDENCE_PREPARATION", execution_status: "WAITING_USER", current_action: "文献与证据审阅",
          artifact_ids: ["artifact-evidence-review-demo"], gate_ids: ["gate-demo-evidence"], blocker_ids: [], state_revision: 3,
        }],
        route_decision: null, active_workstream_id: `ws-${projectId}-main`, active_gate_id: "gate-demo-evidence", active_blocking_issue_id: null,
        updated_at: new Date().toISOString(),
      },
      gate: {
        gate_id: "gate-demo-evidence", project_id: projectId, workstream_id: `ws-${projectId}-main`, gate_type: "evidence_sufficiency_review",
        level: "G1", status: "PENDING", artifact_ids: ["artifact-evidence-review-demo"], reason: "请查看右侧证据覆盖和研究缺口，并在对话中决定是否继续。",
        warnings: [], risk_acceptance: [], requested_by: "orchestrator", decided_by: null, decision_reason: null,
        created_at: new Date().toISOString(), decided_at: null,
      },
      execution_started: false,
    } as T;
  }
  if (path.includes("/gates/") && path.endsWith("/decision") && init?.method === "POST") {
    const body = typeof init.body === "string" ? JSON.parse(init.body) as { decision?: string } : {};
    return {
      project_id: path.split("/")[3] || "physics-ai-demo", lifecycle_status: body.decision === "stop" ? "TERMINATED" : "ACTIVE",
      review_policy: "REHEARSAL_ONLY", state_revision: 2, workstreams: [], route_decision: null,
      active_workstream_id: null, active_gate_id: null, active_blocking_issue_id: null, updated_at: new Date().toISOString(),
    } as T;
  }
  if (path.endsWith("/control-state")) {
    return {
      project_id: path.split("/")[3] || "physics-ai-demo", lifecycle_status: "ACTIVE", review_policy: "REHEARSAL_ONLY",
      state_revision: 1, workstreams: [], route_decision: null, active_workstream_id: null, active_gate_id: null,
      active_blocking_issue_id: null, updated_at: new Date().toISOString(),
    } as T;
  }
  if (path.endsWith("/blockers")) return [] as T;
  if (path.endsWith("/orchestration/tasks")) return [] as T;
  if (path.includes("/orchestration/tasks/") && path.endsWith("/retry")) {
    return {
      task_id: `demo-retry-${Date.now()}`, project_id: path.split("/")[3] || "physics-ai-demo",
      workstream_id: "ws-demo-main", action: "evidence_normalization", status: "QUEUED",
      claimed_by: null, lease_until: null, heartbeat_at: null, attempt: 1, max_attempts: 3,
      idempotency_key: "demo", input_hash: "demo", expected_state_revision: 1,
      output_artifact_ids: [], error: null, created_at: new Date().toISOString(),
    } as T;
  }
  if (path.endsWith("/workflow/plans") && init?.method === "POST") {
    demoAgentPlan = {
      ...demoAgentPlan,
      status: "PENDING_APPROVAL",
      user_request: init?.body ? JSON.parse(String(init.body)).user_request ?? demoAgentPlan.user_request : demoAgentPlan.user_request,
    };
    return demoAgentPlan as T;
  }
  if (path.includes("/workflow/plans/") && path.endsWith("/approve") && init?.method === "POST") {
    const body = init?.body ? JSON.parse(String(init.body)) as { decision?: string; selected_task_ids?: string[] } : {};
    demoAgentPlan = {
      ...demoAgentPlan,
      status: body.decision === "approved" ? "APPROVED" : "REJECTED",
      approved_task_ids: body.selected_task_ids ?? demoAgentPlan.tasks.map((task) => task.task_id),
      tasks: demoAgentPlan.tasks.map((task) => ({
        ...task,
        status: body.decision === "approved" ? task.status : "SKIPPED",
      })),
    };
    return demoAgentPlan as T;
  }
  if (path.includes("/workflow/plans/") && path.endsWith("/execute") && init?.method === "POST") {
    demoAgentPlan = {
      ...demoAgentPlan,
      status: "COMPLETED",
      executed_at: new Date().toISOString(),
      tasks: demoAgentPlan.tasks.map((task) => ({
        ...task,
        status: "COMPLETED",
        agent_run_id: `${task.agent_id}-demo-run`,
        output_refs: task.expected_output_types.map((type) => `candidate://${task.agent_id}/${type}`),
        persisted_artifact_ids: [`artifact-${task.agent_id}-demo`],
      })),
    };
    return demoAgentPlan as T;
  }
  if (path.endsWith("/workflow/agent-outputs") || path.includes("/workflow/plans/") && path.endsWith("/outputs")) return demoAgentOutputs as T;
  if (path.endsWith("/workflow/page-materials")) return [] as T;
  if (path.includes("/workflow/artifacts/") && path.endsWith("/decision") && init?.method === "POST") {
    return { ok: true, decision: "retain", formalization: "project_material" } as T;
  }
  if (path.startsWith("/workflow/projects/") && path.endsWith("/data-pipeline/raw")) {
    demoPipelineState = {
      ...demoPipelineState,
      stage: "WAITING_PROCESSING_APPROVAL",
      raw_dataset: {
        dataset_id: "raw-demo-upload",
        version: 1,
        sha256: "demo-upload",
      },
      data_audit_report: {
        passed: true,
        missing_required_variables: [],
        risk_flags: [],
      },
      pending_approval: {
        request_id: "data-approval-demo-processing",
        approval_type: "data_processing",
        artifact_ref: "processing-plan-candidate://demo",
        reason: "请确认数据处理计划后继续。",
      },
    };
    return demoPipelineState as T;
  }
  if (path.startsWith("/workflow/projects/") && path.endsWith("/data-pipeline/decide")) {
    const body = typeof init?.body === "string"
      ? JSON.parse(init.body) as { decision?: string }
      : {};
    const transitions: Record<string, DataPipelineStage> = {
      data_processing: "WAITING_FREEZE_APPROVAL",
      data_freeze: "WAITING_EXECUTION_APPROVAL",
      analysis_execution: "ANALYZED",
    };
    const approvalType = demoPipelineState.pending_approval?.approval_type ?? "data_processing";
    const nextStage = body.decision === "approved"
      ? transitions[approvalType] ?? "ANALYZED"
      : "REWORK";
    demoPipelineState = {
      ...demoPipelineState,
      stage: nextStage,
      pending_approval: nextStage === "ANALYZED" || nextStage === "REWORK"
        ? null
        : {
          request_id: `data-approval-demo-${nextStage.toLowerCase()}`,
          approval_type: nextStage === "WAITING_FREEZE_APPROVAL" ? "data_freeze" : "analysis_execution",
          artifact_ref: `candidate://demo/${nextStage}`,
          reason: "请确认下一阶段操作后继续。",
        },
      processed_dataset: nextStage === "WAITING_EXECUTION_APPROVAL" || nextStage === "ANALYZED"
        ? { ref: "dataset://processed-demo/1" }
        : demoPipelineState.processed_dataset,
      frozen_dataset: nextStage === "WAITING_EXECUTION_APPROVAL" || nextStage === "ANALYZED"
        ? { ref: "dataset://frozen-demo/1" }
        : demoPipelineState.frozen_dataset,
      executable_plan: nextStage === "WAITING_EXECUTION_APPROVAL" || nextStage === "ANALYZED"
        ? { analysis_mode: "PYTHON_ONLY", executable_plan_id: "demo-plan" }
        : demoPipelineState.executable_plan,
      validation_report: nextStage === "ANALYZED"
        ? { passed: true, execution_run_refs: ["execution://demo-python"] }
        : demoPipelineState.validation_report,
      statistical_result_card: nextStage === "ANALYZED"
        ? {
          result_id: "demo-result-card",
          execution_status: "execution_verified",
          values: { analysis_sample_size: 48, transfer_mean_difference_group_2_minus_group_1: 0.42 },
        }
        : demoPipelineState.statistical_result_card,
    };
    return demoPipelineState as T;
  }
  if (path.startsWith("/workflow/projects/") && path.endsWith("/data-pipeline/start")) {
    demoPipelineState = {
      ...demoPipelineState,
      stage: "WAITING_RAW_DATA",
      project_id: path.split("/")[3] || demoPipelineState.project_id,
    };
    return demoPipelineState as T;
  }
  if (path.startsWith("/workflow/projects/") && !path.includes("/data-pipeline/")) {
    return {
      project_id: path.split("/")[3] || "physics-ai-demo",
      current_stage: demoPipelineState.stage === "WAITING_RAW_DATA" ? "DATA_READY" : "STUDY_PROTOCOL_APPROVED",
      pending_approval_ref: demoPipelineState.pending_approval?.request_id ?? null,
      last_route_decision: null,
      data_pipeline: demoPipelineState,
      research_state: demoWorkflowState.research_state,
    } as T;
  }
  if (path.includes("/executions")) return demoExecutionRows as T;
  if (path.includes("/routes")) return demoRouteRows as T;
  if (path.includes("/artifacts") || path.includes("/artifact-contents") || path.includes("/agent-runs")) {
    return demoWorkflowState.research_state?.artifact_refs.map((artifact_ref) => ({ artifact_ref, status: "CANDIDATE" })) as T;
  }
  if (path.endsWith("/approve") && init?.method === "POST") return demoResearchState as T;
  if (path.endsWith("/next") && init?.method === "POST") return demoWorkflowRun as T;
  if ((path.includes("/projects/") && path.endsWith("/workflow")) || path.includes("/workflow/projects/")) {
    if (init?.method === "POST") return demoPlanningRun as T;
    return demoWorkflowState as T;
  }
  return demoWorkflowState as T;
}

let demoPipelineState: DataPipelineState = {
  project_id: "physics-ai-demo",
  stage: "WAITING_RAW_DATA",
  preregistered_plan_ref: "prereg-plan://physics-ai-demo/v1",
  preregistration_approval_ref: "approval://physics-ai-demo/prereg-v1",
  code_artifact_ref: null,
  code_specification_ref: null,
  code_review_ref: null,
  code_generation_provider: null,
  code_generation_fallback_reason: null,
  spss_code_artifact_ref: null,
  spss_execution_run_ref: null,
  result_consistency_report_ref: null,
  raw_dataset: null,
  data_audit_report: null,
  processed_dataset: null,
  frozen_dataset: null,
  executable_plan: null,
  validation_report: null,
  statistical_result_card: null,
  pending_approval: null,
  rework_reason: null,
  blocked_target_ids: [],
};

let demoAgentPlan: AgentExecutionPlan = {
  plan_id: "plan-demo-001",
  project_id: "physics-ai-demo",
  conversation_id: "conversation-demo",
  turn_id: "turn-demo-017",
  user_request: "根据当前证据设计一个师范生 Python 物理建模实验",
  conversation_context: [],
  intent_summary: "本轮将处理：文献证据、研究设计",
  status: "PENDING_APPROVAL",
  tasks: [
    {
      task_id: "task-evidence-demo",
      agent_id: "evidence_review",
      task_type: "synthesize_evidence",
      reason: "检索、筛选和组织与当前问题相关的来源证据。",
      input_refs: ["context://demo"],
      required_context: ["context://demo"],
      depends_on: [],
      expected_output_types: ["PaperCardCollection", "EvidenceMatrixCandidate", "ResearchGapReport"],
      risk_level: "HIGH",
      approval_required: true,
      status: "PLANNED",
      blocked_reason: null,
      agent_run_id: null,
      output_refs: [],
      persisted_artifact_ids: [],
      evidence_refs: [],
      risk_flags: ["FORMAL_EVIDENCE_REQUIRES_SOURCE_VERIFICATION"],
      unresolved_questions: [],
      error: null,
      review_note: null,
    },
    {
      task_id: "task-design-demo",
      agent_id: "research_design",
      task_type: "draft_study_protocol",
      reason: "把研究目标转换为变量、测量方案和可审批研究设计。",
      input_refs: ["context://demo"],
      required_context: ["context://demo"],
      depends_on: ["agent:evidence_review"],
      expected_output_types: ["Estimand", "StudyProtocolCandidate", "MeasurementPlan"],
      risk_level: "MEDIUM",
      approval_required: true,
      status: "WAITING_DEPENDENCY",
      blocked_reason: null,
      agent_run_id: null,
      output_refs: [],
      persisted_artifact_ids: [],
      evidence_refs: [],
      risk_flags: [],
      unresolved_questions: [],
      error: null,
      review_note: null,
    },
  ],
  source_context_refs: ["context://demo"],
  risk_flags: ["FORMAL_EVIDENCE_REQUIRES_SOURCE_VERIFICATION"],
  unresolved_questions: [],
  planner_mode: "capability_rules",
  execution_mode: "automatic",
  pending_review_task_id: null,
  rework_note: null,
  approved_task_ids: [],
  approved_by: null,
  approved_at: null,
  executed_at: null,
  created_at: new Date().toISOString(),
};

const demoAgentOutputs: AgentOutputSummary[] = [
  {
    plan_id: "plan-demo-001",
    task_id: "task-evidence-demo",
    project_id: "physics-ai-demo",
    user_request: "根据当前证据设计一个师范生 Python 物理建模实验",
    conversation_id: "conversation-demo",
    turn_id: "turn-demo-017",
    agent_id: "evidence_review",
    task_type: "synthesize_evidence",
    status: "COMPLETED",
    input_refs: ["conversation-turn://conversation-demo/turn-demo-017"],
    depends_on: [],
    risk_level: "HIGH",
    output_types: ["PaperCardCollection", "EvidenceMatrixCandidate"],
    artifact_ids: ["artifact-evidence_review-demo"],
    artifact_refs: ["candidate://evidence_review/PaperCardCollection"],
    evidence_refs: ["evd_demo_001"],
    output_previews: [],
    risk_flags: ["FORMAL_EVIDENCE_REQUIRES_SOURCE_VERIFICATION"],
    unresolved_questions: [],
    decision: "candidate",
    target_pages: ["knowledge_evidence", "evidence_gate"],
    error: null,
  },
];

export const workflowApi = {
  getRuntime() {
    return request<RuntimeStatus>("/workflow/runtime");
  },
  exportResultForSciDAVis(projectId: string) {
    return request<SciDAVisExport>(
      `/workflow/projects/${encodeURIComponent(projectId)}/data-pipeline/visualization/export`,
      { method: "POST" },
    );
  },
  startProject(input: { project_id: string; research_intent: string; run_id?: string }) {
    return request<PlanningRun>(`/projects/${encodeURIComponent(input.project_id)}/workflow`, {
      method: "POST",
      // Project ID is part of the path. The authenticated project endpoint
      // intentionally rejects unknown body fields.
      body: JSON.stringify({ research_intent: input.research_intent, run_id: input.run_id }),
    });
  },
  getProject(projectId: string) {
    return request<WorkflowState>(`/projects/${encodeURIComponent(projectId)}/workflow`);
  },
  getControllerProject(projectId: string) {
    return request<ControllerWorkflowState>(
      `/workflow/projects/${encodeURIComponent(projectId)}`,
    );
  },
  approve(projectId: string, decision: string, decidedBy: string, reason?: string) {
    return request<ResearchState>(`/projects/${encodeURIComponent(projectId)}/workflow/approve`, {
      method: "POST",
      body: JSON.stringify({ decision, decided_by: decidedBy, reason }),
    });
  },
  uploadControllerRawCsv(projectId: string, file: File) {
    const body = new FormData();
    body.append("file", file);
    return request<DataPipelineState>(
      `/workflow/projects/${encodeURIComponent(projectId)}/data-pipeline/raw`,
      { method: "POST", body },
    );
  },
  decideControllerDataPipeline(projectId: string, decision: "approved" | "rejected", decidedBy: string) {
    return request<DataPipelineState>(
      `/workflow/projects/${encodeURIComponent(projectId)}/data-pipeline/decide`,
      {
        method: "POST",
        body: JSON.stringify({ decision, decided_by: decidedBy }),
      },
    );
  },
  listAgents() {
    return request<AgentCapability[]>("/workflow/agents");
  },
  createAgentPlan(input: {
    project_id: string;
    user_request: string;
    conversation_id?: string;
    turn_id?: string;
    context_refs?: string[];
    conversation_context?: string[];
  }) {
    return request<AgentExecutionPlan>(
      `/projects/${encodeURIComponent(input.project_id)}/workflow/plans`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    );
  },
  listAgentPlans(projectId: string) {
    return request<AgentExecutionPlan[]>(
      `/projects/${encodeURIComponent(projectId)}/workflow/plans`,
    );
  },
  approveAgentPlan(
    projectId: string,
    planId: string,
    decision: "approved" | "rejected",
    decidedBy: string,
    selectedTaskIds?: string[],
    executionMode: AgentExecutionMode = "automatic",
  ) {
    return request<AgentExecutionPlan>(
      `/projects/${encodeURIComponent(projectId)}/workflow/plans/${encodeURIComponent(planId)}/approve`,
      {
        method: "POST",
        body: JSON.stringify({
          decision,
          decided_by: decidedBy,
          selected_task_ids: selectedTaskIds,
          execution_mode: executionMode,
        }),
      },
    );
  },
  executeAgentPlan(projectId: string, planId: string) {
    return request<AgentExecutionPlan>(
      `/projects/${encodeURIComponent(projectId)}/workflow/plans/${encodeURIComponent(planId)}/execute`,
      { method: "POST" },
    );
  },
  continueAgentPlan(
    projectId: string,
    planId: string,
    decision: "approved" | "rework",
    decidedBy: string,
    note?: string,
  ) {
    return request<AgentExecutionPlan>(
      `/projects/${encodeURIComponent(projectId)}/workflow/plans/${encodeURIComponent(planId)}/continue`,
      {
        method: "POST",
        body: JSON.stringify({ decision, decided_by: decidedBy, note }),
      },
    );
  },
  listAgentOutputs(
    projectId: string,
    filters: { planId?: string; conversationId?: string; turnId?: string } = {},
  ) {
    const query = new URLSearchParams();
    if (filters.planId) query.set("plan_id", filters.planId);
    if (filters.conversationId) query.set("conversation_id", filters.conversationId);
    if (filters.turnId) query.set("turn_id", filters.turnId);
    const suffix = query.size ? `?${query.toString()}` : "";
    return request<AgentOutputSummary[]>(
      `/projects/${encodeURIComponent(projectId)}/workflow/agent-outputs${suffix}`,
    );
  },
  listPlanOutputs(projectId: string, planId: string) {
    return request<AgentOutputSummary[]>(
      `/projects/${encodeURIComponent(projectId)}/workflow/plans/${encodeURIComponent(planId)}/outputs`,
    );
  },
  listAgentPageMaterials(
    projectId: string,
    filters: { target?: string; conversationId?: string; turnId?: string } = {},
  ) {
    const query = new URLSearchParams();
    if (filters.target) query.set("target", filters.target);
    if (filters.conversationId) query.set("conversation_id", filters.conversationId);
    if (filters.turnId) query.set("turn_id", filters.turnId);
    const suffix = query.size ? `?${query.toString()}` : "";
    return request<AgentPageMaterial[]>(
      `/projects/${encodeURIComponent(projectId)}/workflow/page-materials${suffix}`,
    );
  },
  listFormalEvidence(projectId: string) {
    return request<FormalEvidenceRecord[]>(
      `/projects/${encodeURIComponent(projectId)}/workflow/formal-evidence`,
    );
  },
  decideAgentOutput(
    projectId: string,
    artifactId: string,
    decision: "retain" | "reject" | "apply" | "promote",
    decidedBy: string,
    target?: string,
  ) {
    return request<Record<string, unknown>>(
      `/projects/${encodeURIComponent(projectId)}/workflow/artifacts/${encodeURIComponent(artifactId)}/decision`,
      {
        method: "POST",
        body: JSON.stringify({ decision, decided_by: decidedBy, target }),
      },
    );
  },
  applyAgentManuscript(projectId: string, artifactId: string) {
    return request<{ document_id: string }>(
      `/projects/${encodeURIComponent(projectId)}/workflow/artifacts/${encodeURIComponent(artifactId)}/apply-to-manuscript`,
      { method: "POST" },
    );
  },
  listExecutions(projectId: string) {
    return request<Array<Record<string, unknown>>>(`/workflow/projects/${encodeURIComponent(projectId)}/executions`);
  },
  listArtifacts(projectId: string) {
    return request<Array<Record<string, unknown>>>(`/workflow/projects/${encodeURIComponent(projectId)}/artifacts`);
  },
  listArtifactContents(projectId: string) {
    return request<Array<Record<string, unknown>>>(`/workflow/projects/${encodeURIComponent(projectId)}/artifact-contents`);
  },
  listAgentRuns(projectId: string) {
    return request<Array<Record<string, unknown>>>(`/workflow/projects/${encodeURIComponent(projectId)}/agent-runs`);
  },
  listRoutes(projectId: string) {
    return request<Array<Record<string, unknown>>>(`/workflow/projects/${encodeURIComponent(projectId)}/routes`);
  },
  orchestrationCommand(
    projectId: string,
    message: string,
    interactionMode: "auto" | "discussion" | "workflow" = "auto",
    evidenceMode: "discovery" | "formal" = "discovery",
    conversationId?: string,
    intent?: string,
    executionMode: "sync" | "background" = "background",
    clientTurnId?: string,
  ) {
    return request<ConversationCommandResult>(
      `/projects/${encodeURIComponent(projectId)}/collaboration/turn`,
      {
        method: "POST",
        body: JSON.stringify({
          project_id: projectId,
          message,
          interaction_mode: interactionMode,
          evidence_mode: evidenceMode,
          conversation_id: conversationId,
          intent,
          execution_mode: executionMode,
          client_turn_id: clientTurnId,
        }),
      },
    );
  },
  getResearchCanvas(projectId: string) {
    return request<ResearchBeliefGraph>(
      `/projects/${encodeURIComponent(projectId)}/research-canvas`,
    );
  },
  listResearchBranches(projectId: string) {
    return request<ResearchBranch[]>(
      `/projects/${encodeURIComponent(projectId)}/research-branches`,
    );
  },
  createResearchBranch(projectId: string, branch: Omit<ResearchBranch, "branch_id" | "project_id" | "status" | "version" | "created_at" | "updated_at">) {
    return request<ResearchBranch>(
      `/projects/${encodeURIComponent(projectId)}/research-branches`,
      { method: "POST", body: JSON.stringify(branch) },
    );
  },
  activateResearchBranch(projectId: string, branchId: string, reason?: string) {
    return request<ResearchBranch>(
      `/projects/${encodeURIComponent(projectId)}/research-branches/${encodeURIComponent(branchId)}/activate`,
      { method: "POST", body: JSON.stringify({ reason }) },
    );
  },
  parkResearchBranch(projectId: string, branchId: string, reason?: string) {
    return request<ResearchBranch>(
      `/projects/${encodeURIComponent(projectId)}/research-branches/${encodeURIComponent(branchId)}/park`,
      { method: "POST", body: JSON.stringify({ reason }) },
    );
  },
  getControlState(projectId: string) {
    return request<OrchestrationControlState>(`/projects/${encodeURIComponent(projectId)}/control-state`);
  },
  listProjectBlockers(projectId: string) {
    return request<OrchestrationBlocker[]>(`/projects/${encodeURIComponent(projectId)}/blockers`);
  },
  listOrchestrationTasks(projectId: string) {
    return request<OrchestrationTask[]>(`/projects/${encodeURIComponent(projectId)}/orchestration/tasks`);
  },
  listResearchRuns(projectId: string) {
    return request<ResearchRun[]>(`/projects/${encodeURIComponent(projectId)}/research-runs`);
  },
  getResearchHistory(projectId: string, limit = 200) {
    return request<Array<{
      turn_id: string;
      message: string;
      response: ConversationCommandResult | null;
      status: string;
      created_at: string;
    }>>(`/projects/${encodeURIComponent(projectId)}/conversation/history?limit=${limit}`);
  },
  listOrchestrationEvents(projectId: string, afterId?: string) {
    const query = afterId ? `?after_id=${encodeURIComponent(afterId)}` : "";
    return request<OrchestrationEvent[]>(`/projects/${encodeURIComponent(projectId)}/orchestration/events${query}`);
  },
  async streamOrchestrationEvents(
    projectId: string,
    token: string,
    afterId: string | undefined,
    onEvent: (event: OrchestrationEvent) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    const query = new URLSearchParams();
    if (afterId) query.set("after_id", afterId);
    query.set("timeout_seconds", "55");
    const response = await fetch(
      `${apiBase}/projects/${encodeURIComponent(projectId)}/orchestration/events/stream?${query.toString()}`,
      { headers: { Accept: "text/event-stream", Authorization: `Bearer ${token}` }, signal },
    );
    if (!response.ok || !response.body) {
      throw new Error(`研究动态连接失败（${response.status}）`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          const data = frame
            .split("\n")
            .filter((line) => line.startsWith("data:"))
            .map((line) => line.slice(5).trim())
            .join("\n");
          if (!data) continue;
          try {
            onEvent(JSON.parse(data) as OrchestrationEvent);
          } catch {
            // Ignore malformed frames and keep the stream alive.
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  },
  retryOrchestrationTask(projectId: string, taskId: string) {
    return request<OrchestrationTask>(
      `/projects/${encodeURIComponent(projectId)}/orchestration/tasks/${encodeURIComponent(taskId)}/retry`,
      { method: "POST" },
    );
  },
  setPublicationTarget(projectId: string, targetJournal: string, articleType: string) {
    return request<OrchestrationControlState>(
      `/projects/${encodeURIComponent(projectId)}/publication-target`,
      {
        method: "PUT",
        body: JSON.stringify({ target_journal: targetJournal, article_type: articleType }),
      },
    );
  },
  listProjectClaims(projectId: string) {
    return request<ProjectClaim[]>(`/projects/${encodeURIComponent(projectId)}/claims`);
  },
  getOrchestrationGate(projectId: string, gateId: string) {
    return request<OrchestrationGate>(
      `/projects/${encodeURIComponent(projectId)}/gates/${encodeURIComponent(gateId)}`,
    );
  },
  getEvidenceReviewPackage(projectId: string) {
    return request<EvidenceReviewPackage>(
      `/projects/${encodeURIComponent(projectId)}/evidence-review`,
    );
  },
  decideOrchestrationGate(projectId: string, gateId: string, decision: "approve" | "reject" | "revise" | "stop", riskAcceptance: string[] = [], reason?: string) {
    return request<OrchestrationControlState>(
      `/projects/${encodeURIComponent(projectId)}/gates/${encodeURIComponent(gateId)}/decision`,
      { method: "POST", body: JSON.stringify({ decision, risk_acceptance: riskAcceptance, reason }) },
    );
  },
  continueOrchestration(projectId: string) {
    return request<{ task: Record<string, unknown> | null; control_state: OrchestrationControlState; gate: OrchestrationGate | null; execution_started: boolean; waiting_for_user?: boolean; checkpoint?: string | null }>(
      `/projects/${encodeURIComponent(projectId)}/orchestration/continue`,
      { method: "POST" },
    );
  },
  uploadRawCsv(projectId: string, file: File) {
    const body = new FormData();
    body.append("file", file);
    return request<DataPipelineState>(`/projects/${encodeURIComponent(projectId)}/workflow/data-pipeline/raw`, {
      method: "POST", body,
    });
  },
  decideDataPipeline(projectId: string, decision: "approved" | "rejected", decidedBy: string) {
    return request<DataPipelineState>(`/projects/${encodeURIComponent(projectId)}/workflow/data-pipeline/decide`, {
      method: "POST", body: JSON.stringify({ decision, decided_by: decidedBy }),
    });
  },
};
import {
  demoAgents,
  demoApproval,
  demoExecutionRows,
  demoPlanningRun,
  demoResearchState,
  demoRouteRows,
  demoRuntime,
  demoWorkflowRun,
  demoWorkflowState,
} from "../demo/data";
import type { QAAnswerResponse } from "./qa";
import { apiBase, authenticatedRequest } from "./auth";
