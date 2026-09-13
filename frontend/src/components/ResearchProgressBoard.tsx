import type { QAAnswerResponse } from "../api/qa";
import type { ApprovalRequest, EvidenceReviewPackage, OrchestrationBlocker, OrchestrationControlState, OrchestrationTask, ProjectStage, WorkflowState } from "../api/workflow";
import { buildResearchContext, stageDefinitions, toResearchStage } from "../utils/researchViewModel";

type ResearchProgressBoardProps = {
  workflow?: WorkflowState | null;
  approval?: ApprovalRequest | null;
  response?: QAAnswerResponse | null;
  busy?: boolean;
  onAdvance?: () => void;
  orchestration?: OrchestrationControlState | null;
  evidenceReview?: EvidenceReviewPackage | null;
  blockers?: OrchestrationBlocker[];
  tasks?: OrchestrationTask[];
  onRetryTask?: (task: OrchestrationTask) => void;
};

const emptyWorkflowState: WorkflowState = {
  project_id: "",
  current_stage: "INTAKE",
  pending_approval_ref: null,
  last_agent_run_id: null,
  last_route_decision: null,
  research_state: null,
};

function stageState(index: number, currentIndex: number, waiting: boolean, completedProject = false) {
  if (completedProject && index <= currentIndex) return "complete";
  if (index < currentIndex) return "complete";
  if (index === currentIndex) return waiting ? "waiting" : "current";
  return "upcoming";
}

export function ResearchProgressBoard({
  workflow,
  approval,
  response,
  busy = false,
  onAdvance,
  orchestration,
  evidenceReview,
  blockers = [],
  tasks = [],
  onRetryTask,
}: ResearchProgressBoardProps) {
  const snapshot = workflow ?? emptyWorkflowState;
  const routeStage = response?.workflow_action?.current_stage ?? snapshot.last_route_decision?.current_stage;
  const activeStream = orchestration?.workstreams.find((item) => item.workstream_id === orchestration.active_workstream_id)
    ?? orchestration?.workstreams[0];
  const orchestrationStage: Partial<Record<string, ProjectStage>> = {
    PROJECT_INGESTION: "INTAKE",
    EVIDENCE_PREPARATION: "EVIDENCE_READY",
    RESEARCH_DESIGN: "RESEARCH_QUESTION_APPROVED",
    DATA_PREPARATION: "DATA_READY",
    ANALYSIS_EXECUTION: "ANALYZED",
    RESULT_VALIDATION: "VERIFIED",
    WRITING_PUBLICATION: "DRAFTED",
  };
  const currentStage = orchestration?.lifecycle_status === "COMPLETED"
    ? "release"
    : toResearchStage(
      orchestrationStage[activeStream?.phase ?? ""] ?? snapshot.current_stage,
      routeStage as ProjectStage | null,
    );
  const currentIndex = stageDefinitions.findIndex((stage) => stage.id === currentStage);
  const current = stageDefinitions[currentIndex] ?? stageDefinitions[0];
  const completedProject = orchestration?.lifecycle_status === "COMPLETED";
  const explicitCommitGateTypes = new Set([
    "preregistration_freeze_approval",
    "dataset_freeze_hash_approval",
    "manual_execution_approval_approval",
    "reviewer_final_confirmation_approval",
    "manuscript_citation_verification_approval",
  ]);
  const activeGateIsCommit = Boolean(
    orchestration?.active_gate_id
    && activeStream?.current_action
    && explicitCommitGateTypes.has(`${activeStream.current_action}_approval`),
  );
  const waiting = completedProject
    ? false
    : Boolean(activeGateIsCommit || approval || snapshot.pending_approval_ref || snapshot.current_stage === "WAITING_HUMAN");
  const completedCount = orchestration?.lifecycle_status === "COMPLETED"
    ? stageDefinitions.length
    : Math.max(0, currentIndex + (waiting ? 0 : 1));
  const artifactCount = activeStream?.artifact_ids.length ?? snapshot.research_state?.artifact_refs.length ?? 0;
  const evidenceCount = evidenceReview?.body.coverage.evidence_count ?? response?.citations.length ?? snapshot.research_state?.evidence_refs.length ?? 0;
  const pendingActionLabel: Record<string, string> = {
    create_project: "创建科研项目",
    import_materials: "导入论文、报告和研究材料",
    evidence_normalization: "文献整理与证据规范化",
    hybrid_retrieval: "BM25、Dense 与图谱混合检索",
    rrf_fusion: "RRF 候选证据融合",
    cross_encoder_rerank: "Cross-Encoder 重排序",
    claim_evidence_support: "文献与证据审阅包",
    research_question_design: "形成研究问题",
    research_design: "形成研究方案",
    causal_DAG: "因果结构检查",
    power_analysis: "样本量与统计功效分析",
    preregistration_freeze: "预注册方案",
    raw_data_import: "导入原始研究数据",
    data_audit: "数据审计",
    data_processing_approval: "数据处理审批",
    dataset_freeze_hash: "数据冻结并生成哈希",
    analysis_code_generation: "根据冻结方案生成分析代码",
    physics_code_validation: "物理研究代码校验",
    code_review: "代码审查",
    manual_execution_approval: "人工执行审批",
    sandbox_analysis_execution: "沙箱运行分析代码",
    statistical_result_validation: "统计结果验证",
    bootstrap_robustness: "Bootstrap 稳健性分析",
    permutation_test: "置换检验",
    result_direction_consistency: "结果方向一致性检查",
    uncertainty_gate: "结果可靠性确认",
    statistical_result_card: "生成统计结果卡",
    thematic_analysis: "主题分析",
    qualitative_validation: "定性结果复核",
    writing: "论文写作和引用核验",
    manuscript_citation_verification: "论文引用核验",
    reviewer_final_confirmation: "审稿复核与最终确认",
    mixed_methods_merge: "合并定性与定量论文",
  };
  const nextAction = orchestration?.lifecycle_status === "COMPLETED"
    ? "流程已完成"
    : activeStream?.current_action
    ? pendingActionLabel[activeStream.current_action] ?? activeStream.current_action
    : "当前研究设计";
  const routeLabel: Record<string, string> = {
    QUALITATIVE: "定性研究线",
    EXPERIMENTAL: "实验研究线",
    OBSERVATIONAL_QUANTITATIVE: "观察性定量线",
    PREDICTIVE: "预测研究线",
  };
  const activeBlocker = blockers
    .filter((item) => item.status === "OPEN")
    .sort((left, right) => right.priority - left.priority || left.created_at.localeCompare(right.created_at))[0];
  const taskLabel: Record<string, string> = {
    evidence_normalization: "文献整理与证据规范化",
    hybrid_retrieval: "混合检索",
    rrf_fusion: "RRF 融合",
    cross_encoder_rerank: "证据重排序",
    claim_evidence_support: "主张—证据判断",
    research_question_design: "研究问题设计",
    research_design: "研究方案",
    qualitative_design: "定性研究设计",
    writing: "论文写作",
  };
  const taskStatusLabel: Record<string, string> = {
    QUEUED: "排队中", RUNNING: "执行中", COMPLETED: "已完成", FAILED: "失败",
    STALE: "已过期", CANCELLED: "已取消",
  };
  const retryable = (task: OrchestrationTask) =>
    ["FAILED", "STALE", "CANCELLED"].includes(task.status)
    && task.workstream_id === orchestration?.active_workstream_id
    && !orchestration?.active_gate_id
    && activeStream !== undefined
    && activeStream.current_step_index < activeStream.workflow_steps.length
    && activeStream.workflow_steps[activeStream.current_step_index] === task.action;

  return (
    <section className="research-progress-board" aria-label="研究推进进度">
      <div className="progress-board-topline">
        <div>
          <span className="chat-kicker">研究上下文</span>
          <h2>当前研究的证据与记录</h2>
          <p>系统在后台保留证据、产物和确认记录；你可以继续用自然语言讨论。</p>
        </div>
        <div className="progress-board-summary">
          <strong>{completedCount} / {stageDefinitions.length}</strong>
          <span>已有研究记录</span>
          <small>研究记录状态</small>
        </div>
      </div>

      <details className="progress-board-records">
        <summary>查看研究记录</summary>
        <div className="progress-track" role="list" aria-label="科研阶段">
        {stageDefinitions.map((stage, index) => {
          const state = stageState(index, currentIndex, waiting, completedProject);
          return (
            <div className={`progress-stage progress-stage-${state}`} key={stage.id} role="listitem">
              <div className="progress-stage-marker">{state === "complete" ? "✓" : String(index + 1).padStart(2, "0")}</div>
              <div className="progress-stage-copy">
                <strong>{stage.label}</strong>
                <span>{state === "complete" ? "已记录" : state === "waiting" ? "需要你的判断" : state === "current" ? "处理中" : "尚未涉及"}</span>
              </div>
              {index < stageDefinitions.length - 1 && <i className="progress-connector" aria-hidden="true" />}
              </div>
            );
          })}
        </div>

      <div className="progress-board-detail">
        <div className="progress-current-stage">
          <div className="current-stage-index">{String(currentIndex + 1).padStart(2, "0")}</div>
          <div>
            <span className="eyebrow">当前研究进展</span>
            <h3>{current.label}</h3>
            {activeStream?.current_action && <small>{pendingActionLabel[activeStream.current_action] ?? activeStream.current_action}</small>}
            <p>{orchestration?.lifecycle_status === "COMPLETED" ? "研究记录已经完整，可随时复核证据、结果和论文。" : waiting ? "你可以直接在对话中提问、质疑、修改方向或确认一个具体判断。" : "系统会把对话中的研究意图转成后台任务，并持续回报发现和风险。"}</p>
          </div>
        </div>
        <div className="progress-facts">
          <div><span>研究协作</span><strong>STEM-SSCI/SCI 研究助手</strong></div>
          <div><span>证据</span><strong>{evidenceCount ? `${evidenceCount} 条` : "待收集"}</strong></div>
          <div><span>研究产物</span><strong>{artifactCount ? `${artifactCount} 项` : "待生成"}</strong></div>
          <div><span>互动状态</span><strong className={waiting ? "fact-waiting" : "fact-ready"}>{orchestration?.lifecycle_status === "COMPLETED" ? "可复核" : waiting ? "需要你的判断" : "后台处理中"}</strong></div>
        </div>
        <div className="progress-next-action">
          <span>当前上下文</span>
          <strong>{orchestration?.lifecycle_status === "COMPLETED" ? "研究记录已完成，可复核全部证据" : waiting ? `对话中可讨论${nextAction}` : `后台正在整理${nextAction}`}</strong>
        </div>
      </div>
      {orchestration && orchestration.workstreams.length > 1 && (
        <div className="workstream-overview" aria-label="研究工作线">
          <span className="eyebrow">研究工作线</span>
          <div className="workstream-overview-list">
            {orchestration.workstreams.map((stream) => (
              <div className={`workstream-overview-item${stream.workstream_id === orchestration.active_workstream_id ? " is-active" : ""}`} key={stream.workstream_id}>
                <strong>{routeLabel[stream.route] ?? stream.name}</strong>
                <span>{stream.status === "COMPLETED" ? "已完成" : stream.workstream_id === orchestration.active_workstream_id ? "当前推进" : "等待推进"}</span>
                <small>{stream.current_action ? pendingActionLabel[stream.current_action] ?? stream.current_action : "尚未开始"}</small>
              </div>
            ))}
          </div>
        </div>
      )}
        {activeBlocker && (
        <div className="orchestration-visibility" aria-label="编排状态详情">
          {activeBlocker && (
            <div className="orchestration-blocker" role="status">
              <div><span className="eyebrow">当前待处理事项</span><strong>{activeBlocker.message}</strong></div>
            </div>
          )}
        </div>
        )}
      </details>
    </section>
  );
}
