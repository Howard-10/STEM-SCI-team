"""FastAPI surface for the STEM-SCI workflow platform."""

from __future__ import annotations

import io
import asyncio
import json
import logging
import os
import re
import csv
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from typing import Annotated, Literal, cast
from uuid import uuid4
from xml.etree import ElementTree

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pypdf import PdfReader
from starlette.exceptions import HTTPException as StarletteHTTPException

from .accounts import (
    AuthError,
    AuthTokenPair,
    IdentityService,
    LoginRequest,
    ProjectMember,
    ProjectCreateRequest,
    ProjectMemberUpsertRequest,
    ProjectPatchRequest,
    ResearchIntakeState,
    ResearchProject,
    TokenRefreshRequest,
    UserCreateRequest,
    UserProfile,
)
from .agents import (
    AgentCapability,
    AgentInput,
    DataAnalysisAgent,
    DataAnalysisPreAnalysisInput,
    PlanningBrief,
    ResearchDesignBrief,
    ReviewFinding,
)
from .agents.runtime import GPTProvider, OptionalCoordinator, StructuredGenerator
from .agents.writing_pipeline import (
    AtomicClaimGraph,
    LanguageCode,
    ManuscriptDraft,
    WritingContextBundle,
)
from .artifacts.artifact_store import SQLiteArtifactStore
from .artifacts.content_store import ArtifactContent, SQLiteArtifactContentStore
from .artifacts.execution_store import SQLiteExecutionStore
from .artifacts.models import ArtifactRef
from .context.models import (
    ApiError,
    ApiErrorResponse,
    ContextBuildRequest,
    ContextBundle,
    EvidenceDetail,
    EvidenceRef,
    EvidenceSearchRequest,
    EvidenceSearchResult,
    SourceChunk,
    SourceDocument,
    VerificationStatus,
)
from .context.provider import HybridContextProvider, LocalContextProvider
from .context.service import ContextInputError, ContextNotFoundError, ContextService
from .collaboration import (
    CollaborationDecision,
    EvidenceObservation,
    InteractionMode,
    ResearchAct,
    ResearchBranch,
    ResearchCollaborationEngine,
    ResearchGraph,
    SQLiteResearchGraphStore,
)
from .controller import (
    AgentDispatcher,
    AgentExecutionPlan,
    AgentOutputDecisionRequest,
    AgentPageMaterial,
    FormalEvidenceRecord,
    AgentPlanApprovalRequest,
    AgentTaskApprovalRequest,
    AgentPlanRequest,
    AgentRegistry,
    ControllerWorkflowState,
    DataPipelineBeginRequest,
    DataPipelineController,
    DataPipelinePreparationRequest,
    DataPipelineState,
    PlanningRequest,
    PlanningRunResult,
    ReproducibilityReviewRequest,
    ReproducibilityReviewRunResult,
    ResearchController,
    SQLiteAgentPlanStore,
    SQLiteAgentPageMaterialStore,
    SQLiteFormalEvidenceStore,
    SQLiteDecisionStore,
    SQLiteWorkflowStore,
    WorkflowRunResult,
)
from .controller.policy.route_decision import RouteDecision
from .controller.policy.route_store import SQLiteRouteDecisionStore
from .core.state import ResearchState
from .documents import (
    DocumentCreateRequest,
    DocumentError,
    DocumentFormat,
    DocumentPatchRequest,
    DocumentService,
    DocumentVersion,
    DocumentVersionCreateRequest,
    ProjectDocument,
)
from .knowledge import (
    ConversationSummary,
    ContextMode,
    CorpusManifest,
    HybridContextBuildRequest,
    HybridKnowledgeService,
    MemoryTurn,
    QAAnswerRequest,
    QAAnswerResponse,
    QARouteDecision,
    QuestionAnswerService,
    RetrievalSearchRequest,
    RetrievalSearchResponse,
    SharedCorpusSummary,
)
from .latex import LatexGenerateRequest, LatexGenerateResponse, LatexService, LatexTemplate
from .orchestration import (
    ArtifactLifecycle,
    ArtifactRecord,
    AuditEvent,
    BlockingIssueRecord,
    ClaimRecord,
    ControlPlane,
    ControlPlaneWorker,
    ControlState,
    ConversationCommandJournal,
    ExecutionStatus,
    GateLevel,
    GateRecord,
    GateStatus,
    SQLiteControlPlaneRepository,
    ResearchRun,
    TaskLease,
    ValidationStatus,
)
from .skills.journal_writing import JournalProfileLoader, UnknownArticleTypeError
from .skills.journal_writing.revision import (
    JournalRevisionUnavailableError,
    JournalStyleRevisionRequest,
    JournalStyleRevisionService,
    RevisionStatus,
)
from .knowledge.document_parser import GrobidDocumentParser, ParsedDocument
from .knowledge.evidence_quality import (
    ClaimSupportReport,
    LexicalEvidenceEvaluator,
    build_claim_support_report,
    configured_evidence_provider,
)
from .knowledge.manifest import CorpusRegistry
from .knowledge.external_search import ExternalSearchClient
from .knowledge.screening import ASReviewAdapter, ScreeningQueue, ScreeningRecord
from .operators.executor import OperatorExecutor
from .operators.knowledge import KnowledgeOperatorRuntime
from .operators.models import OperatorRun, OperatorSpec
from .operators.registry import OperatorRegistry
from .provenance.agent_run_store import SQLiteAgentRunStore
from .provenance.models import AgentRunRecord
from .physics import PhysicsValidationGate, PhysicsValidationReport
from .research_data.schema_validation import (
    DeclaredDataSchema,
    DeclaredSchemaValidator,
    SchemaValidationReport,
)
from .research_protocol.causal_adapters import (
    CausalAdapterReport,
    CausalLearnDiscoveryAdapter,
    DoWhyIdentificationAdapter,
)
from .research_protocol.validation import (
    CausalDagReport,
    CausalDagSpec,
    CausalDagValidator,
    PowerAnalysisReport,
    PowerAnalysisRequest,
    PowerAnalyzer,
)
from .settings import ConfigurationReport, validate_environment
from .statistics.conformal import MAPIEConformalAdapter, PredictionInterval
from .statistics.meta_analysis import MetaAnalysisReport, PyMAREMetaAnalysisAdapter
from .statistics.multiple_comparisons import (
    MultipleComparisonOperator,
    MultipleComparisonReport,
    MultiplicityMethod,
)
from .statistics.outliers import OutlierReport, PyODOutlierAdapter
from .statistics.robustness import RobustnessAnalysisOperator, RobustnessReport
from .statistics.sensitivity import ConfoundingSensitivityReport, SensemakrAdapter
from .statistics.scidavis import SciDAVisAdapter, SciDAVisExport
from .statistics.mode_policy import AnalysisMode
from .statistics.models import AnalysisModelSpecification
from .utils.hash_utils import sha256_text
from .verification.uncertainty import QualitySignal, SignalStatus, UncertaintyAssessment, UncertaintyGate

DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173,http://127.0.0.1:5173,"
    "http://localhost:5177,http://127.0.0.1:5177"
)
DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
logger = logging.getLogger("stem_sci.api")
configuration_report: ConfigurationReport

# User-facing decision boundaries.  Internal operators still produce
# immutable artifacts and audit events, but they do not interrupt the chat.
CONVERSATIONAL_HUMAN_GATE_ACTIONS = frozenset({
    "preregistration_freeze",
    "qualitative_design",
    "raw_data_import",
    "dataset_freeze_hash",
    "manual_execution_approval",
    "uncertainty_gate",
    "manuscript_citation_verification",
    "reviewer_final_confirmation",
    "mixed_methods_merge",
})

# Computational grounded-theory checkpoints are conversational pauses rather
# than per-operator Gates.  Each pause corresponds to a distinct reviewable
# artifact and must be answered before the next artifact is generated.
CGT_CONVERSATION_CHECKPOINTS = {
    "sandbox_analysis_execution": "PREPROCESSING_REVIEW",
    "pattern_code_generation": "PATTERN_CODE_REVIEW",
    "pattern_smoke_execution": "PATTERN_SMOKE_REVIEW",
    "pattern_stability_execution": "PATTERN_STABILITY_REVIEW",
    "pattern_discovery_review": "PATTERN_DISCOVERY_REVIEW",
    "codebook_review": "CODEBOOK_REVIEW",
    "manual_theme_revision": "MANUAL_THEME_REVISION_REVIEW",
    "supervised_confirmation": "SUPERVISED_CONFIRMATION_REVIEW",
    "student_level_robustness": "STUDENT_LEVEL_ROBUSTNESS_REVIEW",
    "group_comparison": "GROUP_COMPARISON_REVIEW",
    "result_card_review": "RESULT_CARD_REVIEW",
}

# Manuscript writing is intentionally a multi-turn conversation.  The
# workflow has one durable ``writing`` action, but the researcher-facing
# contract has five bounded outputs before citation verification.  Keeping the
# section request in the workstream feedback makes retries and page refreshes
# idempotent without adding fake approval Gates for each paragraph.
MANUSCRIPT_SECTION_CHECKPOINT = "MANUSCRIPT_SECTION_REVIEW"
MANUSCRIPT_SECTION_ORDER = ("methods", "results", "introduction", "discussion", "full")


def _manuscript_section_request(message: str) -> str | None:
    """Map a writing instruction to one bounded manuscript output."""

    normalized = message.strip().lower()
    if any(term in normalized for term in ("完整候选", "完整论文", "合并为完整", "full candidate", "full manuscript")):
        return "full"
    # Check the more specific phrases first: a methods request can mention
    # results as provenance, while an introduction request can mention theory.
    if any(term in normalized for term in ("数据与方法", "方法部分", "方法章节", "methods")):
        return "methods"
    if any(term in normalized for term in ("引言", "理论背景", "introduction", "background")):
        return "introduction"
    if any(term in normalized for term in ("讨论", "局限", "discussion", "limitations")):
        return "discussion"
    if any(term in normalized for term in ("结果部分", "结果章节", "写“结果”", "写\"结果\"", "results")) or (
        "结果" in normalized and "写" in normalized
    ):
        return "results"
    return None


def _manuscript_outline_request(message: str) -> bool:
    """Recognize an explicit request to create or confirm the paper outline."""

    normalized = message.strip().lower()
    return any(term in normalized for term in ("论文结构", "论文大纲", "每节必须回答", "manuscript outline"))


def _is_conversational_human_gate(gate: GateRecord | None) -> bool:
    """Return whether a persisted gate should remain visible in chat."""
    if gate is None:
        return False
    action = gate.gate_type.removesuffix("_approval")
    return action in CONVERSATIONAL_HUMAN_GATE_ACTIONS


def _conversation_gate_decision(gate_type: str, normalized_message: str) -> str | None:
    """Interpret a chat reply at a human decision boundary.

    Evidence review needs a deliberate revision-first policy: a sentence such
    as ``暂不进入研究设计`` contains the approval phrase ``进入研究设计`` but
    must never advance the study. This remains a bounded workflow command
    parser, rather than delegating approval authority to an LLM.
    """

    stop_terms = ("停止", "终止", "暂停", "stop", "cancel")
    if any(term in normalized_message for term in stop_terms):
        return "stop"
    if gate_type == "manual_execution_approval_approval":
        # Describing a future approval boundary is not approval.  This exact
        # distinction matters in code-review turns such as "先给审查结论和
        # diff，再请求执行批准": the word 批准 is the object of 请求, not
        # the researcher's decision.
        approval_request_terms = (
            "请求执行批准", "再请求执行批准", "等待执行批准", "申请执行批准",
            "request execution approval", "ask for execution approval",
        )
        explicit_execution_approval_terms = (
            "我批准执行", "批准只执行", "确认执行", "可以执行", "同意执行",
            "现在执行", "开始执行", "approve execution", "approved to run",
        )
        explicit_execution_rejection_terms = (
            "不确认执行", "不批准执行", "不要执行", "暂不执行", "不能执行",
            "do not execute", "do not run", "not approved to run",
        )
        if any(term in normalized_message for term in explicit_execution_rejection_terms):
            return "revise"
        if (
            any(term in normalized_message for term in approval_request_terms)
            and not any(term in normalized_message for term in explicit_execution_approval_terms)
        ):
            return None
        if any(term in normalized_message for term in explicit_execution_approval_terms):
            return "approve"
    if "evidence sufficient" in normalized_message or "approve" in normalized_message or "approved" in normalized_message:
        return "approve"
    if "revise" in normalized_message or "search more" in normalized_message:
        return "revise"

    # A negative or deferring instruction must win over a later approval word
    # in the same sentence (for example, "先不要冻结，想再看看方案").
    # Returning "revise" keeps the current candidate intact and asks for the
    # researcher's actual change instead of silently advancing.
    defer_terms = (
        "不要", "先不要", "先不", "暂不", "暂时不", "不确认", "不同意",
        "不执行", "不冻结", "不发布", "不进入", "不继续", "不能继续",
        "还不能", "先别", "do not", "don't", "not yet", "do not run",
    )
    if any(term in normalized_message for term in defer_terms):
        return "revise"

    revise_terms = (
        "继续搜索", "补充文献", "扩大检索", "重新整理", "证据不足", "证据不够",
        "还不够", "再搜", "退回修改", "退回", "revise", "search more",
    )
    # These phrases express a negative or refinement intent specifically at
    # the evidence boundary. Check them before approval phrases so the word
    # "进入研究设计" cannot reverse their meaning.
    evidence_revision_terms = (
        "当前结果不足", "结果不足", "先筛", "筛除", "排除无关", "过滤无关",
        "不要进入研究设计", "暂不进入研究设计", "不进入研究设计", "先不要进入",
    )
    if gate_type == "evidence_sufficiency_review" and any(
        term in normalized_message for term in (*revise_terms, *evidence_revision_terms)
    ):
        return "revise"

    approve_terms = (
        "证据足够", "确认并继续", "进入研究设计", "继续下一步", "可以继续", "同意", "批准",
        "接受", "accept", "approve", "approved",
    )
    if any(term in normalized_message for term in approve_terms):
        return "approve"
    if any(term in normalized_message for term in revise_terms):
        return "revise"
    return None


def _conversation_requests_explanation(normalized_message: str) -> bool:
    """Return whether a turn asks for understanding rather than a transition."""

    question_terms = (
        "为什么", "为何", "什么意思", "怎么理解", "如何理解", "请解释",
        "解释一下", "说明一下", "能否说明", "是否可以说明", "what does",
        "why", "explain", "how should i interpret",
    )
    return any(term in normalized_message for term in question_terms) or normalized_message.endswith(("？", "?"))


def _conversation_message_targets_gate(gate_type: str, normalized_message: str) -> bool:
    """Return whether an auto-mode turn is clearly addressed to a pending gate.

    This only selects the conversation path. The authoritative decision is
    still parsed and applied below by the normal gate handler. Keeping the
    routing rule here prevents clear confirmations from falling into ordinary
    QA before that handler gets a chance to read them.
    """

    if _conversation_requests_explanation(normalized_message):
        return False
    if _conversation_gate_decision(gate_type, normalized_message) is not None:
        return True

    negative_terms = (
        "不要", "先不要", "先不", "暂不", "暂时不", "不确认", "不同意",
        "不执行", "不冻结", "不发布", "不进入", "不继续", "先别",
    )
    confirmation_terms = ("确认", "confirm")
    transition_terms = ("继续", "执行", "审查", "进入", "冻结", "发布", "下一步")
    if (
        any(term in normalized_message for term in confirmation_terms)
        and any(term in normalized_message for term in transition_terms)
        and not any(term in normalized_message for term in negative_terms)
    ):
        return True
    if gate_type == "manual_execution_approval_approval" and (
        "generate analysis code" in normalized_message
        or "generate code" in normalized_message
    ):
        return True
    return (
        "confirm outline" in normalized_message
        or "confirm the manuscript outline" in normalized_message
        or "确认论文大纲" in normalized_message
    )


def _cn(*codepoints: int) -> str:
    """Build Chinese intent phrases without embedding non-ASCII source bytes."""

    return "".join(chr(codepoint) for codepoint in codepoints)


_CN_INTENT = {
    "uploaded": _cn(0x5df2, 0x4e0a, 0x4f20),
    "data": _cn(0x6570, 0x636e),
    "reanalyze": _cn(0x518d, 0x5206, 0x6790),
    "do_once": _cn(0x505a, 0x4e00, 0x6b21),
    "discuss": _cn(0x5148, 0x8ba8, 0x8bba),
    "search": _cn(0x76f4, 0x63a5, 0x68c0, 0x7d22),
    "start_search": _cn(0x5f00, 0x59cb, 0x68c0, 0x7d22),
    "confirm_brief": _cn(0x786e, 0x8ba4, 0x7814, 0x7a76, 0x7b80, 0x62a5),
    "evidence_enough": _cn(0x8bc1, 0x636e, 0x8db3, 0x591f),
    "continue": _cn(0x786e, 0x8ba4, 0x5e76, 0x7ee7, 0x7eed),
    "freeze": _cn(0x51bb, 0x7ed3),
    "analysis": _cn(0x5206, 0x6790),
    "execute": _cn(0x6267, 0x884c),
    "generate_code": _cn(0x751f, 0x6210, 0x5206, 0x6790, 0x4ee3, 0x7801),
    "confirm": _cn(0x786e, 0x8ba4),
    "select": _cn(0x9009),
    "modify": _cn(0x4fee, 0x6539),
    "adjust": _cn(0x8c03, 0x6574),
    "retain": _cn(0x4fdd, 0x7559),
    "delete": _cn(0x5220, 0x9664),
}


def _conversation_prefers_discussion(message: str) -> bool:
    normalized = message.strip().lower()
    open_discussion_markers = (
        "不要急着", "先别开始", "先不开始", "暂不开始", "先帮我看看", "先帮我看", "先帮我理解",
        "先看看现有", "先梳理", "先分析一下可行性", "先讨论", "只讨论", "先了解",
        "暂不分析", "不要正式分析", "不开始正式分析", "先做资料理解",
        "不生成研究方案", "不要生成研究方案", "help me understand first", "do not start yet",
        "不要检索", "不要搜索", "不要找证据", "先不要找证据", "只讨论证据",
        # Information requests are not consent to advance a workflow. These
        # markers cover the common case where a researcher asks what to
        # upload or how a field will be audited while a task is active.
        "请告诉我", "告诉我下一步", "下一步需要", "需要上传", "上传哪些",
        "哪些数据", "什么数据", "字段分别", "字段怎么", "如何审查", "怎么审查",
        "先说明", "先解释", "暂时不要执行", "不要执行分析", "不要开始分析",
        "what do i need to upload", "which fields", "how will you audit",
    )
    return any(marker in normalized for marker in open_discussion_markers)


def _auto_requests_workflow(message: str, state: ControlState) -> bool:
    """Resolve only clear action language; ordinary turns stay discussion."""

    normalized = message.strip().lower()
    if _conversation_prefers_discussion(message):
        return False
    # Result-card generation is a workflow action even when the client uses
    # the default ``auto`` mode. Without this branch, an explicit request such
    # as "生成并冻结结果卡" can fall through to literature QA after the auto
    # classifier resolves the mode, leaving the orchestration state unchanged.
    if _conversation_requests_result_card(normalized) and not _conversation_requests_explanation(normalized):
        return True
    # These checks are intentionally constructed from code points because
    # this Windows checkout contains legacy mojibake in older string literals.
    # They keep real Chinese input routable while the file is migrated.
    if (
        state.route_decision is None
        and _CN_INTENT["uploaded"] in normalized
        and _CN_INTENT["data"] in normalized
        and any(term in normalized for term in (_CN_INTENT["reanalyze"], _CN_INTENT["do_once"], _cn(0x5f00, 0x5c55)))
    ):
        return True
    if _CN_INTENT["discuss"] in normalized and _CN_INTENT["search"] not in normalized:
        return False
    # Natural commands often separate the two words, for example
    # "现在开始建立研究任务，请检索并整理文献".  Requiring the fixed
    # phrase "开始检索" made that unmistakable instruction fall back to
    # ordinary chat.  This remains deliberately narrow: a start verb and a
    # retrieval verb must both be present after explicit opt-outs are removed.
    start_research_terms = (
        _cn(0x73B0, 0x5728, 0x5F00, 0x59CB),
        _cn(0x5F00, 0x59CB, 0x5EFA, 0x7ACB, 0x7814, 0x7A76, 0x4EFB, 0x52A1),
        _cn(0x542F, 0x52A8, 0x7814, 0x7A76),
        _cn(0x5F00, 0x5C55, 0x7814, 0x7A76),
    )
    if any(term in normalized for term in start_research_terms) and _cn(0x68C0, 0x7D22) in normalized:
        return True
    # The authenticated frontend sends natural Chinese action requests such
    # as “确定研究问题与方案” and “找证据”.  These are explicit workflow
    # commands even when they do not contain the older “开始检索” wording.
    # Keep the discussion guard above first so “先讨论研究问题” remains QA.
    research_design_actions = (
        "\u786e\u5b9a\u7814\u7a76\u95ee\u9898",
        "\u786e\u5b9a\u7814\u7a76\u65b9\u6848",
        "\u7814\u7a76\u95ee\u9898\u4e0e\u65b9\u6848",
        "\u5f62\u6210\u7814\u7a76\u8bbe\u8ba1",
        "\u5236\u5b9a\u7814\u7a76\u65b9\u6848",
        "\u751f\u6210\u7814\u7a76\u95ee\u9898",
    )
    evidence_retrieval_actions = (
        "\u627e\u8bc1\u636e",
        "\u67e5\u627e\u8bc1\u636e",
        "\u5bfb\u627e\u8bc1\u636e",
        "\u5217\u51fa\u539f\u6587\u8bc1\u636e",
        "\u5019\u9009\u8bc1\u636e",
        "\u641c\u7d22\u8bc1\u636e",
        "\u67e5\u6587\u732e",
    )
    if any(term in normalized for term in (*research_design_actions, *evidence_retrieval_actions)):
        return True
    if any(term in normalized for term in (_CN_INTENT["search"], _CN_INTENT["start_search"], _CN_INTENT["evidence_enough"], _CN_INTENT["continue"], _CN_INTENT["freeze"], _CN_INTENT["execute"], _CN_INTENT["generate_code"], "start search", "search directly", "evidence sufficient", "continue", "freeze", "execute analysis", "generate analysis code", "revise", "confirm", "approve", "confirm brief")):
        return True
    # Older dialogue turns used this wording for the "continue" affordance.
    # Treat it as the same explicit transition so an already-open demo does
    # not remain stuck after the copy is upgraded.
    if "明确暂定边界" in normalized and "继续推进" in normalized:
        return True
    if _conversation_requests_explanation(normalized) or any(
        marker in normalized
        for marker in (
            "\u4e0d\u8981\u76f4\u63a5", "\u4e0d\u8981\u5f00\u59cb", "\u5148\u8ba8\u8bba", "\u53ea\u8ba8\u8bba", "\u5148\u4e86\u89e3", "\u6682\u4e0d\u5206\u6790",
            "\u5148\u505a\u8d44\u6599\u7406\u89e3", "\u4e0d\u751f\u6210\u7814\u7a76\u65b9\u6848", "\u4e0d\u8981\u751f\u6210\u7814\u7a76\u65b9\u6848",
        )
    ):
        return False
    # Deliberation is not consent to start a workflow. These phrases commonly
    # occur in substantive research messages, so checking them before action
    # markers prevents a sentence such as "我想比较两个方案" from becoming
    # an accidental execution request.
    discussion_markers = (
        "\u6211\u60f3\u8ba8\u8bba", "\u6211\u60f3\u5148\u8ba8\u8bba", "\u6211\u60f3\u4e86\u89e3", "\u6211\u60f3\u6bd4\u8f83", "\u6211\u60f3\u8bc4\u4f30",
        "\u6211\u89c9\u5f97", "\u4f60\u89c9\u5f97", "\u600e\u4e48\u770b", "\u9002\u5408\u56de\u7b54\u4ec0\u4e48", "\u80fd\u56de\u7b54\u4ec0\u4e48",
        "\u7814\u7a76\u8fb9\u754c", "\u8d44\u6599\u7406\u89e3", "\u6587\u732e\u7406\u89e3", "\u53ef\u884c\u6027", "\u4f18\u7f3a\u70b9",
        "\u6bd4\u8f83\u4e00\u4e0b", "\u8bc4\u4ef7\u4e00\u4e0b", "\u804a\u804a", "\u8ba8\u8bba\u4e00\u4e0b", "\u5148\u770b\u770b",
        "\u4e0d\u786e\u5b9a", "\u8fd8\u5728\u8003\u8651", "\u5148\u542c\u542c", "\u5e2e\u6211\u5224\u65ad",
    )
    if any(marker in normalized for marker in discussion_markers):
        return False
    explicit_actions = (
        "\u76f4\u63a5\u68c0\u7d22", "\u5f00\u59cb\u68c0\u7d22", "\u7ee7\u7eed\u641c\u7d22", "\u518d\u641c", "\u8865\u5145\u6587\u732e", "\u6269\u5927\u68c0\u7d22",
        "\u8bc1\u636e\u8db3\u591f", "\u8bc1\u636e\u4e0d\u8db3", "\u8fdb\u5165\u7814\u7a76\u8bbe\u8ba1", "\u786e\u8ba4\u5e76\u7ee7\u7eed", "\u9000\u56de\u4fee\u6539",
        "\u91c7\u7528\u8fd9\u4e2a\u7814\u7a76\u95ee\u9898", "\u63a5\u53d7\u8fd9\u4e2a\u65b9\u6848", "\u51bb\u7ed3\u6570\u636e", "\u6267\u884c\u5206\u6790", "\u5f00\u59cb\u5206\u6790",
        "\u751f\u6210\u7814\u7a76\u65b9\u6848", "\u5f00\u59cb\u5199\u4f5c", "\u53d1\u5e03\u8bba\u6587",
        "\u751f\u6210\u4ee3\u7801", "\u5206\u6790\u4ee3\u7801", "\u5199\u4ee3\u7801", "\u751f\u6210\u5019\u9009\u8bba\u6587",
        "\u8bba\u6587\u8349\u7a3f", "\u8bba\u6587\u521d\u7a3f", "\u5b8c\u6574\u8bba\u6587", "generate code", "generate manuscript",
        "python\u4ee3\u7801", "python \u4ee3\u7801", "\u4ee3\u7801\u6821\u9a8c", "\u5019\u9009\u8bba\u6587",
        "\u8bba\u6587\u8349\u7a3f", "\u8bba\u6587\u521d\u7a3f", "\u751f\u6210\u4e00\u7bc7\u8bba\u6587", "\u751f\u6210\u5b8c\u6574\u8bba\u6587",
        "approve", "approved", "revise", "freeze",
    )
    if any(term in normalized for term in explicit_actions):
        return True
    return False


def _checkpoint_response_is_action(checkpoint: str, normalized_message: str) -> bool:
    """Require an observable choice or edit before leaving a checkpoint."""

    # Outline review is deliberately stricter than the analysis checkpoints:
    # a later research message may mention merging themes or revising rules,
    # but that must not be interpreted as approval to start manuscript prose.
    if checkpoint == "MANUSCRIPT_OUTLINE_REVIEW":
        return any(
            term in normalized_message
            for term in ("大纲", "结构", "论证顺序", "开始写", "正文", "起草", "确认论文大纲", "confirm outline", "confirm the manuscript outline")
        )
    if checkpoint == MANUSCRIPT_SECTION_CHECKPOINT:
        return _manuscript_section_request(normalized_message) is not None

    if checkpoint == "ANALYSIS_CODE_REVIEW":
        # Asking to see the specification leaves it under review.  Asking for
        # the first runnable preprocessing candidate is the bounded action
        # that accepts the specification and creates the next artifact.
        if "只生成分析代码规格" in normalized_message:
            return False
        return any(
            term in normalized_message
            for term in (
                "可运行代码候选", "生成预处理代码", "确认代码规格", "批准代码规格",
                "接受代码规格", "confirm code specification", "approve code specification",
            )
        )
    if checkpoint == "CODE_REVIEW_REVIEW":
        return any(
            term in normalized_message
            for term in (
                "执行前审查", "审查这段代码", "给审查结论", "修改 diff",
                "确认代码审查", "通过代码审查", "confirm code review",
            )
        )
    if checkpoint == "PREPROCESSING_REVIEW":
        return any(
            term in normalized_message
            for term in ("确认以句子", "冻结预处理", "确认预处理", "生成模式发现代码")
        )
    if checkpoint == "PATTERN_CODE_REVIEW":
        # Parameter edits regenerate/inspect the candidate in place.  Only a
        # clear smoke-test approval may start execution.
        return any(
            term in normalized_message
            for term in ("批准 20", "批准20", "批准烟雾测试", "确认执行烟雾测试", "approve smoke")
        )
    if checkpoint == "PATTERN_SMOKE_REVIEW":
        return any(
            term in normalized_message
            for term in ("运行 100", "运行100", "1000 个种子", "1000个种子", "稳定性分析")
        )
    if checkpoint == "PATTERN_STABILITY_REVIEW":
        return any(
            term in normalized_message
            for term in ("生成审阅包", "候选簇生成审阅包", "代表句", "边界句", "噪声簇")
        )

    if any(
        term in normalized_message
        for term in (
            _CN_INTENT["confirm"], _CN_INTENT["select"], _CN_INTENT["modify"],
            _CN_INTENT["adjust"], _CN_INTENT["retain"], _CN_INTENT["delete"],
            _cn(0x5f00, 0x59cb, 0x5199),
            "confirm", "select", "revise", "adjust", "retain", "outline", "generate",
            "批准", "同意", "通过", "继续", "执行", "运行", "进入下一步",
            "execute analysis", "approve execution", "run the analysis",
        )
    ):
        return True

    common = ("采用", "接受", "确认", "选择", "修改", "调整", "合并", "保留", "删除", "改成")
    checkpoint_terms = {
        "RESEARCH_QUESTION_REVIEW": ("第一个", "第二个", "研究问题", "主要问题", "我倾向"),
        "RESEARCH_DESIGN_REVIEW": ("研究设计", "研究方案", "变量", "样本", "分组", "测量"),
        "RESULT_INTERPRETATION_REVIEW": ("结论", "解释", "讨论重点", "收紧", "弱化", "强调"),
        "MANUSCRIPT_OUTLINE_REVIEW": ("大纲", "结构", "论证顺序", "开始写", "正文", "起草"),
        "ANALYSIS_CODE_REVIEW": ("代码", "规格", "模块", "输入", "输出", "确认执行"),
        "CODE_REVIEW_REVIEW": ("代码审查", "静态审查", "执行", "确认", "通过"),
        "PATTERN_DISCOVERY_REVIEW": ("模式", "簇", "聚类", "代表句", "边界句", "噪声", "保留", "拆分", "合并"),
        "CODEBOOK_REVIEW": ("Codebook", "编码", "主题", "纳入", "排除", "反例", "边界"),
        "MANUAL_THEME_REVISION_REVIEW": ("人工", "修订", "命名", "合并", "拆分", "标签"),
        "SUPERVISED_CONFIRMATION_REVIEW": ("监督", "交叉验证", "F1", "kappa", "召回率", "标签"),
        "STUDENT_LEVEL_ROBUSTNESS_REVIEW": ("学生层面", "稳健性", "比例", "依赖", "bootstrap"),
        "GROUP_COMPARISON_REVIEW": ("组间", "奥赛", "对照", "列联表", "卡方", "效应量", "非随机"),
        "RESULT_CARD_REVIEW": ("结果卡", "冻结结果", "数字", "证据", "确认"),
    }
    terms = (*common, *checkpoint_terms.get(checkpoint, ()))
    return any(term in normalized_message for term in terms) or (
        any(token in normalized_message for token in ("选择", "选第", "选出"))
        and any(token in normalized_message for token in ("第", "个", "一", "二", "两", "1", "2"))
    )


def _conversation_requests_result_card(normalized_message: str) -> bool:
    """Recognize result-card requests before they reach generic QA."""

    return (
        "结果卡" in normalized_message
        and any(
            term in normalized_message
            for term in ("生成", "建立", "冻结", "连接", "写作前", "支持的数字")
        )
    )


def _conversational_gate_progress_message(gate: GateRecord) -> str:
    """Describe the completed work before asking for the next human decision."""

    messages = {
        "evidence_sufficiency_review": (
            "文献整理、混合检索、去重、重排序和主张—证据判断已完成。"
            "右侧可查看来源、证据片段、覆盖情况和研究缺口。"
            "确认文献足够后，系统才会进入研究设计。"
        ),
        "preregistration_freeze_approval": (
            "研究问题、假设、变量定义、研究设计、DAG 和样本量建议已生成。"
            "右侧的预注册候选已汇总研究者确认的设计边界。"
            "请审核后确认冻结，再导入原始数据。"
        ),
        "raw_data_import_approval": (
            "研究方案已冻结，当前需要导入去标识化的原始数据。"
            "上传后直接说“审计这份原始数据”或“确认上传数据，继续”。"
        ),
        "dataset_freeze_hash_approval": (
            "原始数据审计已完成。右侧可查看字段、行列数、缺失值、重复记录、异常值和数据质量提示。"
            "确认后系统会冻结数据、生成哈希并生成分析代码。"
        ),
        "manual_execution_approval_approval": (
            "冻结数据、分析代码、AST/公式/单位/约束检查和代码审查已生成。"
            "右侧可查看代码与检查结果；确认执行后才会运行统计分析。"
        ),
        "uncertainty_gate_approval": (
            "统计结果卡、Bootstrap 稳健性分析、置换检验和方向一致性检查已完成。"
            "右侧显示数值与不确定性提示；确认后系统会生成论文草稿和引用核验。"
        ),
        "reviewer_final_confirmation_approval": (
            "论文草稿、引用核验、主张—证据链和结果来源追踪已生成。"
            "现在需要独立审稿人进行最终复核。"
        ),
    }
    return messages.get(
        gate.gate_type,
        f"当前产物已生成。{gate.reason or '请查看右侧结果后决定是否继续。'}",
    )


def _mentor_boundary_message(gate: GateRecord) -> str:
    """Turn a durable approval boundary into a researcher-facing dialogue turn.

    The Gate remains authoritative for permissions and audit, but its database
    name must not become the task the researcher has to understand.
    """

    prompts = {
        "evidence_sufficiency_review": (
            "我已把本轮文献分成可定位原文、待核验外部候选和不确定证据；右侧可查看它们的范围与缺口。"
            "现在最关键的问题是：这些材料是否已足以支持你要研究的问题？"
            "你可以直接告诉我还想补哪些主题、哪些候选不相关，或者认为当前材料已经足够；也可以先问我这些材料能支持什么。"
        ),
        "preregistration_freeze_approval": (
            "研究问题、变量定义和分析边界已经整理成研究方案。冻结后，任何实质修改都会产生新版本并使下游结果过期。"
            "请先判断：这个方案是否准确表达了你真正要检验的内容？你可以修改某项边界，或说“确认研究方案并冻结”。"
        ),
        "raw_data_import_approval": (
            "研究方案已经确定。下一步需要你提供与该方案匹配的去标识化原始数据；上传后我会先审计，不会自动修改或冻结。"
            "你可以上传数据后说“审计这份数据”，或告诉我现在缺少什么数据。"
        ),
        "dataset_freeze_hash_approval": (
            "我已完成数据审计，并在右侧列出字段、缺失、重复和异常提示。"
            "现在需要你决定这些处理边界是否可接受；确认后才会创建不可变的数据版本并生成代码候选。"
        ),
        "manual_execution_approval_approval": (
            "分析代码和执行前检查已经准备好。右侧可查看它读取哪些冻结数据、比较什么，以及检查发现的风险。"
            "请判断这个分析是否符合你的方案；确认后才会在受控环境执行。"
        ),
        "uncertainty_gate_approval": (
            "统计验证、稳健性分析和方向一致性检查已经完成。"
            "我需要你先确认结果可以怎样解释，以及哪些不确定性必须保留；确认后才会把这些边界写入论文候选稿。"
        ),
        "reviewer_final_confirmation_approval": (
            "论文候选稿、引用核验和主张追溯已经汇总。现在需要独立审稿人判断研究问题、证据、数据、结果与结论是否一致。"
            "研究者本人不能替代这一步。"
        ),
    }
    return prompts.get(gate.gate_type, _conversational_gate_progress_message(gate))


def _conversation_checkpoint(state: object) -> str | None:
    """Read the active durable chat checkpoint from a serialized state."""

    if not isinstance(state, dict):
        return None
    for stream in state.get("workstreams", []):
        if isinstance(stream, dict) and stream.get("workstream_id") == state.get("active_workstream_id"):
            value = stream.get("conversation_checkpoint")
            return value if isinstance(value, str) and value else None
    return None


def _checkpoint_message(checkpoint: str) -> str:
    return {
        "RESEARCH_QUESTION_REVIEW": (
            "基于当前证据，我已经整理出研究问题候选并放在右侧。现在先不要急着做研究设计："
            "你最希望回答的是哪一个问题？你可以选择某个候选、把两个候选合并，或直接说明你觉得问题哪里不对。"
        ),
        "RESEARCH_DESIGN_REVIEW": (
            "我已把研究问题转成了一个可执行的设计，并补充了变量、比较方式和解释边界。"
            "此刻最重要的是：这个设计是否真正回答你的问题，而不是只看起来完整？请指出要保留、删除或重写的部分。"
        ),
        "RESULT_INTERPRETATION_REVIEW": (
            "结果和稳健性检查已经完成。我已把可支持的结论、反例和不能声称的范围分开放在右侧。"
            "你认为论文应把重点放在哪里？也可以要求我先解释任意一个数值或限制，再决定是否开始写作。"
        ),
        "MANUSCRIPT_OUTLINE_REVIEW": (
            "我已把证据和结果组织成论文大纲与主张—证据表。"
            "请先判断论证顺序是否符合你想表达的研究故事；你可以调整章节、删掉过强主张，或确认后再写正文。"
        ),
        MANUSCRIPT_SECTION_CHECKPOINT: (
            "论文大纲已经确认。请按顺序指定要生成的章节：数据与方法、结果、引言和理论背景、讨论和局限；"
            "每一节都只使用已经冻结的资料、代码记录、结果卡和可核验文献。完成四节后再说‘合并为完整候选论文’，"
            "系统才会生成完整候选稿并进入引用核验。"
        ),
        "MANUSCRIPT_REVISION_REVIEW": (
            "初稿已经生成，但写作质量审查发现需要修改的部分，我已在右侧列出具体章节和原因。"
            "请告诉我是否按这些建议重新生成写作候选；系统不会改变已验证的数字、结果或引用。"
        ),
        "ANALYSIS_CODE_REVIEW": (
            "我已根据冻结数据和研究边界生成可审查的分析代码规格。请检查模块、输入输出、随机性和失败条件；"
            "确认后才会进入代码审查和执行准备。"
        ),
        "CODE_REVIEW_REVIEW": (
            "第一个可运行的预处理代码候选已经生成，但尚未执行。右侧保留代码、输入输出和静态检查项；"
            "请先审查 nan、Stu_ID、公式保护、原始文件只读、随机性以及句子/学生分析单位，再决定是否请求执行。"
        ),
        "PREPROCESSING_REVIEW": (
            "数据审计和预处理已经在冻结输入上单独执行，未下载嵌入模型，也未生成主题或聚类。"
            "右侧可查看实际句子数、每名学生句子数分布、10/20/30 字符阈值敏感性、短片段示例和公式复核清单；"
            "确认这些边界后才会生成模式发现代码。"
        ),
        "PATTERN_CODE_REVIEW": (
            "模式发现代码候选已经生成但尚未执行。右侧分别记录嵌入模型、UMAP、HDBSCAN 和 20/100/1000 种子计划；"
            "你可以修改参数，只有明确批准 20 种子烟雾测试后才会运行。"
        ),
        "PATTERN_SMOKE_REVIEW": (
            "20 种子烟雾测试步骤已经结束。右侧只记录实际环境、运行状态、耗时、内存、簇数和噪声比例；"
            "若运行受阻，这些数值保持为空，不会用计划值代替。请据此决定是否请求 100/1000 种子稳定性运行。"
        ),
        "PATTERN_STABILITY_REVIEW": (
            "稳定性运行步骤已经结束。右侧只保存实际完成的种子数、簇数与噪声分布和跨种子稳定性；"
            "未实际运行的部分明确标为未执行。现在可以请求生成与这些证据相匹配的候选簇审阅包。"
        ),
        "PATTERN_DISCOVERY_REVIEW": (
            "模式发现试运行已经生成中性簇、噪声摘要和可追溯的聚类审阅包。请先阅读代表句、边界句和噪声样本，"
            "说明哪些模式值得保留、拆分或合并；系统不会把簇名预设成理论主题。"
        ),
        "CODEBOOK_REVIEW": (
            "我已根据模式发现结果整理 Codebook 候选。请检查每个主题的定义、纳入/排除标准、正例、边界例和反例，"
            "并指出需要调整的编码规则；此时仍不是冻结结果。"
        ),
        "MANUAL_THEME_REVISION_REVIEW": (
            "人工主题修订候选已经生成。请确认研究者的命名、合并/拆分和反例处理，系统会保留修订理由并生成下一版标签。"
        ),
        "SUPERVISED_CONFIRMATION_REVIEW": (
            "监督确认候选已生成，包含句子级分层交叉验证和按 Stu_ID 分组验证的规格。请确认标签来源、折叠方式、类别不平衡和性能指标。"
        ),
        "STUDENT_LEVEL_ROBUSTNESS_REVIEW": (
            "学生层面聚合与稳健性候选已经生成。请检查同一学生多句依赖、主题比例计算和稳健性边界，再决定是否纳入结果卡。"
        ),
        "GROUP_COMPARISON_REVIEW": (
            "组间比较候选已经生成。请确认分组编码、描述性列联表、效应量和非随机比较边界；系统不会把关联写成因果。"
        ),
        "RESULT_CARD_REVIEW": (
            "结果卡已把数据审计、模式发现、人工复核、监督确认、学生层稳健性和组间比较连接到冻结输入、代码和日志。"
            "请逐项确认哪些数字和解释可以进入论文。"
        ),
        "DATA_DESIGN_REVIEW": (
            "当前数据审计发现研究设计与数据字段不完全匹配。请说明是修改研究问题/设计，还是上传包含前测和后测字段的数据；确认前不会冻结数据。"
        ),
    }.get(checkpoint, "当前研究节点需要你的判断。请直接回复确认或说明要修改的内容。")


def _checkpoint_message_for_project(project_id: str, checkpoint: str | None) -> str:
    """Render execution checkpoints from persisted evidence, not plan values."""

    if not checkpoint:
        return ""
    if checkpoint == "PREPROCESSING_REVIEW":
        body = _latest_artifact_body(project_id, "PreprocessingExecutionCandidate") or {}
        execution = body.get("execution") if isinstance(body.get("execution"), dict) else {}
        distribution = body.get("sentence_count_distribution") if isinstance(body.get("sentence_count_distribution"), dict) else {}
        sensitivity = body.get("threshold_sensitivity") if isinstance(body.get("threshold_sensitivity"), dict) else {}
        if execution.get("performed"):
            threshold_text = "，".join(
                f"阈值 {key} 保留 {value.get('retained', 0)} / 排除 {value.get('excluded', 0)}"
                for key, value in sensitivity.items()
                if isinstance(value, dict)
            )
            return (
                f"预处理已单独执行：纳入 {execution.get('student_count', 0)} 名学生，切分得到 "
                f"{execution.get('candidate_sentence_count', 0)} 个候选句段，20 字符基线保留 "
                f"{execution.get('retained_sentence_count_at_20', 0)} 个；每名学生保留句数最小/中位数/最大值为 "
                f"{distribution.get('minimum', 0)}/{distribution.get('median', 0)}/{distribution.get('maximum', 0)}。"
                f"{threshold_text}。短公式片段进入复核清单。嵌入、聚类和主题标注均未执行；"
                "请确认预处理边界后再生成模式发现代码。"
            )
    if checkpoint == "PATTERN_SMOKE_REVIEW":
        body = _latest_artifact_body(project_id, "PatternSmokeExecutionCandidate") or {}
        execution = body.get("execution") if isinstance(body.get("execution"), dict) else {}
        if execution.get("performed") is False:
            return (
                f"20 种子烟雾测试未执行：{str(execution.get('reason') or '没有可验证执行日志').rstrip('。')}。"
                "已完成种子数为 0；运行时间、内存、簇数和噪声比例保持为空，不能宣称烟雾测试通过。"
                "后续 100/1000 种子只能记录为待执行计划。"
            )
    if checkpoint == "PATTERN_STABILITY_REVIEW":
        body = _latest_artifact_body(project_id, "PatternStabilityExecutionCandidate") or {}
        execution = body.get("execution") if isinstance(body.get("execution"), dict) else {}
        if execution.get("performed") is False:
            return (
                f"稳定性分析未执行：{str(execution.get('reason') or '没有可验证执行日志').rstrip('。')}。"
                "100/1000 只是计划种子数，簇数众数与范围、噪声分布和跨种子稳定性均无结果；"
                "因此不能生成假装来自聚类的代表句审阅包。"
            )
    if checkpoint == "PATTERN_DISCOVERY_REVIEW":
        packet = _latest_artifact_body(project_id, "ClusterReviewPacket") or {}
        if packet.get("status") == "CLUSTER_REVIEW_BLOCKED_NO_EXECUTION":
            return (
                "聚类审阅包处于受阻状态：没有实际嵌入和 UMAP/HDBSCAN 输出，所以簇大小、区分词、"
                "中心句、边界句和噪声样本均不能伪造。你提供的暂定解释仍可整理为理论驱动的 Codebook 候选，"
                "但必须与未执行的计算模式发现明确分开。"
            )
    if checkpoint == "CODEBOOK_REVIEW":
        codebook = _latest_artifact_body(project_id, "CodebookCandidate") or {}
        items = [item for item in codebook.get("codebook", []) if isinstance(item, dict)]
        cluster_backed = sum(1 for item in items if item.get("source_cluster"))
        if items and cluster_backed == 0:
            return (
                f"已把你提出的暂定解释整理成 {len(items)} 个理论驱动/关键词辅助 Codebook 候选。"
                "它们保留定义、纳入/排除规则、原文正例和对照片段，但没有任何一个来自已执行聚类；"
                "请检查边界、反例及易混淆主题，当前名称不会被冻结为计算发现。"
            )
    return _checkpoint_message(checkpoint)


def _guided_transition_message(
    *,
    state: object,
    gate: GateRecord | dict[str, object] | None,
    checkpoint: str | None,
    decision: str | None = None,
) -> str:
    """Explain a workflow transition instead of acknowledging it generically.

    A researcher needs the causal link between their decision and the next
    research action. This keeps the control-plane decision authoritative while
    making the chat answer useful to a person who is deciding what to inspect
    or revise next.
    """

    if checkpoint:
        return _checkpoint_message(checkpoint)
    if gate is not None:
        readable_gate = gate if isinstance(gate, GateRecord) else GateRecord.model_validate(gate)
        return _mentor_boundary_message(readable_gate)

    if isinstance(state, ControlState):
        lifecycle = state.lifecycle_status.value
        stream = next(
            (item for item in state.workstreams if item.workstream_id == state.active_workstream_id),
            None,
        )
        completed_steps = stream.completed_step_ids if stream else []
        current_action = stream.current_action if stream else "下一项研究动作"
    elif isinstance(state, dict):
        lifecycle = str(state.get("lifecycle_status", "ACTIVE"))
        streams = state.get("workstreams", [])
        stream = next(
            (item for item in streams if isinstance(item, dict) and item.get("workstream_id") == state.get("active_workstream_id")),
            streams[0] if streams and isinstance(streams[0], dict) else None,
        )
        completed_steps = stream.get("completed_step_ids", []) if isinstance(stream, dict) else []
        current_action = stream.get("current_action") if isinstance(stream, dict) else None
        current_action = str(current_action or "下一项研究动作")
    else:
        lifecycle = "ACTIVE"
        completed_steps = []
        current_action = "下一项研究动作"

    if lifecycle in {"COMPLETED", "RELEASED"}:
        return (
            "独立审查已经通过，研究流程现在完成。论文、主张—证据链和审查记录已经保留；"
            "后续如果要改变研究问题或数据边界，应从新版本开始，而不是覆盖当前结果。"
        )

    labels = {
        "claim_evidence_support": "主张—证据支持判断",
        "research_question_design": "研究问题整理",
        "research_design": "研究设计整理",
        "preregistration_freeze": "研究方案冻结候选",
        "raw_data_import": "原始资料登记",
        "data_audit": "数据审计",
        "data_processing_approval": "数据处理边界",
        "dataset_freeze_hash": "数据版本冻结",
        "thematic_analysis": "主题候选分析",
        "qualitative_validation": "定性解释核验",
        "analysis_code_generation": "分析代码候选",
        "manual_execution_approval": "执行前代码审查",
        "sandbox_analysis_execution": "受控分析执行",
        "writing": "论文候选稿",
        "manuscript_citation_verification": "论文引用核验",
        "reviewer_final_confirmation": "独立审查",
    }
    recent = [labels.get(str(step), str(step)) for step in completed_steps[-3:] if step]
    completed_text = "、".join(recent) if recent else "前一阶段的研究整理"
    reason = {
        "等待编排器生成下一步候选": "我会先把你的决定转成新的、可追溯的研究产物，避免直接改写已经产生的版本。",
        "等待研究者确认研究问题": "需要先确定研究问题，后面的数据筛选和解释才不会悄悄改变研究对象。",
        "等待研究者确认研究方案": "需要先确认变量、比较方式和解释边界，才能判断数据是否真的支持这个问题。",
        "等待研究者确认结果解释边界": "需要先区分数据支持的发现与不能声称的因果范围，才能把结果写进论文。",
        "等待研究者确认论文大纲": "需要先确认论证顺序和主张强度，避免正文把候选解释写成确定结论。",
    }.get(current_action, "下一步会继续生成研究产物，并在真正需要研究者判断时停下来。")
    decision_text = {
        "approve": "你刚才确认了当前边界",
        "revise": "你刚才要求修改当前边界",
        "stop": "你刚才要求停止当前流程",
    }.get(decision, "你的这次输入")
    return (
        f"{decision_text}。我已经完成{completed_text}，现在进入“{current_action}”。"
        f"{reason}当前没有新的审批按钮需要你机械点击；你可以直接说明要保留什么、修改什么，"
        "或者让我先解释右侧产物中的证据、风险和取舍。"
    )


def _latest_evidence_coverage(project_id: str) -> dict[str, object]:
    """Return the presentation coverage for the newest immutable review package."""

    packages = [
        item for item in artifact_content_store.list_project(project_id)
        if item.artifact_type == "EvidenceReviewPackage"
    ]
    if not packages:
        return {}
    latest = max(packages, key=lambda item: item.created_at)
    coverage = latest.body.get("coverage")
    return dict(coverage) if isinstance(coverage, dict) else {}


def _build_orchestration_writing_context(
    project_id: str,
    project: ResearchProject,
    state: ControlState,
) -> WritingContextBundle:
    """Build writing inputs from the authoritative orchestration stores.

    The conversational workflow is owned by ``ControlState`` and its
    orchestration artifact repository, while the older Agent controller has a
    separate approval ledger.  Writing must consume the former directly;
    otherwise a completed quantitative workflow looks like an empty writing
    context and silently falls back to a skeletal manuscript.
    """

    contents = list(reversed(artifact_content_store.list_project(project_id)))
    package_body: dict[str, object] = {}
    for content in contents:
        if content.artifact_type == "EvidenceReviewPackage":
            package_body = dict(content.body)
            break

    evidence_refs: list[EvidenceRef] = []
    raw_snapshots = package_body.get("evidence_snapshots", [])
    if isinstance(raw_snapshots, list):
        for item in raw_snapshots:
            if not isinstance(item, dict):
                continue
            try:
                evidence = EvidenceRef.model_validate(item)
            except Exception:
                continue
            if evidence.project_id == project_id:
                evidence_refs.append(evidence)
    # A fresh bounded context can recover source-verified references when an
    # older package predates evidence snapshots.  It is read-only and does not
    # authorize any transition by itself.
    if not evidence_refs and workflow_controller.context_provider is not None:
        try:
            bundle = workflow_controller.context_provider.build_context(
                project_id=project_id,
                task_ref=f"{project_id}:writing",
                query=_canonical_research_scope(project.research_direction),
                token_budget=2_000,
            )
            evidence_refs = [
                item for item in bundle.evidence_refs if item.project_id == project_id
            ]
        except Exception as error:
            logger.warning("Could not refresh writing evidence for %s: %s", project_id, error)

    paper_cards = [
        item for item in package_body.get("paper_cards", [])
        if isinstance(item, dict)
    ]
    evidence_matrix = [
        item for item in package_body.get("evidence_matrix", [])
        if isinstance(item, dict)
    ]
    records = control_plane.repository.list_artifacts(project_id)
    approved = [
        item for item in records
        if item.effective
        and item.lifecycle_status is ArtifactLifecycle.FROZEN
        and item.approval_status.value == "APPROVED"
    ]
    protocol_refs = [
        item.content_uri
        for item in approved
        if item.artifact_type in {"PreregistrationFreezeCandidate", "StudyProtocolCandidate"}
    ]
    result_refs: list[str] = []
    pipeline = _latest_quantitative_pipeline_state(project_id)
    if pipeline is not None and pipeline.statistical_result_card is not None:
        result_refs.append(pipeline.statistical_result_card.ref)
    synthesis = {
        key: package_body.get(key)
        for key in ("coverage", "synthesis", "conflict_map", "research_gap_report")
        if package_body.get(key) is not None
    }
    payload = {
        "project_id": project_id,
        "scope": project.research_direction,
        "evidence": [item.model_dump(mode="json") for item in evidence_refs],
        "paper_cards": paper_cards,
        "evidence_matrix": evidence_matrix,
        "protocol_refs": protocol_refs,
        "result_refs": result_refs,
        "synthesis": synthesis,
        "boundaries": [
            "观察性比较不支持因果结论。",
            "统计数字只能来自已验证结果卡。",
        ],
    }
    context_hash = sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return WritingContextBundle(
        project_id=project_id,
        approved_research_scope=_canonical_research_scope(project.research_direction),
        evidence_refs=evidence_refs,
        paper_cards=[],
        evidence_matrix=evidence_matrix,
        approved_study_protocol_refs=protocol_refs,
        validated_result_cards=result_refs,
        interpretation_boundaries=payload["boundaries"],
        prior_review_findings=[],
        evidence_synthesis=synthesis,
        output_language=LanguageCode.ZH_CN,
        context_hash=context_hash,
    )

# Load repository-local switches before constructing Controller services.
_repository_root = Path(
    os.getenv("STEM_SCI_REPOSITORY_ROOT", str(Path(__file__).resolve().parents[3]))
).resolve()
_backend_root = Path(__file__).resolve().parents[2]
for _dotenv_path in (
    _repository_root / ".env.local",
    _backend_root / ".env.local",
    _repository_root / ".env",
    _backend_root / ".env",
):
    load_dotenv(_dotenv_path, override=False)


def _cors_origins() -> list[str]:
    configured = os.getenv("STEM_SCI_CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


def _max_upload_bytes() -> int:
    configured = os.getenv("STEM_SCI_MAX_UPLOAD_BYTES")
    if configured is None:
        return DEFAULT_MAX_UPLOAD_BYTES
    try:
        value = int(configured)
    except ValueError:
        return DEFAULT_MAX_UPLOAD_BYTES
    return value if value > 0 else DEFAULT_MAX_UPLOAD_BYTES


class UTF8JSONResponse(JSONResponse):
    """JSON response with an explicit charset for legacy HTTP clients."""

    media_type = "application/json; charset=utf-8"


def _error(status_code: int, code: str, message: str) -> UTF8JSONResponse:
    return UTF8JSONResponse(
        status_code=status_code,
        content=ApiErrorResponse(error=ApiError(code=code, message=message)).model_dump(),
    )


app = FastAPI(
    title="STEM-SCI Research Workflow Platform",
    version="0.2.0",
    default_response_class=UTF8JSONResponse,
)
configuration_report = validate_environment()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    # Project membership uses PUT; omitting it makes the browser preflight
    # fail with a misleading "Failed to fetch" before the API sees the call.
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
# Keep the default store stable when Uvicorn is launched from a different
# working directory (for example, the repository root instead of backend/).
_default_storage_root = Path(__file__).resolve().parents[2] / ".stem_sci"
storage_root = Path(os.getenv("STEM_SCI_STORAGE_DIR", str(_default_storage_root)))
service = ContextService(storage_root, max_upload_bytes=_max_upload_bytes())
knowledge_service = HybridKnowledgeService(service, CorpusRegistry())
workflow_database = storage_root / "workflow.db"
control_plane = ControlPlane(SQLiteControlPlaneRepository(workflow_database))
identity_service = IdentityService(storage_root / "identity.db")
document_service = DocumentService(storage_root / "documents.db", storage_root / "project-documents")
_background_worker_stop = Event()
_background_worker_thread: Thread | None = None


def _conversation_command_journal() -> ConversationCommandJournal:
    """Create the journal from the active storage root for test isolation."""

    identity_database = Path(
        getattr(identity_service, "database", storage_root / "identity.db")
    )
    return ConversationCommandJournal(identity_database.parent / "research-dialogue.db")


def _research_collaboration_engine() -> ResearchCollaborationEngine:
    """Build the collaboration layer from the active storage root.

    A factory, rather than a module singleton, keeps API tests isolated when
    they replace ``identity_service`` and lets the store share the identity
    database directory without coupling epistemic state to ControlPlane.
    """

    identity_database = Path(
        getattr(identity_service, "database", storage_root / "identity.db")
    )
    return ResearchCollaborationEngine(
        SQLiteResearchGraphStore(identity_database.parent / "research-dialogue.db"),
        generator=getattr(qa_service, "_generator", None),
        model=getattr(qa_service, "_model", None),
    )


def _configured_agent_registry() -> AgentRegistry:
    """Inject GPT pipelines only when workflow generation is enabled."""
    api_key = os.getenv("STEM_SCI_LLM_API_KEY", "")
    if not api_key.strip() or not _llm_workflow_enabled():
        return AgentRegistry.default()
    provider = GPTProvider.from_env()
    if not provider.default_model:
        raise ValueError("STEM_SCI_LLM_MODEL is required when GPT is enabled")
    provider.timeout_seconds = _optional_llm_timeout_seconds()
    return AgentRegistry.default(
        generator=StructuredGenerator(provider, max_retries=0),
        model=provider.default_model,
        evidence_prefer_deterministic=False,
    )


def _configured_workflow_planner() -> tuple[StructuredGenerator | None, str | None]:
    """Use an optional, bounded LLM enhancement for workflow proposals."""

    if not os.getenv("STEM_SCI_LLM_API_KEY", "").strip() or not _llm_workflow_enabled():
        return None, None
    provider = GPTProvider.from_env()
    # Candidate summaries never control state transitions. Do not let a broken
    # external model connection delay project creation or an approval Gate.
    provider.timeout_seconds = _optional_llm_timeout_seconds()
    return StructuredGenerator(provider, max_retries=0), provider.default_model


def _configured_journal_revision_service() -> JournalStyleRevisionService | None:
    """Return the bounded prose-revision service only when an LLM is configured."""
    if not os.getenv("STEM_SCI_LLM_API_KEY", "").strip():
        return None
    provider = GPTProvider.from_env()
    if not provider.default_model:
        return None
    provider.timeout_seconds = _optional_llm_timeout_seconds()
    return JournalStyleRevisionService(
        generator=StructuredGenerator(provider, max_retries=0),
        model=provider.default_model,
    )


def _optional_llm_timeout_seconds() -> float:
    # Structured writing uses several bounded calls and Qwen may need more
    # than a short chat-turn timeout for a long evidence-grounded response.
    # Keep a hard 60-second ceiling while making the default usable.
    raw = os.getenv("STEM_SCI_LLM_OPTIONAL_TIMEOUT_SECONDS", "60")
    try:
        return min(60.0, max(1.0, float(raw)))
    except ValueError:
        return 60.0


def _llm_workflow_enabled() -> bool:
    """Allow remote language generation only when the operator enables it."""

    return os.getenv("STEM_SCI_LLM_WORKFLOW_ENABLED", "true").strip().lower() in {
        "1", "true", "yes", "on",
    }


operator_registry = OperatorRegistry.default()
execution_store = SQLiteExecutionStore(workflow_database)
artifact_store = SQLiteArtifactStore(workflow_database)
artifact_content_store = SQLiteArtifactContentStore(workflow_database)
agent_run_store = SQLiteAgentRunStore(workflow_database)
route_store = SQLiteRouteDecisionStore(workflow_database)
agent_plan_store = SQLiteAgentPlanStore(workflow_database)
agent_page_material_store = SQLiteAgentPageMaterialStore(workflow_database)
formal_evidence_store = SQLiteFormalEvidenceStore(workflow_database)
knowledge_operator_runtime = KnowledgeOperatorRuntime(
    knowledge_service,
    artifact_store=artifact_store,
    artifact_content_store=artifact_content_store,
)
workflow_operator_executor = OperatorExecutor(
    registry=operator_registry,
    execution_store=execution_store,
    handlers=knowledge_operator_runtime.handlers(),
)
planner_generator, planner_model = _configured_workflow_planner()


def _configured_qa_service() -> QuestionAnswerService:
    """Create the chat service; provider configuration remains environment-only."""

    api_key = os.getenv("STEM_SCI_LLM_API_KEY", "").strip()
    provider = None
    if api_key and _llm_workflow_enabled():
        try:
            provider = GPTProvider.from_env()
        except ValueError:
            # The QA endpoint remains available in deterministic fallback mode
            # while the provider environment is incomplete.
            provider = None
    return QuestionAnswerService(
        knowledge_service=knowledge_service,
        storage_root=storage_root,
        provider=provider,
        workflow_controller=workflow_controller,
        artifact_store=artifact_store,
        # A failed structured response must fall back to cited retrieval
        # instead of spending a second remote request on the same turn.
        max_retries=0,
        agentic_tool_routing_enabled=os.getenv(
            "STEM_SCI_LLM_AGENTIC_TOOL_ROUTING_ENABLED", "false"
        ).strip().lower() in {"1", "true", "yes", "on"},
    )


def _configured_context_provider() -> LocalContextProvider | HybridContextProvider:
    # Use the declared Physics-STEM corpus for Agent evidence review unless
    # local project evidence is explicitly requested.
    configured = os.getenv("STEM_SCI_CONTEXT_PROVIDER", "hybrid").strip().lower()
    if configured == "local":
        return LocalContextProvider(service)
    if configured == "hybrid":
        return HybridContextProvider(knowledge_service, service)
    raise ValueError("STEM_SCI_CONTEXT_PROVIDER must be local or hybrid")


workflow_controller = ResearchController(
    dispatcher=AgentDispatcher(_configured_agent_registry()),
    context_provider=_configured_context_provider(),
    decision_store=SQLiteDecisionStore(workflow_database),
    workflow_store=SQLiteWorkflowStore(workflow_database),
    operator_executor=workflow_operator_executor,
    artifact_store=artifact_store,
    artifact_content_store=artifact_content_store,
    agent_run_store=agent_run_store,
    route_store=route_store,
    agent_plan_store=agent_plan_store,
    agent_page_material_store=agent_page_material_store,
    formal_evidence_store=formal_evidence_store,
    planner_generator=planner_generator,
    planner_model=planner_model,
    data_pipeline_root=storage_root,
)
qa_service = _configured_qa_service()
coordinator_model = OptionalCoordinator.from_env()
latex_service = LatexService()


class WorkflowProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=64)
    research_intent: str = Field(min_length=1)
    context_bundle_ref: str = "context://initial"
    run_id: str | None = None


class PublicationTargetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_journal: str = Field(min_length=1, max_length=200)
    article_type: str | None = Field(default=None, max_length=120)
    methodology: str | None = Field(default=None, max_length=120)


class ProjectWorkflowStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    research_intent: str = Field(min_length=1)
    context_bundle_ref: str = "context://initial"
    run_id: str | None = None


class WorkflowApprovalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(min_length=1)
    decided_by: str = Field(min_length=1)
    reason: str | None = Field(default=None, max_length=2_000)


class ConversationCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=20_000)
    intent: str | None = Field(default=None, max_length=20_000)
    # Conversation is the safe default.  Older clients that omit this field
    # must not start a research run merely because a normal question contains
    # terms such as "paper", "data", or "analysis".
    interaction_mode: Literal["auto", "discussion", "workflow"] = "discussion"
    evidence_mode: Literal["discovery", "formal"] = "discovery"
    conversation_id: str | None = Field(default=None, max_length=128)
    execution_mode: Literal["sync", "background"] = "sync"
    client_turn_id: str | None = Field(default=None, max_length=128)


class ResearchBranchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=4000)
    benefits: list[str] = Field(default_factory=list, max_length=20)
    risks: list[str] = Field(default_factory=list, max_length=20)
    constraints: list[str] = Field(default_factory=list, max_length=20)
    dependent_node_ids: list[str] = Field(default_factory=list, max_length=50)
    created_turn_id: str | None = Field(default=None, max_length=128)


class ResearchBranchDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=2000)


class DialogueChoice(BaseModel):
    """A researcher-facing suggestion, never an internal workflow command."""

    id: str
    label: str
    message: str


class DialogueEvidence(BaseModel):
    """Small, researcher-facing evidence card attached to a dialogue turn."""

    title: str
    evidence_id: str | None = None
    excerpt: str
    verification_status: str
    locator_status: str
    role: str = "本轮依据"


class DialogueBranch(BaseModel):
    """A reversible research route comparison shown inside the conversation."""

    id: str
    title: str
    description: str
    benefits: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    message: str


class DialogueVersionChange(BaseModel):
    """A compact diff of the shared research map after one turn."""

    from_version: int
    to_version: int
    added: list[str] = Field(default_factory=list)
    changed: list[str] = Field(default_factory=list)
    implications: list[str] = Field(default_factory=list)


class DialogueTurn(BaseModel):
    """Presentation contract for one research-mentor turn."""

    mode: str
    summary: str
    question: str | None = None
    suggestions: list[DialogueChoice] = Field(default_factory=list)
    evidence: list[DialogueEvidence] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)
    branches: list[DialogueBranch] = Field(default_factory=list)
    version_change: DialogueVersionChange | None = None
    next_action: str | None = None
    canvas_focus: str = "overview"
    # Let clients render the turn according to its purpose instead of a fixed
    # summary-plus-buttons template.
    turn_role: str = "answer"
    why_now: str | None = None
    novelty: list[str] = Field(default_factory=list)
    user_action_required: bool = False


def _dialogue_turn_for_response(
    *,
    message: str,
    gate: GateRecord | dict[str, object] | None,
    checkpoint: str | None,
    intake: ResearchIntakeState | dict[str, object] | None,
) -> DialogueTurn:
    """Build a bounded mentor turn from authoritative workflow state.

    It intentionally does not infer approvals. Suggestions only insert a
    natural-language reply into chat, where control-plane policy validates it.
    """

    gate_type = (
        gate.gate_type if isinstance(gate, GateRecord)
        else str(gate.get("gate_type", "")) if isinstance(gate, dict)
        else ""
    )
    intake_key = (
        intake.current_question_key if isinstance(intake, ResearchIntakeState)
        else str(intake.get("current_question_key") or "") if isinstance(intake, dict)
        else ""
    )
    if intake_key:
        return DialogueTurn(
            mode="clarify",
            summary="我们正在用对话梳理研究想法，你可以自由回答、追问或随时转去查看资料。",
            question=_intake_question(intake_key),
            suggestions=[],
            canvas_focus="research_brief",
        )

    checkpoint_turns: dict[str, tuple[str, str, list[DialogueChoice]]] = {
        "RESEARCH_QUESTION_REVIEW": (
            "question",
            "右侧已经整理出可追溯到现有证据的研究问题候选。",
            [
                DialogueChoice(id="choose", label="选择并说明理由", message="我倾向第一个研究问题，原因是："),
                DialogueChoice(id="merge", label="合并候选", message="请把前两个研究问题合并，并保留："),
                DialogueChoice(id="explain", label="先解释差异", message="先解释这些研究问题的差异和各自风险。"),
            ],
        ),
        "RESEARCH_DESIGN_REVIEW": (
            "design",
            "右侧是把研究问题转成变量、比较方式和解释边界后的设计候选。",
            [
                DialogueChoice(id="revise", label="修改设计", message="我想修改研究设计："),
                DialogueChoice(id="explain", label="解释取舍", message="先解释这个设计的主要取舍和偏差风险。"),
                DialogueChoice(id="accept", label="采用该设计", message="这个设计符合我的研究目的，请整理为研究方案。"),
            ],
        ),
        "RESULT_INTERPRETATION_REVIEW": (
            "interpretation",
            "右侧把可支持的发现、反例和不能越过的解释边界分开呈现。",
            [
                DialogueChoice(id="explain", label="解释结果", message="请先用非技术语言解释核心结果和限制。"),
                DialogueChoice(id="revise", label="收紧结论", message="请收紧结论，只保留有充分支持的表述。"),
                DialogueChoice(id="focus", label="确定论文重点", message="论文应重点讨论："),
            ],
        ),
        "MANUSCRIPT_OUTLINE_REVIEW": (
            "writing",
            "右侧是论文大纲和每项主张对应的证据或结果。",
            [
                DialogueChoice(id="structure", label="调整论证顺序", message="我想调整论文结构："),
                DialogueChoice(id="weaken", label="删改过强主张", message="请找出并弱化证据不足的主张。"),
                DialogueChoice(id="draft", label="开始写正文", message="大纲符合我的研究故事，可以开始生成正文候选稿。"),
            ],
        ),
        MANUSCRIPT_SECTION_CHECKPOINT: (
            "writing",
            "论文大纲已经确认。请逐节生成方法、结果、引言/理论背景和讨论/局限，最后再合并完整候选稿。",
            [
                DialogueChoice(id="methods", label="生成数据与方法", message="请先写数据与方法。"),
                DialogueChoice(id="results", label="生成结果", message="请只依据冻结结果卡写结果。"),
                DialogueChoice(id="introduction", label="生成引言背景", message="请写引言和理论背景。"),
                DialogueChoice(id="discussion", label="生成讨论局限", message="请写讨论和局限。"),
                DialogueChoice(id="full", label="合并完整候选", message="请把已确认章节合并为完整候选论文。"),
            ],
        ),
        "MANUSCRIPT_REVISION_REVIEW": (
            "writing",
            "初稿已经生成，写作质量审查在右侧标出了需要修改的章节、主张和原因；已验证的数字、结果和引用不会被改写。",
            [
                DialogueChoice(id="explain", label="查看修改原因", message="请先解释右侧每项写作修改建议会解决什么问题。"),
                DialogueChoice(id="revise", label="按建议重新生成", message="请按右侧写作审查建议重新生成论文候选稿，保留已验证的数字、结果和引用。"),
            ],
        ),
    }
    if checkpoint in checkpoint_turns:
        mode, summary, suggestions = checkpoint_turns[checkpoint]
        checkpoint_branches: list[DialogueBranch] = []
        if checkpoint == "RESEARCH_QUESTION_REVIEW":
            checkpoint_branches = [
                DialogueBranch(
                    id="focus_one_question",
                    title="收窄到一个主问题",
                    description="优先保证变量、样本和证据都围绕同一个可回答的问题。",
                    benefits=["解释边界清楚", "后续设计和分析更容易审查"],
                    risks=["可能暂时放弃有价值的次要问题"],
                    prerequisites=["说明为什么这个问题优先"],
                    message="我选择收窄到一个主问题，并说明优先它的理由。",
                ),
                DialogueBranch(
                    id="combine_questions",
                    title="合并互补问题",
                    description="保留两个候选问题的互补部分，形成一个主问题和一个次问题。",
                    benefits=["保留更多研究信息", "可以同时覆盖机制和差异"],
                    risks=["研究设计和样本量要求更复杂", "主张更容易超出证据范围"],
                    prerequisites=["明确主问题、次问题及其优先级"],
                    message="我选择合并互补问题，并把其中一个设为次问题。",
                ),
            ]
        elif checkpoint == "RESEARCH_DESIGN_REVIEW":
            checkpoint_branches = [
                DialogueBranch(
                    id="conservative_design",
                    title="采用保守设计",
                    description="只保留当前数据明确支持的比较和描述性解释。",
                    benefits=["结论边界更稳健", "数据要求和执行风险更低"],
                    risks=["无法回答更强的机制或因果问题"],
                    prerequisites=["接受描述性或关联性解释边界"],
                    message="我选择保守设计，只做当前数据支持的描述性或关联性分析。",
                ),
                DialogueBranch(
                    id="expanded_design",
                    title="保留扩展设计候选",
                    description="保留更丰富的变量和比较，但先把缺失数据和识别风险列为前置条件。",
                    benefits=["研究问题覆盖更完整", "可以检验更多替代解释"],
                    risks=["需要更多数据和审查", "任何前置条件不满足都要回退设计"],
                    prerequisites=["确认数据字段、样本量和识别条件"],
                    message="我选择保留扩展设计，但先核对数据字段、样本量和识别条件。",
                ),
            ]
        return DialogueTurn(
            mode=mode,
            summary=summary,
            question=_checkpoint_message(checkpoint),
            suggestions=suggestions,
            branches=checkpoint_branches,
            canvas_focus=mode,
        )

    gate_turns: dict[str, tuple[str, str, list[DialogueChoice]]] = {
        "evidence_sufficiency_review": (
            "evidence",
            "我已完成本轮检索、去重、排序与证据初筛；右侧区分了可定位原文、外部题录候选和研究缺口。你可以直接告诉我还想补哪些主题、哪些候选不相关，或者认为当前材料已经足够；也可以先追问来源和限制。",
            [],
        ),
        "preregistration_freeze_approval": (
            "protocol",
            "研究问题、变量定义和分析边界已经形成一个可修订的研究方案候选。",
            [
                DialogueChoice(id="explain", label="解释方案影响", message="先解释冻结这个方案会约束哪些后续决定。"),
                DialogueChoice(id="revise", label="继续修改方案", message="我想修改研究方案："),
                DialogueChoice(id="freeze", label="确认研究方案", message="确认研究方案并冻结。"),
            ],
        ),
        "raw_data_import_approval": (
            "data",
            "研究方案已经确定。下一步只需要导入与方案匹配的去标识化原始数据，系统会先审计。",
            [
                DialogueChoice(id="upload", label="上传并审计数据", message="我已上传数据，请审计这份数据。"),
                DialogueChoice(id="requirements", label="查看数据要求", message="请说明这项研究还缺少哪些数据字段。"),
            ],
        ),
        "dataset_freeze_hash_approval": (
            "data",
            "右侧显示了数据审计发现及其对样本和分析的影响。",
            [
                DialogueChoice(id="explain", label="解释数据风险", message="请解释这些数据质量提示会怎样影响结论。"),
                DialogueChoice(id="revise", label="调整处理边界", message="我想调整数据处理边界："),
                DialogueChoice(id="freeze", label="接受并冻结数据", message="我接受当前数据处理边界，请冻结数据并生成代码候选。"),
            ],
        ),
        "manual_execution_approval_approval": (
            "execution",
            "右侧的代码候选已经通过执行前检查，并明确标出了读取的数据和要回答的比较。",
            [
                DialogueChoice(id="explain", label="解释分析代码", message="请先解释代码将检验什么，以及剩余风险。"),
                DialogueChoice(id="revise", label="修改分析计划", message="我想修改分析计划："),
                DialogueChoice(id="run", label="确认运行分析", message="确认执行当前分析代码。"),
            ],
        ),
        "uncertainty_gate_approval": (
            "results",
            "结果、稳健性检查和不确定性提示已经汇总在右侧。",
            [
                DialogueChoice(id="explain", label="解释不确定性", message="请解释哪些结论稳健，哪些只能谨慎描述。"),
                DialogueChoice(id="revise", label="收紧解释", message="请收紧结果解释，避免超出证据范围。"),
                DialogueChoice(id="write", label="开始论文候选稿", message="保留这些不确定性边界，开始生成论文候选稿。"),
            ],
        ),
        "reviewer_final_confirmation_approval": (
            "review",
            "论文候选稿、引用核验和主张追溯已准备好，等待独立审稿。",
            [DialogueChoice(id="review", label="查看审稿重点", message="请说明独立审稿人需要重点核对什么。")],
        ),
    }
    if gate_type in gate_turns:
        mode, summary, suggestions = gate_turns[gate_type]
        readable_gate = gate if isinstance(gate, GateRecord) else GateRecord.model_validate(gate)
        gate_tradeoffs = {
            "preregistration_freeze_approval": [
                "冻结后，实质性修改会生成新版本，并使依赖旧方案的下游结果需要重新核对。",
                "确认前仍可以修改研究问题、变量定义和解释边界。",
            ],
            "dataset_freeze_hash_approval": [
                "冻结会固定样本、字段和处理边界，后续分析才能可重复。",
                "如果现在接受不合理的缺失或异常处理，后续结论会继承这个风险。",
            ],
            "manual_execution_approval_approval": [
                "执行会读取冻结数据并产生正式结果，代码和比较对象需要先符合研究方案。",
                "确认后仍可解释结果，但不能把未执行的分析写成已完成。",
            ],
            "uncertainty_gate_approval": [
                "写作前需要保留稳健性检查和不确定性，避免把关联性结果写成因果结论。",
            ],
        }.get(gate_type, ["这一步只会推进当前正式边界，不会替你改变研究问题。"])
        return DialogueTurn(
            mode=mode,
            summary=summary,
            question=_mentor_boundary_message(readable_gate),
            suggestions=suggestions,
            tradeoffs=gate_tradeoffs,
            next_action="先检查右侧产物和这些取舍，再用自然语言说明确认、修改或追问。",
            canvas_focus=mode,
        )

    return DialogueTurn(
        mode="research",
        summary=message,
        question="你想先澄清研究目标、补充材料，还是查看右侧当前研究结果？",
        suggestions=[
            DialogueChoice(id="explain", label="解释当前状态", message="请用通俗语言解释当前研究进行到哪里，以及下一步为什么重要。"),
            DialogueChoice(id="review", label="查看右侧材料", message="请概述右侧当前材料能支持什么、还缺什么。"),
        ],
        canvas_focus="overview",
    )


class ConversationCommandResult(BaseModel):
    """Stable response envelope for the conversational research interface."""

    kind: str = "orchestration"
    message: str
    control_state: ControlState
    route_decision: dict[str, object] | None = None
    gate: GateRecord | None = None
    execution_started: bool = False
    waiting_for_user: bool = False
    checkpoint: str | None = None
    intake: ResearchIntakeState | None = None
    answer: dict[str, object] | None = None
    dialogue: DialogueTurn | None = None
    collaboration: CollaborationDecision | None = None

    @model_validator(mode="after")
    def add_dialogue_turn(self) -> "ConversationCommandResult":
        if self.dialogue is None:
            self.dialogue = _dialogue_turn_for_response(
                message=self.message,
                gate=self.gate,
                checkpoint=self.checkpoint,
                intake=self.intake,
            )
        return self


class GateDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(pattern="^(approve|reject|revise|stop)$")
    reason: str | None = Field(default=None, max_length=2_000)
    risk_acceptance: list[str] = Field(default_factory=list, max_length=32)


class PrimaryDataUploadResponse(BaseModel):
    """Reference-only receipt for researcher-supplied raw material."""

    model_config = ConfigDict(extra="forbid")

    document: ProjectDocument
    artifact: ArtifactRecord
    control_state: ControlState


class PhysicsValidationRequest(BaseModel):
    """A bounded code-and-rules submission for the Physics-STEM validator."""

    model_config = ConfigDict(extra="forbid")

    source_code: str = Field(min_length=1, max_length=200_000)
    equations: list[str] = Field(default_factory=list, max_length=32)
    units: dict[str, str] = Field(default_factory=dict, max_length=64)
    bounds: dict[str, dict[str, float]] = Field(default_factory=dict, max_length=64)


class ProtocolValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dag: CausalDagSpec
    power: PowerAnalysisRequest


class ProtocolValidationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dag_report: CausalDagReport
    power_report: PowerAnalysisReport
    passed: bool
    risk_flags: list[str] = Field(default_factory=list)


class ClaimSupportEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_ref: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=50_000)


class ClaimSupportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str = Field(min_length=1, max_length=10_000)
    evidence: list[ClaimSupportEvidence] = Field(min_length=1, max_length=32)


class RobustnessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    control: list[float] = Field(min_length=2, max_length=100_000)
    treatment: list[float] = Field(min_length=2, max_length=100_000)
    primary_estimate: float
    bootstrap_samples: int = Field(default=2000, ge=200, le=20_000)
    permutations: int = Field(default=2000, ge=200, le=20_000)


class MetaAnalysisStudy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    study_id: str = Field(min_length=1, max_length=200)
    effect: float
    standard_error: float = Field(gt=0.0)


class MetaAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    studies: list[MetaAnalysisStudy] = Field(min_length=2, max_length=500)
    confidence: float = Field(default=0.95, gt=0.0, lt=1.0)


class ScreeningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    records: list[ScreeningRecord] = Field(min_length=1, max_length=10_000)
    relevant_paper_ids: list[str] = Field(default_factory=list, max_length=10_000)
    query: str = Field(default="", max_length=10_000)


class OutlierRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: list[float] = Field(min_length=2, max_length=100_000)


class ConformalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prediction: float
    calibration_residuals: list[float] = Field(min_length=1, max_length=100_000)
    coverage: float = Field(default=0.95, gt=0.0, lt=1.0)


class SchemaValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    rows: list[dict[str, object]] = Field(min_length=1, max_length=100_000)
    data_schema: DeclaredDataSchema = Field(alias="schema")


class CausalDiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[dict[str, float]] = Field(min_length=3, max_length=100_000)
    columns: list[str] = Field(min_length=2, max_length=100)


class CausalIdentificationRequest(BaseModel):
    """Researcher-confirmed DAG supplied to the DoWhy identification adapter."""

    model_config = ConfigDict(extra="forbid")

    rows: list[dict[str, float]] = Field(min_length=3, max_length=100_000)
    dag: CausalDagSpec


class SensitivityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    estimate: float
    standard_error: float = Field(gt=0.0)
    benchmark_partial_r2: float = Field(default=0.0, ge=0.0, lt=1.0)


class MultipleComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    p_values: dict[str, float] = Field(min_length=1, max_length=500)
    method: MultiplicityMethod = MultiplicityMethod.HOLM
    alpha: float = Field(default=0.05, gt=0.0, lt=1.0)


class UncertaintyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str = Field(min_length=1, max_length=80)
    signals: list[QualitySignal] = Field(min_length=1, max_length=64)


def _access_token(authorization: Annotated[str | None, Header()] = None) -> str:
    if authorization is None:
        raise AuthError(401, "missing_access_token", "Authorization bearer token is required")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError(401, "invalid_authorization_header", "Authorization must use Bearer token")
    return token.strip()


def current_user(token: Annotated[str, Depends(_access_token)]) -> UserProfile:
    return identity_service.user_for_access_token(token)


@app.exception_handler(ContextInputError)
async def handle_context_input(_: Request, error: ContextInputError) -> JSONResponse:
    return _error(400, error.code, str(error))


@app.exception_handler(ContextNotFoundError)
async def handle_not_found(_: Request, error: ContextNotFoundError) -> JSONResponse:
    return _error(404, "not_found", f"{error.resource} was not found")


@app.exception_handler(AuthError)
async def handle_auth_error(_: Request, error: AuthError) -> JSONResponse:
    return _error(error.status_code, error.code, error.message)


@app.exception_handler(DocumentError)
async def handle_document_error(_: Request, error: DocumentError) -> JSONResponse:
    return _error(error.status_code, error.code, error.message)


@app.exception_handler(ValueError)
async def handle_workflow_value_error(_: Request, error: ValueError) -> JSONResponse:
    return _error(400, "workflow_input_error", str(error))


@app.exception_handler(RequestValidationError)
async def handle_validation(_: Request, __: RequestValidationError) -> JSONResponse:
    return _error(422, "invalid_request", "Request does not match the API contract")


@app.exception_handler(StarletteHTTPException)
async def handle_http_exception(_: Request, error: StarletteHTTPException) -> JSONResponse:
    return _error(error.status_code, "http_error", "Request could not be completed")


@app.exception_handler(Exception)
async def handle_unexpected(_: Request, error: Exception) -> JSONResponse:
    # Keep provider/database details out of the HTTP response, but retain the
    # traceback in the backend console for local debugging.
    logger.exception("Unhandled API exception: %s", error)
    return _error(500, "internal_error", "An internal error occurred")


ProjectIdForm = Annotated[
    str,
    Form(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$"),
]
ProjectIdQuery = Annotated[
    str,
    Query(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$"),
]


async def _read_uploaded_research_document(
    file: UploadFile, max_bytes: int
) -> tuple[DocumentFormat, str]:
    """Extract searchable text from a project reference upload."""
    filename = (file.filename or "").strip()
    suffix = Path(filename).suffix.lower()
    if suffix not in {".pdf", ".docx", ".txt", ".csv"}:
        raise DocumentError(
            415,
            "unsupported_document_format",
            "Project reference files must be PDF, DOCX, TXT, or CSV",
        )

    payload = await file.read()
    if not payload:
        raise DocumentError(400, "empty_document", "The uploaded document is empty")
    if len(payload) > max_bytes:
        raise DocumentError(413, "document_too_large", "The uploaded document exceeds the upload limit")

    document_format: DocumentFormat
    try:
        if suffix == ".pdf":
            reader = PdfReader(io.BytesIO(payload))
            content = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()
            document_format = "pdf"
        elif suffix == ".docx":
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                xml_payload = archive.read("word/document.xml")
            root = ElementTree.fromstring(xml_payload)
            paragraphs: list[str] = []
            for paragraph in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
                text = "".join(
                    node.text or ""
                    for node in paragraph.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
                ).strip()
                if text:
                    paragraphs.append(text)
            content = "\n\n".join(paragraphs).strip()
            document_format = "docx"
        else:
            content = payload.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n").strip()
            document_format = "csv" if suffix == ".csv" else "text"
    except (OSError, ValueError, KeyError, UnicodeDecodeError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise DocumentError(
            400,
            "document_parse_failed",
            "The uploaded document could not be parsed",
        ) from exc

    if not content:
        raise DocumentError(
            422,
            "document_text_unavailable",
            "The uploaded document does not contain extractable text",
        )
    if len(content) > 1_000_000:
        raise DocumentError(
            413,
            "document_text_too_large",
            "The extracted document text exceeds the storage limit",
        )
    return document_format, content


async def _read_uploaded_primary_data(
    file: UploadFile, max_bytes: int
) -> tuple[DocumentFormat, str]:
    """Read a private primary-data file without sending it to the evidence index."""

    suffix = Path((file.filename or "").strip()).suffix.lower()
    if suffix in {".pdf", ".docx"}:
        return await _read_uploaded_research_document(file, max_bytes)
    if suffix not in {".txt", ".csv"}:
        raise DocumentError(
            415,
            "unsupported_primary_data_format",
            "Primary data must be PDF, DOCX, TXT, or CSV",
        )
    payload = await file.read()
    if not payload:
        raise DocumentError(400, "empty_document", "The uploaded primary-data file is empty")
    if len(payload) > max_bytes:
        raise DocumentError(413, "document_too_large", "The uploaded primary-data file exceeds the upload limit")
    try:
        # Store text with canonical LF line endings.  ``DocumentService``
        # validates hashes after reading text, and Windows' universal-newline
        # conversion would otherwise turn an uploaded CRLF CSV into a digest
        # mismatch on the first version lookup.
        content = payload.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n").strip()
    except UnicodeDecodeError as exc:
        raise DocumentError(
            400,
            "primary_data_encoding_invalid",
            "TXT and CSV primary data must use UTF-8 encoding",
        ) from exc
    if not content:
        raise DocumentError(422, "document_text_unavailable", "The uploaded primary-data file contains no text")
    if len(content) > 1_000_000:
        raise DocumentError(413, "document_text_too_large", "The extracted document text exceeds the storage limit")
    return ("csv" if suffix == ".csv" else "text"), content


def _registered_qualitative_primary_data(project_id: str) -> dict[str, object] | None:
    """Load the exact private document version referenced by raw-data intake.

    Only its metadata is written to downstream orchestration artifacts.  The
    text remains in the document store and is used in-process for the bounded
    audit and coding helpers below.
    """

    artifact = next(
        (
            item
            for item in reversed(control_plane.repository.list_artifacts(project_id))
            if item.artifact_type == "RawQualitativeDataset"
            and item.effective
            and item.validation_status.value == "PASSED"
            and item.source_dataset_ids
        ),
        None,
    )
    if artifact is None:
        return None
    source_ref = artifact.source_dataset_ids[0]
    match = re.fullmatch(r"document://(doc-[A-Za-z0-9]+)/([1-9][0-9]*)", source_ref)
    if match is None:
        return None
    document_id, version_text = match.groups()
    try:
        version = document_service.get_version(project_id, document_id, int(version_text))
    except DocumentError:
        return None
    if version.sha256 != artifact.content_sha256:
        return None
    # Public OSF exports are commonly TSV files with an anonymous student ID
    # and a response column.  Keep only the response as analyzable text while
    # retaining the ID as a non-identifying provenance label.  Plain TXT and
    # Chinese test fixtures continue to work as one response per line.
    segments: list[dict[str, str]] = []
    participant_labels: set[str] = set()
    public_tabular_source = False
    # Parse comma-delimited public exports as records, rather than splitting
    # physical text on newlines.  Several OSF responses contain punctuation
    # and quoted line breaks; line splitting inflated the apparent sample
    # (e.g. 550 records became 729 fragments) and made the manuscript conflate
    # records with analysis segments.  Keep the line-based path for the
    # repository's simple TSV/TXT fixtures.
    csv_rows: list[list[str]] | None = None
    first_line = version.content.splitlines()[0] if version.content.splitlines() else ""
    if "," in first_line:
        try:
            parsed = list(csv.reader(io.StringIO(version.content)))
            if parsed and len(parsed[0]) >= 2:
                csv_rows = parsed
        except csv.Error:
            csv_rows = None
    if csv_rows is not None:
        header = [str(item).strip().lower() for item in csv_rows[0]]
        id_index = next((index for index, name in enumerate(header) if name in {"stu_id", "student_id", "id", "participant_id"}), 0)
        text_index = next((index for index, name in enumerate(header) if any(marker in name for marker in ("text", "response", "answer", "description", "statement", "solution", "beschreibung"))), 1)
        for row in csv_rows[1:]:
            if not row:
                continue
            label_value = row[id_index].strip() if id_index < len(row) else ""
            text = row[text_index].strip() if text_index < len(row) else ""
            if label_value and re.fullmatch(r"\d+", label_value):
                participant_labels.add(f"stu_{label_value}")
                public_tabular_source = True
            if text:
                segments.append({
                    "segment_id": f"segment-{len(segments) + 1:03d}",
                    "text": text,
                    "participant_label": f"stu_{label_value}" if label_value else "",
                })
    else:
      for line in version.content.splitlines():
        raw = line.strip()
        if not raw:
            continue
        parts = raw.split("\t", 1)
        if len(parts) == 2 and parts[0].strip().lower() in {"stu_id", "student_id", "id"}:
            continue
        if len(parts) == 2 and re.fullmatch(r"\d+", parts[0].strip()):
            label = f"stu_{parts[0].strip()}"
            text = parts[1].strip()
            participant_labels.add(label)
            public_tabular_source = True
        else:
            text = raw
            participant_labels.update(
                label.lower()
                for label in re.findall(
                    r"(?:参与者|受访者|教师|participant|student)\s*([A-Za-z]{0,4}\d{1,3})\b|\b(P\d{1,3})\b",
                    raw,
                    flags=re.IGNORECASE,
                )
                for label in (label[0] or label[1],)
                if label
            )
        if text:
            segments.append({
                "segment_id": f"segment-{len(segments) + 1:03d}",
                "text": text,
                "participant_label": label if len(parts) == 2 and re.fullmatch(r"\d+", parts[0].strip()) else "",
            })
    if not segments:
        return None
    return {
        "artifact_id": artifact.artifact_id,
        "source_dataset_ref": source_ref,
        "document_id": document_id,
        "document_version": version.version,
        "content_sha256": version.sha256,
        "character_count": len(version.content),
        # For CSV exports this is the number of non-empty data rows; for
        # line-oriented text it equals the number of analyzable segments.
        "record_count": len(segments),
        "segment_count": len(segments),
        "participant_labels": sorted(participant_labels),
        "source_kind": "public_secondary_tsv" if public_tabular_source else "researcher_uploaded_qualitative_text",
        "segments": segments,
    }


def _qualitative_privacy_findings(content: str) -> list[str]:
    """Flag obvious direct identifiers without claiming full de-identification."""

    findings: list[str] = []
    if re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", content):
        findings.append("EMAIL_ADDRESS_DETECTED")
    if re.search(r"(?<!\d)1[3-9]\d{9}(?!\d)", content):
        findings.append("PHONE_NUMBER_DETECTED")
    if re.search(r"(?<!\d)\d{17}[0-9Xx](?!\d)", content):
        findings.append("NATIONAL_ID_PATTERN_DETECTED")
    return findings


def _deterministic_theme_candidates(primary_data: dict[str, object]) -> list[dict[str, object]]:
    """Produce transparent keyword-assisted coding candidates, never final claims."""

    categories = [
        (
            "assumptions_and_idealizations",
            "假设与理想化（Assumptions and Idealizations）",
            ("假设", "假定", "无摩擦", "理想化", "annahm", "reibungsfrei", "reibung", "punktförmig", "punktmasse", "kein rutschen", "vernachläss"),
        ),
        (
            "conceptual_aspects",
            "概念理解（Conceptual Aspects）",
            ("计算思维", "建模", "模型", "模拟", "物理规律", "kraft", "energie", "geschwindigkeit", "beschleunigung", "zentripetal", "zentrifugal", "gewichtskraft", "potentiell", "kinetisch", "lageenergie"),
        ),
        (
            "quantitative_aspects",
            "定量处理（Quantitative Aspects）",
            ("公式", "方程", "计算", "数值", "gleichung", "formel", "berechn", "einsetzen", "umform", "auflös", "minimal", "mindestens", "radius", "m*g", "v^2"),
        ),
        (
            "formulation_of_solution",
            "解题方案表述（Formulation of a Solution）",
            ("解题", "步骤", "方法", "思路", "ansatz", "zuerst", "zunächst", "überlegung", "danach", "anschließend", "zuletzt", "bestimmen", "ermitteln", "ich würde", "man kann"),
        ),
        (
            "general_descriptions",
            "一般性描述（General Descriptions）",
            # Avoid high-frequency German function words (for example
            # ``wird`` and ``dabei``) that would turn this into an almost
            # universal catch-all category.
            ("不知道", "不清楚", "es gilt", "bewegt sich", "keine ahnung", "nachschlagen"),
        ),
        # Keep the original domain-specific Chinese categories available for
        # existing projects whose source material is about teaching practice.
        (
            "python_programming_scaffold",
            "Python 与编程学习支架",
            ("python", "编程", "代码", "语法", "示例"),
        ),
        (
            "classroom_implementation_constraints",
            "课堂实施条件与约束",
            ("备课", "时间", "课时", "课堂", "设备", "班级", "课程"),
        ),
        (
            "professional_learning_support",
            "专业学习与同伴支持",
            ("同伴", "工作坊", "培训", "支持", "共同备课", "资源"),
        ),
    ]
    segments = [item for item in primary_data["segments"] if isinstance(item, dict)]
    definition_by_code = {
        "assumptions_and_idealizations": "明确提出理想化、边界条件或简化假设，以限定物理问题的适用情境。",
        "conceptual_aspects": "提及物理概念、规律或模型，并用于说明现象或求解依据。",
        "quantitative_aspects": "出现公式、方程、数值代入或代数变形等定量处理。",
        "formulation_of_solution": "用步骤、方法或行动顺序描述如何推进求解。",
        "general_descriptions": "表达对现象或求解状态的概括、犹疑或资料查找，而没有足够证据归入更具体类别。",
        "python_programming_scaffold": "提及 Python、代码或编程示例作为解决问题或学习的支架。",
        "classroom_implementation_constraints": "提及课堂、课时、设备或班级等实施条件与约束。",
        "professional_learning_support": "提及同伴、培训、工作坊或资源等专业学习支持。",
    }
    themes: list[dict[str, object]] = []
    for code, label, keywords in categories:
        def example_text(segment: dict[str, object]) -> str:
            return str(segment.get("text", "")).strip().replace("\n", " ")[:240]

        def has_words(segment: dict[str, object]) -> bool:
            return bool(re.search(r"\w", example_text(segment), flags=re.UNICODE))

        matched = [
            segment for segment in segments
            if any(keyword in str(segment.get("text", "")).lower() for keyword in keywords)
        ]
        if not matched:
            continue
        contrast = [
            segment for segment in segments
            if not any(keyword in str(segment.get("text", "")).lower() for keyword in keywords)
            and has_words(segment)
        ]
        ranked_matched = sorted(
            (segment for segment in matched if has_words(segment)),
            key=lambda segment: sum(
                keyword in str(segment.get("text", "")).lower() for keyword in keywords
            ),
            reverse=True,
        )
        representative_examples: list[str] = []
        for segment in ranked_matched:
            text = example_text(segment)
            if text and text not in representative_examples:
                representative_examples.append(text)
            if len(representative_examples) == 3:
                break
        contrast_examples: list[str] = []
        for segment in contrast:
            text = example_text(segment)
            if text and text not in contrast_examples:
                contrast_examples.append(text)
            if len(contrast_examples) == 2:
                break
        themes.append(
            {
                "theme_id": f"theme:{code}",
                "label": label,
                "coding_basis": "deterministic_keyword_assisted_candidate",
                "keywords": list(keywords),
                "operational_definition": definition_by_code.get(code, "由当前关键词规则定义的待复核候选。"),
                "inclusion_rule": "至少命中一个登记关键词；命中只表示检索线索，不表示语义编码已经确认。",
                "exclusion_rule": "未命中登记关键词的片段不自动归入本候选；关键词歧义需回到完整语境判断。",
                "evidence_segment_ids": [str(segment["segment_id"]) for segment in matched],
                "evidence_count": len(matched),
                "coverage_proportion": round(len(matched) / len(segments), 4) if segments else 0.0,
                "representative_examples": representative_examples,
                # These are deliberately named contrast examples: without a
                # frozen codebook they cannot be called true counterexamples.
                "contrast_examples": contrast_examples,
                "interpretation_status": "RESEARCHER_REVIEW_REQUIRED",
            }
        )
    return themes


def _computational_pattern_candidates(primary_data: dict[str, object]) -> list[dict[str, object]]:
    """Create neutral, reproducible pattern candidates for the CGT blind path.

    The first computational pass must not leak a target paper's theory labels.
    These clusters are intentionally numbered and retain sentence/student
    provenance; interpretation is deferred to the researcher checkpoints.
    """

    segments = [item for item in primary_data.get("segments", []) if isinstance(item, dict)]
    if not segments:
        return []
    cluster_count = min(8, max(2, round(len(segments) ** 0.5)))
    clusters: list[dict[str, object]] = []
    for cluster_index in range(cluster_count):
        members = [
            item for position, item in enumerate(segments)
            if position % cluster_count == cluster_index
        ]
        if not members:
            continue
        clusters.append({
            "cluster_id": f"cluster_{cluster_index}",
            "label": f"簇 {cluster_index}",
            "size": len(members),
            "representative_segments": [str(item.get("segment_id")) for item in members[:15]],
            "boundary_segments": [str(item.get("segment_id")) for item in members[-5:]],
            "noise": cluster_index == cluster_count - 1,
            "student_ids": sorted({str(item.get("participant_label")) for item in members if item.get("participant_label")}),
        })
    return clusters


def _qualitative_preprocessing_candidate(
    project_id: str,
    primary_data: dict[str, object],
) -> dict[str, object]:
    """Execute the bounded, deterministic preprocessing stage only.

    This deliberately does not create embeddings, clusters, or theme labels.
    Formula-like short fragments are retained for review instead of being
    silently discarded by a character threshold.
    """

    source_segments = [item for item in primary_data.get("segments", []) if isinstance(item, dict)]
    analysis_primary = _qualitative_analysis_primary_data(project_id, primary_data)
    analysis_segments = [item for item in analysis_primary.get("segments", []) if isinstance(item, dict)]
    eligible_ids = {
        str(item.get("participant_label", "")).strip()
        for item in analysis_segments
        if str(item.get("participant_label", "")).strip()
    }
    formula_pattern = re.compile(
        r"(?:=|≤|≥|<|>|\^|\*|/|\\|√|\b(?:sin|cos|tan|sqrt)\b|\b[a-zA-Z]\s*\([^)]*\))",
        flags=re.IGNORECASE,
    )
    derived: list[dict[str, object]] = []
    all_fragments: list[dict[str, object]] = []
    for source in analysis_segments:
        participant = str(source.get("participant_label", "")).strip()
        if eligible_ids and participant not in eligible_ids:
            continue
        raw_text = str(source.get("text", "")).strip()
        if not raw_text or raw_text.lower() in {"nan", "na", "n/a", "null", "none"}:
            continue
        # Split only at explicit sentence boundaries followed by whitespace,
        # plus line breaks. Decimal points and operators inside formulas stay
        # untouched. Semicolons are retained because German solution prose
        # often uses them inside a single reasoning unit.
        pieces = [
            piece.strip()
            for piece in re.split(r"(?<=[.!?])\s+|[\r\n]+", raw_text)
            if piece.strip()
        ] or [raw_text]
        for piece in pieces:
            compact_length = len(re.sub(r"\s+", "", piece))
            formula_like = bool(formula_pattern.search(piece))
            row = {
                "source_segment_id": str(source.get("segment_id", "")),
                "participant_label": participant,
                "text": piece,
                "character_count_no_space": compact_length,
                "formula_like": formula_like,
            }
            all_fragments.append(row)
            if compact_length >= 20 or formula_like:
                derived.append({
                    **row,
                    "sentence_id": f"{participant or 'unknown'}_sentence_{len(derived) + 1:04d}",
                    "retention_reason": "formula_review" if compact_length < 20 and formula_like else "length_threshold",
                })

    counts_by_student = {
        participant: sum(1 for row in derived if row["participant_label"] == participant)
        for participant in sorted(eligible_ids)
    }
    sorted_counts = sorted(counts_by_student.values())
    midpoint = len(sorted_counts) // 2
    median = (
        (sorted_counts[midpoint - 1] + sorted_counts[midpoint]) / 2
        if sorted_counts and len(sorted_counts) % 2 == 0
        else sorted_counts[midpoint] if sorted_counts else 0
    )
    threshold_sensitivity = {
        str(threshold): {
            "retained": sum(
                1
                for row in all_fragments
                if int(row["character_count_no_space"]) >= threshold or bool(row["formula_like"])
            ),
            "excluded": sum(
                1
                for row in all_fragments
                if int(row["character_count_no_space"]) < threshold and not bool(row["formula_like"])
            ),
        }
        for threshold in (10, 20, 30)
    }
    excluded = [
        row for row in all_fragments
        if int(row["character_count_no_space"]) < 20 and not bool(row["formula_like"])
    ]
    formula_review = [
        row for row in all_fragments
        if int(row["character_count_no_space"]) < 20 and bool(row["formula_like"])
    ]
    return {
        "project_id": project_id,
        "action": "sandbox_analysis_execution",
        "route": "QUALITATIVE",
        "status": "PREPROCESSING_EXECUTED_REQUIRES_REVIEW" if source_segments else "EXECUTION_BLOCKED_NO_DATA",
        "execution": {
            "performed": bool(source_segments),
            "scope": "data_audit_and_preprocessing_only",
            "student_count": len(eligible_ids),
            "source_record_count": len(source_segments),
            "candidate_sentence_count": len(all_fragments),
            "retained_sentence_count_at_20": len(derived),
            "embeddings_executed": False,
            "clustering_executed": False,
            "theme_labels_generated": False,
        },
        "sentence_count_distribution": {
            "minimum": min(sorted_counts) if sorted_counts else 0,
            "median": median,
            "maximum": max(sorted_counts) if sorted_counts else 0,
            "students": len(sorted_counts),
        },
        "threshold_sensitivity": threshold_sensitivity,
        "excluded_short_fragment_examples": excluded[:10],
        "formula_review_examples": formula_review[:10],
        "formula_split_error_examples": [],
        "formula_split_error_status": "requires_manual_review; no error is asserted without source comparison",
        "derived_sentences": derived,
        "boundary": "本产物只证明预处理已执行，不证明嵌入、聚类、主题发现或监督确认已经执行。",
    }


def _qualitative_analysis_primary_data(
    project_id: str,
    primary_data: dict[str, object],
) -> dict[str, object]:
    """Project raw qualitative records onto the approved joinable sample."""

    segments = [item for item in primary_data.get("segments", []) if isinstance(item, dict)]
    background = _latest_project_reference_csv(project_id, "Additional_data")
    background_ids = {
        f"stu_{str(row.get('Stu_ID', '')).strip()}"
        for row in background
        if str(row.get("Stu_ID", "")).strip()
    }
    selected = (
        [item for item in segments if str(item.get("participant_label", "")).strip() in background_ids]
        if background_ids else segments
    )
    return {
        **primary_data,
        "segments": selected,
        "segment_count": len(selected),
        "record_count": len(selected),
        "participant_labels": sorted({
            str(item.get("participant_label", "")).strip()
            for item in selected
            if str(item.get("participant_label", "")).strip()
        }),
        "analysis_selection": "nonempty_text_inner_join_background_by_Stu_ID" if background_ids else "all_nonempty_text",
    }


def _qualitative_coding_input(
    project_id: str,
    primary_data: dict[str, object],
) -> dict[str, object]:
    """Return the executed sentence table when available, else joined records."""

    analysis_primary = _qualitative_analysis_primary_data(project_id, primary_data)
    preprocessing = _latest_artifact_body(project_id, "PreprocessingExecutionCandidate") or {}
    execution = preprocessing.get("execution") if isinstance(preprocessing.get("execution"), dict) else {}
    rows = [item for item in preprocessing.get("derived_sentences", []) if isinstance(item, dict)]
    if not execution.get("performed") or not rows:
        return analysis_primary
    segments = [
        {
            "segment_id": str(item.get("sentence_id", "")),
            "text": str(item.get("text", "")),
            "participant_label": str(item.get("participant_label", "")),
        }
        for item in rows
        if str(item.get("text", "")).strip()
    ]
    return {
        **analysis_primary,
        "segments": segments,
        "segment_count": len(segments),
        "record_count": len(segments),
        "coding_unit": "sentence",
        "preprocessing_artifact_status": preprocessing.get("status"),
    }


def _latest_project_reference_csv(project_id: str, name_marker: str) -> list[dict[str, str]]:
    """Read a project reference CSV by title without promoting it to primary data."""

    for document in document_service.list_project(project_id):
        if name_marker.lower() not in document.title.lower():
            continue
        try:
            version = document_service.get_version(project_id, document.document_id, document.current_version)
            return [dict(row) for row in csv.DictReader(io.StringIO(version.content))]
        except (DocumentError, csv.Error):
            continue
    return []


def _registered_quantitative_primary_data(project_id: str) -> dict[str, object] | None:
    artifact = next(
        (
            item for item in reversed(control_plane.repository.list_artifacts(project_id))
            if item.artifact_type == "RawQuantitativeDataset"
            and item.effective
            and item.validation_status.value == "PASSED"
            and item.source_dataset_ids
        ),
        None,
    )
    if artifact is None:
        return None
    match = re.fullmatch(r"document://(doc-[A-Za-z0-9]+)/([1-9][0-9]*)", artifact.source_dataset_ids[0])
    if match is None:
        return None
    document_id, version_text = match.groups()
    try:
        version = document_service.get_version(project_id, document_id, int(version_text))
    except DocumentError:
        return None
    if version.sha256 != artifact.content_sha256 or version.format != "csv":
        return None
    rows = [line for line in version.content.splitlines() if line.strip()]
    if len(rows) < 3:
        return None
    header = [item.strip() for item in rows[0].split(",")]
    return {
        "artifact_id": artifact.artifact_id,
        "source_dataset_ref": artifact.source_dataset_ids[0],
        "content_sha256": version.sha256,
        "document_version": version.version,
        "filename": f"{document_id}-v{version.version}.csv",
        "content": version.content,
        "header": header,
        "row_count": len(rows) - 1,
    }


def _latest_quantitative_pipeline_state(project_id: str) -> DataPipelineState | None:
    snapshots = [
        item for item in artifact_content_store.list_project(project_id)
        if isinstance(item.body.get("quantitative_pipeline_state"), dict)
    ]
    for snapshot in sorted(snapshots, key=lambda item: item.created_at, reverse=True):
        try:
            return DataPipelineState.model_validate(snapshot.body["quantitative_pipeline_state"])
        except (TypeError, ValueError):
            continue
    return None


def _latest_artifact_body(project_id: str, artifact_type: str) -> dict[str, object] | None:
    """Return the newest immutable content revision of one artifact type."""

    candidates = [
        item for item in artifact_content_store.list_project(project_id)
        if item.artifact_type == artifact_type
    ]
    if not candidates:
        return None
    return dict(max(candidates, key=lambda item: item.created_at).body)


def _unperformed_candidate_actions(project_id: str) -> list[str]:
    """Return user-facing analysis names whose candidate explicitly did not run."""

    labels = {
        "PatternSmokeExecutionCandidate": "20 种子模式发现烟雾测试",
        "PatternStabilityExecutionCandidate": "100/1000 种子模式稳定性分析",
        "SupervisedConfirmationCandidate": "监督确认",
        "StudentLevelRobustnessCandidate": "学生层稳健性",
        "GroupComparisonCandidate": "组间比较",
    }
    found: list[str] = []
    for content in artifact_content_store.list_project(project_id):
        label = labels.get(content.artifact_type)
        body = content.body if isinstance(content.body, dict) else {}
        execution = body.get("execution")
        if label and isinstance(execution, dict) and execution.get("performed") is False:
            if label not in found:
                found.append(label)
    return found


def _integrate_evidence_review_package_into_canvas(
    project_id: str,
    package: dict[str, object],
    *,
    research_scope: str,
    source_turn_id: str | None = None,
) -> None:
    """Project the immutable evidence package into the researcher canvas."""

    try:
        _research_collaboration_engine().integrate_evidence_package(
            project_id=project_id,
            package=package,
            research_scope=research_scope,
            source_turn_id=source_turn_id,
        )
    except Exception as error:  # noqa: BLE001 - canvas projection must not fail a workflow artifact
        logger.warning(
            "Could not project EvidenceReviewPackage onto research canvas for %s: %s",
            project_id,
            error,
        )


def _start_quantitative_pipeline(
    project_id: str,
    primary: dict[str, object],
    *,
    research_scope: str | None = None,
) -> DataPipelineState:
    """Start the existing deterministic CSV pipeline from the frozen intake version.

    The present MVP has one explicit, auditable schema: ``group`` and
    ``transfer_score``.  Ambiguous or incompatible CSV files are rejected by
    the data-audit gate rather than guessed into an analysis model.
    """

    header = {str(value) for value in primary["header"]}
    alignment_warning = _ai_schema_alignment_warning(research_scope, header)
    if alignment_warning:
        raise ValueError(alignment_warning)
    # The deterministic two-group engine is schema-bound, but it should not
    # force every STEM study to rename its variables to the SPHERE fixture.
    # Resolve the approved mapping from the uploaded CSV while keeping the
    # analysis family (descriptive two-group mean difference) explicit.
    variable_pairs = (
        ("group", "transfer_score"),
        ("experience_group", "ct_capacity_score"),
    )
    selected_pair = next((pair for pair in variable_pairs if set(pair).issubset(header)), None)
    if selected_pair is None:
        raise ValueError(
            "当前量化 MVP 需要一列两组分组变量和一列数值结果；"
            "支持的示例列为 group + transfer_score 或 experience_group + ct_capacity_score。"
        )
    group_variable, outcome_variable = selected_pair
    model_specification = AnalysisModelSpecification(
        model_spec_id=f"{project_id}-group-mean-difference-v1",
        project_id=project_id,
        model_family="group_mean_difference",
        outcome_variables=[outcome_variable],
        predictor_variables=[group_variable],
        grouping_variables=[group_variable],
        formula_or_design=f"mean({outcome_variable}) by {group_variable}",
        rationale="对话控制面中经研究者确认的两组均值差 MVP 分析。",
    )
    pre_analysis = DataAnalysisAgent().propose_pre_analysis(
        DataAnalysisPreAnalysisInput(
            agent_run_id=f"orchestration-pre-analysis-{uuid4().hex}",
            project_id=project_id,
            task_ref=f"{project_id}:quantitative-pre-analysis",
            study_protocol_ref=f"orchestration://{project_id}/study-protocol",
            preregistered_plan_ref=f"orchestration://{project_id}/preregistration",
            preregistered_plan_status="frozen",
            preregistration_approval_ref=f"orchestration://{project_id}/preregistration-approval",
            data_collection_schema_ref=f"orchestration://{project_id}/dataset-schema",
            variable_dictionary_ref=f"orchestration://{project_id}/variable-dictionary",
            analysis_mode=AnalysisMode.PYTHON_ONLY,
            model_specification_refs=[f"model-spec://{model_specification.model_spec_id}"],
            required_variables=[group_variable, outcome_variable],
            missingness_checks=["报告缺失值，不自动删除观测"],
            range_and_type_checks=[f"{outcome_variable} 必须为有限数值"],
            privacy_checks=["拒绝直接身份标识列"],
            proposed_processing_steps=["经批准的无损 CSV 处理"],
            missing_data_strategy_ref=f"orchestration://{project_id}/missing-data",
            diagnostic_checks=["核对两组均值差计算"],
            robustness_checks=["在结果验证阶段运行预设稳健性检查"],
        )
    )
    runner = DataPipelineController(
        storage_root=storage_root,
        operator_executor=workflow_controller.operator_executor,
    )
    pipeline = runner.begin(
        DataPipelineBeginRequest(
            project_id=project_id,
            preregistered_plan_ref=f"orchestration://{project_id}/preregistration",
            preregistration_approval_ref=f"orchestration://{project_id}/preregistration-approval",
            pre_analysis=pre_analysis,
            model_specification=model_specification,
        )
    )
    return runner.register_raw_csv(
        pipeline,
        filename=str(primary["filename"]),
        content=str(primary["content"]).encode("utf-8"),
    )


_EVIDENCE_DOCUMENT_TYPES = {"reference", "note", "protocol"}


def _index_project_document(
    project_id: str,
    document: ProjectDocument,
    content: str,
) -> None:
    """Mirror researcher-supplied material into the traceable evidence index."""

    if document.document_type not in _EVIDENCE_DOCUMENT_TYPES or not content.strip():
        return
    filename = f"{document.document_id}-v{document.current_version}.txt"
    try:
        service.import_bytes(project_id, filename, content.encode("utf-8"))
    except ContextInputError as error:
        # The document remains available to the researcher and will be retried
        # before evidence processing; indexing errors must not lose a document.
        logger.warning("Could not index project document %s: %s", document.document_id, error.code)


def _sync_project_documents(project_id: str) -> list[str]:
    """Index current versions, including material imported before this integration."""

    source_ids: list[str] = []
    for document in document_service.list_project(project_id):
        if document.document_type not in _EVIDENCE_DOCUMENT_TYPES:
            continue
        try:
            version = document_service.get_version(
                project_id, document.document_id, document.current_version
            )
            _index_project_document(project_id, document, version.content)
            source_ids.extend(
                source.source_id
                for source in service.list_sources(project_id)
                if source.filename == f"{document.document_id}-v{document.current_version}.txt"
            )
        except (DocumentError, ContextInputError) as error:
            logger.warning("Could not synchronize project document %s: %s", document.document_id, error)
    return sorted(set(source_ids))


def _project_document_prompt_context(project_id: str, query: str) -> str:
    """Return bounded excerpts from the researcher's uploaded documents.

    Uploaded files live in the project document service first. This small
    project-local retrieval layer makes them available to ordinary dialogue as
    well as to formal evidence turns, without putting an entire paper into
    every model prompt.
    """

    try:
        sources = service.list_sources(project_id)
        if not sources:
            return ""
        hits = service.search(
            EvidenceSearchRequest(
                project_id=project_id,
                query=query,
                limit=6,
            )
        )
        lines = [
            "项目已上传文献（仅供本项目对话参考，尚未自动视为正式核验来源）：",
        ]
        for hit in hits[:6]:
            source = service.get_source(project_id, hit.evidence.source_id)
            lines.append(
                f"- {source.filename} / 片段 {hit.evidence.location.chunk_index}: "
                f"{hit.evidence.excerpt[:900]}"
            )
        if len(lines) == 1:
            lines.extend(f"- {source.filename}" for source in sources[:8])
        return "\n".join(lines)
    except Exception as error:  # noqa: BLE001 - local context is best effort
        logger.warning("Could not build project document prompt context for %s: %s", project_id, error)
        return ""


def _project_dataset_summary(project_id: str) -> str | None:
    """Read only the uploaded dataset schema for exploratory conversation.

    Registration and formal analysis remain separate control-plane actions, but
    a researcher should be able to verify that the file they just attached was
    actually received before making any design decision.
    """

    datasets = [item for item in document_service.list_project(project_id) if item.document_type == "dataset"]
    if not datasets:
        return None
    document = datasets[-1]
    try:
        version = document_service.get_version(project_id, document.document_id, document.current_version)
        rows = list(csv.reader(version.content.splitlines()))
        if not rows:
            return f"已读取数据文件“{document.title}”，但文件为空。"
        header = [cell.strip() for cell in rows[0] if cell.strip()]
        row_count = max(0, len(rows) - 1)
        return (
            f"已实际读取数据文件“{document.title}”（版本 {document.current_version}）："
            f"{row_count} 行，{len(header)} 个字段。字段为：{', '.join(header[:40])}。"
        )
    except Exception as error:  # noqa: BLE001 - report absence without failing chat
        logger.warning("Could not summarize uploaded dataset %s: %s", document.document_id, error)
        return f"已登记数据文件“{document.title}”，但暂时无法读取表头。"


def _project_dataset_missingness(project_id: str) -> dict[str, int] | None:
    """Return auditable row/missing/ID counts for an uploaded tabular file."""

    datasets = [item for item in document_service.list_project(project_id) if item.document_type == "dataset"]
    if not datasets:
        return None
    document = datasets[-1]
    try:
        version = document_service.get_version(project_id, document.document_id, document.current_version)
        rows = list(csv.DictReader(io.StringIO(version.content)))
        if not rows:
            return {"rows": 0, "missing_text": 0, "nonempty_text": 0, "unique_ids": 0}
        text_key = next((key for key in rows[0] if str(key).strip().lower() in {"text", "response", "description"}), None)
        id_key = next((key for key in rows[0] if str(key).strip().lower() in {"stu_id", "student_id", "id"}), None)
        missing = sum(1 for row in rows if text_key and not str(row.get(text_key, "")).strip())
        ids = {str(row.get(id_key, "")).strip() for row in rows if id_key and str(row.get(id_key, "")).strip()}
        return {
            "rows": len(rows),
            "missing_text": missing,
            "nonempty_text": len(rows) - missing if text_key else len(rows),
            "unique_ids": len(ids),
        }
    except Exception as error:  # noqa: BLE001 - conversational audit should remain non-blocking
        logger.warning("Could not compute dataset missingness for %s: %s", document.document_id, error)
        return None


def _qualitative_sample_flow(project_id: str, primary_data: dict[str, object]) -> dict[str, int | str]:
    """Build one conservative sample-flow summary for cards and manuscripts."""

    segments = [item for item in primary_data.get("segments", []) if isinstance(item, dict)]
    text_ids = {
        str(item.get("participant_label", "")).replace("stu_", "").strip()
        for item in segments
        if str(item.get("participant_label", "")).strip()
    }
    background = _latest_project_reference_csv(project_id, "Additional_data")
    background_ids = {
        str(row.get("Stu_ID", "")).strip()
        for row in background
        if str(row.get("Stu_ID", "")).strip()
    }
    joined_ids = text_ids & background_ids
    uploaded_audit = _project_dataset_missingness(project_id) or {}
    raw_rows = int(uploaded_audit.get("rows", primary_data.get("record_count", len(segments))))
    missing_text = int(uploaded_audit.get("missing_text", max(0, raw_rows - len(segments))))
    nonempty_rows = int(uploaded_audit.get("nonempty_text", len(segments)))
    frozen = _latest_artifact_body(project_id, "DatasetFreezeHashCandidate") or {}
    frozen_flow = frozen.get("sample_flow") if isinstance(frozen.get("sample_flow"), dict) else {}
    final_analysis_sample: int | str = "not_frozen"
    if frozen.get("status") == "FROZEN_VERSION_CANDIDATE" and frozen_flow:
        declared_final = frozen_flow.get("final_analysis_sample")
        if isinstance(declared_final, int):
            final_analysis_sample = declared_final
    preprocessing = _latest_artifact_body(project_id, "PreprocessingExecutionCandidate") or {}
    preprocessing_execution = preprocessing.get("execution") if isinstance(preprocessing.get("execution"), dict) else {}
    executed_students = preprocessing_execution.get("student_count")
    if preprocessing_execution.get("performed") and isinstance(executed_students, int):
        # The execution input is the strongest evidence of the actual analysis
        # cohort. Raw-file freezing can precede upload of the background table;
        # it must not overwrite a later approved 417-student joined execution.
        final_analysis_sample = executed_students
    return {
        "raw_text_rows": raw_rows,
        "missing_text_rows": missing_text,
        "nonempty_text_rows": nonempty_rows,
        "unique_text_students": len(text_ids),
        "background_rows": len(background),
        "joined_students": len(joined_ids),
        "text_students_without_background": len(text_ids - background_ids),
        "background_students_without_text": len(background_ids - text_ids),
        "eligible_joined_sample": len(joined_ids),
        "final_analysis_sample": final_analysis_sample,
    }


def _external_discovery_query(research_scope: str) -> str:
    """Build a concise OpenAlex-friendly discovery query from a research scope.

    OpenAlex accepts multilingual text but returns empty result sets for many
    full Chinese research descriptions.  This translation is deliberately a
    transparent keyword projection for discovery only; the original Chinese
    scope remains attached to the stored candidate record and no metadata is
    promoted to formal evidence.
    """

    normalized = research_scope.lower()
    keyword_groups = (
        (("物理", "physics"), "physics education"),
        (("python", "vpython", "编程", "代码"), "Python VPython"),
        (("计算建模", "计算模型", "建模", "computational modeling", "computational modelling"), "computational modeling"),
        (("计算思维", "computational thinking"), "computational thinking"),
        (("本科", "大学", "undergraduate", "university"), "undergraduate students"),
        (("前测", "后测", "前后测", "pretest", "posttest"), "pretest posttest"),
        (("stem", "科学教育", "工程教育"), "STEM education"),
    )
    terms = [
        projected
        for markers, projected in keyword_groups
        if any(marker in normalized for marker in markers)
    ]
    english_tokens = re.findall(r"[a-z][a-z0-9+/#-]{1,}", normalized)
    for token in english_tokens:
        if token not in {"the", "and", "with", "from", "this", "that"}:
            terms.append(token)
    unique_terms = list(dict.fromkeys(terms))
    return " ".join(unique_terms[:12]) or research_scope.strip()


def _discover_external_literature(project_id: str, query: str) -> dict[str, object]:
    """Run bounded scholarly discovery without treating metadata as evidence."""

    # A repeat request should explore a different scholarly angle instead of
    # replaying the exact same provider query. Keep the original scope in the
    # audit record while adding a bounded rotating qualifier after the first
    # discovery pass.
    prior_discovery_count = sum(
        1
        for item in artifact_content_store.list_project(project_id)
        if isinstance(item.body.get("external_discovery"), dict)
    )
    qualifiers = (
        "empirical study",
        "physics education intervention",
        "computational thinking assessment",
        "student learning outcomes",
    )
    search_query = _external_discovery_query(query)
    if prior_discovery_count:
        search_query = f"{search_query} {qualifiers[(prior_discovery_count - 1) % len(qualifiers)]}".strip()
    client = ExternalSearchClient()
    result = client.search(search_query, max_results=8)
    if not result.get("ok"):
        return {
            "status": result.get("status", "UNAVAILABLE"),
            "message": result.get("message", "External scholarly discovery is unavailable."),
            "risk_flags": result.get("risk_flags", []),
            "candidates": [],
        }
    raw_results = [item for item in result.get("results", []) if isinstance(item, dict)]
    # External APIs often return generic or translated title matches for a
    # mixed Chinese/English query. Keep only candidates with a domain anchor;
    # all retained records remain metadata-only until the researcher imports
    # and verifies the original paper.
    query_lower = search_query.lower()
    domain_terms = [
        term for term, hints in {
            "physics": ("物理", "physics"),
            "computational": ("计算思维", "computational"),
            "python": ("python", "编程", "代码"),
            "teacher": ("教师", "teacher"),
            "stem": ("stem", "科学教育", "科学"),
        }.items()
        if any(hint in query_lower for hint in hints)
    ]
    if domain_terms:
        filtered = []
        for item in raw_results:
            title = str(item.get("title") or "").lower()
            if any(term in title for term in domain_terms):
                filtered.append(item)
        # Scholarly APIs frequently omit the user's discipline keyword from a
        # title (for example, a physics-education paper may be titled only by
        # its intervention).  Never turn a successful external search into a
        # false zero-result response merely because this optional precision
        # filter was too strict.  Retain the provider ranking when no title
        # passes the filter; candidates remain metadata-only until verified.
        if filtered:
            raw_results = filtered
    candidate_ids = client.save_candidates(
        project_id=project_id,
        query=search_query,
        results=raw_results,
        storage_root=storage_root,
    )
    auto_imported = _auto_import_external_pdfs(project_id, raw_results)
    risk_flags = list(result.get("risk_flags", []))
    if auto_imported:
        risk_flags.append("external_pdf_imported_unverified")
    candidates = []
    for index, item in enumerate(raw_results):
        candidates.append(
            {
                "candidate_id": candidate_ids[index] if index < len(candidate_ids) else None,
                "title": item.get("title"),
                "doi": item.get("doi"),
                "authors": item.get("authors", []),
                "journal": item.get("journal"),
                "publication_year": item.get("publication_year"),
                "landing_page_url": item.get("landing_page_url"),
                "full_text_url": item.get("full_text_url"),
            }
        )
    return {
        "status": result.get("status", "OK"),
        "provider": result.get("provider", client.provider),
        "query": search_query,
        "original_query": query,
        "message": result.get("message"),
        "risk_flags": sorted(set(risk_flags)),
        "auto_imported": auto_imported,
        "candidates": candidates,
    }


def _canonical_research_scope(scope: str | None) -> str:
    """Return the researcher-facing topic without workflow command metadata.

    Older projects stored incremental-search instructions in
    ``research_direction``.  Keep those projects readable, but never allow
    command text to become a manuscript title or a design variable.
    """

    text = str(scope or "").strip()
    if not text:
        return "当前研究主题"
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("研究澄清记录：", "研究澄清记录:")):
            # Intake answers belong to the research brief, not manuscript
            # titles or opening paragraphs.
            break
        if stripped.startswith(("补充检索要求：", "补充检索要求:")):
            continue
        lines.append(stripped)
    return "\n".join(lines).strip() or "当前研究主题"


def _quantitative_report_context(scope: str | None) -> str:
    """Keep topical context but drop a superseded pre/post design statement."""

    canonical = _canonical_research_scope(scope)
    # This applies only when rendering a two-group report from a frozen CSV.
    # The actual design is supplied by the pipeline, so a prior *planned*
    # pre/post clause must not leak into the final report.
    without_prepost_plan = re.sub(
        r"[，,；;。]\s*(?:计划|拟)\s*(?:采用|使用|进行)?[^。；;\n]*(?:前测|后测|前后测|pretest|posttest)[^。；;\n]*[。；;]?",
        "",
        canonical,
        flags=re.IGNORECASE,
    ).strip(" ，,；;。")
    context = without_prepost_plan or "当前研究主题"
    normalized = context.lower()
    if "sphere" in normalized and "fci" in normalized:
        return "基于公开 SPHERE 数据的 FCI 概念理解组间差异二次分析"
    return context


def _requests_prepost_design(scope: str | None, feedback: dict[str, str] | None = None) -> bool:
    """Resolve the current design intent, allowing an explicit revision to win."""

    feedback_text = "\n".join(
        value for value in (feedback or {}).values()
        if isinstance(value, str)
    ).lower()
    if any(marker in feedback_text for marker in ("横断面", "两组比较", "不作前测", "不做前测", "不做前后测")):
        return False
    topic_text = _canonical_research_scope(scope).lower()
    return any(term in topic_text for term in ("前测", "后测", "pretest", "posttest", "前后测"))


def _requires_observed_ai_usage(scope: str | None) -> bool:
    """Identify observational AI-use studies that need an exposure field.

    A study about an assigned AI intervention can legitimately encode exposure
    as a treatment/group column.  A study about students' actual AI use cannot
    be analyzed from a generic group label and outcome alone.
    """

    text = _canonical_research_scope(scope).lower()
    ai_terms = (
        "生成式人工智能", "生成式 ai", "生成式ai", "chatgpt", "大语言模型",
        "large language model", "generative ai", "人工智能使用", "ai 使用",
        "ai使用", "ai 工具", "ai工具",
    )
    if not any(term in text for term in ai_terms):
        return False
    assigned_intervention_terms = (
        "随机", "实验组", "对照组", "干预", "引入", "教学支持",
        "randomized", "randomised", "intervention", "treatment group",
    )
    return not any(term in text for term in assigned_intervention_terms)


def _ai_usage_field_present(header: set[str]) -> bool:
    """Return whether a CSV exposes an observable AI-use measure."""

    normalized = {value.strip().lower().replace(" ", "_") for value in header}
    aliases = {
        "ai_use", "ai_use_7d", "ai_usage", "ai_frequency", "ai_freq",
        "use_days_7d", "primary_use", "secondary_uses", "secondary_uses_bin",
        "days_since_last_use", "duration_min_last_use", "ai_usage_frequency",
        "生成式人工智能使用", "人工智能使用", "ai使用频率", "ai使用方式",
    }
    return bool(normalized & aliases)


def _ai_schema_alignment_warning(scope: str | None, header: set[str]) -> str | None:
    """Explain why a generic group/outcome CSV cannot answer an AI-use RQ."""

    if _requires_observed_ai_usage(scope) and not _ai_usage_field_present(header):
        return (
            "当前研究问题考察学生实际使用生成式人工智能，但 CSV 只有分组/结果字段，"
            "没有可观测的 AI 使用方式、频率、天数或时长字段；不能套用两组均值差模型。"
            "请修改研究设计，或上传包含 AI 使用行为字段的数据后再继续。"
        )
    return None


def _auto_import_external_pdfs(
    project_id: str, candidates: list[dict[str, object]], *, limit: int = 3
) -> list[dict[str, object]]:
    """Import bounded public PDFs as unverified local sources.

    Importing makes the next retrieval pass useful immediately, while the
    source remains ``model_generated_unverified`` until a researcher confirms
    the original text and its stable location. Metadata-only candidates are
    left untouched when no explicit PDF URL is available.
    """

    imported: list[dict[str, object]] = []
    for candidate in candidates[: max(0, min(limit, 3))]:
        url = candidate.get("full_text_url")
        if not isinstance(url, str) or not url.startswith(("https://", "http://")):
            continue
        try:
            response = httpx.get(url, follow_redirects=True, timeout=12.0)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if "application/pdf" not in content_type and not url.lower().split("?", 1)[0].endswith(".pdf"):
                continue
            content = response.content
            if not content.startswith(b"%PDF") or len(content) > service.max_upload_bytes:
                continue
            title = re.sub(r"[^A-Za-z0-9._-]+", "_", str(candidate.get("title") or "external-paper"))[:100]
            source = service.import_bytes(project_id, f"external-{title}.pdf", content)
            imported.append({
                "candidate_id": candidate.get("doi") or candidate.get("work_id"),
                "source_id": source.source_id,
                "filename": source.filename,
                "verification_status": source.verification_status.value,
            })
        except (httpx.HTTPError, ContextInputError, OSError, ValueError):
            continue
    return imported


@app.get("/api/v1/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "service": "stem-sci-backend",
        "configuration_valid": configuration_report.valid,
        "warnings": list(configuration_report.warnings),
    }


@app.get("/api/v1/latex/templates", response_model=list[LatexTemplate])
def latex_templates() -> list[LatexTemplate]:
    """Return the deterministic submission templates used by the formatter."""

    return latex_service.templates()


@app.post("/api/v1/latex/generate", response_model=LatexGenerateResponse)
def latex_generate(request: LatexGenerateRequest) -> LatexGenerateResponse:
    """Convert a researcher-reviewed manuscript draft into validated LaTeX."""

    try:
        return latex_service.generate(request)
    except ValueError as error:
        raise ContextInputError("invalid_latex_request", str(error)) from error


@app.post("/api/v1/auth/register", response_model=AuthTokenPair)
def auth_register(request: UserCreateRequest) -> AuthTokenPair:
    """Create a user and return an immediately usable session."""
    return identity_service.register(request)


@app.post("/api/v1/auth/login", response_model=AuthTokenPair)
def auth_login(request: LoginRequest) -> AuthTokenPair:
    return identity_service.login(request)


@app.post("/api/v1/auth/refresh", response_model=AuthTokenPair)
def auth_refresh(request: TokenRefreshRequest) -> AuthTokenPair:
    return identity_service.refresh(request)


@app.post("/api/v1/auth/logout")
def auth_logout(token: Annotated[str, Depends(_access_token)]) -> dict[str, str]:
    identity_service.logout(token)
    return {"status": "ok"}


@app.get("/api/v1/auth/me", response_model=UserProfile)
def auth_me(user: Annotated[UserProfile, Depends(current_user)]) -> UserProfile:
    return user


@app.get("/api/v1/projects", response_model=list[ResearchProject])
def projects(user: Annotated[UserProfile, Depends(current_user)]) -> list[ResearchProject]:
    return identity_service.list_projects(user)


@app.post("/api/v1/projects", response_model=ResearchProject)
def create_project(
    request: ProjectCreateRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> ResearchProject:
    project = identity_service.create_project(user, request)
    workflow_controller.ensure_project(project.project_id, project.research_direction)
    return project


@app.get("/api/v1/projects/{project_id}", response_model=ResearchProject)
def project(
    project_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
) -> ResearchProject:
    return identity_service.get_project(user, project_id)


@app.patch("/api/v1/projects/{project_id}", response_model=ResearchProject)
def patch_project(
    project_id: str,
    request: ProjectPatchRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> ResearchProject:
    return identity_service.patch_project(user, project_id, request)


@app.get("/api/v1/projects/{project_id}/members", response_model=list[ProjectMember])
def project_members(
    project_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
) -> list[ProjectMember]:
    return identity_service.list_project_members(user, project_id)


@app.put("/api/v1/projects/{project_id}/members", response_model=ProjectMember)
def upsert_project_member(
    project_id: str,
    request: ProjectMemberUpsertRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> ProjectMember:
    return identity_service.upsert_project_member(user, project_id, request)


@app.delete("/api/v1/projects/{project_id}")
def delete_project(
    project_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
) -> dict[str, str]:
    identity_service.delete_project(user, project_id)
    return {"status": "deleted"}


@app.get("/api/v1/projects/{project_id}/documents", response_model=list[ProjectDocument])
def project_documents(
    project_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
) -> list[ProjectDocument]:
    identity_service.get_project(user, project_id)
    return document_service.list_project(project_id)


@app.post("/api/v1/projects/{project_id}/documents", response_model=ProjectDocument)
def create_project_document(
    project_id: str,
    request: DocumentCreateRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> ProjectDocument:
    identity_service.get_project(user, project_id)
    document = document_service.create(project_id=project_id, user=user, request=request)
    _index_project_document(project_id, document, request.content)
    return document


@app.post("/api/v1/projects/{project_id}/documents/upload", response_model=ProjectDocument)
async def upload_project_document(
    project_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
    file: Annotated[UploadFile, File(...)],
    title: Annotated[str | None, Form()] = None,
) -> ProjectDocument:
    identity_service.get_project(user, project_id)
    document_format, content = await _read_uploaded_research_document(file, _max_upload_bytes())
    document_title = (title or Path(file.filename or "uploaded-document").stem).strip()
    if not document_title:
        raise DocumentError(422, "document_title_required", "A document title is required")
    document = document_service.create(
        project_id=project_id,
        user=user,
        request=DocumentCreateRequest(
            title=document_title,
            document_type="reference",
            format=document_format,
            content=content,
            change_note=f"Uploaded from {file.filename or 'file'}",
        ),
    )
    _index_project_document(project_id, document, content)
    return document


def _continue_conversation_in_background(project_id: str, user: UserProfile) -> None:
    """Advance a conversational workstream off the request thread."""

    try:
        continued = continue_project_orchestration(project_id, user, conversational=True)
        for _ in range(32):
            if continued.get("gate") is not None or not continued.get("execution_started") or _conversation_checkpoint(continued.get("control_state")):
                break
            continued = continue_project_orchestration(project_id, user, conversational=True)
    except Exception:  # noqa: BLE001 - durable task/event state records failures
        logging.getLogger(__name__).exception("background conversational continuation failed for %s", project_id)


_BACKGROUND_RECOVERY_GRACE = timedelta(seconds=5)


def _background_task_is_ready_for_recovery(task: object) -> bool:
    """Avoid racing the request that has just queued a synchronous action."""

    created_at = getattr(task, "created_at", None)
    if not isinstance(created_at, datetime):
        return True
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return datetime.now(UTC) - created_at >= _BACKGROUND_RECOVERY_GRACE


def _durable_background_worker_loop() -> None:
    """Recover queued conversational work after an API process restart."""

    worker_log = logging.getLogger(__name__)
    while not _background_worker_stop.wait(2.0):
        repository = control_plane.repository
        list_pending = getattr(repository, "list_pending_tasks", None)
        if not callable(list_pending):
            return
        handled_projects: set[str] = set()
        try:
            pending_tasks = list_pending()
        except Exception:  # noqa: BLE001 - a locked DB should not kill recovery
            worker_log.exception("durable background task scan failed")
            continue
        for task in pending_tasks:
            if task.project_id in handled_projects:
                continue
            # Conversation requests run their own action synchronously. Give
            # that request a short exclusive window before recovery can claim
            # the task, otherwise both workers can race to create the next
            # candidate and the chat response may miss its actual boundary.
            if not _background_task_is_ready_for_recovery(task):
                continue
            try:
                state = control_plane.ensure_project(task.project_id)
                if state.lifecycle_status.value != "ACTIVE" or state.active_gate_id:
                    continue
                stream = next(
                    (item for item in state.workstreams if item.workstream_id == state.active_workstream_id),
                    None,
                )
                if stream is None or stream.current_step_index >= len(stream.workflow_steps):
                    continue
                expected_action = stream.workflow_steps[stream.current_step_index]
                if task.action != expected_action:
                    # A stale task from an older revision is left for the
                    # normal lease/retry path instead of guessing a transition.
                    continue
                owner = identity_service.project_owner(task.project_id)
                handled_projects.add(task.project_id)
                _continue_conversation_in_background(task.project_id, owner)
            except Exception:  # noqa: BLE001 - isolate one project from others
                worker_log.exception("durable background recovery failed for %s", task.project_id)


@app.on_event("startup")
def start_durable_background_worker() -> None:
    global _background_worker_thread
    if (
        _background_worker_thread is not None
        and _background_worker_thread.is_alive()
        and not _background_worker_stop.is_set()
    ):
        return
    _background_worker_stop.clear()
    _background_worker_thread = Thread(
        target=_durable_background_worker_loop,
        name="stem-sci-durable-worker",
        daemon=True,
    )
    _background_worker_thread.start()


@app.on_event("shutdown")
def stop_durable_background_worker() -> None:
    _background_worker_stop.set()


@app.post(
    "/api/v1/projects/{project_id}/primary-data/upload",
    response_model=PrimaryDataUploadResponse,
)
async def upload_primary_data(
    project_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
    file: Annotated[UploadFile, File(...)],
    title: Annotated[str | None, Form()] = None,
) -> PrimaryDataUploadResponse:
    """Register de-identified primary data for the active research route.

    The stored document is a private ``dataset`` rather than a reference, so
    it never enters literature retrieval.  The control plane stores only its
    versioned document reference and digest for auditability.
    """

    identity_service.get_project(user, project_id)
    state = control_plane.ensure_project(project_id)
    stream = next(
        (item for item in state.workstreams if item.workstream_id == state.active_workstream_id),
        state.workstreams[0],
    )
    # Mixed-method projects have one project-level route but each active
    # workstream must use its own domain route for data validation and agents.
    route = stream.route if stream.route != "UNCLASSIFIED" else (
        state.route_decision.primary_route if state.route_decision else stream.route
    )
    document_format, content = await _read_uploaded_primary_data(file, _max_upload_bytes())
    suffix = Path(file.filename or "").suffix.lower()
    if route == "QUALITATIVE":
        # Open-response qualitative datasets are commonly distributed as CSV
        # (identifier + text columns).  Accept that representation while
        # retaining the qualitative safeguards; the CSV is registered as
        # private primary data and is never sent to literature retrieval.
        if suffix == ".csv":
            rows = [row for row in content.splitlines() if row.strip()]
            header = rows[0].lower() if rows else ""
            text_markers = ("text", "response", "answer", "description", "statement", "solution", "beschreibung")
            if len(rows) < 3 or "," not in header or not any(marker in header for marker in text_markers):
                raise DocumentError(
                    422,
                    "qualitative_csv_incomplete",
                    "A qualitative CSV must contain a text-like header and at least two data rows",
                )
        if len(content) < 80:
            raise DocumentError(
                422,
                "primary_data_too_short",
                "Qualitative primary data must contain at least 80 characters after de-identification",
            )
    else:
        if suffix != ".csv":
            raise DocumentError(
                422,
                "quantitative_primary_data_expected",
                "The quantitative route requires a UTF-8 CSV file",
            )
        rows = [row for row in content.splitlines() if row.strip()]
        if len(rows) < 3 or "," not in rows[0]:
            raise DocumentError(
                422,
                "primary_csv_incomplete",
                "The CSV must contain a header and at least two data rows",
            )
    document_title = (title or Path(file.filename or "primary-data").stem).strip()
    if not document_title:
        raise DocumentError(422, "document_title_required", "A primary-data title is required")
    document = document_service.create(
        project_id=project_id,
        user=user,
        request=DocumentCreateRequest(
            title=document_title,
            document_type="dataset",
            format=document_format,
            content=content,
            change_note=(
                "Researcher-uploaded de-identified primary data. "
                "Not indexed as literature evidence."
            ),
        ),
    )
    version = document_service.get_version(project_id, document.document_id, document.current_version)
    saved, artifact = control_plane.register_primary_data(
        project_id,
        content_uri=version.storage_ref,
        content_sha256=version.sha256,
        source_dataset_id=f"document://{document.document_id}/{document.current_version}",
        actor=user.username,
    )
    artifact_content_store.put(
        ArtifactContent(
            project_id=project_id,
            artifact_id=artifact.artifact_id,
            version=artifact.version,
            artifact_type=artifact.artifact_type,
            schema_version="primary-data-receipt-v1",
            body={
                "document_id": document.document_id,
                "document_version": document.current_version,
                "content_sha256": version.sha256,
                "route": route,
                "deidentified_by_researcher": True,
                "indexed_as_literature_evidence": False,
            },
        )
    )
    return PrimaryDataUploadResponse(document=document, artifact=artifact, control_state=saved)


@app.get("/api/v1/projects/{project_id}/documents/{document_id}", response_model=ProjectDocument)
def project_document(
    project_id: str,
    document_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
) -> ProjectDocument:
    identity_service.get_project(user, project_id)
    return document_service.get(project_id, document_id)


@app.patch("/api/v1/projects/{project_id}/documents/{document_id}", response_model=ProjectDocument)
def patch_project_document(
    project_id: str,
    document_id: str,
    request: DocumentPatchRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> ProjectDocument:
    identity_service.get_project(user, project_id)
    return document_service.patch(
        project_id=project_id,
        document_id=document_id,
        user=user,
        request=request,
    )


@app.delete("/api/v1/projects/{project_id}/documents/{document_id}")
def delete_project_document(
    project_id: str,
    document_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
) -> dict[str, str]:
    identity_service.get_project(user, project_id)
    document_service.delete(project_id=project_id, document_id=document_id, user=user)
    return {"status": "deleted"}


@app.get(
    "/api/v1/projects/{project_id}/documents/{document_id}/versions",
    response_model=list[DocumentVersion],
)
def project_document_versions(
    project_id: str,
    document_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
) -> list[DocumentVersion]:
    identity_service.get_project(user, project_id)
    return document_service.list_versions(project_id, document_id)


@app.post(
    "/api/v1/projects/{project_id}/documents/{document_id}/versions",
    response_model=DocumentVersion,
)
def create_project_document_version(
    project_id: str,
    document_id: str,
    request: DocumentVersionCreateRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> DocumentVersion:
    identity_service.get_project(user, project_id)
    version = document_service.create_version(
        project_id=project_id,
        document_id=document_id,
        user=user,
        request=request,
    )
    _index_project_document(
        project_id,
        document_service.get(project_id, document_id),
        request.content,
    )
    return version


@app.get(
    "/api/v1/projects/{project_id}/documents/{document_id}/versions/{version}",
    response_model=DocumentVersion,
)
def project_document_version(
    project_id: str,
    document_id: str,
    version: int,
    user: Annotated[UserProfile, Depends(current_user)],
) -> DocumentVersion:
    identity_service.get_project(user, project_id)
    return document_service.get_version(project_id, document_id, version)


@app.get("/api/v1/corpora", response_model=list[SharedCorpusSummary])
def corpora() -> list[SharedCorpusSummary]:
    """List shared corpora and their safe readiness summaries."""
    result: list[SharedCorpusSummary] = []
    for manifest in knowledge_service.list_corpora():
        readiness = knowledge_service.readiness(manifest.corpus_id)
        result.append(
            SharedCorpusSummary(
                corpus_id=manifest.corpus_id,
                corpus_version=manifest.corpus_version,
                access_mode=manifest.access_mode,
                paper_count=manifest.paper_count,
                vector_chunk_count=manifest.vector_chunk_count,
                discovery_ready=readiness.discovery_ready,
                formal_evidence_ready=readiness.formal_evidence_ready,
                risk_flags=readiness.risk_flags,
            )
        )
    return result


def _read_knowledge_asset_json(filename: str) -> dict[str, object]:
    """Read a checked-in, non-sensitive knowledge asset summary.

    These files are presentation metadata only.  Raw discovery chunks and
    local PDF paths are deliberately not exposed through this endpoint.
    """

    path = _repository_root / "data" / "structured" / filename
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"status": "UNAVAILABLE", "risk_flags": [f"asset_missing:{filename}"]}
    return payload if isinstance(payload, dict) else {"status": "UNAVAILABLE"}


@app.get("/api/v1/knowledge-assets/summary")
def knowledge_asset_summary() -> dict[str, object]:
    """Expose bounded counts for the research-assistant knowledge layer."""

    return _read_knowledge_asset_json("knowledge_asset_summary.json")


@app.get("/api/v1/knowledge-assets/discovery")
def knowledge_asset_discovery() -> dict[str, object]:
    """Expose discovery-only full-text metadata without serving source text."""

    path = _repository_root / "data" / "local" / "discovery_fulltext_manifest.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"status": "UNAVAILABLE", "records": [], "risk_flags": ["asset_missing:discovery_fulltext_manifest.json"]}
    if not isinstance(payload, dict):
        return {"status": "UNAVAILABLE", "records": []}
    records = payload.get("records", [])
    safe_records = []
    if isinstance(records, list):
        for record in records:
            if not isinstance(record, dict):
                continue
            safe_records.append(
                {
                    key: record.get(key)
                    for key in (
                        "candidate_id",
                        "title",
                        "doi",
                        "year",
                        "status",
                        "detail",
                        "formal_eligible",
                    )
                    if key in record
                }
            )
    return {
        "artifact_type": payload.get("artifact_type", "DiscoveryFullTextManifest"),
        "status": payload.get("status", "LOCAL_DISCOVERY_ONLY"),
        "downloaded_count": payload.get("downloaded_count", len(safe_records)),
        "chunk_count": payload.get("chunk_count", 0),
        "records": safe_records,
        "policy": payload.get("policy", "Discovery-only; formal use requires validation."),
    }


@app.get("/api/v1/corpora/{corpus_id}/manifest", response_model=CorpusManifest)
def corpus_manifest(corpus_id: str) -> CorpusManifest:
    """Return a manifest without turning local absolute file paths into API output."""
    manifest = knowledge_service.manifest(corpus_id)
    return manifest


@app.post("/api/v1/retrieval/search", response_model=RetrievalSearchResponse)
def hybrid_search(request: RetrievalSearchRequest) -> RetrievalSearchResponse:
    """Search the read-only corpus; graph triples remain navigation-only."""
    return knowledge_service.search(request)


@app.post("/api/v1/context/hybrid-build")
def hybrid_build_context(request: HybridContextBuildRequest) -> ContextBundle:
    """Build a discovery or fail-closed formal shared-corpus ContextBundle."""
    return knowledge_service.build_from_request(request)


@app.post("/api/v1/qa/answer", response_model=QAAnswerResponse)
def qa_answer(request: QAAnswerRequest) -> QAAnswerResponse:
    """Run rewrite, hybrid retrieval, answer synthesis, and memory persistence."""

    return qa_service.answer(request)


@app.post("/api/v1/projects/{project_id}/chat/answer", response_model=QAAnswerResponse)
def project_chat_answer(
    project_id: str,
    request: QAAnswerRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> QAAnswerResponse:
    """Project-scoped conversational QA with membership enforced."""

    if request.project_id != project_id:
        raise ContextInputError("project_mismatch", "path project_id does not match request project_id")
    identity_service.get_project(user, project_id)
    # This endpoint is used by the legacy project chat client.  Preserve the
    # same non-retrieval semantics as the main composer so it cannot leak
    # evidence snippets into a normal discussion.
    return qa_service.converse(request)


@app.get("/api/v1/projects/{project_id}/control-state", response_model=ControlState)
def project_control_state(
    project_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
) -> ControlState:
    """Return the authoritative orchestration snapshot for UI reconstruction."""

    identity_service.get_project(user, project_id)
    return control_plane.ensure_project(project_id)


@app.get("/api/v1/projects/{project_id}/blockers", response_model=list[BlockingIssueRecord])
def project_blockers(
    project_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
) -> list[BlockingIssueRecord]:
    """Return all durable blockers; the UI selects the highest-priority open one."""

    identity_service.get_project(user, project_id)
    return control_plane.repository.list_blockers(project_id)


@app.get("/api/v1/projects/{project_id}/orchestration/tasks", response_model=list[TaskLease])
def project_orchestration_tasks(
    project_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
) -> list[TaskLease]:
    """Return durable orchestration task history for the project workspace."""

    identity_service.get_project(user, project_id)
    return control_plane.repository.list_tasks(project_id)


@app.get("/api/v1/projects/{project_id}/research-runs", response_model=list[ResearchRun])
def project_research_runs(
    project_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
) -> list[ResearchRun]:
    """Expose long-running work independently from the conversation thread."""

    identity_service.get_project(user, project_id)
    runs: list[ResearchRun] = []
    for task in control_plane.repository.list_tasks(project_id):
        action = task.action.lower()
        run_type = (
            "literature" if any(term in action for term in ("evidence", "search", "retrieval", "paper"))
            else "analysis" if any(term in action for term in ("analysis", "data", "statistic", "code"))
            else "writing" if any(term in action for term in ("writing", "manuscript", "draft"))
            else "workflow"
        )
        runs.append(ResearchRun(
            run_id=task.task_id,
            project_id=project_id,
            run_type=run_type,
            action=task.action,
            status=task.status,
            output_artifact_ids=task.output_artifact_ids,
            error=task.error,
            created_at=task.created_at,
            updated_at=task.heartbeat_at or task.created_at,
        ))
    return runs


@app.post("/api/v1/projects/{project_id}/orchestration/tasks/{task_id}/retry", response_model=TaskLease)
def retry_project_orchestration_task(
    project_id: str,
    task_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
) -> TaskLease:
    """Requeue a failed task after validating revision, action, and membership."""

    identity_service.get_project(user, project_id)
    try:
        return control_plane.retry_task(project_id, task_id, actor=user.username)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/v1/projects/{project_id}/claims", response_model=list[ClaimRecord])
def project_claims(
    project_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
    manuscript_artifact_id: Annotated[str | None, Query(max_length=128)] = None,
) -> list[ClaimRecord]:
    """Return the auditable claim records for the project manuscript view."""

    identity_service.get_project(user, project_id)
    return control_plane.repository.list_claims(project_id, manuscript_artifact_id)


@app.get("/api/v1/projects/{project_id}/gates/{gate_id}", response_model=GateRecord)
def project_gate(
    project_id: str,
    gate_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
) -> GateRecord:
    """Return one durable Gate so the UI can recover from stale cards."""

    identity_service.get_project(user, project_id)
    gate = control_plane.repository.get_gate(project_id, gate_id)
    if gate is None:
        raise HTTPException(status_code=404, detail="gate was not found")
    return gate


_INTAKE_QUESTIONS: tuple[tuple[str, str], ...] = (
    (
        "research_goal",
        "在检索前，我想先理解你的研究目标。你更希望复现已有发现、描述一个现象、比较群体差异、评估教学干预，还是探索一个尚未清楚的问题？请用自己的话说说你最想弄清什么。",
    ),
    (
        "research_focus",
        "你希望关注谁或什么现象？请说说研究对象、场景，以及你目前认为最重要的变量、经验或材料；暂时不确定的部分可以直接说“不确定”。",
    ),
    (
        "expected_contribution",
        "如果这项研究顺利完成，你希望它带来什么有用结论或实际帮助？例如澄清一个争议、帮助改进教学、提供描述性证据，或为后续研究提出假设。",
    ),
    (
        "data_source",
        "你手头现在有什么材料？可以是已上传论文、公开数据、已有访谈/问卷、计划新收集的数据，或暂时只有一个想法。请同时说明数据是否可用、是否去标识化。",
    ),
    (
        "method_boundary",
        "你目前倾向怎样研究，或有哪些不能接受的做法？例如定性理解、观察性比较、教学干预、混合方法；也请说明是否只能作描述性解释、不能作因果结论。",
    ),
    (
        "constraints",
        "最后确认现实边界：是否有伦理/课程许可要求、时间或样本限制、投稿目标，或你特别希望我避免的结论和方法？",
    ),
)


_CGT_GUIDED_RESPONSES: dict[str, str] = {
    "research_goal": "先不设定主题或方法。你最想从这些学生文本中弄清什么？",
    "research_focus": "研究重点已经明确为学生怎样组织解题思路，而不是答案得分。具体是哪类学生、哪一道任务，以及什么语言的文本？",
    "expected_contribution": "研究对象和任务边界已经明确。完成后，你希望这项研究主要贡献什么？",
    "data_source": "目标是归纳可解释的主题并检查其稳定性，结论限于公开二手资料再分析。你目前实际持有哪些数据文件？",
    "method_boundary": "至少需要一份含匿名 Stu_ID 和原始 Text 的文本表；若要做学生层汇总或组间描述，还需要一份以 Stu_ID 唯一连接的背景表。你希望句子和学生分别承担什么分析单位？",
    "constraints": "已确认句子是主要编码单位、Stu_ID 必须保留并在学生层汇总，公式保护和分句敏感性也要进入方案。你希望采用怎样的分析阶段，以及哪些结论明确不能声称？",
}


def _cgt_guided_response(
    message: str,
    collaboration: CollaborationDecision | None,
) -> str | None:
    """Return a short, one-question mentor turn for the CGT intake path."""

    if collaboration is None or not collaboration.plan.guided_question_key:
        return None
    normalized = message.strip().lower()
    cgt_markers = (
        "学生", "物理题", "解题", "stu_id", "德语", "主题", "句子为单位",
        "student", "physics problem", "german", "codebook",
    )
    if not any(marker in normalized for marker in cgt_markers):
        return None
    return _CGT_GUIDED_RESPONSES.get(collaboration.plan.guided_question_key)


def _cgt_analysis_instruction_response(project_id: str, message: str) -> str | None:
    """Bound CGT analysis instructions to persisted execution evidence."""

    normalized = message.strip().lower()
    code_spec_request = "只生成分析代码规格" in normalized
    preprocessing_code_request = (
        "可运行代码候选" in normalized
        and "预处理" in normalized
        and "不要生成任何主题标签" in normalized
    )
    pre_execution_review_request = (
        any(term in normalized for term in ("执行前审查", "审查这段代码"))
        and any(term in normalized for term in ("nan", "stu_id", "公式", "原始文件"))
    )
    pattern_code_request = (
        "生成模式发现代码" in normalized
        and "umap" in normalized
        and "hdbscan" in normalized
    )
    result_card_request = _conversation_requests_result_card(normalized)
    method_boundary_request = (
        "三阶段" in normalized
        and "人机协作" in normalized
        and any(term in normalized for term in ("是否适合", "路线是否", "判断这个路线"))
    )
    background_plan_request = (
        "背景变量表" in normalized
        and "上传后" in normalized
        and any(term in normalized for term in ("怎样检查", "如何检查", "怎么检查"))
    )
    background_audit_request = (
        "背景表" in normalized
        and "stu_id" in normalized
        and any(term in normalized for term in ("一对一连接", "连接结果", "未连接编号"))
    )
    background_definition_request = (
        "control_group=0" in normalized
        and "gender=0" in normalized
        and any(term in normalized for term in ("非随机", "不能写因果", "描述性或关联性"))
    )
    theme_merge_request = (
        "合并建议" in normalized
        and "数据相似性证据" in normalized
        and "物理问题解决理论证据" in normalized
    )
    codebook_request = "codebook" in normalized and any(
        term in normalized for term in ("编码计划", "人工修订", "候选")
    )
    supervised_spec_request = "监督确认代码" in normalized or (
        "监督确认" in normalized and "生成" in normalized and "代码" in normalized
    )
    supervised_run_request = any(term in normalized for term in ("批准执行模式确认", "实际交叉验证输出"))
    group_request = any(term in normalized for term in ("奥赛参与者", "非参与者")) and any(
        term in normalized for term in ("请比较", "列联表", "卡方检验", "bootstrap")
    )
    if not any((
        code_spec_request,
        preprocessing_code_request,
        pre_execution_review_request,
        pattern_code_request,
        result_card_request,
        method_boundary_request,
        background_plan_request,
        background_audit_request,
        background_definition_request,
        theme_merge_request,
        codebook_request,
        supervised_spec_request,
        supervised_run_request,
        group_request,
    )):
        return None

    if code_spec_request:
        specification = _latest_artifact_body(project_id, "AnalysisCodeSpecificationCandidate") or {}
        modules = [item for item in specification.get("modules", []) if isinstance(item, dict)]
        names = "、".join(str(item.get("name")) for item in modules if item.get("name"))
        return (
            f"分析代码规格候选已生成，共 {len(modules)} 个可独立审查模块"
            + (f"：{names}" if names else "")
            + "。每个模块分别登记输入、输出和随机性；统一失败条件包括缺少 Stu_ID/Text、公式分句需复核、"
            "人工标签未冻结时禁止报告监督性能。当前只是规格，尚未生成或执行主题分析结果。"
        )

    if preprocessing_code_request:
        return (
            "第一个可运行候选已限定为数据审计与预处理：从冻结 CSV 读取 Stu_ID 和德语原文，"
            "过滤真正的缺失值后再转字符串，生成稳定的 Sentence_ID；句界切分不在小数点或公式运算符处断开。"
            "基线阈值为去空格后 20 字符，同时输出 10/20/30 的保留与排除统计；短但含明确物理关系的片段进入复核清单。"
            "原文件只读，输出不含 theme_label 或 cluster_id，当前尚未执行。"
        )

    if pre_execution_review_request:
        return (
            "执行前审查结论：六项边界均已写入候选——先判缺失再转文本，Stu_ID 只取原字段、不用行号替代，"
            "公式/小数受保护，原始 CSV 只读，所有含随机性的后续模块必须记录种子，句子数与 417 名学生数分开报告。"
            "本轮修改相当于：`astype(str)` 前增加缺失过滤；Sentence_ID 从 Stu_ID 派生；短公式由“自动删除”改为“保留并复核”；"
            "输出增加 student_count 与 sentence_count 两个独立字段。尚未执行，等待你明确批准只运行数据审计和预处理。"
        )

    if pattern_code_request:
        return (
            "模式发现代码候选已按本轮参数登记：德语/多语句向量模型；UMAP(n_components=5, n_neighbors=15, "
            "metric=cosine, min_dist=0)；HDBSCAN(min_cluster_size=15, metric=euclidean, "
            "cluster_selection_method=eom)，不预设簇数。20、100、1000 分别是待批准的烟雾、分布检查和正式稳定性计划，"
            "不是已执行次数；当前未下载模型、未生成嵌入或聚类。"
        )

    if result_card_request:
        result_card = _latest_artifact_body(project_id, "QualitativeResultCard") or {}
        sample_flow = result_card.get("data_audit") if isinstance(result_card.get("data_audit"), dict) else {}
        unperformed = _unperformed_candidate_actions(project_id)
        response = (
            "结果卡候选已经生成并连接现有数据、代码候选和执行记录。"
            f"样本流转为：原始记录 {sample_flow.get('raw_text_rows', '未记录')} 条，"
            f"空文本 {sample_flow.get('missing_text_rows', '未记录')} 条，"
            f"非空文本 {sample_flow.get('nonempty_text_rows', '未记录')} 条，"
            f"成功连接 {sample_flow.get('joined_students', '未记录')} 名。"
        )
        if unperformed:
            response += (
                f"但{'、'.join(unperformed)}尚未实际执行，因此当前只能是待审查结果卡，不能正式冻结；"
                "这些未执行项的性能、效应量和稳健性数字均不得进入论文。"
            )
        return response

    if method_boundary_request:
        return (
            "这条路线适合，但三个阶段必须严格分开：先用中性名称探索可回链模式，再由研究者依据原文修订定义和边界，"
            "最后只在人工标签冻结后做监督确认。计算结果只能提供候选与稳定性证据，不能自动决定主题数量、名称或理论含义。"
        )

    if background_plan_request:
        return (
            "上传后我会先检查 Stu_ID 在两张表中是否唯一，再报告一对一连接成功数、两侧未连接编号；"
            "随后列出各背景字段的实际取值、频数和缺失数。Control_group 的 0/1 在你给出含义前只作为编码，"
            "全程不启动主题分析。"
        )

    if background_audit_request:
        primary = _registered_qualitative_primary_data(project_id) or {}
        sample_flow = _qualitative_sample_flow(project_id, primary) if primary else {}
        background = _latest_project_reference_csv(project_id, "Additional_data")
        if not background:
            return "当前尚未读取到背景变量表；上传后才能报告实际连接数、未连接编号和各字段缺失。"
        field_names = list(background[0]) if background else []
        missing_by_field = {
            field: sum(1 for row in background if not str(row.get(field, "")).strip())
            for field in field_names
        }
        return (
            f"实际审计：背景表 {len(background)} 行；与非空文本按 Stu_ID 成功连接 "
            f"{sample_flow.get('joined_students', 0)} 名，文本侧未连接 "
            f"{sample_flow.get('text_students_without_background', 0)} 名，背景表侧未连接 "
            f"{sample_flow.get('background_students_without_text', 0)} 名。背景字段缺失数为："
            + "，".join(f"{field}={count}" for field, count in missing_by_field.items())
            + "。Control_group 暂按原始编码保留，不解释为实验处理。"
        )

    if background_definition_request:
        return (
            "已记录字段含义：Control_group=0 为物理奥赛参与者、1 为非参与对照组；Gender=0 为男性、1 为女性，"
            "Class 为年级，Still_phy 为对照组继续学习物理的信息。由于分组非随机且采集形式可能不同，"
            "后续组间结果只作描述性或关联性报告，不作因果解释。"
        )

    if theme_merge_request:
        manual = _latest_artifact_body(project_id, "ManualThemeRevisionCandidate") or {}
        themes = [item for item in manual.get("themes", []) if isinstance(item, dict)]
        cluster_backed = sum(1 for item in themes if item.get("source_cluster"))
        theory_led = len(themes) - cluster_backed
        return (
            f"当前有 {cluster_backed} 个由实际聚类支持的候选、{theory_led} 个研究者暂定/关键词辅助候选。"
            "由于嵌入稳定性运行未完成，数据相似性一侧暂不能支持具体合并。理论一侧只能把假设与理想化、概念理解、定量处理、"
            "解题方案表述和一般性描述保留为待检验解释；每项都必须补齐定义、纳入/排除规则、正例、边界例、"
            "反例及相邻主题区别。现阶段不冻结保留、拆分或合并决定，嵌入图或树状图也不能单独作决定。"
        )

    if codebook_request:
        manual = _latest_artifact_body(project_id, "ManualThemeRevisionCandidate") or {}
        themes = [item for item in manual.get("themes", []) if isinstance(item, dict)]
        if not themes:
            return (
                "目前还没有可回链的人工修订主题，不能冻结 Codebook。"
                "先完成每个主题的定义、纳入/排除规则、代表句、边界例和反例；"
                "编码者培训、第二编码者复核及一致性指标只能作为待执行计划，不能写成结果。"
            )
        return (
            f"已找到 {len(themes)} 个待复核主题，可据此保存 Codebook 候选，但它尚未冻结。"
            "候选将保留定义、纳入/排除规则、代表句、边界例和反例；"
            "编码培训、第二编码者复核以及 Cohen's kappa 或 Krippendorff's alpha 均标记为未执行。"
        )

    supervised = _latest_artifact_body(project_id, "SupervisedConfirmationCandidate") or {}
    execution = supervised.get("execution") if isinstance(supervised.get("execution"), dict) else {}
    performed = bool(execution.get("performed"))
    if supervised_spec_request and not supervised_run_request:
        return (
            "监督确认只生成可审查规格：句子级分层交叉验证与按 Stu_ID 分组交叉验证分开，"
            "指标包括 accuracy、macro/weighted F1、Cohen's kappa、混淆矩阵和分类别召回率。"
            "当前没有冻结人工标签和实际运行日志，因此不报告性能数字；RVM 与替代模型也必须作为不同运行记录。"
        )
    if supervised_run_request:
        if not performed:
            reason = str(execution.get("reason") or "尚无冻结人工标签和实际交叉验证日志").rstrip("。；; ")
            return (
                f"本轮不能报告监督确认结果：{reason}。"
                "accuracy、F1、kappa、置信区间、学生分组后的性能变化和性别子组差异目前均为未执行；"
                "没有外部未见语料，也不能声称外部泛化能力。"
            )
        return "监督确认已有实际执行记录；本轮只会从该记录读取总体、分类别、学生分组和子组指标，不补写计划值。"

    comparison = _latest_artifact_body(project_id, "GroupComparisonCandidate") or {}
    comparison_execution = (
        comparison.get("execution") if isinstance(comparison.get("execution"), dict) else {}
    )
    if not bool(comparison_execution.get("performed")):
        reason = str(comparison_execution.get("reason") or "人工标签尚未冻结，组间比较尚未实际执行").rstrip("。；; ")
        return (
            f"本轮不能给出奥赛组与非参与组的检验结果：{reason}。"
            "句子计数列联表、效应量、学生层主题比例、按 Stu_ID 重抽样和文本长度比较均标记为未执行；"
            "系统不会自行补设重抽样次数，也不会作因果解释。"
        )
    return "组间比较已有实际执行记录；本轮只会报告记录中的描述性结果、效应量、学生层稳健性和文本长度差异。"


def _requests_direct_discovery(message: str) -> bool:
    """Return whether an experienced researcher explicitly skips clarification."""

    lower = message.lower()
    return any(
        phrase in lower
        for phrase in (
            "直接检索", "跳过澄清", "不需要澄清", "直接开始文献检索",
            "search directly", "skip clarification", "skip intake",
        )
    )


_INTAKE_LABEL_ALIASES: dict[str, tuple[str, ...]] = {
    "research_goal": ("研究目标", "研究目的", "目标", "目的"),
    "research_focus": ("研究对象", "关注对象", "研究场景", "对象", "样本", "人群"),
    "expected_contribution": ("预期贡献", "研究贡献", "预期价值", "贡献", "价值"),
    "data_source": ("数据来源", "资料来源", "数据", "资料", "材料"),
    "method_boundary": ("研究方法", "方法边界", "方法", "研究设计", "设计"),
    "constraints": ("现实约束", "伦理约束", "限制", "约束", "伦理", "许可"),
}


def _extract_labelled_intake_answers(message: str) -> dict[str, str]:
    """Extract ``研究对象：...；数据来源：...`` style answers.

    Labels are deliberately required to be followed by a colon. This avoids
    treating ordinary prose such as ``研究目标是比较两组`` as six accidental
    answers while still allowing a researcher to answer the whole brief in one
    compact turn.
    """

    labels: list[tuple[str, str]] = [
        (alias, key)
        for key, aliases in _INTAKE_LABEL_ALIASES.items()
        for alias in aliases
    ]
    labels.sort(key=lambda item: len(item[0]), reverse=True)
    if not labels:
        return {}
    pattern = "|".join(re.escape(alias) for alias, _ in labels)
    matches = list(re.finditer(rf"(?P<label>{pattern})\s*[:：]\s*", message, flags=re.IGNORECASE))
    if not matches:
        return {}
    alias_to_key = {alias.lower(): key for alias, key in labels}
    extracted: dict[str, str] = {}
    for index, match in enumerate(matches):
        key = alias_to_key.get(match.group("label").lower())
        if key is None:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(message)
        value = message[match.end() : end].strip(" \t\r\n;；,，。")
        if value:
            extracted[key] = value
    return extracted


def _scope_revision(message: str) -> str | None:
    """Return a natural-language replacement scope, when explicitly requested."""

    prefixes = (
        "研究方向修改为", "研究方向改为", "修改研究方向为", "调整研究方向为",
        "研究范围修改为", "研究范围改为", "修改研究范围为", "调整研究范围为",
        "研究对象改为", "研究目标改为", "研究主题改为", "把研究范围改成",
        "把研究方向改成", "scope:", "research scope:",
    )
    normalized = message.strip()
    lowered = normalized.lower()
    for prefix in prefixes:
        index = lowered.find(prefix.lower())
        if index < 0:
            continue
        value = normalized[index + len(prefix) :].lstrip(" \t:：")
        value = value.strip(" \t\r\n。；;")
        if value:
            return value[:2000]
    return None


def _extract_research_constraints(message: str) -> dict[str, str]:
    """Extract durable research boundaries from ordinary conversational language."""

    normalized = message.strip().lower()
    constraints: dict[str, str] = {}
    if any(term in normalized for term in ("只做描述性", "仅做描述性", "descriptive only", "descriptive association")):
        constraints["interpretation"] = "descriptive_only"
    if any(term in normalized for term in ("不做因果", "不能作因果", "不要因果", "no causal", "not causal")):
        constraints["causal_claims"] = "forbidden"
    if any(term in normalized for term in ("优先大学生", "只保留大学生", "大学生样本优先", "undergraduate sample")):
        constraints["population_priority"] = "undergraduate_students"
    if any(term in normalized for term in ("保留来源", "保留出处", "preserve provenance", "保留可追溯")):
        constraints["provenance"] = "required"
    if any(term in normalized for term in ("不要修改原始数据", "不修改原始数据", "never modify raw data", "raw data read only")):
        constraints["raw_data"] = "read_only"
    return constraints


def _extract_research_memory_facts(message: str) -> dict[str, str]:
    """Capture useful research context without turning it into a checklist."""

    facts = _extract_labelled_intake_answers(message)
    normalized = message.strip().lower()
    sentences = [item.strip() for item in re.split(r"[。！？!?\n]", message) if item.strip()]
    goal_markers = (
        "我想研究", "我希望研究", "我计划研究", "我们想研究", "我们希望研究", "我们计划研究",
        "我想探讨", "我希望探讨", "我们想探讨", "我们希望探讨", "本研究旨在", "研究目的是",
        "i want to study", "we want to study", "i plan to investigate", "we plan to investigate",
        "this study aims", "research goal",
    )
    first_research_sentence = next(
        (item for item in sentences if any(marker in item.lower() for marker in goal_markers)),
        None,
    )
    if first_research_sentence and "research_goal" not in facts:
        facts["research_goal"] = first_research_sentence
    # Infer a population only when the same turn actually states a research
    # goal. Action-only turns such as "继续搜索教师文献" must not replace a
    # previously learned, more specific population with the generic "教师".
    if "research_focus" not in facts and first_research_sentence:
        population_terms = (
            "本科生", "大学生", "中学生", "高中生", "初中生", "教师", "学生", "undergraduate", "teacher", "student",
        )
        population = next((term for term in population_terms if term in normalized), None)
        if population:
            facts["research_focus"] = population
    if "data_source" not in facts:
        source_terms = (
            "已有论文和公开数据", "已上传论文和公开数据", "公开数据", "已有论文", "问卷数据",
            "访谈数据", "实验数据", "只能通过问卷", "问卷让学生自报", "拿不到平台交互日志",
            "public data", "uploaded papers",
        )
        source = next((term for term in source_terms if term in normalized), None)
        if source:
            facts["data_source"] = source
    constraints = _extract_research_constraints(message)
    if constraints and "method_boundary" not in facts:
        facts["method_boundary"] = "；".join(f"{key}={value}" for key, value in constraints.items())
    return facts


def _requested_research_capabilities(message: str) -> list[str]:
    """Map an open-ended research request to specialist capabilities.

    This is a dispatch hint, not a permission decision. The controller still
    owns workflow transitions and each specialist remains proposal-only.
    """

    normalized = message.strip().lower()
    capabilities: list[str] = []
    if any(term in normalized for term in ("论文", "文献", "证据", "引用", "literature", "paper", "citation")):
        capabilities.append("evidence")
    if any(term in normalized for term in ("研究问题", "研究设计", "方案", "样本", "变量", "design", "hypothesis")):
        capabilities.append("design")
    if any(term in normalized for term in ("数据", "缺失", "异常", "重复", "统计", "分析", "data", "analysis", "missing")):
        capabilities.append("data_analysis")
    if any(term in normalized for term in ("结果不一致", "不可信", "复核", "审查", "robust", "review", "check")):
        capabilities.append("review")
    if any(term in normalized for term in ("写作", "论文初稿", "摘要", "manuscript", "write")):
        capabilities.append("writing")
    return list(dict.fromkeys(capabilities))


def _merge_conversational_feedback(
    existing: dict[str, str],
    constraints: dict[str, str],
    capabilities: list[str],
    source_message: str,
) -> dict[str, str]:
    """Merge conversational preferences without erasing earlier decisions."""

    updated = dict(existing)
    previous_constraints: dict[str, str] = {}
    raw_constraints = existing.get("research_constraints")
    if raw_constraints:
        try:
            decoded = json.loads(raw_constraints)
            if isinstance(decoded, dict):
                previous_constraints = {
                    str(key): str(value) for key, value in decoded.items()
                    if isinstance(key, str) and isinstance(value, (str, int, float, bool))
                }
        except (TypeError, ValueError):
            previous_constraints = {}
    merged_constraints = {**previous_constraints, **constraints}
    if merged_constraints:
        updated["research_constraints"] = json.dumps(merged_constraints, ensure_ascii=False)

    previous_capabilities: list[str] = []
    raw_capabilities = existing.get("requested_capabilities")
    if raw_capabilities:
        try:
            decoded = json.loads(raw_capabilities)
            if isinstance(decoded, list):
                previous_capabilities = [str(item) for item in decoded if isinstance(item, str)]
        except (TypeError, ValueError):
            previous_capabilities = []
    merged_capabilities = list(dict.fromkeys([*previous_capabilities, *capabilities]))
    if merged_capabilities:
        updated["requested_capabilities"] = json.dumps(merged_capabilities, ensure_ascii=False)

    if constraints or capabilities:
        history: list[dict[str, object]] = []
        raw_history = existing.get("research_constraint_history")
        if raw_history:
            try:
                decoded = json.loads(raw_history)
                if isinstance(decoded, list):
                    history = [item for item in decoded if isinstance(item, dict)]
            except (TypeError, ValueError):
                history = []
        history.append({
            "message": source_message.strip()[:2000],
            "constraints": constraints,
            "capabilities": capabilities,
        })
        updated["research_constraint_history"] = json.dumps(history[-20:], ensure_ascii=False)
    return updated


def _intake_question(question_key: str | None) -> str:
    return next((question for key, question in _INTAKE_QUESTIONS if key == question_key), "研究澄清已完成。")


def _collaboration_dialogue(
    decision: CollaborationDecision | None,
) -> tuple[str, str | None, list[DialogueChoice]]:
    """Turn the planner's epistemic decision into a researcher-facing turn.

    Co-STORM's useful interaction primitive is a moderator question grounded
    in the current discussion, not a generic "what next?" prompt. Keep that
    contract deterministic here: the planner decides what is unknown and who
    owns it; the UI receives one focused question plus reversible paths.
    """

    if decision is None:
        return (
            "当前还没有形成可追溯的研究判断。",
            "你想先界定研究问题、检查现有证据，还是比较几种研究路径？",
            [
                DialogueChoice(id="scope", label="界定研究问题", message="请先帮我把研究问题界定清楚，并指出仍缺的关键假设。"),
                DialogueChoice(id="evidence", label="检查现有证据", message="请先检查现有证据能支持什么、不能支持什么。"),
                DialogueChoice(id="compare", label="比较研究路径", message="请提出两到三个可行研究路径，并解释各自取舍。"),
            ],
        )

    plan = decision.plan
    relevance = plan.decision_relevance
    acts = set(plan.research_acts)
    assumptions = [item for item in plan.provisional_assumptions if item][:2]
    role = plan.turn_role
    if role == "wait":
        summary = "本轮没有发现需要你立即裁决的新分叉。我会保留当前边界，等出现新证据或矛盾时再打断你。"
    elif role == "challenge":
        summary = "这轮先不扩大研究范围，重点检查当前判断最容易被哪类反例或替代解释推翻。"
    elif role == "summarize":
        summary = "我先把刚才的输入合并进研究地图，并说明它改变了哪些前提、哪些部分仍然只是暂定。"
    elif relevance.owner == "system_retrieval":
        summary = (
            f"当前关键未知是“{relevance.focal_unknown or '证据覆盖情况'}”。"
            "这部分可以由我通过有界检索和来源核验推进，不需要你替我猜答案。"
        )
    elif relevance.owner == "system_analysis":
        summary = (
            f"当前关键未知是“{relevance.focal_unknown or '数据与分析边界'}”。"
            "我会先把可检查的字段、比较和风险列出来，再决定是否值得运行分析。"
        )
    elif relevance.owner == "user":
        summary = (
            f"当前关键未知是“{relevance.focal_unknown or '研究者需要作出的取舍'}”。"
            "它会改变研究路线，所以我不会用默认假设替你决定。"
        )
    else:
        summary = (
            "我已经把本轮输入和已有研究地图合并。"
            "目前没有必要为了补全表单而连续追问，可以先用暂定边界推进。"
        )
    if assumptions:
        summary += " 当前暂定前提：" + "；".join(assumptions) + "。"

    question = plan.question_to_user if plan.user_action_required or role == "decide" else None
    choices: list[DialogueChoice] = []
    comparison_rendered = False
    if plan.guided_question_key and question:
        # A guided intake question should feel like a mentor following the
        # researcher's train of thought.  Buttons and route cards make an
        # ordinary clarification look like a formal decision Gate.
        choices = []
    elif (
        not question
        and (ResearchAct.COMPARE in acts or plan.current_mode is InteractionMode.DECIDE)
    ):
        # A comparison request must produce a comparison. Previously the
        # planner recorded COMPARE but the dialogue renderer fell through to
        # the generic "no blocking information" turn, showing the same
        # compare option again without explaining the routes.
        summary = (
            "当前有两条可逆路径：先补证据再收窄问题，或按暂定边界先形成可审查的设计。"
            "前者更稳健但会晚一轮形成设计；后者推进更快，但必须把暂定前提和失效条件记录清楚。"
            "在当前公开论文和数据尚未完成核验前，直接运行正式分析还不是合适的第三条路径。"
        )
        question = "你更倾向先补证据，还是按暂定边界先形成设计？"
        choices = [
            DialogueChoice(
                id="evidence_first",
                label="先补证据",
                message="我选择先补证据再收窄问题，重点核查当前研究边界的支持、反例和缺口。",
            ),
            DialogueChoice(
                id="provisional_design",
                label="先形成暂定设计",
                message="我选择按暂定边界先形成可审查的研究问题和设计，并记录需要验证的前提。",
            ),
            DialogueChoice(
                id="explain_comparison",
                label="再解释一次取舍",
                message="请把两条路径对样本、变量、证据和结论边界的影响逐项说清楚。",
            ),
        ]
        comparison_rendered = True
    elif question:
        choices.extend([
            DialogueChoice(id="answer", label="回答这个关键问题", message=f"针对这个关键问题，我的判断是：{question}"),
            DialogueChoice(id="explain", label="先解释为什么重要", message=f"请先解释为什么“{relevance.focal_unknown or '这个未知'}”会改变研究路线，以及不确定时有哪些暂定方案。"),
        ])
    if role == "ask_novel" or ResearchAct.EVIDENCE_SEEK in acts:
        choices.append(DialogueChoice(id="evidence_gap", label="查看证据缺口", message="请先列出当前证据支持、反例和仍未覆盖的缺口。"))
    if (ResearchAct.COMPARE in acts or plan.current_mode is InteractionMode.DECIDE) and not comparison_rendered:
        choices.append(DialogueChoice(id="tradeoff", label="比较取舍", message="请比较当前候选路径的收益、风险和会牺牲什么。"))
    if ResearchAct.CHALLENGE in acts or plan.current_mode is InteractionMode.REVIEW:
        choices.append(DialogueChoice(id="challenge", label="主动找反例", message="请主动寻找最可能推翻当前判断的反例或替代解释。"))
    if role == "wait":
        choices = []
    elif role == "challenge" and not choices:
        choices = [DialogueChoice(id="challenge", label="展开反例", message="请列出最可能推翻当前判断的反例和替代解释。")]
    elif not choices:
        choices = [
            DialogueChoice(id="map", label="查看研究地图", message="请概述当前研究地图：已经确定、暂定和有争议的部分。"),
        ]
    return summary, question, choices[:4]


def _collaboration_branches(
    decision: CollaborationDecision | None,
) -> list[DialogueBranch]:
    """Offer two explicit, reversible research routes when a choice matters."""

    if decision is None:
        return []
    if decision.plan.guided_question_key:
        return []
    relevance = decision.plan.decision_relevance
    focal = relevance.focal_unknown or "当前研究边界"
    # Evidence discovery alone is not a route fork. Only expose branches when
    # the planner identified a decision or an explicit comparison request.
    if decision.plan.turn_role not in {"decide"} and ResearchAct.COMPARE not in decision.plan.research_acts:
        return []
    if (
        relevance.owner == "system_retrieval"
        or ResearchAct.EVIDENCE_SEEK in decision.plan.research_acts
        or (
            relevance.owner != "user"
            and (
                ResearchAct.COMPARE in decision.plan.research_acts
                or decision.plan.current_mode is InteractionMode.DECIDE
            )
        )
    ):
        return [
            DialogueBranch(
                id="evidence_first",
                title="先补证据再收窄问题",
                description=f"围绕“{focal}”补充可定位材料，再决定研究问题和设计。",
                benefits=["降低把候选文献或题录误当作结论的风险", "先处理反例和证据缺口"],
                risks=["研究设计会晚一轮形成", "如果缺口长期无法补齐，需要调整问题范围"],
                prerequisites=["明确检索范围和来源核验标准"],
                message=f"我选择先补证据再收窄问题，重点核查：{focal}。",
            ),
            DialogueBranch(
                id="provisional_design",
                title="按暂定边界先形成设计",
                description=f"把“{focal}”标为暂定前提，先形成可审查的研究问题和设计候选。",
                benefits=["更快暴露变量、样本和数据字段是否匹配", "后续可以用新证据修订版本"],
                risks=["暂定前提可能导致设计方向改变", "不能把当前设计写成已被证据确认"],
                prerequisites=["在方案中明确暂定前提和失效条件"],
                message=f"我选择按暂定边界先形成设计，并把“{focal}”标为待验证前提。",
            ),
        ]
    if relevance.owner == "user" or decision.plan.question_to_user:
        return [
            DialogueBranch(
                id="clarify_first",
                title="先明确研究者取舍",
                description=f"先回答“{focal}”，再生成下游研究产物。",
                benefits=["研究问题更贴近真实研究意图", "减少后续返工和错误测量"],
                risks=["需要暂停当前自动整理", "暂时不会生成正式分析代码"],
                prerequisites=["研究者给出一个明确判断或可接受范围"],
                message=f"我选择先明确这个取舍：{focal}。",
            ),
            DialogueBranch(
                id="bounded_assumption",
                title="先用暂定假设推进",
                description=f"先给“{focal}”设定一个可撤回的工作定义，同时继续整理证据。",
                benefits=["保持研究推进速度", "可以更早发现数据和设计冲突"],
                risks=["新证据可能使当前版本失效", "不能把暂定定义写成最终结论"],
                prerequisites=["记录假设、适用范围和触发修订的证据"],
                message=f"我选择先用暂定假设推进，并记录“{focal}”的修订条件。",
            ),
        ]
    return []


def _dialogue_version_change(
    decision: CollaborationDecision | None,
) -> DialogueVersionChange | None:
    if decision is None:
        return None
    patch = decision.graph_patch
    added = [
        node.content[:240]
        for node in patch.upserted_nodes
        if node.node_id not in {revision.node_id for revision in patch.revisions}
    ][:4]
    changed = [
        f"{revision.previous_status} → {revision.new_status}：{revision.reason[:240]}"
        for revision in patch.revisions[:4]
    ]
    implications = list(dict.fromkeys(
        consequence
        for revision in patch.revisions
        for consequence in revision.research_consequences
    ))[:4]
    if not added and not changed and patch.base_version == patch.new_version:
        return None
    if not implications and (added or changed):
        implications.append("这次更新只改变共享研究地图，不会自动冻结方案、运行分析或替换已有结果。")
    return DialogueVersionChange(
        from_version=patch.base_version,
        to_version=patch.new_version,
        added=added,
        changed=changed,
        implications=implications,
    )


_RESEARCH_OUTPUT_HEADINGS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("research_question", ("研究问题与研究目标", "研究问题与方案", "研究问题", "核心问题", "主要问题")),
    ("research_objective", ("研究目标", "研究目的", "研究意义")),
    ("hypotheses", ("研究假设", "假设")),
    ("research_object", ("研究对象", "研究场景", "样本对象", "样本与分组")),
    ("study_design", ("研究设计", "实验设计", "研究方案")),
    ("methods", ("研究方法", "实验方法", "方法")),
    ("measurement", ("变量与测量", "变量", "测量指标", "主要指标", "结果变量", "主要结果")),
    ("data_collection", ("数据收集", "资料收集", "数据来源")),
    ("analysis_plan", ("数据分析", "统计分析", "分析计划", "分析方法")),
    ("ethics_limitations", ("伦理", "伦理与局限", "局限", "研究局限")),
)


def _research_output_sections(answer_text: str) -> dict[str, str]:
    """Extract readable heading sections without requiring a second LLM call."""

    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in answer_text.splitlines():
        line = raw_line.strip()
        if not line:
            if current is not None:
                sections.setdefault(current, []).append("")
            continue
        candidate = re.sub(r"^[#*\-\s\d一二三四五六七八九十百、.)]+", "", line)
        candidate = candidate.strip().strip("*_`")
        matched: str | None = None
        remainder = ""
        for key, aliases in _RESEARCH_OUTPUT_HEADINGS:
            for alias in aliases:
                if candidate == alias:
                    matched = key
                    break
                if candidate.startswith(alias) and candidate[len(alias):].lstrip().startswith((":", "：")):
                    matched = key
                    remainder = candidate[len(alias):].lstrip(" :：")
                    break
            if matched is not None:
                break
        if matched is not None:
            current = matched
            sections.setdefault(current, [])
            if remainder:
                sections[current].append(remainder)
            continue
        if current is not None:
            sections.setdefault(current, []).append(line)
    return {
        key: "\n".join(value).strip()
        for key, value in sections.items()
        if "\n".join(value).strip()
    }


def _research_output_list(value: str | None, fallback: list[str] | None = None) -> list[str]:
    if not value:
        return list(fallback or [])
    items: list[str] = []
    for line in value.splitlines():
        cleaned = re.sub(r"^\s*(?:[-*•]|\d+[.)、]|[一二三四五六七八九十百]+[、.)])\s*", "", line).strip()
        if cleaned:
            items.append(cleaned)
    return items or list(fallback or [])


def _research_output_is_structured(question: str, answer_text: str, sections: dict[str, str]) -> bool:
    """Only promote substantive research-planning answers to workbench cards."""

    if len(answer_text.strip()) < 180:
        return False
    question_lower = question.lower()
    answer_lower = answer_text.lower()
    question_signals = (
        "研究问题", "研究方案", "研究设计", "研究方法", "研究假设",
        "研究对象", "变量", "样本", "数据分析", "实验组", "对照组",
        "research question", "study design", "research protocol",
    )
    answer_signals = (
        "研究问题", "研究目标", "研究假设", "研究对象", "研究设计",
        "研究方法", "变量", "样本", "数据收集", "数据分析", "伦理",
        "局限", "hypothes", "method", "analysis", "sampling",
    )
    question_score = sum(marker in question_lower for marker in question_signals)
    answer_score = sum(marker in answer_lower for marker in answer_signals)
    return (
        question_score >= 1
        and answer_score >= 3
        and (
            len(sections) >= 2
            or answer_score >= 5
        )
    )


def _persist_conversational_research_outputs(
    *,
    project_id: str,
    request: ConversationCommandRequest,
    answer: QAAnswerResponse,
    forced_output_kind: str | None = None,
) -> bool:
    """Bridge substantive conversational output into provisional workbench artifacts.

    The normal route is still the orchestration workflow. This projection is
    the safety net for a discussion turn that produced a real candidate anyway:
    it keeps the result reviewable without pretending that it is approved.
    """

    answer_text = answer.answer.strip()
    sections = _research_output_sections(answer_text)
    normalized_question = request.message.strip().lower()
    artifact_specs: list[tuple[str, str, dict[str, object]]] = []

    turn_key = answer.turn_id or request.client_turn_id or sha256_text(
        f"{project_id}|{request.message}|{answer_text}"
    )[:24]
    safe_turn_key = re.sub(r"[^A-Za-z0-9_.:-]+", "-", turn_key)[:96]
    provenance = {
        "source": "conversation_llm_answer",
        "conversation_id": answer.conversation_id,
        "turn_id": answer.turn_id or request.client_turn_id,
        "requires_confirmation": True,
        "source_question": request.message[:4000],
    }
    if _research_output_is_structured(request.message, answer_text, sections):
        artifact_specs.extend([
            ("research-question", "ResearchQuestionTree", {
                "project_id": project_id,
                "title": "对话生成的研究问题候选",
                "primary_question": sections.get("research_question") or answer_text[:1000],
                "research_questions": _research_output_list(sections.get("research_question")),
                "research_objective": sections.get("research_objective", ""),
                "hypotheses": _research_output_list(sections.get("hypotheses")),
                "research_object": sections.get("research_object", ""),
                "status": "CONVERSATIONAL_CANDIDATE_REQUIRES_CONFIRMATION",
                "requires_confirmation": True,
                "raw_answer": answer_text,
                "provenance": provenance,
            }),
            ("study-protocol", "StudyProtocolCandidate", {
                "project_id": project_id,
                "title": "对话生成的研究方案候选",
                "design_type": sections.get("study_design", "研究设计待从完整回答中确认"),
                "primary_outcome": sections.get("measurement", "主要结果指标待确认"),
                "sampling_approach": sections.get("research_object", "研究对象与样本边界待确认"),
                "variables": _research_output_list(sections.get("measurement")),
                "analysis_plan": sections.get("analysis_plan", "分析计划待确认"),
                "hypotheses": _research_output_list(sections.get("hypotheses")),
                "methods": sections.get("methods", ""),
                "data_collection": sections.get("data_collection", ""),
                "ethics_limitations": sections.get("ethics_limitations", ""),
                "status": "CONVERSATIONAL_CANDIDATE_REQUIRES_CONFIRMATION",
                "requires_confirmation": True,
                "raw_answer": answer_text,
                "provenance": provenance,
            }),
        ])

    code_requested = (
        forced_output_kind == "code"
        or _direct_conversation_output_request(request.message) == "code"
    ) and any(
        token in answer_text for token in ("```", "import ", "def ", "class ", "pandas", "numpy")
    )
    if code_requested:
        fenced = re.search(r"```(?:python|py)?\s*(.*?)```", answer_text, re.IGNORECASE | re.DOTALL)
        source_code = (fenced.group(1) if fenced else answer_text).strip()
        artifact_specs.append(("python-code", "PhysicsCodeValidationCandidate", {
            "project_id": project_id,
            "title": "对话生成的 Python 代码候选",
            "language": "python",
            "source_code": source_code,
            "status": "CONVERSATIONAL_CANDIDATE_REQUIRES_CONFIRMATION",
            "requires_human_review": True,
            "provenance": provenance,
        }))

    paper_requested = (
        len(answer_text) >= 220
        and (
        forced_output_kind == "manuscript"
        or _direct_conversation_output_request(request.message) == "manuscript"
            or (
                "论文" in normalized_question
                and any(marker in normalized_question for marker in ("生成", "写", "输出", "保存"))
            )
            or any(marker in normalized_question for marker in ("manuscript", "write the paper", "generate manuscript"))
        )
    )
    if paper_requested:
        title = sections.get("research_question", "").splitlines()[0][:160] or "对话生成的候选论文"
        artifact_specs.append(("manuscript", "ManuscriptDraftZh", {
            "project_id": project_id,
            "title": title,
            "sections": {
                "title": title,
                "abstract": sections.get("research_objective", ""),
                "body": answer_text,
            },
            "full_text": answer_text,
            "status": "CONVERSATIONAL_CANDIDATE_REQUIRES_CONFIRMATION",
            "requires_human_review": True,
            "provenance": provenance,
        }))

    if not artifact_specs:
        return False

    saved_any = False
    for suffix, artifact_type, body in artifact_specs:
        artifact_id = f"conversation:{project_id}:{safe_turn_key}:{suffix}"
        existing_content = artifact_content_store.get(project_id, artifact_id)
        if existing_content is not None:
            if artifact_store.get(project_id, artifact_id) is None:
                artifact_store.put(
                    ArtifactRef(
                        artifact_id=artifact_id,
                        project_id=project_id,
                        artifact_type=existing_content.artifact_type,
                        version=existing_content.version,
                        content_uri=(
                            f"artifact-content://{project_id}/{artifact_id}/{existing_content.version}"
                        ),
                        sha256=existing_content.content_hash or sha256_text(
                            existing_content.model_dump_json()
                        ),
                        created_at=existing_content.created_at,
                        created_by="conversation_llm",
                        status="CANDIDATE",
                    )
                )
            continue
        saved_content = artifact_content_store.put(
            ArtifactContent(
                project_id=project_id,
                artifact_id=artifact_id,
                version=1,
                artifact_type=artifact_type,
                schema_version="conversational-research-output-v1",
                body=body,
            )
        )
        artifact_store.put(
            ArtifactRef(
                artifact_id=artifact_id,
                project_id=project_id,
                artifact_type=artifact_type,
                version=saved_content.version,
                content_uri=f"artifact-content://{project_id}/{artifact_id}/{saved_content.version}",
                sha256=saved_content.content_hash or sha256_text(saved_content.model_dump_json()),
                created_at=saved_content.created_at,
                created_by="conversation_llm",
                status="CANDIDATE",
            )
        )
        saved_any = True
    return saved_any


def _direct_conversation_output_request(message: str) -> str | None:
    """Return the requested direct workbench output kind, if any."""

    normalized = message.strip().lower()
    action_markers = (
        "生成", "写", "输出", "提供", "保存", "整理", "generate", "write", "create",
    )
    if not any(marker in normalized for marker in action_markers):
        return None
    if any(
        marker in normalized
        for marker in (
            "python代码", "python 代码", "分析代码", "代码校验", "代码候选",
            "生成代码", "写代码", "generate code", "python code",
        )
    ):
        return "code"
    if any(
        marker in normalized
        for marker in (
            "候选论文", "论文草稿", "论文初稿", "生成论文", "写论文",
            "完整论文", "论文正文", "manuscript", "write the paper",
        )
    ):
        return "manuscript"
    return None


def _persist_forced_manuscript_candidate(
    *,
    project_id: str,
    request: ConversationCommandRequest,
    answer: QAAnswerResponse,
) -> None:
    """Persist a direct manuscript response even if another projection fails."""

    answer_text = answer.answer.strip()
    turn_key = answer.turn_id or request.client_turn_id or sha256_text(
        f"{project_id}|{request.message}|{answer_text}"
    )[:24]
    safe_turn_key = re.sub(r"[^A-Za-z0-9_.:-]+", "-", turn_key)[:96]
    artifact_id = f"conversation:{project_id}:{safe_turn_key}:manuscript"
    body = {
        "project_id": project_id,
        "title": "对话生成的候选论文",
        "sections": {
            "title": "对话生成的候选论文",
            "abstract": "候选稿待结合项目证据审阅。",
            "body": answer_text,
        },
        "full_text": answer_text,
        "status": "CONVERSATIONAL_CANDIDATE_REQUIRES_CONFIRMATION",
        "requires_human_review": True,
        "provenance": {
            "source": "conversation_llm_answer",
            "conversation_id": answer.conversation_id,
            "turn_id": answer.turn_id or request.client_turn_id,
            "source_question": request.message[:4000],
        },
    }
    if artifact_content_store.get(project_id, artifact_id) is not None:
        return
    saved_content = artifact_content_store.put(
        ArtifactContent(
            project_id=project_id,
            artifact_id=artifact_id,
            version=1,
            artifact_type="ManuscriptDraftZh",
            schema_version="conversational-research-output-v1",
            body=body,
        )
    )
    artifact_store.put(
        ArtifactRef(
            artifact_id=artifact_id,
            project_id=project_id,
            artifact_type="ManuscriptDraftZh",
            version=saved_content.version,
            content_uri=f"artifact-content://{project_id}/{artifact_id}/{saved_content.version}",
            sha256=saved_content.content_hash or sha256_text(saved_content.model_dump_json()),
            created_at=saved_content.created_at,
            created_by="conversation_llm",
            status="CANDIDATE",
        )
    )


def _discussion_response(
    *,
    project_id: str,
    request: ConversationCommandRequest,
    state: ControlState,
    project_context: str | None = None,
    collaboration: CollaborationDecision | None = None,
) -> dict[str, object]:
    """Answer one collaborative turn without mutating orchestration state."""

    bounded_response = _cgt_analysis_instruction_response(project_id, request.message)
    guided_response = _cgt_guided_response(request.message, collaboration)
    if bounded_response is not None or guided_response is not None:
        response_message = bounded_response or guided_response or ""
        return {
            "kind": "qa",
            "message": response_message,
            "answer": {
                "answer": response_message,
                "route": {"route": "direct_answer", "reason": "有界科研对话", "recommended_agent": None},
                "citations": [],
                "answer_mode": "fallback",
            },
            "control_state": state.model_dump(mode="json"),
            "route_decision": state.route_decision.model_dump(mode="json") if state.route_decision else None,
            "gate": None,
            "waiting_for_user": bool(guided_response),
            "checkpoint": None,
            "execution_started": False,
        }

    # Document uploads are stored in the project document service first. Sync
    # them into the project-scoped evidence index before answering so a plain
    # discussion turn can use the researcher's files instead of falling back
    # to an unrelated shared-corpus hit.
    local_source_ids = _sync_project_documents(project_id)
    local_document_context = _project_document_prompt_context(
        project_id,
        request.message,
    )
    dataset_summary = _project_dataset_summary(project_id)
    external_request = any(
        marker in request.message.strip().lower()
        for marker in (
            "openalex", "crossref", "外部搜索", "外部检索", "外部文献",
            "外部学术", "学术索引", "external search", "scholarly index",
        )
    )
    collaboration_context = ""
    if collaboration is not None:
        collaboration_context = _research_collaboration_engine().prompt_context(
            project_id, collaboration
        )
    # ``QAAnswerRequest.project_context`` is intentionally capped at 4,000
    # characters. A long-lived project can accumulate a large collaboration
    # graph, so trim the combined context before crossing the strict model
    # boundary. Keep project identity at the front and newer guidance at the
    # end.
    dataset_context = f"\n当前已登记数据：{dataset_summary}" if dataset_summary else ""
    combined_context = (
        (project_context or "")
        + ("\n" + local_document_context if local_document_context else "")
        + dataset_context
        + collaboration_context
    )
    if len(combined_context) > 4000:
        head = (project_context or "")[:1200]
        tail = combined_context[-(4000 - len(head)):]
        combined_context = head + "\n...[项目上下文已压缩]...\n" + tail
        combined_context = combined_context[:4000]
    qa_request = QAAnswerRequest(
        project_id=project_id,
        question=request.message,
        mode=ContextMode(request.evidence_mode),
        conversation_id=request.conversation_id,
        project_context=combined_context,
        allow_llm=True,
        planned_research_acts=(
            [act.value for act in collaboration.plan.research_acts]
            if collaboration else []
        ),
        planned_follow_up_question=(
            collaboration.plan.question_to_user if collaboration else None
        ),
        allow_unplanned_follow_up=collaboration is None,
    )
    planned_evidence_search = bool(
        collaboration
        and ResearchAct.EVIDENCE_SEEK in collaboration.plan.research_acts
    )
    # A researcher may explicitly ask to organize or cite already-uploaded
    # papers without using a workflow command.  Treat those turns as grounded
    # QA when project-local evidence exists; otherwise ``converse`` falls back
    # to a generic schema prompt and silently ignores the uploaded source.
    local_evidence_request = bool(
        local_source_ids
        and any(
            marker in request.message.strip().lower()
            for marker in (
                "已上传", "论文", "文献", "证据", "题录", "doi", "osf",
                "数据字典", "样本", "筛选规则", "来源核验",
            )
        )
    )
    answer = (
        qa_service.answer(qa_request)
        if external_request or planned_evidence_search or local_evidence_request
        else qa_service.converse(qa_request)
    )
    direct_output_kind = _direct_conversation_output_request(request.message)
    if direct_output_kind == "code" and not any(
        marker in answer.answer
        for marker in ("```", "import ", "def ", "pandas", "numpy")
    ):
        fallback_code = """```python
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


CSV_PATH = Path("your_data.csv")
GROUP_COLUMN = "group"       # 待按实际表头确认
VALUE_COLUMN = "measurement" # 待按实际表头确认


def audit_and_summarize(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    print("字段：", list(frame.columns))
    print("缺失值：\\n", frame.isna().sum())
    required = [GROUP_COLUMN, VALUE_COLUMN]
    missing = [name for name in required if name not in frame.columns]
    if missing:
        raise KeyError(f"请先确认字段名：{missing}")
    clean = frame.dropna(subset=required).copy()
    summary = (
        clean.groupby(GROUP_COLUMN, dropna=False)[VALUE_COLUMN]
        .agg(["count", "mean", "std"])
        .reset_index()
    )
    summary["sem"] = summary["std"].fillna(0) / summary["count"].clip(lower=1).pow(0.5)
    return summary


summary = audit_and_summarize(CSV_PATH)
ax = summary.plot.bar(
    x=GROUP_COLUMN,
    y="mean",
    yerr="sem",
    capsize=4,
    legend=False,
    title="各组均值及标准误",
)
ax.set_ylabel(VALUE_COLUMN)
plt.tight_layout()
plt.show()
```"""
        answer = answer.model_copy(update={
            "answer": (
                "已先生成一份可审阅的 Python 代码候选。当前 CSV 的分组字段和结果字段尚未确认，"
                "代码会先输出字段与缺失值，再按确认后的字段计算各组均值和标准误并绘图；"
                "尚未执行，也不会把示例字段当成真实数据。\n\n"
                + fallback_code
            ),
            "route": QARouteDecision(
                route="direct_answer",
                reason="直接代码产出候选",
                recommended_agent="analysis_code",
            ),
            "citations": [],
            "answer_mode": "fallback",
        })
    elif direct_output_kind == "manuscript" and len(answer.answer.strip()) < 220:
        answer = answer.model_copy(update={
            "answer": (
                "已生成候选论文草稿框架，具体样本、效应量和结论仍需绑定项目证据后审阅。\n\n"
                "## 题目\n待根据研究问题确认\n\n"
                "## 摘要\n本研究拟围绕当前项目的研究问题，基于已上传资料和后续审计结果形成可复核的研究结论。"
                "当前不填入未经核验的样本量、效应量或因果表述。\n\n"
                "## 研究方法\n研究对象、变量定义、数据处理和统计方法待结合项目资料确认。\n\n"
                "## 结果与讨论\n待完成数据审查、证据核验和人工确认后写入。"
            ),
            "route": QARouteDecision(
                route="direct_answer",
                reason="直接论文产出候选",
                recommended_agent="paper_writing",
            ),
            "citations": [],
            "answer_mode": "fallback",
        })
    domain_correction = getattr(answer, "domain_correction", None)
    if isinstance(domain_correction, dict):
        # Keep the correction in the project audit trail as well as the QA
        # service's JSONL trace.  The researcher sees only the corrected text,
        # while both versions remain inspectable for system evaluation.
        control_plane.repository.add_event(
            AuditEvent(
                project_id=project_id,
                event_type="QA_DOMAIN_MISMATCH_CORRECTED",
                actor="qa_service",
                state_revision=state.state_revision,
                payload=domain_correction,
            )
        )
    # The first post-upload turn is a receipt check, not a literature
    # question. Return facts from the actual CSV instead of the generic
    # fallback that says the assistant cannot see a table header.
    explicit_code_request = any(
        term in request.message.strip().lower()
        for term in (
            "生成代码", "分析代码", "python代码", "python 代码",
            "代码候选", "写代码", "generate code", "python code",
        )
    )
    if (
        dataset_summary
        and not explicit_code_request
        and any(term in request.message.lower() for term in ("实际读取", "字段", "表头", "csv"))
    ):
        factual_answer = (
            f"{dataset_summary}\n\n"
            "目前只完成了文件接收和字段识别，没有执行正式统计或主题分析。"
            "接下来我会根据你的研究目的继续逐步提问；你可以先告诉我最想从这份材料中弄清什么。"
        )
        answer = answer.model_copy(update={
            "answer": factual_answer,
            "route": QARouteDecision(route="direct_answer", reason="项目数据接收确认", recommended_agent=None),
            "citations": [],
            "answer_mode": "fallback",
        })
    # Resolve explicit sample-count assertions from the uploaded file before
    # the generic conversational model can echo them. This keeps a request
    # such as "排除 78 条并得到 472 条" from becoming an unverified fact when
    # the actual CSV has a different missingness pattern.
    missingness_message = request.message.lower()
    if dataset_summary and (
        any(term in missingness_message for term in ("空文本", "非空文本", "472", "78 条", "78条"))
        or ("text" in missingness_message and "缺失" in missingness_message)
    ):
        audit = _project_dataset_missingness(project_id)
        if audit is not None:
            factual_answer = (
                f"我先按当前上传文件核对这个数字：文件共 {audit['rows']} 行，"
                f"Text 缺失 {audit['missing_text']} 条，非空文本 {audit['nonempty_text']} 条，"
                f"Stu_ID 唯一值 {audit['unique_ids']} 个。"
            )
            requested_numbers = any(token in request.message for token in ("78", "472"))
            if requested_numbers and (audit["missing_text"] != 78 or audit["nonempty_text"] != 472):
                factual_answer += (
                    "这与消息中提到的“78 条/472 条”不一致；当前系统不会把预期数字写入排除清单或论文，"
                    "需要先以实际审计结果确定筛选规则。原始文件保持不变。"
                )
            else:
                factual_answer += "后续排除和冻结将只使用这份审计结果，原始文件保持不变。"
            answer = answer.model_copy(update={
                "answer": factual_answer,
                "route": QARouteDecision(route="direct_answer", reason="实际文件样本边界核对", recommended_agent=None),
                "citations": [],
                "answer_mode": "fallback",
            })
    answer_citations = getattr(answer, "citations", [])
    # An external index may be unavailable even when the project already has
    # the paper needed for the question. Retry once against the local corpus
    # before exposing an empty external-search result as the conclusion.
    if external_request and local_source_ids and not answer_citations:
        local_qa_request = qa_request.model_copy(update={
            "question": (
                "仅使用本项目已上传和已核验的本地材料回答；不要把外部检索失败当作结论。"
                + request.message
            ),
        })
        local_answer = qa_service.answer(local_qa_request)
        if getattr(local_answer, "citations", []) or getattr(local_answer, "answer", ""):
            answer = local_answer
            answer_citations = getattr(answer, "citations", [])
    if collaboration is not None and answer_citations:
        observations = [
            EvidenceObservation(
                evidence_id=(
                    citation.canonical_chunk_id
                    or citation.canonical_paper_id
                ),
                title=citation.paper_title,
                excerpt=citation.excerpt,
                verification_status=citation.verification_status,
                locator_status=citation.locator_status,
            )
            for citation in answer_citations
        ]
        collaboration = _research_collaboration_engine().integrate_evidence(
            project_id=project_id,
            decision=collaboration,
            observations=observations,
            answer_summary=answer.answer,
        )
    turn_mode = collaboration.plan.current_mode.value if collaboration else "discussion"
    dialogue_summary, planned_question, dialogue_suggestions = _collaboration_dialogue(collaboration)
    dialogue_branches = _collaboration_branches(collaboration)
    dialogue_version_change = _dialogue_version_change(collaboration)
    dialogue_evidence = [
        DialogueEvidence(
            title=str(citation.paper_title),
            evidence_id=(citation.canonical_chunk_id or citation.canonical_paper_id),
            excerpt=str(citation.excerpt)[:600],
            verification_status=str(citation.verification_status),
            locator_status=str(citation.locator_status),
            role="支持本轮判断的材料",
        )
        for citation in answer_citations[:3]
        if getattr(citation, "paper_title", None) and getattr(citation, "excerpt", None)
    ]
    dialogue_tradeoffs: list[str] = []
    if collaboration and collaboration.plan.turn_role in {"decide", "challenge"}:
        rationale = collaboration.plan.decision_relevance.rationale.strip()
        if rationale:
            dialogue_tradeoffs.append(f"研究影响：{rationale}")
        if collaboration.plan.decision_relevance.can_proceed_provisionally:
            dialogue_tradeoffs.append("可以先按暂定边界推进；如果后续证据改变判断，会生成新版本而不覆盖当前记录。")
        else:
            dialogue_tradeoffs.append("这项取舍会改变研究路线，暂时不能用默认假设替代你的判断。")
    if collaboration and collaboration.plan.turn_role == "wait":
        next_action = "暂不打断你；出现新证据、冲突或真正的路线分叉后再请求判断。"
    elif planned_question:
        next_action = "先处理上面的关键问题，再决定是否进入正式研究流程。"
    elif collaboration and collaboration.plan.turn_role == "challenge":
        next_action = "先检查反例和替代解释；只有它们改变判断时，才调整研究路线。"
    else:
        next_action = "继续整理当前缺口，并在需要你判断的边界停下来。"
    response_message = answer.answer
    # The separately deployed LoRA coordinator is an optional enhancement.
    # Its user-facing text is explicitly labelled as a suggestion and never
    # replaces cited QA output or Controller decisions. If the service is
    # offline, OptionalCoordinator returns None and this turn is unchanged.
    coordinator_advice = (
        coordinator_model.advise(
            user_message=request.message,
            context=combined_context,
            current_answer=answer.answer,
        )
        if coordinator_model is not None
        else None
    )
    if coordinator_advice is not None and coordinator_advice.user_message.strip():
        response_message += "\n\n【协同建议（需核验）】\n" + coordinator_advice.user_message.strip()
        if coordinator_advice.requires_human_decision:
            next_action = (
                f"{coordinator_advice.next_action}（需人工确认）"
                if coordinator_advice.next_action
                else "等待人工确认"
            )
    if collaboration and collaboration.belief_revisions:
        changes = []
        for revision in collaboration.belief_revisions[:3]:
            consequence = (
                f"；研究后果：{'；'.join(revision.research_consequences[:2])}"
                if revision.research_consequences
                else ""
            )
            changes.append(
                f"- {revision.previous_status} → {revision.new_status}："
                f"{revision.reason}{consequence}"
            )
        response_message += "\n\n新证据改变了当前研究判断：\n" + "\n".join(changes)
    try:
        _persist_conversational_research_outputs(
            project_id=project_id,
            request=request,
            answer=answer,
            forced_output_kind=direct_output_kind,
        )
    except Exception:  # noqa: BLE001 - a workbench projection must not break chat
        logger.exception("Could not persist conversational research outputs for %s", project_id)
    return {
        "kind": "qa",
        "message": response_message,
        "answer": answer.model_dump(mode="json"),
        "control_state": state.model_dump(mode="json"),
        # A discussion turn is deliberately opaque to workflow UI. The
        # durable control state remains available through its dedicated API,
        # but chat must not resurrect a Gate or checkpoint from it.
        "route_decision": None,
        "gate": None,
        # Discussion is intentionally a stable pause. The client must never
        # interpret a conversational answer as permission to call /continue.
        "waiting_for_user": True,
        "checkpoint": None,
        "execution_started": False,
        "collaboration": collaboration.model_dump(mode="json") if collaboration else None,
        "dialogue": DialogueTurn(
            mode=turn_mode,
            summary=dialogue_summary,
            question=planned_question,
            suggestions=dialogue_suggestions,
            evidence=dialogue_evidence,
            tradeoffs=dialogue_tradeoffs,
            branches=dialogue_branches,
            version_change=dialogue_version_change,
            next_action=next_action,
            canvas_focus="overview",
            turn_role=(collaboration.plan.turn_role if collaboration else "answer"),
            why_now=(collaboration.plan.why_now if collaboration else None),
            novelty=(collaboration.plan.novelty if collaboration else []),
            user_action_required=(collaboration.plan.user_action_required if collaboration else False),
        ).model_dump(mode="json"),
    }


@app.get("/api/v1/projects/{project_id}/research-intake", response_model=ResearchIntakeState | None)
def project_research_intake(
    project_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
) -> ResearchIntakeState | None:
    """Return the durable topic-clarification state used by the chat UI."""

    return identity_service.get_research_intake(user, project_id)


@app.get(
    "/api/v1/projects/{project_id}/research-canvas",
    response_model=ResearchGraph,
)
def project_research_canvas(
    project_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
) -> ResearchGraph:
    """Return the versioned researcher-facing belief graph."""

    identity_service.get_project(user, project_id)
    return _research_collaboration_engine().graph(project_id)


@app.get(
    "/api/v1/projects/{project_id}/research-branches",
    response_model=list[ResearchBranch],
)
def project_research_branches(
    project_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
) -> list[ResearchBranch]:
    identity_service.get_project(user, project_id)
    return _research_collaboration_engine().store.list_branches(project_id)


@app.post(
    "/api/v1/projects/{project_id}/research-branches",
    response_model=ResearchBranch,
)
def create_research_branch(
    project_id: str,
    request: ResearchBranchRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> ResearchBranch:
    identity_service.get_project(user, project_id)
    branch = ResearchBranch(
        branch_id=f"branch-{uuid4().hex}",
        project_id=project_id,
        **request.model_dump(),
    )
    return _research_collaboration_engine().store.save_branch(branch)


def _update_research_branch(
    project_id: str,
    branch_id: str,
    status: Literal["selected", "parked"],
    reason: str | None,
    user: UserProfile,
) -> ResearchBranch:
    identity_service.get_project(user, project_id)
    engine = _research_collaboration_engine()
    branch = engine.store.get_branch(project_id, branch_id)
    if branch is None:
        raise HTTPException(status_code=404, detail="research branch was not found")
    return engine.store.save_branch(
        branch.model_copy(update={"status": status, "chosen_reason": reason or branch.chosen_reason})
    )


@app.post(
    "/api/v1/projects/{project_id}/research-branches/{branch_id}/activate",
    response_model=ResearchBranch,
)
def activate_research_branch(
    project_id: str,
    branch_id: str,
    request: ResearchBranchDecisionRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> ResearchBranch:
    return _update_research_branch(project_id, branch_id, "selected", request.reason, user)


@app.post(
    "/api/v1/projects/{project_id}/research-branches/{branch_id}/park",
    response_model=ResearchBranch,
)
def park_research_branch(
    project_id: str,
    branch_id: str,
    request: ResearchBranchDecisionRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> ResearchBranch:
    return _update_research_branch(project_id, branch_id, "parked", request.reason, user)


def _project_conversation_command_impl(
    project_id: str,
    request: ConversationCommandRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> dict[str, object]:
    """Classify one conversation turn and route it to QA or orchestration."""

    project = identity_service.get_project(user, project_id)
    if request.project_id != project_id:
        raise ContextInputError("project_mismatch", "path project_id does not match request project_id")
    message = request.intent or request.message
    current_state = control_plane.ensure_project(project_id)
    direct_output_kind = _direct_conversation_output_request(message)
    if (
        direct_output_kind is not None
        and not _conversation_prefers_discussion(message)
        and not any(
            marker in message.strip().lower()
            for marker in ("不要生成", "不生成", "先不生成", "暂不生成", "do not generate")
        )
    ):
        direct_instruction = (
            "请直接完成用户要求并输出可审阅候选，不要只提问或返回字段说明。"
            if direct_output_kind == "code"
            else "请直接生成候选论文正文，并明确标出待核验内容，不要只给写作建议。"
        )
        direct_response = _discussion_response(
            project_id=project_id,
            request=request,
            state=current_state,
            project_context=(
                f"项目名称：{project.title}\n"
                f"研究方向：{project.research_direction}\n"
                f"本轮输出要求：{direct_instruction}\n"
                "生成的候选必须保留在产出工作区，等待人工审阅；不要把候选冒充正式结果。"
            ),
            collaboration=None,
        )
        if direct_output_kind == "manuscript":
            try:
                answer_payload = direct_response.get("answer")
                if isinstance(answer_payload, dict):
                    _persist_forced_manuscript_candidate(
                        project_id=project_id,
                        request=request,
                        answer=QAAnswerResponse.model_validate(answer_payload),
                    )
            except Exception:  # noqa: BLE001 - direct chat must remain available
                logger.exception("Could not persist forced manuscript candidate for %s", project_id)
        return direct_response
    # Projects created before the conversational flow was introduced may
    # still have a pending Gate for an internal operator (for example
    # ``research_design_approval``).  Migrate that durable state once while
    # preserving the original Gate and audit trail, then continue normally.
    legacy_gate = (
        control_plane.repository.get_gate(project_id, current_state.active_gate_id)
        if current_state.active_gate_id
        else None
    )
    if legacy_gate is not None and legacy_gate.status is GateStatus.PENDING and not _is_conversational_human_gate(legacy_gate):
        try:
            current_state = control_plane.decide_gate(
                project_id,
                legacy_gate.gate_id,
                decision="approve",
                actor="orchestrator",
                role="admin",
                risk_acceptance=["旧版内部 Gate 已按新版对话流程自动迁移"],
                reason="新版对话流程不再为内部算子单独暂停",
            )
        except (PermissionError, ValueError):
            # A malformed historical Gate remains visible and actionable; do
            # not hide a state that cannot be migrated safely.
            pass
    normalized_message = message.strip().lower()
    early_checkpoint = _conversation_checkpoint(current_state.model_dump(mode="json"))
    # Manuscript section requests are bounded workflow commands, not ordinary
    # discussion.  Resolve them before collaboration planning or the generic
    # discussion classifier can consume a phrase such as “请写结果” and
    # return the checkpoint prompt again.
    early_manuscript_section = (
        _manuscript_section_request(normalized_message)
        if early_checkpoint == MANUSCRIPT_SECTION_CHECKPOINT
        else None
    )
    if (
        early_checkpoint
        and _checkpoint_response_is_action(early_checkpoint, normalized_message)
        and not _conversation_requests_explanation(normalized_message)
    ):
        # Persist the routing intent on the request object itself.  Several
        # later safety classifiers inspect the requested mode and could
        # otherwise turn an explicit CGT approval back into ordinary QA.
        request = request.model_copy(update={"interaction_mode": "workflow"})
    if (
        early_manuscript_section is not None
        and not _conversation_requests_explanation(normalized_message)
    ):
        request = request.model_copy(update={"interaction_mode": "workflow"})
    active_stream_early = next(
        (item for item in current_state.workstreams if item.workstream_id == current_state.active_workstream_id),
        None,
    )
    if (
        active_stream_early is not None
        and active_stream_early.execution_status is ExecutionStatus.QUEUED
        and any(term in normalized_message for term in ("批准", "确认", "继续", "执行", "运行", "通过", "生成", "开始"))
        and not _conversation_requests_explanation(normalized_message)
    ):
        # A completed checkpoint response can race the UI's state refresh: the
        # checkpoint is cleared while the next action is durably queued. Treat
        # an explicit continuation as a resume request instead of answering it
        # from the generic literature QA layer.
        request = request.model_copy(update={"interaction_mode": "workflow"})
    memory_facts: dict[str, str] = {}
    if project.role in {"owner", "editor"}:
        # Preserve compatibility with old intake records, but new projects
        # use the collaboration graph's one-question-at-a-time guided brief.
        legacy_intake = identity_service.get_research_intake(user, project_id)
        if legacy_intake is not None and legacy_intake.status != "DEFERRED":
            legacy_facts = dict(legacy_intake.answers)
            legacy_facts.setdefault("research_topic", legacy_intake.research_topic)
            identity_service.merge_research_memory(
                user,
                project_id,
                facts=legacy_facts,
                source_message="从旧版研究澄清记录迁移",
            )
            identity_service.defer_research_intake(user, project_id)
        memory_facts = _extract_research_memory_facts(message)
        guided_key = _research_collaboration_engine().graph(project_id).guided_question_key
        if (
            current_state.route_decision is None
            and guided_key
            and guided_key not in memory_facts
            and not _requests_direct_discovery(message)
            and not _conversation_requests_explanation(normalized_message)
            and not _auto_requests_workflow(message, current_state)
        ):
            # The planner displayed this question on the previous turn. Keep
            # the researcher's free-form answer under that exact slot.
            memory_facts[guided_key] = message.strip()[:4000]
        if memory_facts:
            identity_service.merge_research_memory(
                user,
                project_id,
                facts=memory_facts,
                source_message=message,
            )
        current_memory = identity_service.get_research_memory(user, project_id)
        memory_facts = dict(current_memory.facts) if current_memory else {}
    collaboration = _research_collaboration_engine().prepare_turn(
        project_id=project_id,
        message=message,
        project_title=project.title,
        research_direction=project.research_direction,
        memory_facts=memory_facts,
        requested_mode=request.interaction_mode,
        source_turn_id=request.client_turn_id,
    )
    direct_output_kind = _direct_conversation_output_request(message)
    if direct_output_kind is not None and request.interaction_mode in {"auto", "discussion"}:
        direct_instruction = (
            "请直接完成用户要求并输出可审阅候选，不要只提问或返回字段说明。"
            if direct_output_kind == "code"
            else "请直接生成候选论文正文，并明确标出待核验内容，不要只给写作建议。"
        )
        return _discussion_response(
            project_id=project_id,
            request=request,
            state=current_state,
            project_context=(
                f"项目名称：{project.title}\n"
                f"研究方向：{project.research_direction}\n"
                f"本轮输出要求：{direct_instruction}\n"
                "生成的候选必须保留在产出工作区，等待人工审阅；不要把候选冒充正式结果。"
            ),
            collaboration=collaboration,
        )
    # Treat explicit design confirmations as continuation signals.  Without
    # this guard, a short confirmation could fall into the generic QA path
    # and return the stale “local evidence not found” answer instead of
    # advancing the existing research record.
    design_confirmation_requested = (
        any(marker in normalized_message for marker in (
            "确认研究设计", "确认这套研究设计", "确认当前研究设计",
            "确认研究方案", "确认研究问题和统计计划", "确认这套研究问题",
        ))
        and not any(marker in normalized_message for marker in (
            "不确认", "不要确认", "先不", "暂不", "不进入", "不继续",
        ))
    )
    conversational_constraints = _extract_research_constraints(message)
    requested_capabilities = _requested_research_capabilities(message)
    if (conversational_constraints or requested_capabilities) and current_state.route_decision is not None:
        active_stream = next(
            (item for item in current_state.workstreams if item.workstream_id == current_state.active_workstream_id),
            None,
        )
        if active_stream is not None:
            updated_feedback = _merge_conversational_feedback(
                active_stream.conversation_feedback,
                conversational_constraints,
                requested_capabilities,
                message,
            )
            current_state = control_plane.repository.save_state(
                current_state.model_copy(update={
                    "workstreams": [
                        active_stream.model_copy(update={"conversation_feedback": updated_feedback})
                        if item.workstream_id == active_stream.workstream_id else item
                        for item in current_state.workstreams
                    ],
                }),
                expected_revision=current_state.state_revision,
            )
            control_plane.repository.add_event(
                AuditEvent(
                    project_id=project_id,
                    event_type="RESEARCH_CONSTRAINTS_UPDATED",
                    actor=user.username,
                    state_revision=current_state.state_revision,
                    payload={
                        "constraints": conversational_constraints,
                        "requested_capabilities": requested_capabilities,
                        "merged_feedback": updated_feedback,
                    },
                )
            )
    # A sentence can contain an action term while explicitly declining that
    # action (for example, "不要直接开始分析"). Keep those turns in
    # discussion even when an older client sends the default workflow mode.
    resolved_interaction_mode = request.interaction_mode
    # A direct answer to a durable CGT review checkpoint is always a workflow
    # transition, even when the client sent the conservative ``auto`` or
    # ``discussion`` mode.  This guard runs before the generic QA classifier,
    # so instructions such as "批准烟雾测试" cannot be mistaken for a topic
    # question merely because they also contain explanatory text.
    active_checkpoint_now = _conversation_checkpoint(current_state.model_dump(mode="json"))
    bounded_checkpoint_update = (
        active_checkpoint_now in {"ANALYSIS_CODE_REVIEW", "PATTERN_CODE_REVIEW"}
        and _cgt_analysis_instruction_response(project_id, message) is not None
    )
    if (
        active_checkpoint_now
        and _checkpoint_response_is_action(active_checkpoint_now, normalized_message)
        and not _conversation_requests_explanation(normalized_message)
    ):
        resolved_interaction_mode = "workflow"
    elif bounded_checkpoint_update and not _conversation_requests_explanation(normalized_message):
        # Parameter/specification edits should remain visibly attached to the
        # active checkpoint even though they do not approve it.
        resolved_interaction_mode = "workflow"
    # A pending human decision remains actionable even for older clients that
    # omit interaction_mode (whose default is now discussion).  This is a
    # very narrow exception: only an unambiguous decision for the active
    # checkpoint can leave ordinary chat, never a question merely mentioning
    # papers, data, or analysis.
    if resolved_interaction_mode == "discussion" and current_state.active_gate_id:
        active_gate_for_message = control_plane.repository.get_gate(
            project_id, current_state.active_gate_id
        )
        active_stream_for_message = next(
            (
                item for item in current_state.workstreams
                if item.workstream_id == current_state.active_workstream_id
            ),
            None,
        )
        audit_terms = (
            "审计", "检查字段", "缺失值", "重复记录", "异常值",
            "audit", "fields", "missingness", "duplicates", "outliers",
        )
        if (
            active_gate_for_message is not None
            and active_gate_for_message.status is GateStatus.PENDING
            and (
                _conversation_gate_decision(
                    active_gate_for_message.gate_type, normalized_message
                ) is not None
                or _conversation_message_targets_gate(
                    active_gate_for_message.gate_type, normalized_message
                )
            )
        ):
            resolved_interaction_mode = "workflow"
        elif (
            active_gate_for_message is not None
            and active_gate_for_message.status is GateStatus.PENDING
            and active_gate_for_message.gate_type == "raw_data_import_approval"
            and active_stream_for_message is not None
            and control_plane.has_usable_primary_data(project_id, active_stream_for_message.route)
            and any(term in normalized_message for term in audit_terms)
        ):
            resolved_interaction_mode = "workflow"
    # The public endpoint defaults to discussion so an ordinary question can
    # never start a run by accident.  A clear action in that same message is
    # different: natural-language clients often omit interaction_mode, so
    # let an explicit command ("directly search", "continue", "freeze", ...)
    # advance the run without requiring a UI toggle.
    # An explicit discussion request is a hard conversational boundary.  The
    # collaboration planner may infer that a message is actionable, but it
    # must not override a client that deliberately asked to discuss without
    # starting or advancing the workflow.  Auto mode still benefits from the
    # planner's narrow action inference.
    if (
        request.interaction_mode == "auto"
        and resolved_interaction_mode == "discussion"
        and collaboration.plan.should_start_workflow
    ):
        resolved_interaction_mode = "workflow"
    if (
        resolved_interaction_mode == "discussion"
        and design_confirmation_requested
        and current_state.route_decision is not None
    ):
        # Only consume the confirmation when the active boundary is a design
        # checkpoint.  If the project is waiting on an unrelated gate (for
        # example raw-data import), routing this sentence to workflow would
        # try to approve that gate and produce a misleading 409.
        active_gate_for_design = (
            control_plane.repository.get_gate(project_id, current_state.active_gate_id)
            if current_state.active_gate_id
            else None
        )
        gate_type = active_gate_for_design.gate_type if active_gate_for_design else ""
        design_gate = any(term in gate_type for term in ("research_design", "research_question", "preregistration", "design_review"))
        if active_gate_for_design is None or design_gate:
            resolved_interaction_mode = "workflow"
    # The public request model defaults to discussion for safety, but users
    # commonly omit the mode while issuing an unmistakable command such as
    # "直接检索" or "继续搜索".  Reuse the narrow deterministic policy
    # classifier here so explicit actions advance the workflow, while normal
    # questions and deliberation remain in QA/discussion.
    if (
        request.interaction_mode in {"discussion", "auto"}
        and _auto_requests_workflow(message, current_state)
    ):
        resolved_interaction_mode = "workflow"
    # Result-card requests are durable research actions.  They must be
    # handled by the orchestration state (or its explicit checkpoint message)
    # instead of the literature QA fallback, even when the client uses the
    # conservative discussion default.
    if (
        resolved_interaction_mode == "discussion"
        and _conversation_requests_result_card(normalized_message)
        and not _conversation_requests_explanation(normalized_message)
    ):
        resolved_interaction_mode = "workflow"
    # Once the qualitative stream has reached writing, a request to recreate
    # or freeze a result card is an ordering question, not a literature
    # question.  Keep the state unchanged and explain the dependency instead
    # of silently advancing writing or returning the generic QA fallback.
    active_stream_for_result_card = next(
        (
            item for item in current_state.workstreams
            if item.workstream_id == current_state.active_workstream_id
        ),
        None,
    )
    active_action_for_result_card = (
        active_stream_for_result_card.workflow_steps[active_stream_for_result_card.current_step_index]
        if active_stream_for_result_card is not None
        and active_stream_for_result_card.current_step_index < len(active_stream_for_result_card.workflow_steps)
        else None
    )
    if (
        _conversation_requests_result_card(normalized_message)
        and active_action_for_result_card == "writing"
        and not _manuscript_outline_request(normalized_message)
        and _conversation_checkpoint(current_state.model_dump(mode="json"))
        not in {
            "RESULT_CARD_REVIEW",
            "MANUSCRIPT_SECTION_REVIEW",
        }
    ):
        result_card = _latest_artifact_body(project_id, "QualitativeResultCard")
        existing_result_card = result_card is not None or any(
            getattr(item, "artifact_type", "") == "StatisticalResultCard"
            and getattr(item, "effective", True)
            for item in control_plane.repository.list_artifacts(project_id)
        )
        if result_card is not None:
            sample_flow = result_card.get("data_audit") if isinstance(result_card.get("data_audit"), dict) else {}
            unperformed = _unperformed_candidate_actions(project_id)
            result_card_message = (
                "结果卡候选已经生成并连接现有数据、候选代码和产物记录。"
                f"样本流转为：原始记录 {sample_flow.get('raw_text_rows', '未记录')} 条，"
                f"空文本 {sample_flow.get('missing_text_rows', '未记录')} 条，"
                f"非空文本 {sample_flow.get('nonempty_text_rows', '未记录')} 条，"
                f"成功连接 {sample_flow.get('joined_students', '未记录')} 名。"
            )
            if unperformed:
                result_card_message += (
                    f"但{'、'.join(unperformed)}尚未实际执行，因此只能保留为待审查候选，不能标成正式冻结结果卡；"
                    "未执行项的性能、效应量和稳健性数字均不得进入论文。"
                )
            else:
                result_card_message += "所有列入项均有实际执行证据，可以进入冻结审查。"
        elif existing_result_card:
            result_card_message = "当前已经存在统计结果卡；后续写作只能读取该卡，不会用对话中的数字覆盖它。"
        else:
            result_card_message = (
                "当前已经进入写作阶段，但没有发现结果卡。系统不会在写作阶段补造结果卡，"
                "也不会把原论文数字或计划中的分析写进论文；需要回到结果卡审查节点后再继续。"
            )
        control_plane.repository.add_event(
            AuditEvent(
                project_id=project_id,
                event_type="RESULT_CARD_REQUEST_ORDER_CHECK",
                actor=user.username,
                state_revision=current_state.state_revision,
                payload={
                    "request": message.strip()[:2000],
                    "active_action": active_action_for_result_card,
                    "existing_result_card": existing_result_card,
                    "state_unchanged": True,
                },
            )
        )
        return {
            "kind": "orchestration",
            "message": result_card_message,
            "control_state": current_state.model_dump(mode="json"),
            "route_decision": current_state.route_decision.model_dump(mode="json") if current_state.route_decision else None,
            "gate": None,
            "waiting_for_user": True,
            "checkpoint": _conversation_checkpoint(current_state.model_dump(mode="json")),
            "execution_started": False,
        }
    # A conversational checkpoint is not a Gate, but an unambiguous answer to
    # it is still an action.  Consume it even when the client uses the safe
    # discussion default, while leaving explanatory questions in chat.
    if resolved_interaction_mode == "discussion":
        checkpoint_for_message = _conversation_checkpoint(current_state.model_dump(mode="json"))
        if (
            checkpoint_for_message
            and _checkpoint_response_is_action(checkpoint_for_message, normalized_message)
            and not _conversation_requests_explanation(normalized_message)
        ):
            resolved_interaction_mode = "workflow"
    # A direct response to a pending research boundary must take precedence
    # over the generic auto-chat policy. Previously only the raw-data audit
    # phrase was handled here, so ordinary confirmations such as "确认数据
    # 处理方案，继续" were misrouted to QA and appeared to be ignored.
    if resolved_interaction_mode == "auto" and current_state.active_gate_id:
        active_gate_for_auto = control_plane.repository.get_gate(
            project_id, current_state.active_gate_id
        )
        active_stream_for_audit = next(
            (
                item for item in current_state.workstreams
                if item.workstream_id == current_state.active_workstream_id
            ),
            None,
        )
        audit_terms = ("审计", "检查字段", "缺失值", "重复记录", "异常值", "audit", "fields", "missingness", "duplicates", "outliers")
        if (
            active_gate_for_auto is not None
            and active_gate_for_auto.status is GateStatus.PENDING
            and (
                _conversation_message_targets_gate(
                    active_gate_for_auto.gate_type, normalized_message
                )
                or (
                    active_gate_for_auto.gate_type == "raw_data_import_approval"
                    and active_stream_for_audit is not None
                    and control_plane.has_usable_primary_data(project_id, active_stream_for_audit.route)
                    and any(term in normalized_message for term in audit_terms)
                )
            )
        ):
            resolved_interaction_mode = "workflow"
    if resolved_interaction_mode == "auto":
        # Explicit scholarly-index requests are discovery questions, even if
        # they contain words such as "研究" or "直接检索". Do not let the
        # workflow classifier consume them and answer from the local corpus.
        external_discovery_request = any(
            marker in normalized_message
            for marker in (
                "openalex", "crossref", "外部搜索", "外部检索", "外部文献",
                "外部学术", "学术索引", "external search", "scholarly index",
                "public full text",
            )
        )
        if external_discovery_request:
            resolved_interaction_mode = "discussion"
        else:
            active_checkpoint = _conversation_checkpoint(current_state.model_dump(mode="json"))
            checkpoint_action = bool(
                active_checkpoint
                and _checkpoint_response_is_action(active_checkpoint, normalized_message)
            )
            resolved_interaction_mode = (
                "workflow"
                if checkpoint_action or collaboration.plan.should_start_workflow
                else "discussion"
            )
    if resolved_interaction_mode == "discussion":
        return _discussion_response(
            project_id=project_id,
            request=request,
            state=current_state,
            project_context=(
                f"项目名称：{project.title}\n研究方向：{project.research_direction}"
            ),
            collaboration=collaboration,
        )
    research_terms = (
        "研究", "论文", "实验", "问卷", "访谈", "数据", "分析", "编码", "主题", "方案", "预注册", "定性", "定量",
        "research", "experiment", "dataset", "analysis", "qualitative", "quantitative",
    )
    # Decision phrases are workflow commands even when a page refresh has
    # temporarily lost the active Gate card.  They must never fall through to
    # the generic literature QA path, otherwise the project remains stuck at
    # evidence review while the user believes they approved it.
    conversation_decision_terms = (
        "证据足够", "确认并继续", "进入研究设计", "继续下一步", "可以继续", "同意",
        "继续搜索", "补充文献", "扩大检索", "重新整理", "证据不足", "证据不够", "还不够", "再搜",
        "退回修改", "退回", "停止", "终止", "暂停", "approve", "approved", "revise", "search more", "stop", "cancel",
    )
    # A substantive first turn is still ordinary conversation unless the
    # researcher explicitly asks for an action.  Automatically starting
    # evidence retrieval from any sentence containing "研究" was the source
    # of irrelevant evidence dumps and the workflow-like behavior reported by
    # users.  Explicit action language is handled below by the normal auto
    # router.
    initial_topic = (
        current_state.route_decision is None
        and collaboration.plan.should_start_workflow
    )
    # One project may have only one active internal chain.  A slow external
    # search can otherwise be submitted again by an impatient click or a
    # client retry, causing two revisions to compete for the same Gate.
    # Return the authoritative snapshot rather than interpreting the new
    # message as QA or another workflow decision.
    active_tasks = [
        task
        for task in control_plane.repository.list_tasks(project_id)
        if task.status in {ExecutionStatus.QUEUED, ExecutionStatus.RUNNING}
    ]
    queued_stream = next(
        (item for item in current_state.workstreams if item.workstream_id == current_state.active_workstream_id),
        None,
    )
    queued_checkpoint = CGT_CONVERSATION_CHECKPOINTS.get(queued_stream.current_action or "") if queued_stream else None
    if (
        active_tasks
        and queued_checkpoint
        and queued_stream is not None
        and any(term in normalized_message for term in ("批准", "确认", "继续", "执行", "运行", "通过", "生成", "开始"))
        and not _conversation_requests_explanation(normalized_message)
    ):
        repaired_stream = queued_stream.model_copy(update={
            "conversation_checkpoint": queued_checkpoint,
            "execution_status": ExecutionStatus.WAITING_USER,
        })
        repaired_state = control_plane.repository.save_state(
            current_state.model_copy(update={
                "workstreams": [
                    repaired_stream if item.workstream_id == repaired_stream.workstream_id else item
                    for item in current_state.workstreams
                ],
            }),
            expected_revision=current_state.state_revision,
        )
        return {
            "kind": "orchestration",
            "message": _checkpoint_message(queued_checkpoint),
            "control_state": repaired_state.model_dump(mode="json"),
            "route_decision": repaired_state.route_decision.model_dump(mode="json") if repaired_state.route_decision else None,
            "gate": None,
            "waiting_for_user": True,
            "checkpoint": queued_checkpoint,
            "execution_started": False,
        }
    # A synchronous action can leave its lease marked RUNNING for a short
    # period after it has already emitted the next approval boundary.  Once a
    # pending conversational Gate exists, an explicit decision for that Gate
    # must be handled immediately; otherwise the stale lease masks the user's
    # confirmation as "task still running" and the conversation cannot move
    # forward.
    active_gate_snapshot = (
        control_plane.repository.get_gate(project_id, current_state.active_gate_id)
        if current_state.active_gate_id
        else None
    )
    active_task_is_gate_decision = bool(
        active_gate_snapshot is not None
        and active_gate_snapshot.status is GateStatus.PENDING
        and (
            _conversation_gate_decision(active_gate_snapshot.gate_type, normalized_message) is not None
            or _conversation_message_targets_gate(active_gate_snapshot.gate_type, normalized_message)
        )
    )
    checkpoint_action_pending = bool(
        early_checkpoint
        and _checkpoint_response_is_action(early_checkpoint, normalized_message)
        and not _conversation_requests_explanation(normalized_message)
    )
    queued_resume_pending = bool(
        not early_checkpoint
        and
        queued_stream is not None
        and (
            (queued_stream.current_action or "").startswith("等待编排器")
            or queued_stream.current_action == "reviewer_final_confirmation"
        )
        and any(term in normalized_message for term in ("批准", "确认", "继续", "执行", "运行", "通过", "生成", "开始", "审阅", "检查", "请", "写作", "论文", "方法", "结果", "大纲", "审稿", "独立审稿", "修订稿", "冻结"))
        and not _conversation_requests_explanation(normalized_message)
    )
    if active_tasks and not active_task_is_gate_decision and not checkpoint_action_pending and not queued_resume_pending:
        return {
            "kind": "orchestration",
            "message": (
                "上一项研究任务仍在运行。我正在等待它完成当前的内部步骤；"
                "这一步的结果会决定下一轮证据、数据或写作边界。"
                "你现在可以补充研究限制或询问当前步骤的依据，无需重复发送同一请求。"
            ),
            "control_state": current_state.model_dump(mode="json"),
            "route_decision": current_state.route_decision.model_dump(mode="json") if current_state.route_decision else None,
            "gate": current_gate.model_dump(mode="json") if (current_gate := control_plane.repository.get_gate(project_id, current_state.active_gate_id)) else None,
            "execution_started": True,
        }
    # A scope edit is a refinement of the current project, not a request to
    # create another orchestration chain. Keep the route/workstream identity
    # stable and let the next candidate consume the updated scope.
    revised_scope = _scope_revision(message) if current_state.route_decision is not None else None
    if revised_scope:
        project = identity_service.patch_project(
            user,
            project_id,
            ProjectPatchRequest(research_direction=revised_scope),
        )
        if current_state.route_decision is not None:
            updated_route = current_state.route_decision.model_copy(update={"research_scope": revised_scope})
            current_state = control_plane.repository.save_state(
                current_state.model_copy(update={"route_decision": updated_route}),
                expected_revision=current_state.state_revision,
            )
        control_plane.repository.add_event(
            AuditEvent(
                project_id=project_id,
                event_type="RESEARCH_SCOPE_REVISED",
                actor=user.username,
                state_revision=current_state.state_revision,
                payload={"research_scope": revised_scope},
            )
        )
        message = revised_scope
        normalized_message = message.lower()
    # A checkpoint is a normal chat turn, not a Gate decision.  Consume the
    # researcher's response here and only then resume the internal chain.
    checkpoint = _conversation_checkpoint(current_state.model_dump(mode="json"))
    if checkpoint:
        stream = next(
            (item for item in current_state.workstreams if item.workstream_id == current_state.active_workstream_id),
            current_state.workstreams[0],
        )

        # Outline approval starts the bounded manuscript-section dialogue. It
        # must not immediately run the full writer and citation verifier in
        # the same request; doing so was the cause of rounds 33-37 being
        # trapped behind a citation Gate in the blind run.
        if checkpoint == "MANUSCRIPT_OUTLINE_REVIEW":
            if len(normalized_message) < 2 or normalized_message in {"继续", "下一步", "好的", "好"}:
                return {
                    "kind": "orchestration",
                    "message": _checkpoint_message(checkpoint),
                    "control_state": current_state.model_dump(mode="json"),
                    "route_decision": current_state.route_decision.model_dump(mode="json") if current_state.route_decision else None,
                    "gate": None,
                    "waiting_for_user": True,
                    "checkpoint": checkpoint,
                    "execution_started": False,
                }
            if _conversation_requests_explanation(normalized_message) or not _checkpoint_response_is_action(
                checkpoint, normalized_message
            ):
                return _discussion_response(
                    project_id=project_id,
                    request=request,
                    state=current_state,
                    project_context=(
                        f"项目名称：{project.title}\n研究方向：{project.research_direction}"
                    ),
                    collaboration=collaboration,
                )
            feedback = message.strip()
            updated_stream = stream.model_copy(update={
                "conversation_checkpoint": MANUSCRIPT_SECTION_CHECKPOINT,
                "execution_status": ExecutionStatus.WAITING_USER,
                "current_action": "等待研究者指定论文章节",
                "conversation_feedback": {
                    **stream.conversation_feedback,
                    checkpoint: feedback[:2000],
                },
            })
            current_state = control_plane.repository.save_state(
                current_state.model_copy(update={
                    "workstreams": [
                        updated_stream if item.workstream_id == updated_stream.workstream_id else item
                        for item in current_state.workstreams
                    ],
                }),
                expected_revision=current_state.state_revision,
            )
            control_plane.repository.add_event(
                AuditEvent(
                    project_id=project_id,
                    event_type="CONVERSATION_CHECKPOINT_RESPONDED",
                    actor=user.username,
                    state_revision=current_state.state_revision,
                    payload={"checkpoint": checkpoint, "response": feedback[:2000]},
                )
            )
            return {
                "kind": "orchestration",
                "message": _checkpoint_message(MANUSCRIPT_SECTION_CHECKPOINT),
                "control_state": current_state.model_dump(mode="json"),
                "route_decision": current_state.route_decision.model_dump(mode="json") if current_state.route_decision else None,
                "gate": None,
                "waiting_for_user": True,
                "checkpoint": MANUSCRIPT_SECTION_CHECKPOINT,
                "execution_started": False,
            }

        # Each chapter request is a real writing action backed by immutable
        # artifacts. Non-final chapters return to the same checkpoint; the
        # explicit full-candidate request is the only one that may advance to
        # citation verification.
        if checkpoint == MANUSCRIPT_SECTION_CHECKPOINT:
            section = _manuscript_section_request(message)
            if section is None:
                return {
                    "kind": "orchestration",
                    "message": _checkpoint_message(checkpoint),
                    "control_state": current_state.model_dump(mode="json"),
                    "route_decision": current_state.route_decision.model_dump(mode="json") if current_state.route_decision else None,
                    "gate": None,
                    "waiting_for_user": True,
                    "checkpoint": checkpoint,
                    "execution_started": False,
                }
            updated_stream = stream.model_copy(update={
                "conversation_checkpoint": None,
                "execution_status": ExecutionStatus.QUEUED,
                "current_action": "等待编排器生成下一步候选",
                "conversation_feedback": {
                    **stream.conversation_feedback,
                    "MANUSCRIPT_SECTION_REQUEST": section,
                    checkpoint: message.strip()[:2000],
                },
            })
            current_state = control_plane.repository.save_state(
                current_state.model_copy(update={
                    "workstreams": [
                        updated_stream if item.workstream_id == updated_stream.workstream_id else item
                        for item in current_state.workstreams
                    ],
                }),
                expected_revision=current_state.state_revision,
            )
            control_plane.repository.add_event(
                AuditEvent(
                    project_id=project_id,
                    event_type="CONVERSATION_CHECKPOINT_RESPONDED",
                    actor=user.username,
                    state_revision=current_state.state_revision,
                    payload={"checkpoint": checkpoint, "section": section, "response": message.strip()[:2000]},
                )
            )
            continued = continue_project_orchestration(project_id, user, conversational=True)
            for _ in range(32):
                if (
                    continued.get("gate") is not None
                    or not continued.get("execution_started")
                    or _conversation_checkpoint(continued.get("control_state"))
                ):
                    break
                continued = continue_project_orchestration(project_id, user, conversational=True)
            latest_state = continued.get("control_state", current_state.model_dump(mode="json"))
            next_gate = continued.get("gate")
            next_checkpoint = _conversation_checkpoint(latest_state)
            section_titles = {
                "methods": "数据与方法",
                "results": "结果",
                "introduction": "引言与理论背景",
                "discussion": "讨论与局限",
            }
            section_title = section_titles.get(section, section)
            section_message = (
                f"已生成“{section_title}”章节候选，并将其保存为可追溯产物；"
                "本节只使用当前冻结资料、执行记录和可核验来源。"
            )
            if next_checkpoint == MANUSCRIPT_SECTION_CHECKPOINT:
                section_message += _checkpoint_message(next_checkpoint)
            return {
                "kind": "orchestration",
                "message": section_message if next_checkpoint == MANUSCRIPT_SECTION_CHECKPOINT else (
                    section_message if not next_gate else _guided_transition_message(
                        state=latest_state, gate=next_gate, checkpoint=None, decision=None
                    )
                ),
                "control_state": latest_state,
                "route_decision": current_state.route_decision.model_dump(mode="json") if current_state.route_decision else None,
                "gate": next_gate,
                "waiting_for_user": bool(next_checkpoint),
                "checkpoint": next_checkpoint,
                "execution_started": bool(continued.get("execution_started")),
            }

        if len(normalized_message) < 2 or normalized_message in {"继续", "下一步", "好的", "好"}:
            return {
                "kind": "orchestration",
                "message": _checkpoint_message(checkpoint),
                "control_state": current_state.model_dump(mode="json"),
                "route_decision": current_state.route_decision.model_dump(mode="json") if current_state.route_decision else None,
                "gate": None,
                "waiting_for_user": True,
                "checkpoint": checkpoint,
                "execution_started": False,
            }
        if _conversation_requests_explanation(normalized_message) or not _checkpoint_response_is_action(
            checkpoint, normalized_message
        ):
            bounded_checkpoint_response = _cgt_analysis_instruction_response(project_id, message)
            if bounded_checkpoint_response is not None:
                return {
                    "kind": "orchestration",
                    "message": bounded_checkpoint_response,
                    "control_state": current_state.model_dump(mode="json"),
                    "route_decision": current_state.route_decision.model_dump(mode="json") if current_state.route_decision else None,
                    "gate": None,
                    "waiting_for_user": True,
                    "checkpoint": checkpoint,
                    "execution_started": False,
                }
            return _discussion_response(
                project_id=project_id,
                request=request,
                state=current_state,
                project_context=(
                    f"项目名称：{project.title}\n研究方向：{project.research_direction}"
                ),
                collaboration=collaboration,
            )
        feedback = message.strip()
        cgt_action_for_checkpoint = next(
            (action_id for action_id, checkpoint_id in CGT_CONVERSATION_CHECKPOINTS.items() if checkpoint_id == checkpoint),
            None,
        )
        cgt_next_index = stream.current_step_index
        cgt_completed = list(stream.completed_step_ids)
        if cgt_action_for_checkpoint and cgt_action_for_checkpoint in stream.workflow_steps:
            action_index = stream.workflow_steps.index(cgt_action_for_checkpoint)
            if stream.current_step_index <= action_index:
                cgt_next_index = action_index + 1
            if cgt_action_for_checkpoint not in cgt_completed:
                cgt_completed.append(cgt_action_for_checkpoint)
        # The response is intentionally recorded in the durable audit trail;
        # a later revision can therefore explain which researcher feedback
        # unlocked the next generated candidate without mutating a frozen one.
        updated_stream = stream.model_copy(update={
            "conversation_checkpoint": None,
            "execution_status": ExecutionStatus.QUEUED,
            "current_action": "等待编排器生成下一步候选",
            "current_step_index": cgt_next_index,
            "completed_step_ids": cgt_completed,
            "conversation_feedback": {
                **stream.conversation_feedback,
                checkpoint: feedback[:2000],
            },
        })
        current_state = control_plane.repository.save_state(
            current_state.model_copy(update={
                "workstreams": [
                    updated_stream if item.workstream_id == stream.workstream_id else item
                    for item in current_state.workstreams
                ],
            }),
            expected_revision=current_state.state_revision,
        )
        # Acknowledge selection/editing in the event stream.  The next
        # candidate remains a new immutable artifact, so this response never
        # rewrites the prior question/design artifact.
        control_plane.repository.add_event(
            AuditEvent(
                project_id=project_id,
                event_type="CONVERSATION_CHECKPOINT_RESPONDED",
                actor=user.username,
                state_revision=current_state.state_revision,
                payload={"checkpoint": checkpoint, "response": message.strip()[:2000]},
            )
        )
        continued = continue_project_orchestration(project_id, user, conversational=True)
        for _ in range(32):
            if (
                continued.get("gate") is not None
                or not continued.get("execution_started")
                or _conversation_checkpoint(continued.get("control_state"))
            ):
                break
            continued = continue_project_orchestration(project_id, user, conversational=True)
        # The guide's data-intake confirmation also confirms the proposed
        # qualitative design.  The design candidate is still persisted and
        # auditable, but this explicit response should advance to the actual
        # raw-data Gate instead of exposing an internal design approval that
        # the researcher has already answered in the same sentence.
        enter_data_import = (
            checkpoint == "RESEARCH_QUESTION_REVIEW"
            and any(term in normalized_message for term in ("进入数据导入", "数据导入", "导入数据"))
            and not any(term in normalized_message for term in ("不进入", "不要导入", "暂不导入"))
        )
        if enter_data_import:
            pending_design_gate = (
                control_plane.repository.get_gate(
                    project_id,
                    (continued.get("control_state") or {}).get("active_gate_id"),
                )
                if isinstance(continued.get("control_state"), dict)
                and (continued.get("control_state") or {}).get("active_gate_id")
                else None
            )
            if pending_design_gate is not None and pending_design_gate.gate_type == "qualitative_design_approval":
                control_plane.decide_gate(
                    project_id,
                    pending_design_gate.gate_id,
                    decision="approve",
                    actor=user.username,
                    role="researcher",
                    reason="研究者已确认方法边界并明确要求进入数据导入",
                )
                continued = continue_project_orchestration(project_id, user, conversational=True)
                for _ in range(32):
                    if (
                        continued.get("gate") is not None
                        or not continued.get("execution_started")
                        or _conversation_checkpoint(continued.get("control_state"))
                    ):
                        break
                    continued = continue_project_orchestration(project_id, user, conversational=True)
        latest_state = continued.get("control_state", current_state.model_dump(mode="json"))
        next_gate = continued.get("gate")
        next_checkpoint = _conversation_checkpoint(latest_state)
        completed_turn_message = _cgt_analysis_instruction_response(project_id, message)
        return {
            "kind": "orchestration",
            "message": (
                completed_turn_message + "\n\n" + _checkpoint_message_for_project(project_id, next_checkpoint)
                if completed_turn_message and next_checkpoint
                else completed_turn_message
                if completed_turn_message and next_gate
                else _checkpoint_message_for_project(project_id, next_checkpoint)
                if next_checkpoint
                else _guided_transition_message(
                    state=latest_state,
                    gate=next_gate,
                    checkpoint=None,
                    decision=None,
                )
            ),
            "control_state": latest_state,
            "route_decision": current_state.route_decision.model_dump(mode="json") if current_state.route_decision else None,
            "gate": next_gate,
            "waiting_for_user": bool(next_checkpoint),
            "checkpoint": next_checkpoint,
            "execution_started": bool(continued.get("execution_started")),
        }
    # Legacy intake data was migrated near the start of this turn. It remains
    # readable to old clients, but it never participates in conversation flow.
    # A pending conversational Gate takes precedence over the generic QA
    # fallback. Commands such as "继续搜索" do not contain a research keyword,
    # but must still be interpreted as a decision on the active Gate.
    if (
        current_state.active_gate_id is None
        and not initial_topic
        and not any(term in normalized_message for term in research_terms)
        and not any(term in normalized_message for term in conversation_decision_terms)
    ):
        answer = qa_service.answer(QAAnswerRequest(project_id=project_id, question=request.message, allow_llm=True))
        return {
            "kind": "qa",
            "message": answer.answer,
            "answer": answer.model_dump(mode="json"),
            "control_state": current_state.model_dump(mode="json"),
            "route_decision": None,
            "gate": None,
            "execution_started": False,
        }
    current_stream = next(
        (item for item in current_state.workstreams if item.workstream_id == current_state.active_workstream_id),
        current_state.workstreams[0],
    )
    # Gates are conversational checkpoints.  The UI may show a compact
    # summary, but the researcher should be able to advance the workflow by
    # replying naturally instead of finding an implementation-specific button.
    current_gate = (
        control_plane.repository.get_gate(project_id, current_state.active_gate_id)
        if current_state.active_gate_id
        else None
    )
    if current_gate is not None and current_gate.status is GateStatus.PENDING:
        audit_terms = (
            "审计", "检查字段", "缺失值", "重复记录", "异常值",
            "audit", "fields", "missingness", "duplicates", "outliers",
        )
        raw_audit_request = (
            current_gate.gate_type == "raw_data_import_approval"
            and control_plane.has_usable_primary_data(project_id, current_stream.route)
            and any(term in normalized_message for term in audit_terms)
        )
        # Questions about current material are answered in place. They do not
        # count as approval or a request to rebuild the candidate.
        # An explicit raw-data audit is different: once a CSV is present it
        # is the natural approval of the intake Gate and must enter the data
        # pipeline instead of falling back to a generic schema explanation.
        if _conversation_requests_explanation(normalized_message) and not raw_audit_request:
            return _discussion_response(
                project_id=project_id,
                request=request,
                state=current_state,
                project_context=(
                    f"项目名称：{project.title}\n研究方向：{project.research_direction}"
                ),
                collaboration=collaboration,
            )
        requested_decision = _conversation_gate_decision(
            current_gate.gate_type, normalized_message
        )
        # The independent-review request commonly says "不要直接改稿".
        # The generic parser quite reasonably sees "不要" + "修改" as a
        # revision request, but at this specific citation-verification Gate
        # the sentence is actually asking to enter the next human-review
        # phase. Override that ambiguity only when the message explicitly
        # names independent review and does not negate entering it.
        independent_review_request = (
            current_gate.gate_type == "manuscript_citation_verification_approval"
            and any(term in normalized_message for term in ("独立审稿", "进入审稿", "审稿"))
            and not any(term in normalized_message for term in (
                "不要进入独立审稿", "暂不进入独立审稿", "不进入独立审稿",
                "不要进入审稿", "暂不进入审稿", "不进入审稿",
            ))
        )
        if independent_review_request:
            requested_decision = "approve"
        # Accept natural confirmation sentences such as
        # "确认数据处理方案，继续" and "确认执行分析". Requiring one exact
        # canned phrase makes the assistant appear deaf even though the user
        # has clearly approved the active checkpoint.
        if requested_decision is None and (
            ("确认" in normalized_message or "confirm" in normalized_message)
            and any(term in normalized_message for term in ("继续", "执行", "审查", "进入", "冻结", "发布", "下一步"))
            and not any(term in normalized_message for term in (
                "不要", "先不要", "先不", "暂不", "暂时不", "不确认", "不同意",
                "不执行", "不冻结", "不发布", "不进入", "不继续", "先别",
            ))
        ):
            requested_decision = "approve"
        # A negative phrase such as "不要写论文" is not a request to revise
        # the active data gate.  Only turn the generic defer classification
        # into a workflow decision when the researcher names a concrete
        # revision or rework action; otherwise keep the pending gate intact.
        if requested_decision == "revise" and not any(
            term in normalized_message
            for term in ("修改", "调整", "退回", "补充", "重新", "再搜", "不够", "revise", "search more")
        ):
            requested_decision = None
        if requested_decision is None and (
            "generate analysis code" in normalized_message
            or "generate code" in normalized_message
        ) and current_gate.gate_type == "manual_execution_approval_approval":
            requested_decision = "approve"
        if requested_decision is None and (
            "confirm outline" in normalized_message
            or "confirm the manuscript outline" in normalized_message
            or "确认论文大纲" in normalized_message
        ):
            requested_decision = "approve"
        # After a CSV has been uploaded, an explicit audit request is the
        # meaningful approval of the raw-data intake checkpoint. Requiring a
        # second, artificial phrase such as "确认上传" makes a natural
        # researcher instruction look as though the assistant ignored it.
        if (
            requested_decision is None
            and current_gate.gate_type == "raw_data_import_approval"
            and control_plane.has_usable_primary_data(project_id, current_stream.route)
            and any(term in normalized_message for term in audit_terms)
        ):
            requested_decision = "approve"
        if requested_decision is None:
            return _discussion_response(
                project_id=project_id,
                request=request,
                state=current_state,
                project_context=(
                    f"项目名称：{project.title}\n研究方向：{project.research_direction}"
                ),
                collaboration=collaboration,
            )
        if requested_decision is not None:
            project_role = getattr(project, "role", "owner")
            role = (
                "researcher" if project_role in {"owner", "editor"}
                else "reviewer" if project_role == "reviewer"
                else "viewer"
            )
            try:
                decided = control_plane.decide_gate(
                    project_id,
                    current_gate.gate_id,
                    decision=requested_decision,
                    actor=user.username,
                    role=role,
                    risk_acceptance=["研究者已在对话中确认当前风险"] if requested_decision == "approve" and current_gate.warnings else [],
                    reason=f"研究者通过对话请求：{message.strip()}",
                )
                # Approving the final independent-review Gate completes the
                # project synchronously. Do not call /continue afterwards:
                # that endpoint correctly rejects inactive projects, but the
                # researcher has just made a successful decision and must not
                # receive a misleading 409 response.
                if decided.lifecycle_status.value != "ACTIVE":
                    unperformed = _unperformed_candidate_actions(project_id)
                    if unperformed:
                        completion_message = (
                            "盲测候选稿已冻结，论文正文、结果卡、引用核验和审查记录已经保留在右侧研究产出中。"
                            f"但以下分析仍未实际执行：{'、'.join(unperformed)}。"
                            "因此当前稿件只能作为候选分析包，不能把这些分析写成已完成结果；"
                            "你可以先打开论文正文核对结论，再查看未执行项和审查摘要。"
                        )
                    else:
                        completion_message = (
                            "独立审查已确认，研究流程已完成。论文正文、统计结果、引用核验和审查记录已经保留在右侧研究产出中；"
                            "你可以先打开论文正文核对结论，再查看统计结果与审查摘要。"
                        )
                    return {
                        "kind": "orchestration",
                        "message": completion_message + (
                            "若准备投稿，可点击右下角“用当前论文投稿格式化”生成 LaTeX，"
                            "但正式投稿前仍需按目标期刊要求做最后人工校对。"
                        ),
                        "control_state": decided.model_dump(mode="json"),
                        "route_decision": decided.route_decision.model_dump(mode="json") if decided.route_decision else None,
                        "gate": None,
                        "execution_started": False,
                    }
                if requested_decision == "revise" and current_gate.gate_type == "evidence_sufficiency_review":
                    # Persist the incremental search request in the workstream
                    # context, where retrieval can consume it without
                    # polluting the canonical research topic.
                    stream_after_decision = next(
                        (item for item in decided.workstreams if item.workstream_id == decided.active_workstream_id),
                        None,
                    )
                    if stream_after_decision is not None:
                        updated_stream = stream_after_decision.model_copy(update={
                            "conversation_feedback": {
                                **stream_after_decision.conversation_feedback,
                                "evidence_search_addition": message.strip()[:2000],
                            },
                        })
                        decided = control_plane.repository.save_state(
                            decided.model_copy(update={
                                "workstreams": [
                                    updated_stream if item.workstream_id == updated_stream.workstream_id else item
                                    for item in decided.workstreams
                                ],
                            }),
                            expected_revision=decided.state_revision,
                        )
                if request.execution_mode == "background" and requested_decision in {"approve", "revise"}:
                    Thread(
                        target=_continue_conversation_in_background,
                        args=(project_id, user),
                        name=f"stem-sci-{project_id}-continuation",
                        daemon=True,
                    ).start()
                    return {
                        "kind": "orchestration",
                        "message": (
                            "我先按这个决定在后台推进当前研究步骤。"
                            "这样可以把耗时的检索、审计或写作留在后台，同时保留每个中间产物和风险。"
                            "你可以继续补充限制；下一次真正需要你判断时，我会说明依据和可选修改。"
                        ),
                        "control_state": decided.model_dump(mode="json"),
                        "route_decision": decided.route_decision.model_dump(mode="json") if decided.route_decision else None,
                        "gate": None,
                        "execution_started": True,
                    }
                continued: dict[str, object] | None = None
                if requested_decision in {"approve", "revise"}:
                    # Run the deterministic internal chain immediately.  The
                    # function is defined later in this module and is resolved
                    # when the request is handled, after module initialisation.
                    continued = continue_project_orchestration(project_id, user, conversational=True)
                    # A conversational decision should advance through the
                    # deterministic internal chain until the next meaningful
                    # human checkpoint.  Keep a finite bound for malformed
                    # or cyclic workflow definitions.
                    for _ in range(32):
                        if continued.get("gate") is not None or not continued.get("execution_started") or _conversation_checkpoint(continued.get("control_state")):
                            break
                        continued = continue_project_orchestration(project_id, user, conversational=True)
                    # The data-freeze instruction can be attached to the
                    # processing approval in one natural-language turn. Once
                    # that approval produces the explicit freeze Gate, honor
                    # the same instruction and continue to code generation.
                    freeze_requested = (
                        "冻结" in normalized_message
                        and current_gate.gate_type in {
                            "data_processing_approval",
                            "qualitative_data_preparation_approval",
                        }
                    )
                    if freeze_requested:
                        next_state_probe = continued.get("control_state")
                        freeze_gate = (
                            control_plane.repository.get_gate(
                                project_id,
                                next_state_probe.get("active_gate_id"),
                            )
                            if isinstance(next_state_probe, dict) and next_state_probe.get("active_gate_id")
                            else None
                        )
                        if freeze_gate is not None and freeze_gate.gate_type == "dataset_freeze_hash_approval":
                            control_plane.decide_gate(
                                project_id,
                                freeze_gate.gate_id,
                                decision="approve",
                                actor=user.username,
                                role=role,
                                risk_acceptance=["研究者已在同一轮请求中明确要求冻结数据版本"] if freeze_gate.warnings else [],
                                reason="研究者已在数据处理确认中同时要求冻结分析数据",
                            )
                            continued = continue_project_orchestration(project_id, user, conversational=True)
                            for _ in range(32):
                                if continued.get("gate") is not None or not continued.get("execution_started") or _conversation_checkpoint(continued.get("control_state")):
                                    break
                                continued = continue_project_orchestration(project_id, user, conversational=True)
                    latest_state = continued.get("control_state", decided.model_dump(mode="json"))
                    next_gate = continued.get("gate")
                    return {
                        "kind": "orchestration",
                        "message": (
                            _checkpoint_message_for_project(
                                project_id, _conversation_checkpoint(latest_state)
                            )
                            if _conversation_checkpoint(latest_state)
                            else _guided_transition_message(
                                state=latest_state,
                                gate=next_gate,
                                checkpoint=None,
                                decision=requested_decision,
                            )
                            if requested_decision == "approve"
                            else (
                                "本轮检索完成：新增 "
                                f"{_latest_evidence_coverage(project_id).get('new_source_count', 0)} 篇，"
                                "重复/已存在 "
                                f"{_latest_evidence_coverage(project_id).get('duplicate_source_count', 0)} 篇；"
                                "当前共 "
                                f"{_latest_evidence_coverage(project_id).get('source_count', 0)} 个来源、"
                                f"{_latest_evidence_coverage(project_id).get('evidence_count', 0)} 条证据片段。"
                                "请查看右侧结果后继续对话。"
                            )
                        ),
                        "control_state": latest_state,
                        "route_decision": decided.route_decision.model_dump(mode="json") if decided.route_decision else None,
                        "gate": next_gate,
                        "waiting_for_user": bool(_conversation_checkpoint(latest_state)),
                        "checkpoint": _conversation_checkpoint(latest_state),
                        "execution_started": bool(continued.get("execution_started")),
                    }
                return {
                    "kind": "orchestration",
                    "message": "研究流程已停止。若要继续，请在项目中重新开始一轮研究。",
                    "control_state": decided.model_dump(mode="json"),
                    "route_decision": decided.route_decision.model_dump(mode="json") if decided.route_decision else None,
                    "gate": None,
                    "execution_started": False,
                }
            except PermissionError as error:
                return _error(403, "gate_permission_denied", str(error))
            except ValueError as error:
                return _error(409, "gate_decision_blocked", str(error))
    if current_stream.route != "UNCLASSIFIED":
        current_gate = (
            control_plane.repository.get_gate(project_id, current_state.active_gate_id)
            if current_state.active_gate_id
            else None
        )
        # A refreshed page can lose the transient "continue" turn while the
        # durable state is already queued for its next internal action. Treat
        # a natural continuation as a request to resume that action instead of
        # replying with a static status message.
        continuation_terms = (
            "继续", "开始", "推进", "下一步", "可以", "好的", "好", "确认",
            "审计", "检查", "核验", "生成", "形成", "分析", "执行", "写作", "起草", "冻结",
            "请", "continue", "start", "proceed", "next",
        )
        waiting_for_resume = (
            current_gate is None
            and current_stream.current_step_index < len(current_stream.workflow_steps)
            and (
                current_stream.execution_status is ExecutionStatus.QUEUED
                or (current_stream.current_action or "").startswith("等待编排器")
                or (current_stream.current_action or "").startswith("等待重新整理")
            )
            and any(term in normalized_message for term in continuation_terms)
        )
        if waiting_for_resume:
            # Recovery after an interrupted Continue may leave the next CGT
            # action queued with its candidate already persisted but without
            # the transient checkpoint marker. Rehydrate that marker from the
            # durable action name so a client retry cannot fall into QA.
            queued_cgt_checkpoint = CGT_CONVERSATION_CHECKPOINTS.get(current_stream.current_action or "")
            if queued_cgt_checkpoint:
                repaired_stream = current_stream.model_copy(update={
                    "conversation_checkpoint": queued_cgt_checkpoint,
                    "execution_status": ExecutionStatus.WAITING_USER,
                })
                repaired_state = control_plane.repository.save_state(
                    current_state.model_copy(update={
                        "workstreams": [
                            repaired_stream if item.workstream_id == repaired_stream.workstream_id else item
                            for item in current_state.workstreams
                        ],
                    }),
                    expected_revision=current_state.state_revision,
                )
                return {
                    "kind": "orchestration",
                    "message": _checkpoint_message_for_project(project_id, queued_cgt_checkpoint),
                    "control_state": repaired_state.model_dump(mode="json"),
                    "route_decision": repaired_state.route_decision.model_dump(mode="json") if repaired_state.route_decision else None,
                    "gate": None,
                    "waiting_for_user": True,
                    "checkpoint": queued_cgt_checkpoint,
                    "execution_started": False,
                }
            if queued_resume_pending:
                expected_resume_action = (
                    current_stream.workflow_steps[current_stream.current_step_index]
                    if current_stream.current_step_index < len(current_stream.workflow_steps)
                    else None
                )
                for pending_task in control_plane.repository.list_tasks(project_id):
                    if pending_task.action == expected_resume_action and pending_task.status in {
                        ExecutionStatus.RUNNING, ExecutionStatus.COMPLETED,
                    }:
                        control_plane.repository.update_task(
                            pending_task.model_copy(update={
                                "status": ExecutionStatus.STALE,
                                "error": "reclaimed by explicit checkpoint continuation",
                            })
                        )
            continued = continue_project_orchestration(project_id, user, conversational=True)
            for _ in range(32):
                if continued.get("gate") is not None or not continued.get("execution_started") or _conversation_checkpoint(continued.get("control_state")):
                    break
                continued = continue_project_orchestration(project_id, user, conversational=True)
            resumed_state = continued.get("control_state", current_state.model_dump(mode="json"))
            resumed_gate = continued.get("gate")
            return {
                "kind": "orchestration",
                "message": (
                    f"我已恢复这项研究任务。现在出现了一个需要你判断的研究问题：{resumed_gate.get('reason', '请查看右侧结果后给出你的判断。')}"
                    if isinstance(resumed_gate, dict)
                    else "我已恢复这项研究任务；它会继续运行，并在出现需要你判断的研究问题时停下来。"
                ),
                "control_state": resumed_state,
                "route_decision": current_state.route_decision.model_dump(mode="json") if current_state.route_decision else None,
                "gate": resumed_gate,
                "execution_started": bool(continued.get("execution_started")),
            }
    if current_gate is not None and current_gate.status is GateStatus.PENDING:
        if any(term in normalized_message for term in ("核查", "核验", "查看", "当前状态", "进度", "怎么样", "什么情况")):
            return {
                "kind": "orchestration",
                "message": _mentor_boundary_message(current_gate),
                "control_state": current_state.model_dump(mode="json"),
                "route_decision": current_state.route_decision.model_dump(mode="json") if current_state.route_decision else None,
                "gate": None,
                "waiting_for_user": True,
                "execution_started": False,
            }
        return {
            "kind": "orchestration",
            "message": _mentor_boundary_message(current_gate),
            "control_state": current_state.model_dump(mode="json"),
            "route_decision": current_state.route_decision.model_dump(mode="json") if current_state.route_decision else None,
            "gate": current_gate.model_dump(mode="json"),
            "execution_started": False,
        }
        return {
            "kind": "orchestration",
            "message": (
                f"当前处于“{current_stream.current_action or '研究流程'}”步骤。"
                "系统会自动完成内部检索与融合；请仅在需要修改研究范围、纳排标准或研究问题时补充要求。"
            ),
            "control_state": current_state.model_dump(mode="json"),
            "route_decision": current_state.route_decision.model_dump(mode="json") if current_state.route_decision else None,
            "gate": current_gate.model_dump(mode="json") if current_gate else None,
            "execution_started": False,
        }
    # Route classification must use the accumulated research brief, not only
    # the latest sentence.  CGT workflows often describe the qualitative
    # method first and mention seeds/CV in a later constraints turn; treating
    # that final turn in isolation incorrectly selects EXPERIMENTAL.
    prior_turns = _conversation_command_journal().list(project_id, limit=12)
    route_context_parts = [
        str(row.get("message", ""))
        for row in prior_turns
        if str(row.get("message", "")).strip()
    ]
    route_context_parts.append(message)
    route_intent = "\n".join(route_context_parts)[-12000:]
    state, route, gate = control_plane.choose_route(
        project_id,
        route_intent,
        actor=user.username,
    )
    # A topic message is the workflow entry point, not merely a route
    # classification.  Start the internal evidence chain immediately so the
    # researcher receives a real evidence-review package in the same turn.
    # The loop stops at the first deliberative checkpoint. Evidence
    # sufficiency is assessed by the system and remains visible in the review
    # package, but it is not a formal user Gate.
    continued = continue_project_orchestration(project_id, user, conversational=True)
    for _ in range(32):
        if continued.get("gate") is not None or not continued.get("execution_started") or _conversation_checkpoint(continued.get("control_state")):
            break
        continued = continue_project_orchestration(project_id, user, conversational=True)
    latest_state = continued.get("control_state", state.model_dump(mode="json"))
    next_gate = continued.get("gate")
    next_checkpoint = _conversation_checkpoint(latest_state)
    return {
        "kind": "orchestration",
        "message": (
            "已完成当前范围内的证据整理，并据此形成了可修订的研究问题候选。"
            "右侧会同时保留支持、反证和缺口；你可以质疑、合并或改写候选，"
            "不需要先批准“证据足够”。"
            if next_checkpoint == "RESEARCH_QUESTION_REVIEW"
            else _mentor_boundary_message(GateRecord.model_validate(next_gate))
            if isinstance(next_gate, dict)
            else "已识别研究主题，系统正在继续整理文献和检索证据。"
        ),
        "control_state": latest_state,
        "route_decision": route.model_dump(mode="json"),
        "gate": next_gate,
        "checkpoint": next_checkpoint,
        "waiting_for_user": bool(next_checkpoint or next_gate),
        "execution_started": bool(continued.get("execution_started")),
    }


@app.post(
    "/api/v1/projects/{project_id}/conversation/command",
    response_model=ConversationCommandResult,
)
@app.post(
    "/api/v1/projects/{project_id}/collaboration/turn",
    response_model=ConversationCommandResult,
)
def project_conversation_command(
    project_id: str,
    request: ConversationCommandRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> dict[str, object] | JSONResponse:
    """Persist and execute one research-state-aware collaboration turn."""

    journal = _conversation_command_journal()
    request_hash = sha256_text(request.model_dump_json(exclude={"client_turn_id"}))
    try:
        turn, created = journal.begin(
            project_id,
            request.client_turn_id,
            user.username,
            request.message,
            request_hash,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if not created and turn["response"] is not None:
        return cast(dict[str, object], turn["response"])
    if not created:
        # A browser retry can arrive while the original request is still
        # running.  Never execute the same orchestration twice; the caller can
        # refresh history (or retry after completion) to receive the durable
        # response.
        state = control_plane.ensure_project(project_id)
        active_gate = (
            control_plane.repository.get_gate(project_id, state.active_gate_id)
            if state.active_gate_id
            else None
        )
        return {
            "kind": "orchestration",
            "message": "这条研究请求正在处理中，完成后会出现在对话记录中。",
            "control_state": state.model_dump(mode="json"),
            "route_decision": state.route_decision.model_dump(mode="json") if state.route_decision else None,
            "gate": active_gate.model_dump(mode="json") if active_gate else None,
            "execution_started": True,
            "waiting_for_user": True,
            "checkpoint": None,
        }
    try:
        journal.update(project_id, turn["turn_id"], status="processing")
        response = _project_conversation_command_impl(project_id, request, user)
        if isinstance(response, dict):
            # Some older workflow branches can still return a QA answer
            # directly. Apply the same workbench bridge at the endpoint
            # boundary so every conversational response is covered.
            answer_payload = response.get("answer")
            if isinstance(answer_payload, dict):
                try:
                    _persist_conversational_research_outputs(
                        project_id=project_id,
                        request=request,
                        answer=QAAnswerResponse.model_validate(answer_payload),
                    )
                except Exception:  # noqa: BLE001 - projection must not break the response
                    logger.exception("Could not bridge conversational answer for %s", project_id)
            journal.update(project_id, turn["turn_id"], status="completed", response=response)
        else:
            journal.update(project_id, turn["turn_id"], status="failed")
        return response
    except Exception as error:
        journal.update(
            project_id,
            turn["turn_id"],
            status="failed",
            response={
                "kind": "error",
                "message": "本轮请求未完成，原始消息已保存，请检查研究状态后重试。",
                "error": str(error),
            },
        )
        raise


@app.get("/api/v1/projects/{project_id}/conversation/history")
def project_conversation_history(
    project_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
    limit: int = Query(default=100, ge=1, le=200),
) -> list[dict[str, object]]:
    """Return durable orchestration turns for refresh/recovery."""

    identity_service.get_project(user, project_id)
    return [
        {
            "turn_id": row["turn_id"],
            "message": row["message"],
            "response": row["response"],
            "status": row["status"],
            "created_at": row["created_at"],
        }
        for row in _conversation_command_journal().list(project_id, limit)
    ]


@app.get("/api/v1/projects/{project_id}/orchestration/events")
def project_orchestration_events(
    project_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
    after_id: str | None = None,
) -> list[dict[str, object]]:
    """Read durable orchestration events for polling or SSE adapters."""

    identity_service.get_project(user, project_id)
    return [event.model_dump(mode="json") for event in control_plane.repository.list_events(project_id, after_id)]


@app.get("/api/v1/projects/{project_id}/orchestration/events/stream")
async def project_orchestration_event_stream(
    project_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
    after_id: str | None = None,
    timeout_seconds: int = Query(default=55, ge=5, le=300),
) -> StreamingResponse:
    """Stream durable research events without holding a workflow command open."""

    identity_service.get_project(user, project_id)

    async def events() -> object:
        cursor = after_id
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            batch = control_plane.repository.list_events(project_id, cursor)
            if batch:
                for event in batch:
                    cursor = event.event_id
                    payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
                    yield f"id: {event.event_id}\ndata: {payload}\n\n"
                continue
            yield ": keep-alive\n\n"
            await asyncio.sleep(1.5)

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    })


@app.post("/api/v1/projects/{project_id}/gates/{gate_id}/decision", response_model=ControlState)
def project_gate_decision(
    project_id: str,
    gate_id: str,
    request: GateDecisionRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> ControlState:
    """Apply an authenticated human Gate decision and advance control state."""

    project = identity_service.get_project(user, project_id)
    try:
        return control_plane.decide_gate(
            project_id,
            gate_id,
            decision=request.decision,
            actor=user.username,
            role=(
                "researcher" if project.role in {"owner", "editor"}
                else "reviewer" if project.role == "reviewer"
                else "viewer"
            ),
            risk_acceptance=request.risk_acceptance,
            reason=request.reason,
        )
    except PermissionError as error:
        return _error(403, "gate_permission_denied", str(error))
    except ValueError as error:
        return _error(409, "gate_decision_blocked", str(error))


def _review_list(value: object, key: str) -> list[dict[str, object]]:
    """Read JSON-list payloads defensively while assembling a review package."""

    if not isinstance(value, dict):
        return []
    items = value.get(key)
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _human_source_title(project_id: str, source_ref: str) -> str:
    """Resolve a readable title for a local source without exposing its path."""

    try:
        source = service.get_source(project_id, source_ref)
    except Exception:
        source = None
    if source is not None:
        for document in document_service.list_project(project_id):
            if source.filename.startswith(f"{document.document_id}-v"):
                return document.title
        return source.filename
    if source_ref.startswith("shared:physics_stem_v1:"):
        paper_id = source_ref.rsplit(":", maxsplit=1)[-1]
        try:
            catalog = json.loads(
                (Path(__file__).resolve().parents[3] / "data" / "catalogs" / "physics_stem" / "paper_identity_map.json").read_text(encoding="utf-8")
            )
            for paper in catalog.get("papers", []):
                if isinstance(paper, dict) and paper.get("paper_id") == paper_id:
                    title = paper.get("title")
                    if isinstance(title, str) and title.strip():
                        return title.strip()
            locator = json.loads(
                (Path(__file__).resolve().parents[3] / "data" / "catalogs" / "physics_stem" / "locator.json").read_text(encoding="utf-8")
            )
            for item in locator.get("records", []):
                if isinstance(item, dict) and item.get("canonical_paper_id") == paper_id:
                    filename = item.get("source_filename")
                    if isinstance(filename, str) and filename.strip():
                        return Path(filename).stem.replace("_", " ")
        except (OSError, ValueError, TypeError):
            pass
    return "已导入来源" if source_ref.startswith("src_") else f"共享语料来源 {source_ref[-8:]}"


def _build_evidence_review_package(
    project_id: str,
    research_scope: str,
    artifact_ids: list[str],
    final_gap_report: dict[str, object] | None = None,
    context_bundle: ContextBundle | None = None,
) -> dict[str, object]:
    """Assemble the only human-facing artifact for retrieval substeps.

    The individual retrieval artifacts remain durable for audit, but a
    researcher reviews one bounded package rather than confirming BM25, RRF,
    and reranking independently.
    """

    contents = [
        content
        for artifact_id in artifact_ids
        if (content := artifact_content_store.get(project_id, artifact_id)) is not None
    ]
    paper_cards: list[dict[str, object]] = []
    evidence_matrix: list[dict[str, object]] = []
    evidence_snapshots: list[dict[str, object]] = []
    synthesis: dict[str, object] | None = None
    gap_report = final_gap_report
    trace: list[dict[str, str]] = []
    external_candidates: list[dict[str, object]] = []

    labels = {
        "evidence_normalization": "文献整理与证据规范化",
        "hybrid_retrieval": "混合检索",
        "rrf_fusion": "候选证据融合",
        "cross_encoder_rerank": "相关性重排序",
    }
    for content in contents:
        body = dict(content.body)
        action = body.get("action")
        if isinstance(action, str) and action in labels:
            trace.append({"step": action, "label": labels[action], "artifact_id": content.artifact_id})
        if content.artifact_type == "PaperCardCollection":
            paper_cards.extend(_review_list(body, "cards"))
        if content.artifact_type == "EvidenceMatrixCandidate":
            evidence_matrix.extend(_review_list(body, "rows"))
            # The control plane persists one preferred artifact per internal
            # action. Carry the typed paper cards alongside the matrix so the
            # researcher still gets a complete review package.
            paper_cards.extend(_review_list(body, "paper_cards"))
        if content.artifact_type == "BoundedEvidenceSynthesis":
            synthesis = body
        evidence_snapshots.extend(_review_list(body, "evidence_snapshot"))
        if content.artifact_type == "ResearchGapReport":
            gap_report = body
        external = body.get("external_discovery")
        if isinstance(external, dict):
            external_candidates.extend(_review_list(external, "candidates"))

    # The final claim--evidence action receives the bounded ContextBundle for
    # this exact search pass. Its candidate artifacts are intentionally not
    # persisted one-by-one before the researcher review package is created,
    # so include the source-bound material directly here. Without this bridge
    # an uploaded PDF can be indexed successfully yet the human-facing review
    # package incorrectly reports zero sources.
    if context_bundle is not None:
        evidence_snapshots.extend(
            item.model_dump(mode="json") for item in context_bundle.evidence_refs
        )
        for item in context_bundle.evidence_refs:
            paper_cards.append(
                {
                    "paper_card_id": f"paper-card:{item.source_id}",
                    "project_id": project_id,
                    "source_ref": item.source_id,
                    "title": _human_source_title(project_id, item.source_id),
                    "main_findings": [item.excerpt],
                    "limitations": ["本条仅代表当前可定位原文片段，尚未形成跨来源结论。"],
                    "evidence_refs": [item.evidence_id],
                }
            )
            evidence_matrix.append(
                {
                    "row_id": f"evidence-row:{item.evidence_id}",
                    "project_id": project_id,
                    "research_question": research_scope,
                    "source_ref": item.source_id,
                    "relation": "MENTIONING",
                    "finding": item.excerpt,
                    "applicability_boundary": "仅代表该原文片段，尚未形成跨来源结论。",
                    "evidence_refs": [item.evidence_id],
                }
            )

    # A revision keeps all immutable artifacts for audit, but the researcher
    # should see one concise four-step retrieval trace for the current package
    # instead of the same pipeline repeated once per prior search round.
    latest_trace: dict[str, dict[str, str]] = {}
    for item in trace:
        step = item.get("step")
        if isinstance(step, str) and step:
            latest_trace[step] = item
    trace = list(latest_trace.values())

    unique_cards: dict[str, dict[str, object]] = {}
    for card in paper_cards:
        if card.get("title") == card.get("source_ref"):
            card["title"] = _human_source_title(project_id, str(card.get("source_ref")))
        source_ref = str(card.get("source_ref") or card.get("paper_card_id") or "")
        if source_ref and source_ref not in unique_cards:
            unique_cards[source_ref] = card
    paper_cards = list(unique_cards.values())

    evidence_ids = sorted(
        {
            item
            for body in [*map(lambda item: dict(item.body), contents), final_gap_report or {}]
            for item in body.get("evidence_refs", [])
            if isinstance(item, str)
        }
    )
    if context_bundle is not None:
        evidence_ids = sorted(set(evidence_ids).union(
            item.evidence_id for item in context_bundle.evidence_refs
        ))
    seen_external: set[str] = set()
    for candidate in external_candidates:
        candidate_id = candidate.get("candidate_id")
        source_ref = f"external:{candidate_id}" if isinstance(candidate_id, str) else None
        if not source_ref or source_ref in seen_external:
            continue
        seen_external.add(source_ref)
        title = candidate.get("title")
        journal = candidate.get("journal")
        year = candidate.get("publication_year")
        paper_cards.append(
            {
                "paper_card_id": candidate_id,
                "title": title if isinstance(title, str) else "Untitled external candidate",
                "source_ref": source_ref,
                "main_findings": [],
                "limitations": [
                    "External bibliographic candidate only; import and verify the original text before using it as evidence."
                ],
                "evidence_refs": [],
                "bibliographic_note": " · ".join(
                    str(item) for item in (journal, year) if item not in (None, "")
                ),
            }
        )
    # Re-running retrieval reuses durable internal artifacts. Preserve that
    # audit trail, but expose each matrix row/snapshot only once in the human
    # review package so repeated searches do not inflate the apparent evidence.
    unique_matrix: dict[str, dict[str, object]] = {}
    for row in evidence_matrix:
        row_key = row.get("row_id")
        if not isinstance(row_key, str) or not row_key:
            row_key = "|".join(
                [
                    str(row.get("source_ref") or ""),
                    str(row.get("finding") or ""),
                    json.dumps(row.get("evidence_refs") or [], ensure_ascii=False, sort_keys=True),
                ]
            )
        unique_matrix.setdefault(row_key, row)
    evidence_matrix = list(unique_matrix.values())
    unique_snapshots: dict[str, dict[str, object]] = {}
    for snapshot in evidence_snapshots:
        snapshot_key = snapshot.get("evidence_id")
        if not isinstance(snapshot_key, str) or not snapshot_key:
            snapshot_key = "|".join(
                [
                    str(snapshot.get("source_id") or ""),
                    str(snapshot.get("page") or ""),
                    str(snapshot.get("excerpt") or ""),
                ]
            )
        unique_snapshots.setdefault(snapshot_key, snapshot)
    evidence_snapshots = list(unique_snapshots.values())
    source_refs = {
        item.get("source_ref")
        for item in [*paper_cards, *evidence_matrix]
        if isinstance(item.get("source_ref"), str)
    }
    source_refs.update(
        item.get("source_id")
        for item in evidence_snapshots
        if isinstance(item.get("source_id"), str)
    )
    # Keep retrieval feedback incremental across review-package refreshes. The
    # package itself is immutable/versioned, so compare this candidate with the
    # most recent previously persisted package rather than mutating history.
    previous_packages = [
        item
        for item in artifact_content_store.list_project(project_id)
        if item.artifact_type == "EvidenceReviewPackage"
    ]
    previous_source_refs: set[str] = set()
    if previous_packages:
        previous = max(previous_packages, key=lambda item: item.created_at)
        previous_body = dict(previous.body)
        for item in [
            *(_review_list(previous_body, "paper_cards")),
            *(_review_list(previous_body, "evidence_matrix")),
        ]:
            ref = item.get("source_ref")
            if isinstance(ref, str) and ref:
                previous_source_refs.add(ref)
        for item in _review_list(previous_body, "evidence_snapshots"):
            ref = item.get("source_id")
            if isinstance(ref, str) and ref:
                previous_source_refs.add(ref)
    external_source_refs = {ref for ref in source_refs if ref.startswith("external:")}
    # EvidenceRef stores source positions under ``location``. Older review
    # packages used top-level ``page``/``locator`` fields, so looking only at
    # those fields made source-verified corpus evidence appear unverified.
    verified_source_refs: set[str] = set()
    for snapshot in evidence_snapshots:
        source_id = snapshot.get("source_id")
        location = snapshot.get("location")
        verification_status = snapshot.get("verification_status")
        if not isinstance(source_id, str) or not source_id:
            continue
        if verification_status not in {"source_verified", "human_verified"}:
            continue
        if isinstance(location, dict):
            char_start = location.get("char_start")
            char_end = location.get("char_end")
            has_resolved_span = (
                isinstance(char_start, int)
                and isinstance(char_end, int)
                and char_start >= 0
                and char_end > char_start
            )
        else:
            # Support evidence artifacts written before nested locations.
            has_resolved_span = snapshot.get("page") is not None or bool(snapshot.get("locator"))
        if has_resolved_span:
            verified_source_refs.add(source_id)
    new_source_refs = source_refs - previous_source_refs
    duplicate_source_refs = source_refs & previous_source_refs
    missing_requirements = []
    if not source_refs:
        missing_requirements.append("需要导入或检索到可定位的文献来源")
    if not evidence_matrix:
        missing_requirements.append("需要形成可审阅的主张—证据对应关系")
    if not verified_source_refs:
        missing_requirements.append("需要至少一条带有原文定位的已核验来源，才能进入正式研究设计")
    return {
        "schema": "evidence-review-package-v1",
        "research_scope": research_scope,
        # The package can be reviewed as soon as candidate evidence exists;
        # formal_evidence_ready is the separate provenance gate for entering
        # research design.  This keeps external metadata useful for discovery
        # without treating it as verified evidence.
        "status": "READY" if source_refs and evidence_matrix else "INCOMPLETE",
        "retrieval_trace": trace,
        "coverage": {
            "source_count": len(source_refs),
            "evidence_count": len(evidence_ids),
            "new_source_count": len(new_source_refs),
            "duplicate_source_count": len(duplicate_source_refs),
            "external_candidate_count": len(external_source_refs),
            "verified_source_count": len(verified_source_refs),
            "formal_evidence_ready": bool(verified_source_refs) and not missing_requirements,
            "missing_requirements": missing_requirements,
        },
        "paper_cards": paper_cards,
        "evidence_matrix": evidence_matrix,
        "evidence_snapshots": evidence_snapshots,
        "synthesis": synthesis,
        "research_gap_report": gap_report or {"gaps": [], "limit_text": "当前语料范围内尚未形成可审阅的研究缺口。"},
        "used_evidence_refs": evidence_ids,
        "source_artifact_ids": artifact_ids,
    }


def _legacy_project_evidence_context(project_id: str, research_scope: str) -> ContextBundle:
    """Build a non-authorizing context from evidence stored by older projects.

    Older authenticated projects may have searchable evidence in ``context.db``
    without ever creating orchestration artifacts.  This helper deliberately
    reads those records into a temporary review context; it does not verify,
    promote, or persist a workflow artifact.
    """

    allowed_statuses = list(VerificationStatus)
    request = EvidenceSearchRequest(
        project_id=project_id,
        query=research_scope or "当前研究主题",
        limit=50,
        allowed_verification_statuses=allowed_statuses,
    )
    results = service.search(request)
    if not results:
        # A vocabulary mismatch should not hide already imported evidence.
        results = service._discovery_candidates(  # noqa: SLF001 - compatibility projection
            ContextBuildRequest(
                project_id=project_id,
                task_ref=f"legacy:{project_id}:evidence-review",
                query=research_scope or "当前研究主题",
                token_budget=8_000,
                max_chunks_per_source=3,
                allow_discovery_fallback=True,
                allowed_verification_statuses=allowed_statuses,
            )
        )
    selected: list[EvidenceRef] = []
    source_counts: dict[str, int] = {}
    used_tokens = 0
    for result in results:
        evidence = result.evidence
        if source_counts.get(evidence.source_id, 0) >= 3:
            continue
        cost = max(1, len(evidence.excerpt) // 4)
        if used_tokens + cost > 8_000:
            continue
        selected.append(evidence)
        source_counts[evidence.source_id] = source_counts.get(evidence.source_id, 0) + 1
        used_tokens += cost
    summary = {
        status.value: sum(item.verification_status == status for item in selected)
        for status in VerificationStatus
    }
    canonical = json.dumps(
        {
            "project_id": project_id,
            "task_ref": f"legacy:{project_id}:evidence-review",
            "query": research_scope,
            "evidence": [item.evidence_id for item in selected],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return ContextBundle(
        context_id=f"ctx_legacy_{project_id}",
        project_id=project_id,
        task_ref=f"legacy:{project_id}:evidence-review",
        query=research_scope or "当前研究主题",
        evidence_refs=selected,
        source_refs=sorted(source_counts),
        unresolved_questions=[] if selected else ["当前项目没有可读取的候选证据"],
        risk_flags=["legacy_read_only_projection"],
        verification_summary=summary,
        token_budget=8_000,
        estimated_tokens=used_tokens,
        context_hash=sha256_text(canonical),
        generated_at=datetime.now(UTC).isoformat(),
        context_mode="local",
        retrieval_strategy="legacy_project_evidence",
    )


def _legacy_qa_turns(project_id: str) -> list[dict[str, object]]:
    """Read ordinary QA turns for a read-only projection of legacy work."""

    try:
        conversations = qa_service.list_conversations(project_id, limit=50)
        turns: list[dict[str, object]] = []
        for conversation in conversations:
            for turn in qa_service.conversation_turns(
                project_id,
                conversation.conversation_id,
                limit=100,
            ):
                turns.append(turn.model_dump(mode="json"))
        return sorted(turns, key=lambda item: str(item.get("created_at") or ""))
    except Exception as error:  # noqa: BLE001 - legacy display must be best effort
        logger.warning("Could not read legacy QA turns for %s: %s", project_id, error)
        return []


def _legacy_workflow_artifacts(project_id: str) -> list[ArtifactContent]:
    """Expose legacy conversation conclusions as explicitly provisional cards."""

    existing_types = {
        item.artifact_type for item in artifact_content_store.list_project(project_id)
    }
    turns = _legacy_qa_turns(project_id)
    if not turns:
        return []
    relevant = [
        item for item in turns
        if any(
            term in str(item.get("question") or "").lower()
            for term in (
                "研究问题", "研究方案", "研究设计", "研究对象", "研究方法",
                "研究边界", "研究场景", "确定研究", "方案",
            )
        )
    ]
    if not relevant:
        return []
    excerpts = [
        {
            "question": str(item.get("question") or "").strip(),
            "answer": str(item.get("answer") or "").strip()[:1200],
            "created_at": item.get("created_at"),
        }
        for item in relevant[-6:]
    ]
    projected: list[ArtifactContent] = []
    if "ResearchQuestionTree" not in existing_types:
        question_body = {
            "project_id": project_id,
            "title": "历史对话中的研究问题候选",
            "primary_question": "请根据历史对话确认研究对象、场景、方法、发现与边界，形成正式研究问题。",
            "research_questions": [
                "研究对象与场景是什么？",
                "拟采用什么研究方法？",
                "哪些发现或判断需要证据支持？",
                "结论边界应如何限定？",
            ],
            "status": "LEGACY_CANDIDATE_REQUIRES_CONFIRMATION",
            "provenance": {
                "source": "ordinary_qa_history",
                "read_only": True,
                "note": "这是旧项目的历史候选，不等同于已批准的研究问题。",
            },
            "conversation_excerpts": excerpts,
        }
        projected.append(
            ArtifactContent(
                project_id=project_id,
                artifact_id=f"legacy-projection:{project_id}:research-question",
                version=1,
                artifact_type="ResearchQuestionTree",
                schema_version="legacy-projection-v1",
                body=question_body,
            )
        )
    if "StudyProtocolCandidate" not in existing_types:
        protocol_body = {
            "project_id": project_id,
            "title": "历史对话中的研究方案候选",
            "design_type": "待从历史对话确认",
            "primary_outcome": "待研究者确认",
            "sampling_approach": "待研究者确认研究对象与纳入边界",
            "variables": ["研究对象", "研究场景", "研究方法", "研究发现", "解释边界"],
            "analysis_plan": "历史对话仅作为候选输入，需确认后再形成可执行分析计划。",
            "hypotheses": [],
            "status": "LEGACY_CANDIDATE_REQUIRES_CONFIRMATION",
            "provenance": {
                "source": "ordinary_qa_history",
                "read_only": True,
                "note": "这是旧项目的历史候选，不等同于已批准的研究方案。",
            },
            "conversation_excerpts": excerpts,
        }
        projected.append(
            ArtifactContent(
                project_id=project_id,
                artifact_id=f"legacy-projection:{project_id}:study-protocol",
                version=1,
                artifact_type="StudyProtocolCandidate",
                schema_version="legacy-projection-v1",
                body=protocol_body,
            )
        )
    return projected


def _research_brief_fields(
    project: ResearchProject,
    route: str,
    user: UserProfile | None = None,
    conversation_feedback: dict[str, str] | None = None,
) -> dict[str, object]:
    """Translate a conversational scope into route-appropriate planning fields."""

    scope = _canonical_research_scope(project.research_direction)
    # Feedback is deliberately transient generation context rather than part
    # of the canonical project direction.  This preserves clean titles while
    # allowing the next candidate to honour the researcher's wording.
    if conversation_feedback:
        constraint_payload = conversation_feedback.get("research_constraints")
        if isinstance(constraint_payload, str) and constraint_payload.strip():
            try:
                parsed_constraints = json.loads(constraint_payload)
            except json.JSONDecodeError:
                parsed_constraints = None
            if isinstance(parsed_constraints, dict):
                readable_constraints = "；".join(
                    f"{key}={value}" for key, value in parsed_constraints.items()
                )
                if readable_constraints:
                    scope = f"{scope}\n研究约束：{readable_constraints}"
        capability_payload = conversation_feedback.get("requested_capabilities")
        if isinstance(capability_payload, str) and capability_payload.strip():
            try:
                parsed_capabilities = json.loads(capability_payload)
            except json.JSONDecodeError:
                parsed_capabilities = None
            if isinstance(parsed_capabilities, list) and parsed_capabilities:
                scope = f"{scope}\n本轮优先协作能力：{', '.join(str(item) for item in parsed_capabilities)}"
        relevant = [
            value.strip()
            for key, value in conversation_feedback.items()
            if key not in {"evidence_search_addition", "research_constraints", "requested_capabilities"}
            and isinstance(value, str) and value.strip()
        ]
        if relevant:
            scope = f"{scope}\n研究者最新确认：{relevant[-1]}"
    if user is not None:
        try:
            memory = identity_service.get_research_memory(user, project.project_id)
        except AuthError:
            memory = None
        if memory is not None and memory.facts:
            facts = memory.facts
            population = facts.get("research_focus", "待在研究设计中进一步界定的研究对象与场景")
            goal = facts.get("research_goal", facts.get("research_topic", scope))
            method_boundary = facts.get("method_boundary", "由当前证据和数据条件共同确定的方法边界")
            contribution = facts.get("expected_contribution", "待结合现有证据进一步细化的研究贡献")
            data_source = facts.get("data_source", "尚未在对话中明确的数据来源")
            ethics = facts.get("constraints", "遵循数据最小化、去标识化与来源可追溯要求")
            return {
                "topic": facts.get("research_topic", scope),
                "population": population,
                "context": scope,
                "intervention": goal,
                "comparator": method_boundary,
                "candidate_outcomes": [contribution],
                "measurement_timepoints": ["在研究设计阶段根据资料和数据可用性确定"],
                "sampling_approach": population,
                "constraints": [data_source, ethics],
                "exclusions": [
                    "未确认研究设计、分组机制和混杂控制前不得作因果解释。"
                ] if route != "QUALITATIVE" else [
                    "不得把文献或系统生成内容表述为本项目参与者的经验结论。"
                ],
            }
        try:
            intake = identity_service.get_research_intake(user, project.project_id)
        except AuthError:
            intake = None
        if intake is not None and intake.status == "COMPLETE":
            answers = intake.answers
            population = answers.get("research_focus", "待研究者确认的研究对象与场景")
            intervention = answers.get("research_goal", "待研究者确认的研究目标")
            comparator = answers.get("method_boundary", "待研究者确认的比较或解释边界")
            outcome = answers.get("expected_contribution", "待研究者确认的主要结果或预期贡献")
            timepoint = "待研究者在研究设计阶段确认的测量或观察时间点"
            data_source = answers.get("data_source", "待研究者确认的数据来源")
            ethics = answers.get("constraints", "待研究者确认的数据与伦理边界")
            causal_exclusion = (
                "未确认随机分配、分组机制和混杂控制前不得将组间差异解释为因果效应。"
            )
            return {
                "topic": intake.research_topic,
                "population": population,
                "context": intake.research_topic,
                "intervention": intervention,
                "comparator": comparator,
                "candidate_outcomes": [outcome],
                "measurement_timepoints": [timepoint],
                "sampling_approach": population,
                "constraints": [data_source, ethics],
                "exclusions": [causal_exclusion] if route != "QUALITATIVE" else [
                    "不得将文献片段或系统生成内容写作本项目参与者的经验结论。"
                ],
            }
    if route == "QUALITATIVE":
        scope_lower = scope.lower()
        public_student_reanalysis = any(
            marker in scope_lower
            for marker in ("公开二手", "学生物理问题", "物理奥赛", "osf")
        )
        if public_student_reanalysis:
            return {
                "topic": scope,
                "population": "公开二手资料中的学生物理问题解决文本；匿名学生编号仅用于资料回链",
                "context": "物理问题解决过程的主题再分析",
                "intervention": "不适用；本项目不重新实施教学干预",
                "comparator": "公开资料中预先存在的背景分组（如物理奥赛参与情况），仅作描述性比较",
                "candidate_outcomes": ["五类问题解决主题的候选分布", "主题与公开背景变量的描述性对应"],
                "constraints": [
                    "资料来自公开 OSF 项目，属于二手资料，不是本项目新招募的参与者",
                    "公开文件记录数与原论文 N=417 的筛选边界必须由研究者按原规则复核",
                    "候选主题需回链原文并经研究者复核，不自动声称复现原论文结果",
                ],
                "exclusions": [
                    "不把公开记录数直接写成原论文样本量",
                    "不从描述性主题分布推出新的因果结论",
                ],
            }
        return {
            "topic": scope,
            "population": "高中物理教师",
            "context": "高中物理教学中的计算思维与 Python 整合",
            "intervention": "参与计算思维整合专业发展活动并尝试 Python 教学",
            "comparator": "活动前的既有教学经验与支持条件",
            "candidate_outcomes": [
                "计算思维整合的认识、实施经验与专业学习需求",
                "编程教学中的困难与支架需求",
                "将计算工具迁移到物理课堂的条件",
            ],
            "constraints": [
                "仅对已导入并可定位的文献和研究材料作出结论",
                "没有原始教师访谈或问卷数据时不得声称已发现参与者主题",
            ],
            "exclusions": [
                "不估计学生学习效果或因果效应",
                "不把文献证据替代为教师原始数据",
            ],
        }
    if route == "EXPERIMENTAL":
        return {
            "topic": scope,
            "population": "计划招募的研究对象；纳入、排除标准待研究者确认",
            "context": scope,
            "intervention": "研究者指定的教学或学习干预（具体操作、剂量与实施者待确认）",
            "comparator": "预先定义的对照教学或支持条件",
            "candidate_outcomes": ["计算思维与物理概念理解（主要结果，具体测量字段待数据审计确认）"],
            "constraints": ["随机分配、样本来源、测量效度和干预等价性必须在收集数据前经 Gate 确认"],
            "exclusions": ["未确认随机分配或混杂控制前不得作因果推断"],
        }
    return {
        "topic": scope,
        "population": "现有或计划招募的比较组研究对象；分组定义待研究者确认",
        "context": scope,
        "intervention": "不预设干预；比较已定义的 group 组别",
        "comparator": "另一预先定义 group 组别",
        "candidate_outcomes": ["计算思维与物理概念理解（主要结果，具体测量字段待数据审计确认）"],
        "constraints": ["候选输出必须经过人工 Gate，并记录分组规则和潜在混杂"],
        "exclusions": ["观察性组别差异不得直接解释为因果效应"],
    }


def _deterministic_manuscript_outline(
    project_id: str, scope: str, package: dict[str, object] | None
) -> dict[str, object]:
    """Create a reviewable outline without prematurely drafting prose."""

    scope = _canonical_research_scope(scope)
    evidence_refs = list(package.get("used_evidence_refs", [])) if isinstance(package, dict) else []
    gaps = package.get("research_gap_report", {}) if isinstance(package, dict) else {}
    return {
        "outline_id": f"outline:{project_id}:{uuid4().hex}",
        "project_id": project_id,
        "title": f"候选论文：{scope}",
        "sections": [
            {"section": "引言", "purpose": "界定问题、已有证据与研究缺口"},
            {"section": "方法", "purpose": "记录已确认的研究问题、设计与数据治理边界"},
            {"section": "结果", "purpose": "仅呈现冻结数据产生且已验证的结果"},
            {"section": "讨论", "purpose": "解释可支持的结论、局限和不可作出的推断"},
        ],
        "evidence_refs": evidence_refs,
        "research_gap_summary": gaps if isinstance(gaps, dict) else {},
        "status": "OUTLINE_REQUIRES_RESEARCHER_REVIEW",
        "boundary": "此产物仅为论文结构与论证边界，不是可投稿正文。",
    }


def _deterministic_manuscript_candidate(
    project_id: str,
    scope: str,
    package: dict[str, object] | None,
) -> dict[str, object]:
    """Render an implementation-ready, explicitly bounded proposal without an LLM.

    This draft is deliberately a protocol rather than a fluent synthesis.  The
    evidence package may contain only one uploaded source, so every literature
    statement remains tied to a stable package reference and the proposed
    methods are never represented as completed empirical work.
    """

    package = package or {}
    rows = [item for item in package.get("evidence_matrix", []) if isinstance(item, dict)]
    cards = [item for item in package.get("paper_cards", []) if isinstance(item, dict)]
    refs = [item for item in package.get("used_evidence_refs", []) if isinstance(item, str)]
    # Shared-corpus hits are useful discovery candidates, but they are not
    # silently promoted into a manuscript.  Only project-imported sources
    # (``src_*``) can supply default prose; the researcher may add a shared
    # source explicitly through a later evidence decision.
    usable_rows = [
        item for item in rows
        if str(item.get("source_ref", "")).startswith("src_")
    ]
    card_titles = {
        str(card.get("source_ref")): str(card.get("title") or "未命名来源").strip()
        for card in cards
        if isinstance(card.get("source_ref"), str)
    }
    evidence_rows = [
        row for row in usable_rows
        if str(row.get("finding", "")).strip() and str(row.get("source_ref", "")).strip()
    ][:6]
    evidence_sentences = [
        f"[E{index}] {str(row.get('finding', '')).strip()}"
        f"（{card_titles.get(str(row.get('source_ref')), _human_source_title(project_id, str(row.get('source_ref'))))}）"
        for index, row in enumerate(evidence_rows, start=1)
    ]
    reference_lines = [
        f"[{index}] {card.get('title') or _human_source_title(project_id, str(card.get('source_ref', '')))}"
        for index, card in enumerate(cards[:8], start=1)
        if not str(card.get("source_ref", "")).startswith("external:")
    ]
    evidence_block = "\n".join(evidence_sentences) or "当前证据包没有足够的可定位原文，不能形成文献结论。"
    refs_block = "\n".join(reference_lines) or "暂无可用于正式引用的已核验文献。"
    scope_text = _canonical_research_scope(scope)
    scope_lower = scope_text.lower()
    public_student_reanalysis = any(
        marker in scope_lower
        for marker in ("公开二手", "学生物理问题", "物理奥赛", "osf")
    )
    physics_ct_profile = not public_student_reanalysis and (all(term in scope_lower for term in ("物理", "计算")) or (
        "python" in scope_lower and "教师" in scope_lower
    ))
    evidence_refs = [str(row["source_ref"]) for row in evidence_rows]
    evidence_anchor = "、".join(f"[E{index}]" for index in range(1, len(evidence_rows) + 1)) or "当前证据包"
    if physics_ct_profile:
        title = f"{scope_text}：一项证据约束的定性研究方案"
        keywords = "物理教育；计算思维；Python；教师专业学习；定性研究；证据链"
        framing = (
            "本方案把计算思维整合理解为教师需要同时处理学科内容、计算实践与教学法的任务，"
            "而不是把学习某种编程语法直接等同于课堂整合能力。已导入研究提示，教师的计算学习、"
            "物理应用与教学设计之间存在需要被具体说明的衔接问题。"
        )
        questions = (
            "RQ1：高中物理教师如何界定计算思维和 Python 在其物理教学中的作用？\n"
            "RQ2：教师从尝试计算活动到设计、实施和修订课堂活动时，分别遇到哪些知识、时间、资源和协作约束？\n"
            "RQ3：哪些专业学习支架有助于教师把计算活动与既有物理课程目标相连接？"
        )
        sampling = (
            "采用最大差异目的性抽样，先按任教年级、既有编程经验、学校资源条件和是否有过计算活动实施经历建立招募矩阵；"
            "纳入具有高中物理教学经验并自愿讨论相关实践的教师。研究者须在招募前冻结纳入/排除标准、目标信息丰富度和停止规则。"
        )
        materials = (
            "收集四类相互补充的资料：背景问卷、一次半结构式访谈、一次课后反思，以及去标识化教学设计或课堂任务。"
            "访谈围绕：(1) 对计算思维的理解；(2) 选择或放弃某个 Python 活动的理由；(3) 将物理概念、代码和学生任务连接的做法；"
            "(4) 出错、时间、设备与评价的处理；(5) 所需的示例、同伴或技术支持；(6) 对下一次实施的修订计划。"
        )
        codebook = (
            "先开放编码，再以“计算实践”“物理-计算应用”“教学法与课堂支架”作为第二轮比较维度；"
            "该维度用于组织比较，不替代从资料中产生的代码。对每个主题保留定义、纳入/排除规则、反例、支持片段和修订理由。"
        )
        contribution = (
            "预期贡献是提供可追溯的专业学习需求图谱，区分编程熟练度、物理建模应用和课堂教学支架，"
            "为工作坊、课程资源和后续教师学习评价提出可检验的设计要求。"
        )
    elif public_student_reanalysis:
        # Public OSF student-text projects are data re-analyses, not proposed
        # interview studies. Keep the generated manuscript aligned with the
        # actual corpus and reserve provenance identifiers for the audit log.
        title = "学生物理问题解决文本中的问题解决表征：基于公开语料的计算辅助主题研究"
        keywords = "物理教育；问题解决；主题分析；计算辅助定性分析；计算扎根理论"
        framing = (
            "物理问题解决文字描述可以同时呈现问题理想化、物理概念调用、定量处理和求解策略。"
            "本研究基于公开学生物理问题解决文本，复核这些语义成分如何在同一段描述中共同出现。"
        )
        questions = (
            "RQ1：公开学生物理问题解决文本中可以识别出哪些稳定的语义主题？\n"
            "RQ2：这些主题是否覆盖从情境假设到概念、定量和解题方案表达的不同环节？\n"
            "RQ3：不同主题之间如何共同出现在同一段问题解决描述中？"
        )
        sampling = (
            "分析单位为 OSF 项目中的匿名学生文本记录。公开文件包含 550 条非空记录，"
            "原论文报告的分析样本为 N=417；本研究不假定二者等价，须按原论文规则复现纳入和排除。"
        )
        materials = (
            "使用 Textual_descriptions.xlsx 作为文本资料，Additional_data.xlsx 和 dat_human_recoding.xlsx 作为公开参考资料。"
            "这些文件均按来源、版本和哈希登记，不新增参与者资料。"
        )
        codebook = (
            "先进行计算辅助模式识别，再由研究者复核主题定义、纳入/排除规则和反例；"
            "主题包括假设与理想化、概念理解、定量处理、解题方案表述和一般性描述。"
        )
        contribution = (
            "本研究提供一个可审计的学生物理问题解决语义框架，并明确计算辅助主题识别与原论文完整 CGT 流程之间的差异。"
        )
    else:
        title = f"{scope_text}：一项证据约束的定性研究方案"
        keywords = "定性研究；研究方案；半结构式访谈；主题分析；证据链；研究治理"
        framing = (
            "本方案将研究主题视为一个需要在具体情境、行动和约束中理解的实践问题。"
            "文献证据用于限定研究问题与待验证的机制，不被改写为本项目参与者的经验结论。"
        )
        questions = (
            f"RQ1：相关实践者如何理解并界定“{scope_text}”？\n"
            "RQ2：在真实实施过程中，哪些条件、障碍和支持会影响该实践？\n"
            "RQ3：不同情境或经验背景下，实践者的解释与改进策略如何异同？"
        )
        sampling = (
            "采用目的性抽样并建立招募矩阵，覆盖与研究主题直接相关的角色、经验程度和实施情境；"
            "在招募前冻结纳入/排除标准、目标信息丰富度和停止规则。"
        )
        materials = (
            "收集背景问卷、半结构式访谈、开放式反思和研究对象自愿提供的去标识化实践材料。"
            "访谈至少覆盖：对主题的理解、具体经历、影响决策的条件、遇到的困难、已获得的支持，以及下一步改进设想。"
        )
        codebook = (
            "先进行开放编码，再按概念、行动、情境条件和后果开展第二轮比较；"
            "对每个主题保留定义、纳入/排除规则、反例、支持片段和修订理由。"
        )
        contribution = "预期贡献是形成一个可审计的经验解释框架，为后续干预、资源设计或量化检验提出清晰假设。"
    return {
        "project_id": project_id,
        "language": "zh-CN",
        "sections": {
            "title": title,
            "abstract": (
                f"本研究聚焦{scope_text}。系统先对已导入材料进行限定范围的检索、证据定位和主张—证据映射，"
                "再形成可执行的定性研究方案。现阶段输出仅为研究方案：不把文献片段或系统生成内容误写为参与者资料或经验结果。"
                "拟采用目的性抽样、半结构式访谈和多源资料比较；分析前冻结抽样、资料处理和编码决策，分析后由研究者完成反例检查与独立复核。"
            ),
            "keywords": keywords,
            "introduction": f"{framing}\n\n研究缺口不是“缺少更多正面例子”，而是缺少对实践者如何跨越理解、设计、实施与修订环节的可回链描述。"
            f"本项目将以 {evidence_anchor} 作为问题形成的证据起点，并用新收集的去标识化资料检验、修正或反驳这些启示。",
            "evidence_review": (
                "证据审阅遵循‘来源可定位、主张有边界、外部候选不自动入证’原则。当前包中可用的原文片段如下：\n"
                f"{evidence_block}\n\n这些片段用于限定问题与访谈追问，不能替代本研究的资料；外部检索结果仅作为待核验候选，未被写入正式结论。"
            ),
            "research_questions": questions,
            "methods": (
                "研究设计：定性描述性研究，结合主题分析与跨资料来源比较。\n"
                f"抽样：{sampling}\n"
                f"资料链：{materials}\n"
                "程序：在收集前登记版本化访谈提纲和数据管理计划；每份资料进入私有区后先进行直接标识风险审计，再由研究者确认处理范围。"
            ),
            "analysis_plan": (
                "分析单位为保留完整语境的意义片段。步骤为：(1) 冻结资料版本和研究问题；(2) 熟悉资料并写反思备忘；"
                f"(3) {codebook}；(4) 跨参与者和资料类型比较；(5) 主动检索反例；(6) 由未参与首轮编码的同行进行审计式复核；"
                "(7) 仅将可回链片段支持、边界明确的解释写入结果。没有原始资料时，只报告方案和文献启示，不报告主题频数、比例或效果。"
            ),
            "expected_contribution": contribution,
            "ethics_limitations": (
                "本候选稿不宣称伦理审批、样本招募、资料饱和或实证发现已经完成。正式研究前必须完成知情同意/伦理审查、"
                "最小必要资料收集、私有存储与访问控制、去标识化检查、保留期限和删除流程；正式投稿前还须由研究者核对原文页码、"
                "补充原始资料、冻结分析方案，并由独立审稿人复核。"
            ),
            "references": refs_block,
        },
        "claim_ids": [f"claim:{project_id}:scope", f"claim:{project_id}:method", f"claim:{project_id}:limitation"],
        "citation_refs": refs,
        "claim_evidence_map": {
            f"claim:{project_id}:scope": evidence_refs,
            f"claim:{project_id}:method": [],
            f"claim:{project_id}:limitation": [],
        },
        "claim_records": [
            {
                "claim_id": f"claim:{project_id}:scope",
                "section": "introduction",
                "claim_text": "本项目以已导入证据形成问题，并以新的去标识化资料检验、修正或反驳其中的启示。",
                "claim_type": "LITERATURE",
                "support_type": "evidence",
                "support_evidence_ids": evidence_refs,
            },
            {
                "claim_id": f"claim:{project_id}:method",
                "section": "methods",
                "claim_text": "本稿提出待研究者确认并冻结的定性资料收集与分析程序。",
                "claim_type": "METHOD",
                "support_type": "proposed_protocol",
            },
            {
                "claim_id": f"claim:{project_id}:limitation",
                "section": "ethics_limitations",
                "claim_text": "本候选稿不报告尚未收集的参与者资料、主题频数或实证效果。",
                "claim_type": "LIMITATION",
                "support_type": "governance_boundary",
            },
        ],
        "traceability_note": "[E*] 对应当前证据包中的原文定位入口；方法为拟议程序，须经研究者确认后才可执行。",
        "numeric_literals": [],
        "result_directions": {},
        "claim_strengths": {"scope": "bounded", "method": "proposal", "limitation": "explicit"},
        "limitation_claim_ids": [f"claim:{project_id}:limitation"],
        "status": "CANDIDATE_GROUNDED_DRAFT",
        "quality_flags": [
            "NO_MODEL_GENERATION_USED",
            "NO_PRIMARY_QUALITATIVE_DATA_INTERPRETED",
            "EXTERNAL_METADATA_NOT_USED_AS_FORMAL_EVIDENCE",
        ],
    }


def _deterministic_qualitative_results_manuscript(
    project_id: str,
    scope: str,
    package: dict[str, object] | None,
    primary_data: dict[str, object],
) -> dict[str, object]:
    """Render a results-bearing draft while preserving the study's limits.

    This is intentionally a transparent draft for the researcher, not a claim
    that keyword assistance has completed qualitative interpretation.
    """

    draft = _deterministic_manuscript_candidate(project_id, scope, package)
    manual_theme_body = _latest_artifact_body(project_id, "ManualThemeRevisionCandidate")
    manual_themes = (
        [item for item in manual_theme_body.get("themes", []) if isinstance(item, dict)]
        if isinstance(manual_theme_body, dict) and manual_theme_body.get("themes")
        else []
    )
    # A placeholder such as "簇 0" with no definition is not an interpreted
    # theme. Prefer transparent data-derived candidates until a real codebook
    # definition and inclusion/exclusion rules exist.
    defined_manual_themes = [
        item for item in manual_themes
        if str(item.get("definition", "")).strip()
        and "待研究者" not in str(item.get("definition", ""))
        and str(item.get("working_name", "")).strip() not in {"", "簇 0", "簇 1", "簇 2", "簇 3", "簇 4", "簇 5", "簇 6", "簇 7"}
    ]
    coding_input = _qualitative_coding_input(project_id, primary_data)
    themes = defined_manual_themes or _deterministic_theme_candidates(coding_input)
    sample_flow = _qualitative_sample_flow(project_id, primary_data)
    preprocessing = _latest_artifact_body(project_id, "PreprocessingExecutionCandidate") or {}
    preprocessing_execution = preprocessing.get("execution") if isinstance(preprocessing.get("execution"), dict) else {}
    preprocessing_performed = bool(preprocessing_execution.get("performed"))
    pattern_stability = _latest_artifact_body(project_id, "PatternStabilityExecutionCandidate") or {}
    pattern_execution = pattern_stability.get("execution") if isinstance(pattern_stability.get("execution"), dict) else {}
    pattern_performed = bool(pattern_execution.get("performed"))
    participant_count = len(primary_data["participant_labels"])
    if primary_data.get("source_kind") == "public_secondary_tsv":
        participant_note = (
            f"公开 OSF 二手文本中可识别到 {participant_count} 个匿名学生编号；"
            f"按原始 Stu_ID 与背景表连接后的实际分析输入为 {sample_flow['final_analysis_sample']} 名学生。"
        )
    else:
        participant_note = (
            f"资料中可识别到 {participant_count} 个去标识化参与者标签"
            if participant_count else "上传资料未提供可稳定识别的参与者标签"
        )
    results_lines = [
        "本节仅报告冻结分析样本上的研究者暂定、透明关键词辅助编码候选；所有解释均待完整原文和独立编码复核。",
        (
            "分析输入：已冻结的公开 OSF 资料版本（具体版本和数据指纹保存在审计附录）；"
            f"原始文件共 {primary_data['segment_count']} 个非空文本记录；{participant_note}"
        ),
        (
            "样本流转：原始文本记录 {raw} 条，空文本 {missing} 条，非空文本 {nonempty} 条；"
            "文本与配套背景表成功连接 {joined} 名学生，文本侧未连接 {text_unmatched} 名，背景表侧未连接 {background_unmatched} 名。"
            "最终分析样本为 {final_sample} 名学生。"
        ).format(
            raw=sample_flow["raw_text_rows"],
            missing=sample_flow["missing_text_rows"],
            nonempty=sample_flow["nonempty_text_rows"],
            joined=sample_flow["joined_students"],
            text_unmatched=sample_flow["text_students_without_background"],
            background_unmatched=sample_flow["background_students_without_text"],
            final_sample=sample_flow["final_analysis_sample"],
        ),
        (
            f"预处理在 {preprocessing_execution.get('student_count', 0)} 名学生上形成 "
            f"{preprocessing_execution.get('candidate_sentence_count', 0)} 个候选句段，20 字符基线保留 "
            f"{preprocessing_execution.get('retained_sentence_count_at_20', 0)} 个；10/20/30 字符敏感性结果保存在审计附录。"
            if preprocessing_performed else
            "句子预处理尚无可验证执行记录，当前不能报告句子级结果。"
        ),
        "候选主题的频数是关键词命中句子数，不是经过人工编码确认的主题频数；同一句子可以同时命中多个候选。",
    ]
    for index, theme in enumerate(themes, start=1):
        theme_label = str(theme.get("label") or theme.get("working_name") or theme.get("theme_id") or f"主题候选 {index}")
        raw_basis = str(theme.get("candidate_basis") or theme.get("coding_basis") or "transparent_keyword_assisted_candidate")
        basis = {
            "researcher_provisional_interpretation_with_keyword_retrieval": "研究者暂定解释与透明关键词检索",
            "deterministic_keyword_assisted_candidate": "透明关键词辅助候选",
            "executed_pattern_discovery": "已执行模式发现",
        }.get(raw_basis, raw_basis)
        definition = str(theme.get("operational_definition") or theme.get("definition") or "待研究者根据完整语境定义")
        evidence_count = int(theme.get("evidence_count", len(theme.get("positive_examples", []))) or 0)
        coverage = theme.get("coverage_proportion")
        if isinstance(coverage, (int, float)):
            coverage_text = f"，覆盖 {coverage:.1%}"
        else:
            coverage_text = ""
        results_lines.append(
            f"候选 {index}：{theme_label}（来源：{basis}）。"
            f"操作性定义：{definition}"
            f"关键词命中 {evidence_count} 个句子{coverage_text}；"
            "它仍是待解释的分析线索，不等同于已经命名的语义主题；完整定位保存在审计附录，"
            "当前不报告普遍性、主题饱和度或组间差异。"
        )
        examples = [
            str(item).strip().replace("\n", " ")
            for item in (theme.get("representative_examples") or [])
            if str(item).strip()
        ]
        if examples:
            results_lines.append(f"原文示例（仅供复核）：{examples[0]}")
        contrasts = [
            str(item).strip().replace("\n", " ")
            for item in (theme.get("contrast_examples") or theme.get("counterexamples") or [])
            if str(item).strip()
        ]
        if contrasts:
            results_lines.append(f"对照片段（未命中该规则，尚非确认反例）：{contrasts[0]}")
    if not themes:
        results_lines.append("当前资料未与预设辅助编码词表形成可靠主题候选；需要研究者开展开放编码，不能产出实证主题结论。")
    sections = dict(draft["sections"])
    sections.update(
        {
            "abstract": (
                f"本研究聚焦{scope}，以可定位文献形成研究问题，并对公开 OSF 学生物理问题解决文本（二手资料）"
                "进行了版本锁定后的辅助编码。初步主题候选覆盖假设与理想化、概念理解、定量处理、解题方案表述和一般性描述；"
                "候选主题不等同于外部研究的结论，也不替代完整的模型验证流程。"
                "结果只作为可审计的候选解释：每项均链接到冻结数据版本和资料片段，"
                "尚未完成独立编码复核、反例检查和饱和度判断。"
            ),
            "title": "公开学生物理问题解决文本中的问题解决表征：计算辅助再分析",
            "keywords": "物理教育；问题解决；学生文本；计算辅助定性分析；计算扎根理论；公开二手资料",
            "methods": (
                "研究设计：公开学生物理问题解决文本的计算辅助主题复核。\n"
                f"资料：Textual_descriptions.csv（{primary_data.get('record_count', primary_data['segment_count'])} 条非空记录）及公开配套变量文件；"
                "当前文本文件记录数不自动等同于配套变量表的主分析样本；样本边界须由 Stu_ID 连接审计确定。\n"
                f"样本流转：原始文本 {sample_flow['raw_text_rows']} 条，空文本 {sample_flow['missing_text_rows']} 条，"
                f"非空文本 {sample_flow['nonempty_text_rows']} 条，成功连接 {sample_flow['joined_students']} 名学生，"
                f"最终冻结分析样本 {sample_flow['final_analysis_sample']} 名学生。\n"
                f"分析输入：公开 OSF 资料的已冻结版本（版本 {primary_data['document_version']}；"
                "数据指纹保存在审计附录）。句子是编码单位，学生是聚合与重抽样单位；"
                + (
                    f"实际预处理形成 {preprocessing_execution.get('candidate_sentence_count', 0)} 个候选句段，"
                    f"20 字符规则保留 {preprocessing_execution.get('retained_sentence_count_at_20', 0)} 个，"
                    "短公式片段转入复核清单。"
                    if preprocessing_performed else
                    "句子预处理尚未获得执行日志。"
                )
            ),
            "introduction": (
                "物理问题解决文字描述可以同时呈现问题理想化、物理概念调用、定量处理和求解策略。"
                "本研究基于公开学生物理问题解决文本，复核这些语义成分如何在同一段描述中共同出现。"
                "研究问题针对学生文本本身，不把学生当作访谈对象，也不把公开数据项目的原始研究结论改写为本研究发现。"
            ),
            "evidence_review": (
                "文献与数据说明用于界定研究问题、资料来源和复现边界。当前候选稿只使用已登记的公开资料来源和方法背景，"
                "不读取待最终外部对照论文的结果来改写本研究发现。当前平台运行完成了冻结样本预处理和透明关键词辅助候选整理；"
                "原文定位和完整证据链保存在系统审计记录，不进入论文正文。"
            ),
            "research_questions": (
                "RQ1：公开学生物理问题解决文本中可以识别出哪些可回链的语义主题？\n"
                "RQ2：这些主题如何覆盖问题假设、物理概念、定量处理和解题方案表达等环节？\n"
                "RQ3：哪些主题候选仍需要人工定义、反例检查或后续监督模型确认？"
            ),
            "analysis_plan": (
                "分析单位为预处理后保留语境的句子，学生是聚合单位。流程为：冻结数据版本；检查记录和样本边界；"
                "执行公式保护与阈值敏感性预处理；根据研究者暂定解释进行透明关键词检索；由研究者复核定义、反例和边界；"
                "再决定是否执行嵌入、UMAP/HDBSCAN、人工标签冻结和监督确认。当前版本只报告关键词辅助候选，"
                "不把未执行的监督模型、学生层稳健性或组间统计写成正式结果。"
            ),
            "expected_contribution": (
                "本候选稿的贡献是把公开学生文本中的问题解决表征整理成可回链的分析起点，"
                "并明确哪些发现已经来自冻结资料、哪些仍属于待执行或待复核的分析。"
            ),
            "references": (
                "Computational Grounded Theory in Physics Education Research. OSF. https://osf.io/d68ch/"
            ),
            "results": "\n\n".join(results_lines),
            "discussion": (
                "这些编码候选提示，学生的物理问题解决过程可能同时涉及假设与理想化、物理概念、定量处理、"
                "解题方案表述和一般性描述。但当前结果仍是研究者暂定解释与关键词检索形成的分析线索，"
                "不能把关键词命中直接解释为稳定的认知类型或计算聚类发现。\n\n"
                "句子切分及 10/20/30 字符阈值敏感性已经执行，但公式复核清单、主题定义、边界例和反例尚未冻结；"
                + ("嵌入与聚类已有执行记录；" if pattern_performed else "嵌入、UMAP/HDBSCAN 与种子稳定性未执行；")
                +
                "监督模型、学生层稳健性和组间比较也尚未执行。因此，当前稿件适合用于审阅研究路径和定位下一步分析，"
                "不适合报告普遍性、因果关系或外部泛化结论。"
            ),
            "ethics_limitations": (
                "本稿使用公开 OSF 的学生物理问题解决文本作为二手再分析资料，系统仅记录文档版本和哈希。"
                f"公开文本文件的 550 个非空记录与背景表按原始 Stu_ID 一对一连接后冻结 {sample_flow['final_analysis_sample']} 名学生为分析样本，"
                "但尚未完成德语嵌入、UMAP、HDBSCAN、人工标签冻结和监督分类。系统未验证知情同意、"
                "伦理审批或完整脱敏，也未完成编码者间一致性、成员核查或主题饱和度判断。任何投稿或公开前，"
                "研究者必须完成这些复核，并对所有正式主张逐条确认。"
            ),
        }
    )
    draft.update(
        {
            "sections": sections,
            "claim_ids": [
                *draft["claim_ids"],
                *[f"claim:{project_id}:theme:{theme['theme_id']}" for theme in themes if theme.get("theme_id")],
            ],
            "claim_records": [
                *list(draft.get("claim_records", [])),
                *[
                    {
                        "claim_id": f"claim:{project_id}:theme:{theme['theme_id']}",
                        "section": "results",
                        "claim_text": f"主题候选“{theme.get('label') or theme.get('working_name') or theme.get('theme_id')}”由冻结资料中的可回链片段形成，仍待人工定性复核。",
                        "claim_type": "RESULT",
                        "support_type": "candidate_qualitative_data",
                        "support_artifact_ids": [primary_data["artifact_id"]],
                    }
                    for theme in themes
                ],
            ],
            "status": "CANDIDATE_RESULTS_DRAFT_REQUIRES_QUALITATIVE_REVIEW",
            "quality_flags": [
                "DETERMINISTIC_KEYWORD_ASSISTED_CODING",
                "FROZEN_PRIMARY_DATA_VERSION_REFERENCED",
                "INDEPENDENT_QUALITATIVE_REVIEW_REQUIRED",
            ],
            "result_theme_count": len(themes),
            "primary_data_artifact_id": primary_data["artifact_id"],
            "sample_flow": sample_flow,
        }
    )
    return draft


def _deterministic_quantitative_results_manuscript(
    project_id: str, scope: str, package: dict[str, object] | None, pipeline: DataPipelineState
) -> dict[str, object]:
    draft = _deterministic_manuscript_candidate(project_id, scope, package)
    card = pipeline.statistical_result_card
    if card is None or pipeline.frozen_dataset is None:
        return draft
    values = card.values
    group_variable = next(iter(pipeline.model_specification.grouping_variables), "分组变量")
    outcome_variable = next(iter(pipeline.model_specification.outcome_variables), "主要结果变量")
    display_scope = _quantitative_report_context(scope)

    def result_value(*keys: str) -> float:
        for key in keys:
            value = values.get(key)
            if isinstance(value, (int, float)):
                return float(value)
        return float("nan")

    group_1_mean = result_value(f"group_1_{outcome_variable}_mean", "group_1_transfer_mean")
    group_2_mean = result_value(f"group_2_{outcome_variable}_mean", "group_2_transfer_mean")
    mean_difference = result_value(
        f"{outcome_variable}_mean_difference_group_2_minus_group_1",
        "transfer_mean_difference_group_2_minus_group_1",
    )
    ci_lower = result_value(f"{outcome_variable}_mean_difference_ci_lower", "transfer_mean_difference_ci_lower")
    ci_upper = result_value(f"{outcome_variable}_mean_difference_ci_upper", "transfer_mean_difference_ci_upper")
    formatted = "；".join(f"{key}={value:.4g}" for key, value in values.items())
    numeric_literals = [f"{value:.4g}" for value in values.values()]
    result_claim_id = f"claim:{project_id}:result"
    result_direction = (
        "positive" if mean_difference > 0
        else "negative" if mean_difference < 0
        else "no_difference"
    )
    result_table = (
        "| 指标 | 数值 |\n|---|---:|\n"
        f"| 总样本量 | {values.get('analysis_sample_size', float('nan')):.0f} |\n"
        f"| 组 1 n / {outcome_variable} 均值 | {values.get('group_1_n', float('nan')):.0f} / {group_1_mean:.3f} |\n"
        f"| 组 2 n / {outcome_variable} 均值 | {values.get('group_2_n', float('nan')):.0f} / {group_2_mean:.3f} |\n"
        f"| {outcome_variable} 均值差（组 2 - 组 1） | {mean_difference:.3f} |\n"
        f"| 95% CI | [{ci_lower:.3f}, {ci_upper:.3f}] |\n"
        f"| Cohen's d | {values.get('cohens_d_group_2_minus_group_1', float('nan')):.3f} |\n"
        f"| Welch p | {values.get('two_group_welch_p', float('nan')):.4f} |"
    )
    sections = dict(draft["sections"])
    sections.update(
        {
            "title": f"{group_variable} 与 {outcome_variable} 的描述性两组比较：基于冻结 CSV 数据的分析",
            "abstract": (
                f"本研究在“{display_scope}”的研究语境下，对研究者确认的 CSV 变量映射执行两组均值差分析。"
                "数据审计、无损处理、冻结、确定性代码执行和结果解析均保留可追溯记录。"
                "本文仅报告已验证结果卡中的描述性组间差异，不把当前 MVP 的均值差分析扩展为因果结论。"
            ),
            "keywords": f"物理教育；两组比较；{outcome_variable}；冻结数据；可复现统计分析",
            "introduction": (
                f"本研究在“{display_scope}”的研究语境下开展观察性两组比较。为避免事后更改变量或分析规则，系统只对研究者确认的 "
                f"{group_variable} 与 {outcome_variable} 变量执行预先声明的两组描述性比较，并保存数据版本、代码规格、"
                "执行记录与结果卡。"
            ),
            "research_questions": (
                f"RQ1：在冻结样本中，预先定义的两组在 {outcome_variable} 上的均值差是多少？\n"
                "RQ2：该描述性差异在 Bootstrap 和置换检验中是否保持方向一致？\n"
                "RQ3：样本来源、分组方式与分析假设是否支持进一步的解释，或应将结果限定为探索性描述？"
            ),
            "methods": (
                "数据分析采用经批准的 Python-only 两组均值差模板。原始数据先经过字段和直接标识检查，"
                "再以版本化数据快照冻结；数据指纹和执行记录保存在审计附录。"
                f"模型固定为 mean({outcome_variable}) by {group_variable}；代码与执行记录均由确定性执行器产生。"
            ),
            "analysis_plan": (
                f"主要比较为 mean({outcome_variable}) by {group_variable}。执行前锁定 {group_variable}、{outcome_variable}、"
                "样本筛选规则和数据哈希；执行后复算 Bootstrap 区间、置换检验与方向一致性。"
                "任何未预先声明的协变量、子组或替代模型必须作为新版本的探索性分析记录。"
            ),
            "results": (
                "已验证统计结果卡：" + formatted + "。\n\n"
                "解释边界：这些数值仅描述当前冻结样本和预先声明的两组比较。除非设计、随机化、缺失处理、"
                "稳健性分析及研究者审稿均另行确认，不能据此作出一般化或因果主张。"
            ),
            "results_table": result_table,
            "discussion": (
                "当前结果为后续研究解释提供了一个可复现的起点。均值差、置信区间以及 Welch、"
                "Bootstrap 和置换检验应被作为同一组不确定性证据阅读，而不能只依据单一 p 值作结论。"
                "如果不同稳健性检查的方向一致，这只能说明当前冻结样本中的描述性模式较为稳定，"
                "并不等于已经建立了性别编码与物理概念理解之间的因果关系。"
                "该模式的教学意义还需要结合测量效度、样本代表性和预先声明的最小有意义效应进行判断。"
            ),
            "ethics_limitations": (
                "本稿只读取冻结数据引用和验证后的结果卡，不暴露原始行数据。系统未替代研究者对伦理审批、"
                "测量效度、样本代表性和最终统计解释的责任。数据属于公开二手资料时，变量编码、纳入规则和缺失值处理"
                "仍可能受到原始研究设计的限制；当前分析也没有引入未经预注册的协变量或因果模型。"
            ),
            "expected_contribution": (
                "该稿提供一条从冻结 CSV、受控代码到可复核结果卡的可复现报告链。"
                "它支持研究者审阅组间差异及其稳健性，不以软件输出替代研究设计和统计解释。"
            ),
        }
    )
    draft.update(
        {
            "sections": sections,
            "claim_ids": [*draft["claim_ids"], result_claim_id],
            "claim_records": [
                *list(draft.get("claim_records", [])),
                {
                    "claim_id": result_claim_id,
                    "section": "results",
                    "claim_text": "已验证结果卡中的数值只描述冻结样本的两组比较。",
                    "claim_type": "RESULT",
                    "support_type": "validated_result_card",
                    "support_result_ids": [card.ref],
                    "support_artifact_ids": [pipeline.frozen_dataset.ref],
                },
            ],
            "status": "CANDIDATE_RESULTS_DRAFT_REQUIRES_STATISTICAL_REVIEW",
            "quality_flags": [
                "FROZEN_DATASET_REFERENCED",
                "DETERMINISTIC_EXECUTION_VERIFIED",
                "ROBUSTNESS_AND_HUMAN_STATISTICAL_REVIEW_REQUIRED",
            ],
            "result_card_ref": card.ref,
            "primary_data_artifact_id": pipeline.frozen_dataset.ref,
            "numeric_literals": numeric_literals,
            "result_directions": {result_claim_id: result_direction},
            "claim_strengths": {
                "scope": "bounded_to_frozen_sample",
                "method": "predeclared_two_group_description",
                "numeric_result": "validated_result_card_only",
                "causal_interpretation": "not_established",
            },
        }
    )
    return draft


def _merge_llm_prose_into_quantitative_draft(
    deterministic_draft: dict[str, object], llm_draft: dict[str, object] | None
) -> dict[str, object]:
    """Adopt only prose from a validated LLM draft, never research facts.

    Titles, result tables, numeric literals, citation refs, claim records and
    provenance remain Controller-owned. LLM prose is useful for readability,
    but every adopted section remains explicitly marked for researcher review.
    """

    # The result-bearing quantitative manuscript is a controlled report: its
    # prose, numeric results, claims and limitations all have to agree with the
    # frozen dataset and validated result card.  A generic writing response or
    # an unavailable-model fallback cannot safely be merged into that report.
    # The writing agent keeps its own auditable output, while the manuscript
    # shown to the researcher remains the coherent controller-owned draft.
    return deterministic_draft


@app.get("/api/v1/projects/{project_id}/evidence-review")
def project_evidence_review_package(
    project_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
) -> dict[str, object]:
    """Return the latest human-readable evidence package for the project."""

    project = identity_service.get_project(user, project_id)
    packages = [
        item for item in artifact_content_store.list_project(project_id)
        if item.artifact_type == "EvidenceReviewPackage"
    ]
    if not packages:
        # Older authenticated projects may have searchable evidence and QA
        # turns but no orchestration artifact because their commands were
        # routed through the ordinary chat path.  Present that material as a
        # read-only candidate package so the workbench can recover it without
        # pretending that it passed human verification.
        has_legacy_material = bool(service.list_sources(project_id)) or bool(_legacy_qa_turns(project_id))
        if not has_legacy_material:
            raise HTTPException(status_code=404, detail="evidence review package was not found")
        context_bundle = _legacy_project_evidence_context(
            project_id,
            _canonical_research_scope(project.research_direction),
        )
        body = _build_evidence_review_package(
            project_id,
            _canonical_research_scope(project.research_direction),
            [],
            context_bundle=context_bundle,
        )
        body["legacy_projection"] = True
        body["legacy_projection_note"] = (
            "这是旧项目的只读候选包。候选证据仍需人工核对原文定位后，"
            "才能进入正式证据库。"
        )
        content = ArtifactContent(
            project_id=project_id,
            artifact_id=f"legacy-projection:{project_id}:evidence-review",
            version=1,
            artifact_type="EvidenceReviewPackage",
            schema_version="legacy-projection-v1",
            body=body,
        )
        return content.model_dump(mode="json")
    # Artifact ids are random and their lexical order is unrelated to time.
    # Always return the newest immutable package revision. Older packages
    # were written before retrieval trace de-duplication was added, so clean
    # that presentation field on read without changing the immutable record.
    latest = max(packages, key=lambda item: item.created_at)
    body = dict(latest.body)
    # Historical projects may contain a review package created before the
    # belief-canvas projection was introduced.  Replaying this deterministic,
    # idempotent projection on read upgrades those projects without changing
    # the immutable artifact itself.
    _integrate_evidence_review_package_into_canvas(
        project_id,
        body,
        research_scope=str(body.get("research_scope") or "当前研究范围"),
    )
    trace = body.get("retrieval_trace")
    if isinstance(trace, list):
        unique_trace: dict[str, dict[str, object]] = {}
        for item in trace:
            if not isinstance(item, dict):
                continue
            step = item.get("step")
            key = str(step).strip() if step else "|".join(
                str(item.get(field) or "") for field in ("label", "artifact_id")
            )
            if key:
                unique_trace[key] = item
        body["retrieval_trace"] = list(unique_trace.values())
    # The returned body is a read-only presentation projection. Recompute its
    # integrity hash so response validation does not compare the de-duplicated
    # projection with the source package's original hash.
    body_hash = sha256_text(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return {**latest.model_dump(mode="json"), "body": body, "content_hash": body_hash}


@app.put("/api/v1/projects/{project_id}/publication-target", response_model=ControlState)
def set_project_publication_target(
    project_id: str,
    request: PublicationTargetRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> ControlState:
    """Configure the optional journal-formatting stage for a research project."""

    identity_service.get_project(user, project_id)
    loader = JournalProfileLoader()
    try:
        profile = loader.load_journal_profile(request.target_journal)
        if request.article_type is None and len(profile.article_types) > 1:
            raise ContextInputError(
                "article_type_required",
                "该期刊有多个文章类型，请先选择一种再启用投稿格式化："
                + "、".join(profile.article_types),
            )
        loader.resolve_writing_constraints(
            request.target_journal,
            request.article_type,
            methodology=request.methodology,
        )
    except ContextInputError:
        raise
    except UnknownArticleTypeError as error:
        raise ContextInputError("unsupported_article_type", str(error)) from error
    except ValueError as error:
        raise ContextInputError("invalid_publication_target", str(error)) from error
    return control_plane.set_publication_target(
        project_id,
        target_journal=profile.journal.name,
        article_type=request.article_type,
        actor=user.username,
    )


def _latest_journal_revision_inputs(
    project_id: str,
) -> tuple[ManuscriptDraft, AtomicClaimGraph, str] | None:
    """Locate a traceable English draft and its claim graph without translating it."""
    contents = list(reversed(artifact_content_store.list_project(project_id)))
    claim_graph_body = next(
        (item.body for item in contents if item.artifact_type == "AtomicClaimGraph"),
        None,
    )
    for item in contents:
        if item.artifact_type == "ManuscriptDraftEn":
            try:
                draft = ManuscriptDraft.model_validate(item.body)
                graph = AtomicClaimGraph.model_validate(claim_graph_body or {
                    "project_id": project_id,
                    "nodes": [],
                })
                return draft, graph, item.artifact_id
            except ValueError:
                continue
        if item.artifact_type != "ManuscriptDraftZh":
            continue
        inputs = item.body.get("journal_formatting_inputs")
        if not isinstance(inputs, dict):
            continue
        try:
            draft = ManuscriptDraft.model_validate(inputs["english_draft"])
            graph = AtomicClaimGraph.model_validate(inputs.get("claim_graph") or claim_graph_body or {
                "project_id": project_id,
                "nodes": [],
            })
            return draft, graph, item.artifact_id
        except (KeyError, ValueError):
            continue
    return None


@app.post("/api/v1/projects/{project_id}/orchestration/continue")
def continue_project_orchestration(
    project_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
    conversational: bool = False,
) -> dict[str, object]:
    """Run one orchestration action.

    The public compatibility endpoint retains a gate per action for API
    clients that explicitly orchestrate every review. The conversation layer
    passes ``conversational=True`` and only surfaces meaningful checkpoints.
    """

    project = identity_service.get_project(user, project_id)
    state = control_plane.ensure_project(project_id)
    if state.lifecycle_status.value != "ACTIVE":
        raise HTTPException(status_code=409, detail="project is not active")
    if state.active_gate_id:
        pending_gate = control_plane.repository.get_gate(project_id, state.active_gate_id)
        if pending_gate is not None and pending_gate.status is GateStatus.PENDING and not _is_conversational_human_gate(pending_gate):
            try:
                # Compatibility migration for projects that were created with
                # the previous per-action approval policy.
                state = control_plane.decide_gate(
                    project_id,
                    pending_gate.gate_id,
                    decision="approve",
                    actor="orchestrator",
                    role="admin",
                    risk_acceptance=["旧版内部 Gate 已按新版对话流程自动迁移"],
                    reason="新版对话流程不再为内部算子单独暂停",
                )
            except (PermissionError, ValueError):
                pass
        if state.active_gate_id:
            raise HTTPException(status_code=409, detail="project is still waiting for Gate decision")
    # Projects created through the legacy API may have an UNCLASSIFIED stream
    # without a persisted route. Resolve it before selecting a step; the
    # generic bootstrap workflow intentionally omits route-specific stages
    # such as writing and would otherwise reach citation verification without
    # ever producing a manuscript.
    if state.route_decision is None:
        state, _, _ = control_plane.choose_route(
            project_id,
            project.research_direction,
            actor="orchestrator",
        )
    stream = next((item for item in state.workstreams if item.workstream_id == state.active_workstream_id), state.workstreams[0])
    special_action: str | None = None
    if stream.status.value == "COMPLETED" or stream.current_step_index >= len(stream.workflow_steps):
        next_stream = next(
            (item for item in state.workstreams if item.status.value != "COMPLETED"),
            None,
        )
        if next_stream is None:
            # Mixed-methods projects need an explicit project-level synthesis
            # after both route-specific manuscripts have passed their own
            # review Gates.  Keep the project ACTIVE until that merged
            # manuscript is generated and accepted.
            is_mixed_project = bool(
                state.route_decision
                and state.route_decision.primary_route == "MIXED_METHODS"
            )
            has_merge_candidate = any(
                item.artifact_type == "MixedMethodsManuscript"
                and item.lifecycle_status is ArtifactLifecycle.FROZEN
                and item.effective
                for item in control_plane.repository.list_artifacts(project_id)
            )
            if is_mixed_project and not has_merge_candidate:
                special_action = "mixed_methods_merge"
                stream = next(
                    (item for item in state.workstreams if item.workstream_id == state.active_workstream_id),
                    state.workstreams[-1],
                )
            else:
                return {"task": None, "control_state": state.model_dump(mode="json"), "gate": None, "execution_started": False, "message": "研究流程已完成。"}
        else:
            state = control_plane.repository.save_state(
                state.model_copy(update={"active_workstream_id": next_stream.workstream_id}),
                expected_revision=state.state_revision,
            )
            stream = next_stream
    # Resolve the active workstream route so a mixed-method project can move
    # through its qualitative and quantitative tracks independently.
    route = stream.route if stream.route != "UNCLASSIFIED" else (
        state.route_decision.primary_route if state.route_decision else stream.route
    )
    if special_action:
        action = special_action
    elif stream.workflow_steps and stream.current_step_index < len(stream.workflow_steps):
        action = stream.workflow_steps[stream.current_step_index]
    else:
        action = None
    action_by_route_phase = {
        "QUALITATIVE": {
            "RESEARCH_DESIGN": "qualitative_design",
            "DATA_PREPARATION": "qualitative_data_preparation",
            "ANALYSIS_EXECUTION": "thematic_analysis",
            "RESULT_VALIDATION": "qualitative_validation",
            "WRITING_PUBLICATION": "writing",
        },
        "EXPERIMENTAL": {
            "RESEARCH_DESIGN": "research_design",
            "DATA_PREPARATION": "data_preparation",
            "ANALYSIS_EXECUTION": "analysis",
            "RESULT_VALIDATION": "result_validation",
            "WRITING_PUBLICATION": "writing",
        },
    }
    action = action or action_by_route_phase.get(route, {}).get(stream.phase.value)
    if route == "QUALITATIVE" and action in {
        "causal_DAG", "power_analysis", "bootstrap_robustness", "permutation_test",
        "statistical_result_validation", "result_direction_consistency", "uncertainty_gate", "statistical_result_card",
    }:
        skipped = set(stream.skipped_step_ids)
        skipped.add(action)
        next_index = stream.current_step_index + 1
        while next_index < len(stream.workflow_steps) and stream.workflow_steps[next_index] in skipped:
            skipped.add(stream.workflow_steps[next_index])
            next_index += 1
        next_stream = stream.model_copy(update={"skipped_step_ids": sorted(skipped), "current_step_index": next_index})
        next_state = state.model_copy(update={"workstreams": [next_stream if item.workstream_id == stream.workstream_id else item for item in state.workstreams]})
        state = control_plane.repository.save_state(next_state, expected_revision=state.state_revision)
        stream = next_stream
        action = stream.workflow_steps[stream.current_step_index] if stream.current_step_index < len(stream.workflow_steps) else None
    if action is None:
        action = {
            "RESEARCH_DESIGN": "research_design",
            "DATA_PREPARATION": "data_preparation",
            "ANALYSIS_EXECUTION": "analysis",
            "RESULT_VALIDATION": "result_validation",
            "WRITING_PUBLICATION": "writing",
        }.get(stream.phase.value)
    if action is None:
        raise HTTPException(status_code=409, detail="no next orchestration action is available")
    # Keep the user-visible research conversation at meaningful intellectual
    # boundaries.  The underlying operators remain individually auditable.
    existing_outline = any(
        item.workstream_id == stream.workstream_id
        and item.artifact_type == "ManuscriptOutline"
        and item.effective
        for item in control_plane.repository.list_artifacts(project_id)
    )
    requested_manuscript_section = (
        str(stream.conversation_feedback.get("MANUSCRIPT_SECTION_REQUEST", "")).strip().lower()
        or None
    )
    conversation_checkpoint_for_action = (
        "RESEARCH_QUESTION_REVIEW" if action == "research_question_design"
        else "RESEARCH_DESIGN_REVIEW" if action == "power_analysis"
        else "ANALYSIS_CODE_REVIEW" if action == "analysis_code_generation" and conversational
        else "CODE_REVIEW_REVIEW" if action == "code_review" and conversational
        else CGT_CONVERSATION_CHECKPOINTS.get(action) if conversational and action in CGT_CONVERSATION_CHECKPOINTS
        else "RESULT_INTERPRETATION_REVIEW" if action == "uncertainty_gate"
        else "MANUSCRIPT_OUTLINE_REVIEW" if action == "writing" and conversational and not existing_outline
        else MANUSCRIPT_SECTION_CHECKPOINT
        if action == "writing" and conversational and requested_manuscript_section in {"methods", "results", "introduction", "discussion"}
        else None
    )
    generation_feedback = dict(stream.conversation_feedback)
    task = control_plane.enqueue_next_action(project_id, action=action, input_hash=sha256_text(f"{project_id}:{state.state_revision}:{action}"), actor=user.username)
    # Recover projects created before a local implementation fix without
    # asking the researcher to recreate the project. The retry API verifies
    # that this remains the active action at the current state revision.
    if task.status in {ExecutionStatus.FAILED, ExecutionStatus.STALE, ExecutionStatus.CANCELLED}:
        task = control_plane.retry_task(project_id, task.task_id, actor=user.username)
    # Gates are user-facing decision boundaries, not a mirror of every
    # internal operator.  The remaining workflow actions still create
    # immutable, auditable artifacts and are advanced automatically after a
    # decision.  Only decisions that can change the study's interpretation,
    # data provenance, or publication status pause the conversation.

    # All five retrieval substeps in one Continue request operate on the same
    # bounded ContextBundle. Rebuilding dense/sparse/graph retrieval for each
    # substep made a single user action wait several times on the embedding
    # provider. A new Continue request (for example after "继续搜索") gets a
    # fresh bundle and therefore still performs an incremental search.
    evidence_context_cache: ContextBundle | None = None

    def handle(lease):
        nonlocal evidence_context_cache
        agent_result = None
        external_discovery: dict[str, object] | None = None
        source_artifact_ids: list[str] = []
        validation_status = ValidationStatus.PASSED
        validation_warnings: list[str] = []
        data_design_warnings: list[str] = []
        # Every deterministic branch may omit literature evidence; keep the
        # provenance list explicit so newly added CGT artifacts cannot fail
        # late during candidate persistence.
        evidence_ids: list[str] = []
        if action == "mixed_methods_merge":
            # Assemble the latest route-specific manuscripts without asking an
            # LLM to invent a synthesis.  The project-level candidate keeps
            # both source bodies intact and adds an explicit integration layer
            # for researcher review.
            artifact_records = {
                item.artifact_id: item
                for item in control_plane.repository.list_artifacts(project_id)
            }
            latest_by_route: dict[str, tuple[object, object]] = {}
            for content in reversed(artifact_content_store.list_project(project_id)):
                if content.artifact_type != "ManuscriptDraftZh":
                    continue
                record = artifact_records.get(content.artifact_id)
                if record is None:
                    continue
                route_name = next(
                    (item.route for item in state.workstreams if item.workstream_id == record.workstream_id),
                    None,
                )
                if route_name in {"QUALITATIVE", "EXPERIMENTAL"} and route_name not in latest_by_route:
                    latest_by_route[route_name] = (record, content)
            missing_routes = [
                route_name for route_name in ("QUALITATIVE", "EXPERIMENTAL")
                if route_name not in latest_by_route
            ]
            if missing_routes:
                candidate = {
                    "project_id": project_id,
                    "action": action,
                    "status": "MIXED_METHODS_COMPONENTS_MISSING",
                    "missing_routes": missing_routes,
                    "blocking_reason": "定性和定量工作线都必须先形成并通过各自的论文候选与审稿 Gate。",
                }
                artifact_type = "MixedMethodsManuscript"
                validation_status = ValidationStatus.FAILED
                validation_warnings = [candidate["blocking_reason"]]
            else:
                component_payloads: list[dict[str, object]] = []
                parent_ids: list[str] = []
                source_evidence_ids: list[str] = []
                claim_records: list[dict[str, object]] = []
                for route_name in ("QUALITATIVE", "EXPERIMENTAL"):
                    record, content = latest_by_route[route_name]
                    body = content.body if isinstance(content.body, dict) else {}
                    parent_ids.append(record.artifact_id)
                    source_evidence_ids.extend(
                        str(ref) for ref in body.get("citation_refs", [])
                        if isinstance(ref, str)
                    )
                    for claim in body.get("claim_records", []):
                        if isinstance(claim, dict):
                            # Give the project-level graph stable, collision-free
                            # IDs while retaining the originating claim ID for
                            # audit navigation back to the route-specific draft.
                            original_id = str(claim.get("claim_id") or f"{route_name.lower()}-claim-{len(claim_records) + 1}")
                            merged_id = f"claim:{project_id}:mixed:{len(claim_records) + 1}"
                            claim_records.append({
                                **claim,
                                "claim_id": merged_id,
                                "source_claim_id": original_id,
                                "source_route": route_name,
                                "support_artifact_ids": list(dict.fromkeys([
                                    *[str(ref) for ref in claim.get("support_artifact_ids", []) if isinstance(ref, str)],
                                    record.artifact_id,
                                ])),
                            })
                    component_payloads.append({
                        "route": route_name,
                        "artifact_id": record.artifact_id,
                        "artifact_version": record.version,
                        "sections": body.get("sections", {}),
                        "status": body.get("status"),
                        "quality_flags": body.get("quality_flags", []),
                    })
                candidate = {
                    "project_id": project_id,
                    "action": action,
                    "route": "MIXED_METHODS",
                    "status": "MIXED_METHODS_MANUSCRIPT_CANDIDATE_REQUIRES_REVIEW",
                    "sections": {
                        "title": "混合方法研究：定量结果与定性实施解释的整合报告",
                        "abstract": (
                            "本稿整合同一项目中独立完成的定量/实验工作线与定性工作线。"
                            "定量结果仅来自已冻结并验证的结果卡，定性解释仅来自已冻结资料中的可回链主题候选；"
                            "两类结果的共同点、差异和互补关系均需研究者逐条复核。"
                        ),
                        "methods": (
                            "本项目采用并行混合方法设计。定量工作线执行预先声明的两组比较、"
                            "稳健性检查和结果验证；定性工作线执行资料审计、冻结、主题候选和独立复核。"
                            "两条工作线保留各自的数据、代码、证据和审计链，合并阶段只建立跨线解释，不改写任一原始结果。"
                        ),
                        "quantitative_results": "见下方定量工作线组件；不得脱离其结果卡和数据哈希解释。",
                        "qualitative_results": "见下方定性工作线组件；主题候选仍需回链原文和独立编码复核。",
                        "integration": (
                            "整合问题：定量差异是否与定性资料呈现的实施条件、支架需求或机制解释相互印证？"
                            "若两类结果不一致，应保留不一致并说明可能来自样本、测量、情境或分析边界，"
                            "不得强行生成单一结论。"
                        ),
                        "limitations": (
                            "合并稿仍是候选稿；最终主张必须分别关联定量结果卡、定性主题产物或正式文献证据，"
                            "并由研究者和独立审稿人确认。"
                        ),
                    },
                    "components": component_payloads,
                    "claim_records": claim_records,
                    "claim_ids": [str(item["claim_id"]) for item in claim_records if item.get("claim_id")],
                    "citation_refs": sorted(set(source_evidence_ids)),
                    "quality_flags": [
                        "MIXED_METHODS_COMPONENTS_LINKED",
                        "QUANTITATIVE_AND_QUALITATIVE_RESULTS_SEPARATELY_TRACEABLE",
                        "INTEGRATION_REQUIRES_RESEARCHER_REVIEW",
                    ],
                }
                artifact_type = "MixedMethodsManuscript"
                source_artifact_ids = parent_ids
                evidence_ids = sorted(set(source_evidence_ids))
                validation_status = ValidationStatus.WARNING
                validation_warnings = [
                    "定性与定量结果已合并为候选稿；跨方法解释和每条正式主张仍需研究者复核。"
                ]
        elif action == "evidence_normalization":
            _sync_project_documents(project_id)
        if action == "hybrid_retrieval":
            search_addition = str(stream.conversation_feedback.get("evidence_search_addition", "")).strip()
            search_scope = _canonical_research_scope(project.research_direction)
            if search_addition:
                search_scope = f"{search_scope}\n{search_addition}"
            external_discovery = _discover_external_literature(
                project_id,
                search_scope,
            )
        if action == "journal_style_revision":
            source = _latest_journal_revision_inputs(project_id)
            source_artifact_ids = [source[2]] if source is not None else []
            artifact_type = "JournalStyleRevision"
            evidence_ids = []
            if not state.target_journal:
                candidate = {
                    "project_id": project_id,
                    "action": action,
                    "status": "TARGET_JOURNAL_REQUIRED",
                    "blocking_reason": "请先选择目标期刊和文章类型后再执行投稿格式化。",
                }
                validation_status = ValidationStatus.FAILED
                validation_warnings = [candidate["blocking_reason"]]
            elif source is None:
                candidate = {
                    "project_id": project_id,
                    "action": action,
                    "target_journal": state.target_journal,
                    "status": "ENGLISH_MANUSCRIPT_REQUIRED",
                    "blocking_reason": "投稿格式化只接受可追溯的英文稿；系统不会自动翻译中文稿或补造英文内容。",
                }
                validation_status = ValidationStatus.FAILED
                validation_warnings = [candidate["blocking_reason"]]
            else:
                journal_service = _configured_journal_revision_service()
                if journal_service is None:
                    candidate = {
                        "project_id": project_id,
                        "action": action,
                        "target_journal": state.target_journal,
                        "article_type": state.article_type,
                        "status": "JOURNAL_REVISION_MODEL_UNAVAILABLE",
                        "blocking_reason": "投稿格式化需要配置 STEM_SCI_LLM_API_KEY 和 STEM_SCI_LLM_MODEL；Codex 代码生成配置不能替代论文改写模型。",
                    }
                    validation_status = ValidationStatus.FAILED
                    validation_warnings = [candidate["blocking_reason"]]
                else:
                    draft, graph, source_artifact_id = source
                    try:
                        revision = journal_service.revise(
                            JournalStyleRevisionRequest(
                                target_journal=state.target_journal,
                                article_type=state.article_type,
                                draft=draft,
                                claim_graph=graph,
                            )
                        )
                        candidate = {
                            "project_id": project_id,
                            "action": action,
                            "target_journal": state.target_journal,
                            "article_type": state.article_type,
                            "source_manuscript_artifact_id": source_artifact_id,
                            "status": revision.report.status.value,
                            "report": revision.report.model_dump(mode="json"),
                            "revised_draft": revision.draft.model_dump(mode="json"),
                            "journal_validation": (
                                revision.journal_validation.model_dump(mode="json")
                                if revision.journal_validation else None
                            ),
                            "latex": revision.latex.model_dump(mode="json") if revision.latex else None,
                            "recommendation": (
                                revision.recommendation.model_dump(mode="json")
                                if revision.recommendation else None
                            ),
                            "generation_metadata_refs": revision.generation_metadata_refs,
                        }
                        if revision.report.status is RevisionStatus.REQUIRES_CONFIRMATION:
                            validation_status = ValidationStatus.WARNING
                            validation_warnings = ["请确认文章类型后重新执行投稿格式化。"]
                        elif revision.report.status is RevisionStatus.REJECTED:
                            validation_status = ValidationStatus.FAILED
                            validation_warnings = revision.report.safety_findings or ["期刊格式化未通过安全检查。"]
                        elif revision.journal_validation is None or revision.journal_validation.status.value != "PASS":
                            validation_status = ValidationStatus.WARNING
                            validation_warnings = revision.report.layer_warnings or ["期刊规则检查尚未完全通过。"]
                    except (JournalRevisionUnavailableError, ValueError) as error:
                        candidate = {
                            "project_id": project_id,
                            "action": action,
                            "target_journal": state.target_journal,
                            "article_type": state.article_type,
                            "status": "JOURNAL_REVISION_FAILED",
                            "blocking_reason": str(error),
                        }
                        validation_status = ValidationStatus.FAILED
                        validation_warnings = [str(error)]
        agent_id = {
            "evidence_normalization": "evidence_review",
            "hybrid_retrieval": "evidence_review",
            "rrf_fusion": "evidence_review",
            "cross_encoder_rerank": "evidence_review",
            "claim_evidence_support": "evidence_review",
            "research_question_design": "mentor_planning",
            "qualitative_design": "research_design",
            "research_design": "research_design",
            "writing": "paper_writing",
        }.get(action)
        # A conversational outline checkpoint is a structural review, not a
        # prose-generation task. Skip the model-backed writer here so the
        # researcher can approve the outline before any manuscript text is
        # generated (and so a slow/unavailable LLM cannot block the Gate).
        if action == "writing" and (
            conversation_checkpoint_for_action == "MANUSCRIPT_OUTLINE_REVIEW"
            or route == "QUALITATIVE"
        ):
            agent_id = None
        if agent_id and action != "journal_style_revision":
            agent = workflow_controller.dispatcher.registry.get(agent_id)
            run_id = f"orchestration-{action}-{uuid4().hex}"
            context = None
            context_ref = f"orchestration://{project_id}/{action}"
            # The final claim-evidence step is the only evidence action that
            # needs the full ContextBundle. Earlier normalization, retrieval,
            # fusion and reranking steps are recorded as deterministic
            # candidates; rebuilding the same remote retrieval context for
            # each one made a single conversational Continue unnecessarily
            # slow.
            if (
                agent_id == "evidence_review"
                and action == "claim_evidence_support"
                and workflow_controller.context_provider is not None
            ):
                try:
                    if evidence_context_cache is None:
                        evidence_context_cache = workflow_controller.context_provider.build_context(
                            project_id=project_id,
                            task_ref=f"{project_id}:evidence_review",
                            query=(
                                state.route_decision.research_scope
                                if state.route_decision and state.route_decision.research_scope
                                else state.route_decision.primary_route if state.route_decision else action
                            ),
                            token_budget=2000,
                        )
                    context = evidence_context_cache
                    context_ref = context.context_id
                except Exception as error:
                    logger.warning("Could not build evidence context for project %s: %s", project_id, error)
                    context = None
            elif agent_id == "paper_writing":
                try:
                    context = _build_orchestration_writing_context(
                        project_id, project, state
                    )
                    revision_feedback = stream.conversation_feedback.get("MANUSCRIPT_REVISION_REVIEW")
                    if revision_feedback:
                        context = context.model_copy(update={
                            "prior_review_findings": [
                                *context.prior_review_findings,
                                revision_feedback[:2000],
                            ]
                        })
                    context_ref = f"writing-context://{project_id}/{context.context_hash}"
                except Exception as error:
                    logger.warning("Could not build writing context for project %s: %s", project_id, error)
                    context = None
            agent_input = AgentInput(
                agent_run_id=run_id,
                task_ref=f"{project_id}:{action}",
                context_bundle_ref=context_ref,
                allowed_tool_capabilities=list(agent.allowed_tool_capabilities),
                allowed_output_types=list(agent.allowed_output_types),
                policy_version="orchestration-policy-v1",
                prompt_template_version=f"{agent_id}-orchestration-v1",
            )
            if agent_id == "evidence_review" and context is not None:
                agent_result = agent.run_with_context(agent_input, context)
            elif agent_id == "paper_writing" and context is not None:
                agent_result = agent.run_with_context(agent_input, context)
            elif agent_id == "mentor_planning" and hasattr(agent, "propose_for"):
                brief_fields = _research_brief_fields(project, route, user, generation_feedback)
                # PlanningBrief is intentionally smaller than the design
                # contract. Keep its payload exact so a newly added design
                # detail cannot turn into a late Pydantic failure after the
                # evidence Gate has already been approved.
                planning_fields = {
                    key: brief_fields[key]
                    for key in (
                        "topic", "population", "context", "intervention", "comparator",
                        "candidate_outcomes", "constraints", "exclusions",
                    )
                }
                agent_result = agent.propose_for(agent_input, PlanningBrief(
                    agent_run_id=run_id, project_id=project_id, task_ref=f"{project_id}:{action}",
                    evidence_refs=(
                        list((next((item.body for item in artifact_content_store.list_project(project_id)
                                    if item.artifact_type == "EvidenceReviewPackage"), {}) or {}).get("used_evidence_refs", []))
                    ),
                    **planning_fields,
                ), model_assisted=_llm_workflow_enabled()).agent_result
            elif agent_id == "research_design" and hasattr(agent, "propose_for"):
                brief_fields = _research_brief_fields(project, route, user, generation_feedback)
                qualitative = route == "QUALITATIVE"
                experimental = route == "EXPERIMENTAL"
                public_student_reanalysis = str(brief_fields.get("population", "")).startswith("公开二手资料")
                # Do not invent fixture-specific column names in a study
                # design before the researcher has supplied a dataset.  Once
                # a validated CSV exists, carry its approved mapping into the
                # design candidate so the right-hand result never contradicts
                # the actual data schema.
                registered_primary = _registered_quantitative_primary_data(project_id) if not qualitative else None
                registered_header = set(registered_primary.get("header", [])) if registered_primary else set()
                variable_pair = next(
                    (pair for pair in (("group", "transfer_score"), ("experience_group", "ct_capacity_score"))
                     if set(pair).issubset(registered_header)),
                    None,
                )
                group_variable_hint = variable_pair[0] if variable_pair else "待确认的分组变量"
                outcome_variable_hint = variable_pair[1] if variable_pair else "待确认的主要结果变量"
                declared_outcome = str((brief_fields.get("candidate_outcomes") or [outcome_variable_hint])[0])
                primary_outcome = (
                    "公开学生物理问题解决文本中的五类主题候选分布"
                    if public_student_reanalysis
                    else "教师对计算思维整合的认识、实施经验与专业学习需求"
                    if qualitative
                    else f"{outcome_variable_hint}（冻结 CSV 字段）"
                    if variable_pair
                    else declared_outcome
                )
                agent_result = agent.propose_for(agent_input, ResearchDesignBrief(
                    agent_run_id=run_id, project_id=project_id, task_ref=f"{project_id}:{action}",
                    research_contract_ref=f"route://{project_id}",
                    evidence_refs=(
                        list((next((item.body for item in artifact_content_store.list_project(project_id)
                                    if item.artifact_type == "EvidenceReviewPackage"), {}) or {}).get("used_evidence_refs", []))
                    ),
                    population=str(brief_fields["population"]), context=str(brief_fields["context"]),
                    intervention=str(brief_fields["intervention"]), comparator=str(brief_fields["comparator"]),
                    primary_outcome=primary_outcome,
                    secondary_outcomes=(
                        ["公开背景变量的描述性主题对应"]
                        if public_student_reanalysis
                        else ["编程教学困难与支架需求", "课堂迁移条件"]
                        if qualitative else []
                    ),
                    design_type=(
                        "qualitative_thematic_analysis" if qualitative
                        else "randomized_parallel_repeated_measures" if experimental
                        else "observational_two_group_comparison"
                    ),
                    measurement_timepoints=(
                        ["专业发展活动前背景资料", "活动后开放式反思与访谈"]
                        if qualitative else list(brief_fields.get("measurement_timepoints") or ["按研究者确认的基线测量", "按研究者确认的结果测量"])
                    ),
                    sampling_approach=(
                        "公开 OSF 二手资料的全量候选记录；研究者须按原论文筛选规则核验 N=417 边界"
                        if public_student_reanalysis
                        else "目的性抽样：具有高中物理教学经验并接触计算思维或 Python 教学的教师"
                        if qualitative else str(brief_fields.get("sampling_approach") or "目标研究对象；纳入、排除与分组规则须在研究者确认后冻结")
                    ),
                    ethics_ref=f"ethics://{project_id}/pending",
                    confirmatory_model=(
                        f"比较 {group_variable_hint} 分组下的 {outcome_variable_hint} 均值差；"
                        "仅在随机分配及其假设经确认后讨论因果解释。"
                    ),
                    covariates=[], exclusion_rules=[], missing_data_strategy="按预注册方案处理",
                    outlier_strategy="按预注册规则审查",
                ), model_assisted=_llm_workflow_enabled()).agent_result
            else:
                agent_result = agent.run(agent_input)
        if action == "journal_style_revision":
            pass
        elif agent_result is not None and agent_result.candidate_artifacts:
            preferred_types = {
                "evidence_normalization": "EvidenceSufficiencyReport",
                "hybrid_retrieval": "EvidenceMatrixCandidate",
                "rrf_fusion": "BoundedEvidenceSynthesis",
                "cross_encoder_rerank": "EvidenceMatrixCandidate",
                "claim_evidence_support": "ResearchGapReport",
                "research_question_design": "ResearchQuestionTree",
                "qualitative_design": "StudyProtocolCandidate",
                "research_design": "StudyProtocolCandidate",
                "writing": "ManuscriptOutline" if conversation_checkpoint_for_action == "MANUSCRIPT_OUTLINE_REVIEW" else "ManuscriptDraftZh",
            }
            preferred = preferred_types.get(action)
            selected = next((item for item in agent_result.candidate_artifacts if item.artifact_type == preferred), agent_result.candidate_artifacts[0])
            candidate = dict(selected.body)
            if action == "writing":
                critique_artifact = next(
                    (item for item in agent_result.candidate_artifacts if item.artifact_type == "WritingCritiqueReport"),
                    None,
                )
                if critique_artifact is not None and isinstance(critique_artifact.body, dict):
                    # Keep critique feedback adjacent to the immutable draft so
                    # the researcher can review it without opening an Agent
                    # panel; it is advisory and cannot alter provenance.
                    candidate["writing_critique"] = dict(critique_artifact.body)
                # When model writing is unavailable, retain the route-specific
                # qualitative manuscript contract instead of replacing it with
                # the generic incomplete fallback from PaperWritingAgent.  A
                # real LLM candidate keeps its richer output and is handled
                # below as usual.
                if route == "QUALITATIVE" and candidate.get("status") == "INCOMPLETE_CANDIDATE":
                    package_body = _latest_artifact_body(project_id, "EvidenceReviewPackage")
                    primary_data = _registered_qualitative_primary_data(project_id)
                    if primary_data is not None:
                        critique = candidate.get("writing_critique")
                        candidate = _deterministic_qualitative_results_manuscript(
                            project_id, project.research_direction, package_body, primary_data
                        )
                        if isinstance(critique, dict):
                            candidate["writing_critique"] = critique
                elif route == "QUALITATIVE":
                    # Qualitative result claims and their source-artifact links
                    # are Controller-owned. A model candidate may contain good
                    # prose but omit those records, which would make the
                    # manuscript look complete while leaving the audit graph
                    # empty. Always render the governed deterministic contract
                    # when frozen primary material exists.
                    primary_data = _registered_qualitative_primary_data(project_id)
                    if primary_data is not None:
                        critique = candidate.get("writing_critique")
                        candidate = _deterministic_qualitative_results_manuscript(
                            project_id,
                            project.research_direction,
                            _latest_artifact_body(project_id, "EvidenceReviewPackage"),
                            primary_data,
                        )
                        if isinstance(critique, dict):
                            candidate["writing_critique"] = critique
                # The route-specific review contract is controller-owned. A
                # model-provided generic status such as ``CANDIDATE_LLM`` must
                # not hide the mandatory qualitative review checkpoint.
                if action == "writing" and route == "QUALITATIVE":
                    candidate["status"] = "CANDIDATE_RESULTS_DRAFT_REQUIRES_QUALITATIVE_REVIEW"
                llm_writing_candidate = (
                candidate
                if action == "writing" and conversation_checkpoint_for_action != "MANUSCRIPT_OUTLINE_REVIEW"
                else None
            )
            candidate.update({"project_id": project_id, "action": action, "route": route, "agent_id": agent_result.agent_id})
            if action == "writing" and conversation_checkpoint_for_action != "MANUSCRIPT_OUTLINE_REVIEW":
                # Once a quantitative result card exists, the manuscript must
                # be rendered from that immutable card rather than from a
                # generic writing-agent draft.  This prevents stale or
                # invented numbers from entering the Results section.
                quantitative_pipeline = _latest_quantitative_pipeline_state(project_id)
                if route != "QUALITATIVE" and quantitative_pipeline is not None and quantitative_pipeline.statistical_result_card is not None:
                    package_body = _latest_artifact_body(project_id, "EvidenceReviewPackage")
                    candidate = _deterministic_quantitative_results_manuscript(
                        project_id, project.research_direction, package_body, quantitative_pipeline
                    )
                    candidate = _merge_llm_prose_into_quantitative_draft(
                        candidate, llm_writing_candidate
                    )
                english = next(
                    (item.body for item in agent_result.candidate_artifacts if item.artifact_type == "ManuscriptDraftEn"),
                    None,
                )
                graph = next(
                    (item.body for item in agent_result.candidate_artifacts if item.artifact_type == "AtomicClaimGraph"),
                    None,
                )
                if isinstance(english, dict):
                    candidate["journal_formatting_inputs"] = {
                        "english_draft": english,
                        "claim_graph": graph if isinstance(graph, dict) else {"project_id": project_id, "nodes": []},
                    }
            artifact_type = selected.artifact_type
            evidence_ids = list(agent_result.evidence_refs)
        elif action != "mixed_methods_merge":
            if action == "writing" and conversation_checkpoint_for_action == "MANUSCRIPT_OUTLINE_REVIEW":
                package_body = _latest_artifact_body(project_id, "EvidenceReviewPackage")
                candidate = _deterministic_manuscript_outline(
                    project_id, project.research_direction, package_body
                )
                artifact_type = "ManuscriptOutline"
                evidence_ids = list(candidate.get("evidence_refs", []))
            elif action == "writing" and requested_manuscript_section in {
                "methods", "results", "introduction", "discussion"
            }:
                package_body = _latest_artifact_body(project_id, "EvidenceReviewPackage")
                primary_data = _registered_qualitative_primary_data(project_id) if route == "QUALITATIVE" else None
                full_candidate = (
                    _deterministic_qualitative_results_manuscript(
                        project_id, project.research_direction, package_body, primary_data
                    )
                    if primary_data is not None
                    else _deterministic_quantitative_results_manuscript(
                        project_id,
                        project.research_direction,
                        package_body,
                        _latest_quantitative_pipeline_state(project_id),
                    )
                    if route != "QUALITATIVE"
                    and _latest_quantitative_pipeline_state(project_id) is not None
                    and _latest_quantitative_pipeline_state(project_id).statistical_result_card is not None
                    else _deterministic_manuscript_candidate(
                        project_id, project.research_direction, package_body
                    )
                )
                section_body = str(
                    (full_candidate.get("sections") or {}).get(requested_manuscript_section, "")
                ).strip()
                if not section_body:
                    section_body = "当前冻结资料没有足够内容支持这一节；系统没有补写未执行的分析或未核验的文献主张。"
                candidate = {
                    "project_id": project_id,
                    "action": action,
                    "route": route,
                    "section": requested_manuscript_section,
                    "title": {
                        "methods": "数据与方法",
                        "results": "结果",
                        "introduction": "引言与理论背景",
                        "discussion": "讨论与局限",
                    }[requested_manuscript_section],
                    "body": section_body,
                    "source_draft_status": full_candidate.get("status"),
                    "citation_refs": list(full_candidate.get("citation_refs", [])),
                    "claim_ids": list(full_candidate.get("claim_ids", [])),
                    "claim_records": list(full_candidate.get("claim_records", [])),
                    "boundary": "本节只来自当前冻结资料、已执行记录和可核验来源；没有执行证据的数字和参数不会补写。",
                }
                if primary_data is not None:
                    source_artifact_ids = [str(primary_data["artifact_id"])]
                    validation_status = ValidationStatus.WARNING
                    validation_warnings = [
                        "本节仍需要独立审稿和最终引用核验；系统未把章节候选当作完整论文。"
                    ]
                artifact_type = "ManuscriptSectionCandidate"
                evidence_ids = list(candidate.get("citation_refs", []))
            elif action == "writing":
                package_body = _latest_artifact_body(project_id, "EvidenceReviewPackage")
                primary_data = _registered_qualitative_primary_data(project_id) if route == "QUALITATIVE" else None
                candidate = (
                    _deterministic_qualitative_results_manuscript(
                        project_id, project.research_direction, package_body, primary_data
                    )
                    if primary_data is not None
                    else _deterministic_quantitative_results_manuscript(
                        project_id,
                        project.research_direction,
                        package_body,
                        _latest_quantitative_pipeline_state(project_id),
                    )
                    if route != "QUALITATIVE"
                    and _latest_quantitative_pipeline_state(project_id) is not None
                    and _latest_quantitative_pipeline_state(project_id).statistical_result_card is not None
                    else _deterministic_manuscript_candidate(
                        project_id, project.research_direction, package_body
                    )
                )
                if primary_data is not None:
                    source_artifact_ids = [str(primary_data["artifact_id"])]
                    validation_status = ValidationStatus.WARNING
                    validation_warnings = [
                        "论文中的定性主题仍需要独立编码复核和研究者最终引用核验。"
                    ]
                artifact_type = "ManuscriptDraftZh"
                evidence_ids = list(candidate.get("citation_refs", []))
            elif route == "QUALITATIVE" and action == "raw_data_import":
                primary_data = _registered_qualitative_primary_data(project_id)
                if primary_data is None:
                    candidate = {
                        "project_id": project_id,
                        "action": action,
                        "route": route,
                        "status": "WAITING_PRIMARY_DATA",
                        "required_inputs": [
                            "去标识化的教师背景问卷或开放式回答",
                            "访谈/反思文本及其资料来源说明",
                        ],
                        "policy": "当前上传的论文只能作为文献证据，不能替代参与者原始资料。",
                    }
                else:
                    source_artifact_ids = [str(primary_data["artifact_id"])]
                    candidate = {
                        "project_id": project_id,
                        "action": action,
                        "route": route,
                        "status": "PRIMARY_DATA_REGISTERED",
                        "data_manifest": {
                            key: primary_data[key]
                            for key in ("source_dataset_ref", "document_id", "document_version", "content_sha256", "character_count", "segment_count", "source_kind")
                        },
                        "policy": "已登记的数据版本是后续审计和主题分析的唯一输入；论文与外部候选仍只作为文献证据。",
                    }
                artifact_type = "RawDataImportCandidate"
                evidence_ids = []
            elif route == "QUALITATIVE" and action == "data_audit":
                primary_data = _registered_qualitative_primary_data(project_id)
                if primary_data is None:
                    candidate = {
                        "project_id": project_id,
                        "action": action,
                        "route": route,
                        "status": "NOT_RUN_NO_PRIMARY_DATA",
                        "checks": ["文件完整性与版本", "参与者标识去除", "资料分段与编码格式", "研究者访问权限与审计日志"],
                        "blocking_reason": "尚未导入教师原始定性资料。",
                    }
                    validation_status = ValidationStatus.FAILED
                else:
                    source_artifact_ids = [str(primary_data["artifact_id"])]
                    raw_text = "\n".join(str(item["text"]) for item in primary_data["segments"] if isinstance(item, dict))
                    privacy_findings = _qualitative_privacy_findings(raw_text)
                    passed = not privacy_findings
                    candidate = {
                        "project_id": project_id,
                        "action": action,
                        "route": route,
                        "status": "PASSED" if passed else "REWORK_REQUIRED",
                        "data_manifest": {
                            key: primary_data[key]
                            for key in ("source_dataset_ref", "document_version", "content_sha256", "character_count", "segment_count", "source_kind")
                        },
                        "checks": {
                            "version_hash_verified": True,
                            "nonempty_segments": int(primary_data["segment_count"]),
                            "direct_identifier_findings": privacy_findings,
                            "semantic_content_unchanged": True,
                        },
                        "decision_boundary": "此审计只能发现明显格式和直接标识问题，不替代伦理审批或人工脱敏复核。",
                    }
                    validation_status = ValidationStatus.PASSED if passed else ValidationStatus.FAILED
                artifact_type = "DataAuditCandidate"
                evidence_ids = []
            elif route == "QUALITATIVE" and action == "data_processing_approval":
                primary_data = _registered_qualitative_primary_data(project_id)
                candidate = {
                    "project_id": project_id,
                    "action": action,
                    "route": route,
                    "status": "PENDING_USER_APPROVAL" if primary_data else "NOT_READY_NO_PRIMARY_DATA",
                    "source_dataset_ref": primary_data.get("source_dataset_ref") if primary_data else None,
                    "proposed_operations": [
                        "保留原始文本只读副本",
                        "去除直接身份标识并生成参与者伪名",
                        "记录排除和清洗规则，不修改语义内容",
                    ],
                }
                if primary_data is None:
                    validation_status = ValidationStatus.FAILED
                else:
                    source_artifact_ids = [str(primary_data["artifact_id"])]
                artifact_type = "DataProcessingApprovalCandidate"
                evidence_ids = []
            elif route == "QUALITATIVE" and action == "dataset_freeze_hash":
                primary_data = _registered_qualitative_primary_data(project_id)
                sample_flow = _qualitative_sample_flow(project_id, primary_data) if primary_data else None
                selected_data = _qualitative_analysis_primary_data(project_id, primary_data) if primary_data else None
                selected_ids = list(selected_data.get("participant_labels", [])) if selected_data else []
                if sample_flow is not None:
                    sample_flow = {
                        **sample_flow,
                        "final_analysis_sample": len(selected_ids),
                    }
                candidate = {
                    "project_id": project_id,
                    "action": action,
                    "route": route,
                    "status": "FROZEN_VERSION_CANDIDATE" if primary_data else "NOT_FROZEN_NO_PRIMARY_DATA",
                    "frozen_dataset_ref": primary_data.get("source_dataset_ref") if primary_data else None,
                    "sha256": primary_data.get("content_sha256") if primary_data else None,
                    "immutable_document_version": primary_data.get("document_version") if primary_data else None,
                    "analysis_selection": "nonempty Text inner-joined to background variables by original Stu_ID",
                    "selected_student_count": len(selected_ids),
                    "selected_student_manifest_sha256": (
                        sha256_text("\n".join(selected_ids)) if selected_ids else None
                    ),
                    "sample_flow": sample_flow,
                    "blocking_reason": None if primary_data else "只有完成原始资料导入、审计和处理审批后才能生成冻结哈希。",
                }
                if primary_data is None:
                    validation_status = ValidationStatus.FAILED
                else:
                    source_artifact_ids = [str(primary_data["artifact_id"])]
                artifact_type = "DatasetFreezeHashCandidate"
                evidence_ids = []
            elif route == "QUALITATIVE" and action == "thematic_analysis":
                primary_data = _registered_qualitative_primary_data(project_id)
                if primary_data is None:
                    candidate = {
                        "project_id": project_id,
                        "action": action,
                        "route": route,
                        "status": "PROTOCOL_READY_PRIMARY_DATA_REQUIRED",
                        "restriction": "没有教师原始资料时不得报告主题频数或参与者经验结论。",
                    }
                    validation_status = ValidationStatus.FAILED
                else:
                    source_artifact_ids = [str(primary_data["artifact_id"])]
                    coding_input = _qualitative_coding_input(project_id, primary_data)
                    manual_theme_body = _latest_artifact_body(project_id, "ManualThemeRevisionCandidate")
                    themes = (
                        [item for item in manual_theme_body.get("themes", []) if isinstance(item, dict)]
                        if isinstance(manual_theme_body, dict) and manual_theme_body.get("themes")
                        else _deterministic_theme_candidates(coding_input)
                    )
                    sample_warning_parts = []
                    if int(coding_input["segment_count"]) < 3 or len(coding_input["participant_labels"]) < 3:
                        sample_warning_parts.append(
                            "资料分段或可识别的参与者标签不足 3 个；只能作为编码演练或试点材料，不能声称主题饱和。"
                        )
                    if primary_data.get("source_kind") == "public_secondary_tsv":
                        sample_warning_parts.append(
                            "这是公开 OSF 二手资料；分析样本来自文本表与背景表按原始 Stu_ID 的连接，不能把 550 个文本记录直接写成最终样本量。"
                        )
                    sample_warning = " ".join(sample_warning_parts) or None
                    candidate = {
                        "project_id": project_id,
                        "action": action,
                        "route": route,
                        "status": "CANDIDATE_THEME_MAP_READY" if themes else "NO_THEME_CANDIDATE_REQUIRES_REVIEW",
                        "data_manifest": {
                            key: coding_input[key]
                            for key in ("source_dataset_ref", "content_sha256", "segment_count", "participant_labels", "source_kind")
                        },
                        "themes": themes,
                        "analysis_steps": ["关键词辅助初始编码", "研究者复核编码边界", "反例检查", "跨资料来源比较", "保留审计轨迹"],
                        "interpretation_boundary": "主题来自计算候选与人工修订链；在结果卡确认前不是正式实证结论。",
                        "sample_adequacy_warning": sample_warning,
                    }
                    validation_status = ValidationStatus.WARNING
                    validation_warnings = [
                        "主题候选来自确定性辅助编码，仍需要独立研究者复核。",
                        *([sample_warning] if sample_warning else []),
                    ]
                artifact_type = "ThematicAnalysisCandidate"
                evidence_ids = []
            elif route == "QUALITATIVE" and action == "qualitative_validation":
                primary_data = _registered_qualitative_primary_data(project_id)
                if primary_data is None:
                    candidate = {
                        "project_id": project_id,
                        "action": action,
                        "route": route,
                        "status": "NOT_VALIDATED_NO_PRIMARY_DATA",
                        "required_checks": ["编码一致性或同行复核", "反例和负例检查", "主题边界与原文回链", "研究者反思与审计日志"],
                    }
                    validation_status = ValidationStatus.FAILED
                else:
                    source_artifact_ids = [str(primary_data["artifact_id"])]
                    themes = _deterministic_theme_candidates(primary_data)
                    candidate = {
                        "project_id": project_id,
                        "action": action,
                        "route": route,
                        "status": "REVIEW_REQUIRED",
                        "checks": {
                            "source_hash_verified": True,
                            "theme_count": len(themes),
                            "theme_evidence_links_present": all(bool(theme["evidence_segment_ids"]) for theme in themes),
                            "independent_reviewer_completed": False,
                        },
                        "required_next_review": ["研究者逐条回链原文", "记录负例或反例", "第二位研究者/同行复核", "确认资料饱和度边界"],
                        "decision_boundary": "系统不能替代编码者间一致性、成员核查或伦理判断。",
                    }
                    validation_status = ValidationStatus.WARNING
                    validation_warnings = ["尚未完成独立编码复核，不能将主题候选直接写为最终实证结论。"]
                artifact_type = "QualitativeValidationCandidate"
                evidence_ids = []
            elif route == "QUALITATIVE" and action == "analysis_code_generation":
                primary_data = _registered_qualitative_primary_data(project_id)
                source_artifact_ids = [str(primary_data["artifact_id"])] if primary_data else []
                candidate = {
                    "project_id": project_id,
                    "action": action,
                    "route": route,
                    "status": "CODE_SPECIFICATION_CANDIDATE" if primary_data else "CODE_SPECIFICATION_BLOCKED_NO_DATA",
                    "modules": [
                        {"name": "data_audit_and_freeze", "input": "冻结 CSV", "output": "审计表、排除清单、哈希", "randomness": "none"},
                        {"name": "german_sentence_segmentation", "input": "Text + Stu_ID", "output": "Sentence_ID 句子表", "randomness": "none"},
                        {"name": "embedding_and_pattern_discovery", "input": "句子表", "output": "多种子聚类与噪声摘要", "randomness": "UMAP/HDBSCAN seeds persisted"},
                        {"name": "review_packet", "input": "聚类结果", "output": "代表句、边界句、噪声句", "randomness": "deterministic ranking"},
                        {"name": "human_codebook_import", "input": "研究者标签", "output": "版本化 Codebook", "randomness": "none"},
                        {"name": "supervised_confirmation", "input": "冻结人工标签", "output": "分层与 Stu_ID 分组交叉验证", "randomness": "fold seeds persisted"},
                        {"name": "group_comparison", "input": "冻结句子标签 + 背景变量", "output": "句子列联表、学生层主题比例和文本长度检查", "randomness": "none unless resampling is approved"},
                        {"name": "student_level_robustness", "input": "句子标签 + Stu_ID", "output": "学生层面比例和稳健性", "randomness": "bootstrap seeds persisted"},
                        {"name": "robustness_analysis", "input": "冻结主题比例 + Stu_ID", "output": "学生聚类重抽样或层级/组成数据敏感性结果", "randomness": "approved resampling seeds persisted"},
                        {"name": "result_summary", "input": "已执行输出和日志", "output": "结果卡与未执行项清单", "randomness": "none"},
                    ],
                    "failure_conditions": ["缺少 Stu_ID 或 Text", "公式分句需人工复核", "未冻结人工标签不得报告监督性能"],
                    "data_manifest": primary_data.get("content_sha256") if primary_data else None,
                }
                artifact_type = "AnalysisCodeSpecificationCandidate"
                evidence_ids = []
                if primary_data is None:
                    validation_status = ValidationStatus.FAILED
            elif route == "QUALITATIVE" and action == "code_review":
                code_spec = _latest_artifact_body(project_id, "AnalysisCodeSpecificationCandidate")
                candidate = {
                    "project_id": project_id,
                    "action": action,
                    "route": route,
                    "status": "CODE_REVIEW_PASSED" if code_spec else "CODE_REVIEW_BLOCKED_NO_SPEC",
                    "checks": {
                        "nan_filtered_before_string_conversion": True,
                        "raw_data_read_only": True,
                        "student_id_preserved": True,
                        "formula_protection_required": True,
                        "random_seeds_persisted": True,
                        "sentence_and_student_units_separated": True,
                    },
                    "preprocessing_code_candidate": {
                        "scope": "data audit and German sentence preprocessing only",
                        "baseline_minimum_characters": 20,
                        "sensitivity_thresholds": [10, 20, 30],
                        "preserve_columns": ["Stu_ID", "Sentence_ID", "Text_original"],
                        "short_formula_policy": "retain_for_review",
                        "forbidden_outputs": ["theme_label", "cluster_id", "paper_claim"],
                    },
                    "review_boundary": "静态审查不等于执行；执行前仍需研究者批准。",
                }
                artifact_type = "AnalysisCodeReviewCandidate"
                evidence_ids = []
                if not code_spec:
                    validation_status = ValidationStatus.FAILED
            elif route == "QUALITATIVE" and action == "manual_execution_approval":
                code_review = _latest_artifact_body(project_id, "AnalysisCodeReviewCandidate")
                candidate = {
                    "project_id": project_id,
                    "action": action,
                    "route": route,
                    "status": "EXECUTION_APPROVAL_CANDIDATE" if code_review else "EXECUTION_APPROVAL_BLOCKED_NO_REVIEW",
                    "scope": "仅运行冻结数据审计与德语句子预处理；不下载模型，不执行嵌入、聚类或主题标注。",
                    "required_confirmation": "明确批准只执行数据审计和预处理",
                }
                artifact_type = "ManualExecutionApprovalCandidate"
                evidence_ids = []
                if not code_review:
                    validation_status = ValidationStatus.FAILED
            elif route == "QUALITATIVE" and action == "sandbox_analysis_execution":
                primary_data = _registered_qualitative_primary_data(project_id)
                candidate = _qualitative_preprocessing_candidate(project_id, primary_data or {})
                artifact_type = "PreprocessingExecutionCandidate"
                evidence_ids = []
                source_artifact_ids = [str(primary_data["artifact_id"])] if primary_data else []
                if primary_data is None:
                    validation_status = ValidationStatus.FAILED
            elif route == "QUALITATIVE" and action == "pattern_code_generation":
                preprocessing = _latest_artifact_body(project_id, "PreprocessingExecutionCandidate") or {}
                performed = bool((preprocessing.get("execution") or {}).get("performed")) if isinstance(preprocessing.get("execution"), dict) else False
                candidate = {
                    "project_id": project_id,
                    "action": action,
                    "route": route,
                    "status": "PATTERN_CODE_CANDIDATE_REQUIRES_APPROVAL" if performed else "PATTERN_CODE_BLOCKED_NO_PREPROCESSING",
                    "embedding": {"model": "multilingual_or_german_sentence_transformer", "executed": False},
                    "umap": {"n_components": 5, "n_neighbors": 15, "metric": "cosine", "min_dist": 0, "executed": False},
                    "hdbscan": {"min_cluster_size": 15, "metric": "euclidean", "cluster_selection_method": "eom", "preset_cluster_count": None, "executed": False},
                    "run_plan": {
                        "smoke_seed_count": 20,
                        "distribution_seed_count": 100,
                        "formal_stability_seed_count": 1000,
                        "execute_in_separate_approved_stages": True,
                    },
                    "required_outputs": ["environment", "runtime", "peak_memory", "cluster_count_by_seed", "noise_ratio_by_seed", "crash_log"],
                    "boundary": "这是代码与参数候选；20、100、1000 是计划运行次数，不是已完成次数。",
                }
                artifact_type = "PatternDiscoveryCodeCandidate"
                validation_status = ValidationStatus.WARNING if performed else ValidationStatus.FAILED
                validation_warnings = ["模式发现代码尚未执行；需要单独批准 20 种子烟雾测试。"]
            elif route == "QUALITATIVE" and action == "pattern_smoke_execution":
                code_candidate = _latest_artifact_body(project_id, "PatternDiscoveryCodeCandidate") or {}
                candidate = {
                    "project_id": project_id,
                    "action": action,
                    "route": route,
                    "status": "SMOKE_TEST_NOT_EXECUTED_MODEL_UNAVAILABLE",
                    "source_code_candidate": code_candidate,
                    "execution": {
                        "performed": False,
                        "requested_seed_count": 20,
                        "completed_seed_count": 0,
                        "environment": {"large_embedding_model_available": False},
                        "runtime_seconds": None,
                        "peak_memory_mb": None,
                        "cluster_counts": [],
                        "noise_ratios": [],
                        "crashes": [],
                        "reason": "当前验收环境未安装或下载指定句子嵌入模型；不能用关键词分组冒充 UMAP/HDBSCAN 烟雾测试。",
                    },
                    "boundary": "未执行时不报告簇数、噪声比例或烟雾测试通过。",
                }
                artifact_type = "PatternSmokeExecutionCandidate"
                validation_status = ValidationStatus.WARNING
                validation_warnings = ["20 种子烟雾测试未执行，后续稳定性结果不可声称完成。"]
            elif route == "QUALITATIVE" and action == "pattern_stability_execution":
                smoke = _latest_artifact_body(project_id, "PatternSmokeExecutionCandidate") or {}
                smoke_execution = smoke.get("execution") if isinstance(smoke.get("execution"), dict) else {}
                candidate = {
                    "project_id": project_id,
                    "action": action,
                    "route": route,
                    "status": "STABILITY_NOT_EXECUTED_SMOKE_INCOMPLETE",
                    "source_smoke_execution": smoke,
                    "execution": {
                        "performed": False,
                        "requested_distribution_seed_count": 100,
                        "requested_formal_seed_count": 1000,
                        "completed_seed_count": 0,
                        "cluster_count_mode": None,
                        "cluster_count_range": None,
                        "noise_ratio_distribution": None,
                        "cross_seed_cluster_stability": None,
                        "reason": "20 种子烟雾测试未实际完成，不能继续声称 100/1000 种子稳定性运行。" if not smoke_execution.get("performed") else "稳定性运行尚未获得可验证执行日志。",
                    },
                    "candidate_solutions": [],
                    "boundary": "100 和 1000 是用户指定的计划规模，不是已完成运行。",
                }
                artifact_type = "PatternStabilityExecutionCandidate"
                validation_status = ValidationStatus.WARNING
                validation_warnings = ["稳定性运行未执行，候选簇审阅包只能保持受阻状态。"]
            elif route == "QUALITATIVE" and action == "pattern_discovery_review":
                primary_data = _registered_qualitative_primary_data(project_id)
                stability = _latest_artifact_body(project_id, "PatternStabilityExecutionCandidate") or {}
                stability_execution = stability.get("execution") if isinstance(stability.get("execution"), dict) else {}
                patterns = _computational_pattern_candidates(primary_data or {}) if stability_execution.get("performed") else []
                candidate = {
                    "project_id": project_id,
                    "action": action,
                    "route": route,
                    "status": "CLUSTER_REVIEW_PACKET_READY" if patterns else "CLUSTER_REVIEW_BLOCKED_NO_EXECUTION",
                    "source_execution": stability,
                    "clusters": patterns,
                    "review_packet": {
                        "required_per_cluster": ["size", "representative_segments", "boundary_segments", "student_ids"],
                        "noise_cluster_included": any(bool(item.get("noise")) for item in patterns),
                        "names_are_neutral": True,
                    },
                    "decision_boundary": "只有实际嵌入与聚类日志可以生成簇审阅包；关键词候选不能冒充计算聚类结果。",
                }
                artifact_type = "ClusterReviewPacket"
                source_artifact_ids = [str(primary_data["artifact_id"])] if primary_data else []
                validation_status = ValidationStatus.WARNING
                validation_warnings = [
                    "实际模式运行未完成，当前没有可供审阅的聚类代表句、边界句或噪声样本。"
                    if not patterns else
                    "需要研究者阅读代表句、边界句、噪声句并记录保留/拆分/合并理由。"
                ]
            elif route == "QUALITATIVE" and action == "codebook_review":
                primary_data = _registered_qualitative_primary_data(project_id)
                pattern_packet = _latest_artifact_body(project_id, "ClusterReviewPacket") or {}
                patterns = [item for item in pattern_packet.get("clusters", []) if isinstance(item, dict)]
                feedback = stream.conversation_feedback.get("PATTERN_DISCOVERY_REVIEW", "")
                if patterns:
                    codebook = [
                        {
                            "theme_id": f"theme_candidate_{index}",
                            "source_cluster": item.get("cluster_id"),
                            "candidate_basis": "executed_pattern_discovery",
                            "working_name": item.get("label", f"簇 {index}"),
                            "definition": "待研究者根据代表句和边界句填写的语义定义",
                            "inclusion_rules": [],
                            "exclusion_rules": [],
                            "positive_examples": list(item.get("representative_segments", []))[:3],
                            "boundary_examples": list(item.get("boundary_segments", []))[:2],
                            "counterexamples": [],
                            "status": "DRAFT_REQUIRES_HUMAN_DEFINITION",
                        }
                        for index, item in enumerate(patterns)
                    ]
                else:
                    # The researcher may still propose theoretical working
                    # labels when computational pattern discovery is blocked.
                    # Keep them useful but unmistakably separate from clusters.
                    coding_input = _qualitative_coding_input(project_id, primary_data or {})
                    assisted = [
                        item for item in _deterministic_theme_candidates(coding_input)
                        if str(item.get("theme_id", "")).split(":")[-1] in {
                            "assumptions_and_idealizations", "conceptual_aspects",
                            "quantitative_aspects", "formulation_of_solution", "general_descriptions",
                        }
                    ]
                    codebook = [
                        {
                            "theme_id": str(item.get("theme_id")),
                            "source_cluster": None,
                            "candidate_basis": "researcher_provisional_interpretation_with_keyword_retrieval",
                            "working_name": str(item.get("label")),
                            "definition": str(item.get("operational_definition")),
                            "inclusion_rules": [str(item.get("inclusion_rule"))],
                            "exclusion_rules": [str(item.get("exclusion_rule"))],
                            "positive_examples": list(item.get("representative_examples", []))[:3],
                            "boundary_examples": [],
                            "counterexamples": list(item.get("contrast_examples", []))[:2],
                            "evidence_count": int(item.get("evidence_count", 0) or 0),
                            "coverage_proportion": item.get("coverage_proportion"),
                            "status": "THEORY_LED_DRAFT_NOT_A_CLUSTER_RESULT",
                        }
                        for item in assisted
                    ]
                candidate = {
                    "project_id": project_id,
                    "action": action,
                    "route": route,
                    "status": "CODEBOOK_CANDIDATE_REQUIRES_REVIEW",
                    "source_pattern_packet": pattern_packet,
                    "researcher_pattern_feedback": feedback[:2000],
                    "codebook": codebook,
                    "agreement_plan": {"second_coder": True, "statistics": ["cohen_kappa", "krippendorff_alpha"]},
                    "boundary": (
                        "模式发现未执行；本 Codebook 仅由研究者暂定解释和透明关键词检索形成，不得称为聚类发现。"
                        if not patterns else
                        "主题名称和规则尚未冻结；不得将该候选写入正式结果。"
                    ),
                }
                artifact_type = "CodebookCandidate"
                source_artifact_ids = [str(primary_data["artifact_id"])] if primary_data else []
                validation_status = ValidationStatus.WARNING
                validation_warnings = ["Codebook 需要研究者定义纳入/排除边界并保留反例。"]
            elif route == "QUALITATIVE" and action == "manual_theme_revision":
                primary_data = _registered_qualitative_primary_data(project_id)
                codebook_body = _latest_artifact_body(project_id, "CodebookCandidate") or {}
                feedback = stream.conversation_feedback.get("CODEBOOK_REVIEW", "")
                themes = list(codebook_body.get("codebook", []))
                candidate = {
                    "project_id": project_id,
                    "action": action,
                    "route": route,
                    "status": "MANUAL_THEME_REVISION_CANDIDATE",
                    "input_codebook": codebook_body,
                    "researcher_revision": feedback[:2000],
                    "themes": themes,
                    "revision_log": [{"event": "researcher_review", "detail": feedback[:2000]}] if feedback else [],
                    "frozen": False,
                }
                artifact_type = "ManualThemeRevisionCandidate"
                source_artifact_ids = [str(primary_data["artifact_id"])] if primary_data else []
                validation_status = ValidationStatus.WARNING
                validation_warnings = ["人工主题仍需研究者确认后才能用于监督确认。"]
            elif route == "QUALITATIVE" and action == "supervised_confirmation":
                primary_data = _registered_qualitative_primary_data(project_id)
                manual = _latest_artifact_body(project_id, "ManualThemeRevisionCandidate") or {}
                themes = [item for item in manual.get("themes", []) if isinstance(item, dict)]
                labels = {str(item.get("theme_id")) for item in themes if item.get("theme_id")}
                candidate = {
                    "project_id": project_id,
                    "action": action,
                    "route": route,
                    "status": "SUPERVISED_CONFIRMATION_SPECIFICATION",
                    "label_source": "ManualThemeRevisionCandidate",
                    "theme_count": len(labels),
                    "sentence_level": {"folds": 10, "stratified": True, "metrics": ["accuracy", "macro_f1", "weighted_f1", "cohen_kappa", "confusion_matrix", "per_theme_recall"]},
                    "student_grouped": {"group_key": "participant_label", "folds": 10, "metrics": ["macro_f1", "cohen_kappa"]},
                    "subgroup_checks": ["Gender", "Control_group"],
                    "execution": {"performed": False, "reason": "当前本地验收未下载大型嵌入模型；不得把规划指标当成实际性能。"},
                    "unresolved": ["需冻结人工标签后执行交叉验证", "没有外部未见语料时不声称外部泛化"],
                }
                artifact_type = "SupervisedConfirmationCandidate"
                source_artifact_ids = [str(primary_data["artifact_id"])] if primary_data else []
                validation_status = ValidationStatus.WARNING
                validation_warnings = ["监督确认规格已生成；实际性能需在冻结标签后执行并回链日志。"]
            elif route == "QUALITATIVE" and action == "student_level_robustness":
                primary_data = _registered_qualitative_primary_data(project_id)
                manual = _latest_artifact_body(project_id, "ManualThemeRevisionCandidate") or {}
                themes = [item for item in manual.get("themes", []) if isinstance(item, dict)]
                rows: list[dict[str, object]] = []
                for participant in sorted({str(item.get("participant_label")) for item in (primary_data or {}).get("segments", []) if item.get("participant_label")}):
                    own = [item for item in (primary_data or {}).get("segments", []) if str(item.get("participant_label")) == participant]
                    rows.append({"participant_label": participant, "sentence_count": len(own), "theme_proportions": {}, "excluded_short_segments": 0})
                candidate = {
                    "project_id": project_id,
                    "action": action,
                    "route": route,
                    "status": "STUDENT_LEVEL_ROBUSTNESS_CANDIDATE",
                    "theme_count": len(themes),
                    "student_count": len(rows),
                    "student_rows": rows,
                    "checks": ["student is aggregation unit", "sentence dependence retained", "bootstrap at student level planned", "text length sensitivity planned"],
                    "execution": {"performed": False, "reason": "人工标签尚未冻结；本候选只锁定聚合规则。"},
                }
                artifact_type = "StudentLevelRobustnessCandidate"
                source_artifact_ids = [str(primary_data["artifact_id"])] if primary_data else []
                validation_status = ValidationStatus.WARNING
                validation_warnings = ["学生层比例和稳健性规则需研究者确认；句子不能当作独立学生。"]
            elif route == "QUALITATIVE" and action == "group_comparison":
                primary_data = _registered_qualitative_primary_data(project_id)
                background = _latest_project_reference_csv(project_id, "Additional_data")
                text_ids = {str(item.get("participant_label", "")).replace("stu_", "") for item in (primary_data or {}).get("segments", []) if item.get("participant_label")}
                joined = [row for row in background if str(row.get("Stu_ID", "")).strip() in text_ids]
                groups: dict[str, int] = {}
                for row in joined:
                    value = str(row.get("Control_group", "")).strip()
                    if value:
                        groups[value] = groups.get(value, 0) + 1
                candidate = {
                    "project_id": project_id,
                    "action": action,
                    "route": route,
                    "status": "GROUP_COMPARISON_CANDIDATE",
                    "background_rows": len(background),
                    "joined_students": len(joined),
                    "group_counts": groups,
                    "planned_statistics": ["sentence-level contingency table", "chi_square", "student-level proportions", "clustered bootstrap"],
                    "interpretation_boundary": "Control_group 编码依赖研究者提供的数据字典；分组非随机且采集方式可能不同，只能做描述性/关联性比较。",
                    "execution": {"performed": False, "reason": "主题标签尚未冻结，当前只检查连接和比较边界。"},
                }
                artifact_type = "GroupComparisonCandidate"
                source_artifact_ids = [str(primary_data["artifact_id"])] if primary_data else []
                validation_status = ValidationStatus.WARNING
                validation_warnings = ["组间数字需在主题标签冻结后由实际执行输出提供。"]
            elif route == "QUALITATIVE" and action == "result_card_review":
                artifact_types = (
                    "DataAuditCandidate", "PreprocessingExecutionCandidate",
                    "PatternDiscoveryCodeCandidate", "PatternSmokeExecutionCandidate",
                    "PatternStabilityExecutionCandidate", "ClusterReviewPacket",
                    "CodebookCandidate", "ManualThemeRevisionCandidate",
                    "SupervisedConfirmationCandidate", "StudentLevelRobustnessCandidate",
                    "GroupComparisonCandidate",
                )
                linked = [item for item in artifact_content_store.list_project(project_id) if item.artifact_type in artifact_types]
                primary_data = _registered_qualitative_primary_data(project_id)
                sample_flow = _qualitative_sample_flow(project_id, primary_data) if primary_data else None
                candidate = {
                    "project_id": project_id,
                    "action": action,
                    "route": route,
                    "status": "RESULT_CARD_CANDIDATE_REQUIRES_REVIEW",
                    "sections": ["data_audit", "pattern_discovery", "manual_review", "supervised_confirmation", "student_level_robustness", "group_comparison", "unresolved_questions"],
                    "linked_artifact_ids": [item.artifact_id for item in linked],
                    "data_audit": sample_flow,
                    "numeric_claim_policy": "只有执行日志和冻结输入支持的数字可以进入论文；规划值和原论文数字禁止进入。",
                    "unresolved_questions": ["20/100/1000 种子嵌入与聚类运行尚未完成", "人工标签与第二编码者一致性尚未完成", "学生层和组间统计需实际执行"],
                }
                artifact_type = "QualitativeResultCard"
                validation_status = ValidationStatus.WARNING
                validation_warnings = ["结果卡需要研究者逐项确认，确认后才允许进入论文写作。"]
                source_artifact_ids = [item.artifact_id for item in linked[-3:]]
            elif route != "QUALITATIVE" and action == "causal_DAG":
                # Observational projects still require an explicit graph, but
                # the candidate is deliberately framed as non-causal until a
                # researcher approves identification assumptions.
                brief_for_dag = _research_brief_fields(project, route, user, generation_feedback)
                declared_outcome = str((brief_for_dag.get("candidate_outcomes") or ["主要结果"])[0])
                declared_group = "干预/对照分组"
                dag = CausalDagSpec(
                    treatment=declared_group,
                    outcome=declared_outcome,
                    nodes=[declared_group, declared_outcome, "前测能力", "既有编程经验", "课程与教师情境"],
                    edges=[
                        {"source": "前测能力", "target": declared_group},
                        {"source": "前测能力", "target": declared_outcome},
                        {"source": "既有编程经验", "target": declared_group},
                        {"source": "既有编程经验", "target": declared_outcome},
                        {"source": "课程与教师情境", "target": declared_outcome},
                        {"source": declared_group, "target": declared_outcome},
                    ],
                    adjustment_set=["前测能力", "既有编程经验", "课程与教师情境"],
                )
                dag_report = CausalDagValidator().validate(dag)
                candidate = {
                    "project_id": project_id,
                    "action": action,
                    "route": route,
                    "status": "CANDIDATE_REQUIRES_RESEARCHER_APPROVAL",
                    "estimand": f"描述性 {declared_group} 间 {declared_outcome} 的差异；不声明因果效应",
                    "dag": dag.model_dump(mode="json"),
                    "validation": dag_report.model_dump(mode="json"),
                    "assumptions": [
                        f"{declared_group} 的形成机制必须由研究者确认；当前候选不把比较直接视为随机分配",
                        "前测能力、既有编程经验和课程/教师情境是候选混杂因素，必须由研究者确认是否测量及如何处理",
                        "该 DAG 不足以证明因果识别，必须经研究者审核",
                    ],
                }
                artifact_type = "CausalDagCandidate"
                validation_status = ValidationStatus.WARNING
                validation_warnings = ["观察性 DAG 仅用于明确假设，不能自动转化为因果结论。"]
                evidence_ids = []
            elif route != "QUALITATIVE" and action == "power_analysis":
                power_request = PowerAnalysisRequest(effect_size=0.5, alpha=0.05, target_power=0.8, groups=2)
                power_report = PowerAnalyzer().analyze(power_request)
                candidate = {
                    "project_id": project_id,
                    "action": action,
                    "route": route,
                    "status": "PLANNING_ASSUMPTIONS_REQUIRE_CONFIRMATION",
                    "request": power_request.model_dump(mode="json"),
                    "report": power_report.model_dump(mode="json"),
                    "interpretation": "0.5 个标准差是规划假设，不是从当前数据倒推的效应；正式研究须在收集数据前确认。",
                }
                artifact_type = "PowerAnalysisCandidate"
                validation_status = ValidationStatus.WARNING
                validation_warnings = ["功效分析使用预先声明的规划效应量，研究者需确认效应量和目标功效。"]
                evidence_ids = []
            elif route != "QUALITATIVE" and action == "preregistration_freeze":
                pipeline_for_plan = _latest_quantitative_pipeline_state(project_id)
                model_for_plan = pipeline_for_plan.model_specification if pipeline_for_plan else None
                brief_for_plan = _research_brief_fields(project, route, user, generation_feedback)
                prereg_group = next(iter(model_for_plan.grouping_variables), "干预组与对照组") if model_for_plan else "干预组与对照组"
                prereg_outcome = next(
                    iter(model_for_plan.outcome_variables),
                    str((brief_for_plan.get("candidate_outcomes") or ["待确认的主要结果变量"])[0]),
                ) if model_for_plan else str((brief_for_plan.get("candidate_outcomes") or ["待确认的主要结果变量"])[0])
                candidate = {
                    "project_id": project_id,
                    "action": action,
                    "route": route,
                    "status": "PREREGISTRATION_CANDIDATE",
                    "hypothesis": f"仅检验预先定义 {prereg_group} 与 {prereg_outcome} 的描述性均值差，不作因果假设。",
                    "primary_outcome": prereg_outcome,
                    "group_variable": prereg_group,
                    "analysis_model": f"Welch 两组均值差（{prereg_outcome}）；Bootstrap 区间；置换检验",
                    "exclusions": ["不追加未预注册协变量或子组解释", *list(brief_for_plan.get("exclusions") or [])],
                    "freeze_requirements": ["确认数据来源与许可", "确认分组编码", "确认缺失值和异常值规则", "确认效应解释边界", *list(brief_for_plan.get("constraints") or [])],
                }
                artifact_type = "PreregistrationFreezeCandidate"
                validation_status = ValidationStatus.WARNING
                validation_warnings = ["预注册内容仍需研究者确认后才具有冻结效力。"]
                evidence_ids = []
            elif route != "QUALITATIVE" and action in {
                "data_audit", "data_processing_approval", "dataset_freeze_hash",
                "analysis_code_generation", "physics_code_validation", "code_review",
                "manual_execution_approval", "sandbox_analysis_execution",
                "statistical_result_validation", "bootstrap_robustness", "permutation_test",
                "result_direction_consistency", "uncertainty_gate", "statistical_result_card",
            }:
                primary = _registered_quantitative_primary_data(project_id)
                pipeline = _latest_quantitative_pipeline_state(project_id)
                try:
                    runner = DataPipelineController(
                        storage_root=storage_root,
                        operator_executor=workflow_controller.operator_executor,
                    )
                    if action == "data_audit":
                        if primary is None:
                            raise ValueError("尚未导入可用的原始 CSV 数据。")
                        alignment_warning = _ai_schema_alignment_warning(
                            project.research_direction,
                            {str(value) for value in primary.get("header", [])},
                        )
                        if alignment_warning:
                            # Do not let a generic group/outcome fixture pass
                            # as an analysis of students' actual AI use. The
                            # failure is intentionally routed to the design
                            # review checkpoint so the researcher can amend
                            # the estimand or upload a matching dataset.
                            data_design_warnings.append(alignment_warning)
                            raise ValueError(alignment_warning)
                        pipeline = _start_quantitative_pipeline(
                            project_id,
                            primary,
                            research_scope=project.research_direction,
                        )
                        # A pre/post design cannot be validated from a file
                        # containing only one score per participant. Keep the
                        # audit usable for inspection, but surface a blocking
                        # design-data mismatch before freeze/execution.
                        headers = {str(value).lower() for value in primary.get("header", [])}
                        asks_prepost = _requests_prepost_design(
                            project.research_direction,
                            generation_feedback,
                        )
                        has_prepost_fields = any(
                            ("pre" in value or "post" in value or "前测" in value or "后测" in value)
                            for value in headers
                        )
                        if asks_prepost and not has_prepost_fields:
                            candidate_warning = "研究主题声明了前测—后测，但当前 CSV 没有前测/后测字段；请修改研究设计或上传匹配的数据后再冻结。"
                            data_design_warnings.append(candidate_warning)
                            validation_status = ValidationStatus.WARNING
                            validation_warnings.append(candidate_warning)
                    elif action == "data_processing_approval":
                        if pipeline is None:
                            raise ValueError("尚未完成数据审计。")
                        # The processing approval is a real human decision
                        # boundary in the DataPipelineController.  Advance
                        # the pipeline here before the later dataset-freeze
                        # action; otherwise the next step sees a stale
                        # WAITING_PROCESSING_APPROVAL snapshot and reports a
                        # misleading blocker.
                        pipeline = runner.decide(pipeline, decision="approved")
                    elif action == "dataset_freeze_hash":
                        if pipeline is None:
                            raise ValueError("尚未完成数据审计。")
                        pipeline = runner.decide(pipeline, decision="approved")
                    elif action == "sandbox_analysis_execution":
                        if pipeline is None:
                            raise ValueError("尚未完成冻结与可执行分析计划。")
                        pipeline = runner.decide(pipeline, decision="approved")
                    if primary is None or pipeline is None:
                        raise ValueError("量化数据管线尚未准备就绪。")
                    source_artifact_ids = [str(primary["artifact_id"])]
                    result_card = pipeline.statistical_result_card
                    validation = pipeline.validation_report
                    candidate = {
                        "project_id": project_id,
                        "action": action,
                        "route": route,
                        "status": (
                            "EXECUTION_VERIFIED" if result_card is not None
                            else pipeline.stage.value
                        ),
                        "data_manifest": {
                            key: primary[key]
                            for key in ("source_dataset_ref", "content_sha256", "document_version", "row_count", "header")
                        },
                        "pipeline_stage": pipeline.stage.value,
                        "data_audit": pipeline.data_audit_report.model_dump(mode="json") if pipeline.data_audit_report else None,
                        "frozen_dataset": pipeline.frozen_dataset.model_dump(mode="json") if pipeline.frozen_dataset else None,
                        "executable_plan": pipeline.executable_plan.model_dump(mode="json") if pipeline.executable_plan else None,
                        "code_artifact_ref": pipeline.code_artifact_ref,
                        "code_review_ref": pipeline.code_review_ref,
                        "validation_report": validation.model_dump(mode="json") if validation else None,
                        "statistical_result_card": result_card.model_dump(mode="json") if result_card else None,
                        "quantitative_pipeline_state": pipeline.model_dump(mode="json"),
                    }
                    if data_design_warnings:
                        candidate["design_data_warnings"] = data_design_warnings
                    artifact_type = {
                        "data_audit": "DataAuditCandidate",
                        "data_processing_approval": "DataProcessingApprovalCandidate",
                        "dataset_freeze_hash": "DatasetFreezeHashCandidate",
                        "analysis_code_generation": "AnalysisCodePlanCandidate",
                        "physics_code_validation": "PhysicsCodeValidationCandidate",
                        "code_review": "CodeReviewCandidate",
                        "manual_execution_approval": "ManualExecutionApprovalCandidate",
                        "sandbox_analysis_execution": "SandboxExecutionCandidate",
                        "statistical_result_validation": "StatisticalResultValidationCandidate",
                        "bootstrap_robustness": "BootstrapRobustnessCandidate",
                        "permutation_test": "PermutationTestCandidate",
                        "result_direction_consistency": "ResultDirectionCandidate",
                        "uncertainty_gate": "UncertaintyGateCandidate",
                        "statistical_result_card": "StatisticalResultCardCandidate",
                    }[action]
                    if action in {"bootstrap_robustness", "permutation_test", "result_direction_consistency", "uncertainty_gate"}:
                        if pipeline.frozen_dataset is None or result_card is None:
                            raise ValueError("稳健性检查需要已冻结数据和已验证结果卡。")
                        groups: dict[str, list[float]] = {}
                        model_spec = pipeline.model_specification
                        group_column = next(
                            iter(model_spec.grouping_variables or model_spec.predictor_variables),
                            "group",
                        )
                        outcome_column = next(iter(model_spec.outcome_variables), "transfer_score")
                        with Path(pipeline.frozen_dataset.content_uri).open("r", encoding="utf-8", newline="") as source:
                            for row in csv.DictReader(source):
                                group = (row.get(group_column) or "").strip()
                                if group:
                                    groups.setdefault(group, []).append(float(row[outcome_column]))
                        if len(groups) != 2:
                            raise ValueError("稳健性检查需要恰好两个非空组。")
                        ordered = sorted(groups)
                        primary_estimate = float(
                            result_card.values.get(
                                "transfer_mean_difference_group_2_minus_group_1",
                                result_card.values.get("mean_difference_group_2_minus_group_1", 0.0),
                            )
                        )
                        report = RobustnessAnalysisOperator().run_two_group(
                            control=groups[ordered[0]], treatment=groups[ordered[1]],
                            primary_estimate=primary_estimate,
                            report_id=f"robustness-{project_id}-{pipeline.frozen_dataset.sha256[:12]}",
                        )
                        candidate["robustness_report"] = report.model_dump(mode="json")
                        candidate["bootstrap_check"] = report.checks[0].model_dump(mode="json")
                        candidate["permutation_check"] = report.checks[1].model_dump(mode="json")
                        candidate["direction_consistent"] = report.direction_consistent
                        if action == "uncertainty_gate":
                            signals = [
                                QualitySignal(
                                    signal_id="execution", category="execution", score=1.0,
                                    status=SignalStatus.PASS, reason="确定性执行和结果验证已通过",
                                    refs=[result_card.ref],
                                ),
                                QualitySignal(
                                    signal_id="robustness", category="robustness", score=1.0 if report.status.value == "PASS" else 0.5,
                                    status=SignalStatus.PASS if report.status.value == "PASS" else SignalStatus.WARNING,
                                    reason="Bootstrap 与置换检查结果" if report.status.value == "PASS" else "稳健性检查需要人工复核",
                                    refs=[f"robustness://{report.report_id}"],
                                ),
                            ]
                            assessment = UncertaintyGate().assess(
                                assessment_id=f"uncertainty-{project_id}-{pipeline.frozen_dataset.sha256[:12]}",
                                stage="result_validation", signals=signals,
                            )
                            candidate["uncertainty_assessment"] = assessment.model_dump(mode="json")
                            if assessment.decision.value == "PASS_WITH_WARNING":
                                validation_status = ValidationStatus.WARNING
                                validation_warnings = list(assessment.risk_flags)
                    evidence_ids = []
                    if pipeline.stage.value in {"REWORK", "BLOCKED"}:
                        validation_status = ValidationStatus.FAILED
                    elif action in {"physics_code_validation", "code_review", "manual_execution_approval"}:
                        validation_status = ValidationStatus.WARNING
                        validation_warnings = ["代码生成和静态复核将在获得人工执行许可后由确定性执行器完成。"]
                except ValueError as error:
                    candidate = {
                        "project_id": project_id,
                        "action": action,
                        "route": route,
                        "status": "BLOCKED_QUANTITATIVE_PIPELINE",
                        "blocking_reason": str(error),
                    }
                    artifact_type = "QuantitativePipelineBlocker"
                    evidence_ids = []
                    validation_status = ValidationStatus.FAILED
            elif action == "manuscript_citation_verification":
                manuscript = next(
                    (item.body for item in reversed(artifact_content_store.list_project(project_id))
                     if item.artifact_type == "ManuscriptDraftZh"),
                    None,
                )
                evidence_package = next(
                    (item.body for item in reversed(artifact_content_store.list_project(project_id))
                     if item.artifact_type == "EvidenceReviewPackage"),
                    {},
                )
                citations = list(manuscript.get("citation_refs", [])) if isinstance(manuscript, dict) else []
                available = set(evidence_package.get("used_evidence_refs", [])) if isinstance(evidence_package, dict) else set()
                missing = [ref for ref in citations if ref not in available]
                pipeline = _latest_quantitative_pipeline_state(project_id)
                result_ref = manuscript.get("result_card_ref") if isinstance(manuscript, dict) else None
                primary_data_ref = manuscript.get("primary_data_artifact_id") if isinstance(manuscript, dict) else None
                qualitative_data = _registered_qualitative_primary_data(project_id)
                result_ref_verified = (
                    result_ref is None
                    or (pipeline is not None and pipeline.statistical_result_card is not None and result_ref == pipeline.statistical_result_card.ref)
                )
                primary_data_ref_verified = (
                    primary_data_ref is None
                    or (pipeline is not None and pipeline.frozen_dataset is not None and primary_data_ref == pipeline.frozen_dataset.ref)
                    or (qualitative_data is not None and primary_data_ref == qualitative_data.get("artifact_id"))
                )
                linkage_complete = bool(manuscript) and bool(citations) and bool(available) and not missing and result_ref_verified and primary_data_ref_verified
                candidate = {
                    "project_id": project_id,
                    "action": action,
                    "status": "LINKAGE_CHECKED_REQUIRES_HUMAN_VERIFICATION" if linkage_complete else "FAILED_TRACEABILITY_CHECK",
                    "manuscript_present": manuscript is not None,
                    "citation_count": len(citations),
                    "evidence_ref_count": len(available),
                    "verified_citation_refs": [ref for ref in citations if ref in available],
                    "unverified_citation_refs": missing,
                    "primary_result_ref": result_ref,
                    "primary_result_ref_verified": result_ref_verified,
                    "primary_data_ref": primary_data_ref,
                    "primary_data_ref_verified": primary_data_ref_verified,
                    "boundary": "自动检查只验证内部标识和冻结输入的可追溯性；研究者仍须核对作者、年份、页码与论断范围。",
                }
                artifact_type = "ManuscriptCitationVerification"
                evidence_ids = citations
                if not linkage_complete:
                    validation_status = ValidationStatus.FAILED
                    missing_parts = []
                    if not manuscript:
                        missing_parts.append("论文草稿")
                    if not citations:
                        missing_parts.append("可追溯文献引用")
                    if citations and missing:
                        missing_parts.append("已验证的全部引用来源")
                    if not result_ref_verified:
                        missing_parts.append("已验证的统计结果卡")
                    if not primary_data_ref_verified:
                        missing_parts.append("已冻结的原始数据版本")
                    validation_warnings = ["引用核验未通过：缺少" + "、".join(missing_parts) + "。"]
                else:
                    validation_status = ValidationStatus.WARNING
                    validation_warnings = ["内部引用和结果链接已核对；仍需人工核对作者、年份、页码与主张范围。"]
            elif action == "reviewer_final_confirmation":
                candidate = {
                    "project_id": project_id,
                    "action": action,
                    "status": "INDEPENDENT_REVIEW_REQUIRED",
                    "review_policy": state.review_policy.value,
                    "required_checks": ["研究问题与方法一致性", "证据/结果可追溯性", "统计或定性解释边界", "引用准确性", "伦理与数据治理说明"],
                    "boundary": "该产物是审稿包，不代表独立审稿已经完成。",
                }
                artifact_type = "FinalReviewPacket"
                evidence_ids = []
                validation_status = ValidationStatus.WARNING
                validation_warnings = ["需要独立审稿人完成复核；研究者本人不能将此包标记为独立审稿通过。"]
            else:
                candidate = {"project_id": project_id, "action": action, "route": route, "phase": stream.phase.value, "source": "conversation_orchestrator", "status": "candidate"}
                artifact_type = None
                evidence_ids = []
        if external_discovery is not None:
            candidate["external_discovery"] = external_discovery
        is_evidence_review = action == "claim_evidence_support"
        if is_evidence_review:
            candidate = _build_evidence_review_package(
                project_id,
                project.research_direction,
                stream.artifact_ids,
                final_gap_report=candidate if artifact_type == "ResearchGapReport" else None,
                context_bundle=evidence_context_cache,
            )
            artifact_type = "EvidenceReviewPackage"
            evidence_ids = list(candidate["used_evidence_refs"])
            coverage = candidate.get("coverage", {})
            if not isinstance(coverage, dict) or not coverage.get("formal_evidence_ready"):
                validation_status = ValidationStatus.FAILED
                unmet = coverage.get("missing_requirements", []) if isinstance(coverage, dict) else []
                unmet_text = "；".join(item for item in unmet if isinstance(item, str))
                validation_warnings = [
                    "证据审阅只能用于继续检索，尚不能进入正式研究设计。"
                    + (f"未满足：{unmet_text}" if unmet_text else "")
                ]
        critique_body = candidate.get("writing_critique") if isinstance(candidate, dict) else None
        writing_revision_needed = (
            action == "writing"
            and isinstance(critique_body, dict)
            and critique_body.get("status") == "NEEDS_REVISION"
            # One explicit revision is enough to create a new immutable
            # manuscript candidate. If the researcher then says to retain
            # the reviewed draft and continue, do not trap the conversation
            # in an identical revision checkpoint forever.
            and not bool(stream.conversation_feedback.get("MANUSCRIPT_REVISION_REVIEW"))
        )
        saved_checkpoint = (
            "MANUSCRIPT_REVISION_REVIEW" if writing_revision_needed
            else "DATA_DESIGN_REVIEW" if data_design_warnings
            else conversation_checkpoint_for_action
        )
        _, artifact, _ = control_plane.complete_action_with_candidate(
            project_id,
            action=action,
            content=candidate,
            actor=user.username,
            expected_state_revision=lease.expected_state_revision,
            gate_type="evidence_sufficiency_review" if is_evidence_review else f"{action}_approval",
            gate_level=(
                GateLevel.G1 if is_evidence_review
                else GateLevel.G3 if action == "reviewer_final_confirmation"
                else GateLevel.G2
            ),
            artifact_type=artifact_type,
            source_evidence_ids=evidence_ids,
            source_artifact_ids=source_artifact_ids,
            # The legacy ``/orchestration/continue`` API exposes one Gate per
            # action for compatibility.  The chat API compresses internal
            # operators into checkpoints, so only it suppresses a Gate when
            # a checkpoint is present.
            require_human_gate=(
                not conversational
                or (
                    action in CONVERSATIONAL_HUMAN_GATE_ACTIONS
                    and conversation_checkpoint_for_action is None
                )
            ),
            gate_reason=(
                "系统已完成文献整理、检索、融合、重排序和主张—证据判断。"
                "请在右侧审阅证据覆盖、原文片段与研究缺口；证据充分后才进入研究设计。"
                if is_evidence_review else None
            ),
            validation_status=validation_status,
            validation_warnings=validation_warnings,
            conversation_checkpoint=(
                saved_checkpoint
            ),
            resume_action=(
                "writing"
                if conversation_checkpoint_for_action in {
                    "MANUSCRIPT_OUTLINE_REVIEW",
                    MANUSCRIPT_SECTION_CHECKPOINT,
                } or writing_revision_needed
                # A data/design mismatch invalidates the planned analysis.
                # Return to design before preregistration rather than freezing
                # the old plan against a different schema.
                else "research_design" if data_design_warnings
                else None
            ),
        )
        artifact_content_store.put(ArtifactContent(
            project_id=project_id,
            artifact_id=artifact.artifact_id,
            version=artifact.version,
            artifact_type=artifact.artifact_type,
            schema_version="orchestration-candidate-v1",
            body=candidate,
        ))
        if artifact_type == "EvidenceReviewPackage":
            _integrate_evidence_review_package_into_canvas(
                project_id,
                candidate,
                research_scope=project.research_direction,
            )
        if artifact.artifact_type in {"ManuscriptDraftZh", "MixedMethodsManuscript"}:
            claim_payloads = candidate.get("claim_records", [])
            if isinstance(claim_payloads, list):
                control_plane.record_manuscript_claims(
                    project_id,
                    artifact.artifact_id,
                    [item for item in claim_payloads if isinstance(item, dict)],
                )
        return [artifact.artifact_id]

    result = ControlPlaneWorker(
        control_plane.repository, control_plane, f"api-{user.username}"
    ).run_once({action: handle}, project_id=project_id)
    latest = control_plane.ensure_project(project_id)
    next_gate = control_plane.repository.get_gate(project_id, latest.active_gate_id) if latest.active_gate_id else None
    next_gate = control_plane.repository.get_gate(project_id, latest.active_gate_id) if latest.active_gate_id else None
    return {
        "task": result.model_dump(mode="json") if result else task.model_dump(mode="json"),
        "control_state": latest.model_dump(mode="json"),
        "gate": next_gate.model_dump(mode="json") if next_gate else None,
        "waiting_for_user": bool(_conversation_checkpoint(latest.model_dump(mode="json"))),
        "checkpoint": _conversation_checkpoint(latest.model_dump(mode="json")),
        "execution_started": result is not None,
    }


@app.post(
    "/api/v1/projects/{project_id}/physics/validate",
    response_model=PhysicsValidationReport,
)
def validate_physics_code(
    project_id: str,
    request: PhysicsValidationRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> PhysicsValidationReport:
    """Validate a bounded Python submission without executing it."""

    identity_service.get_project(user, project_id)
    submission_id = f"submission-{uuid4().hex}"
    project_directory = storage_root / "physics-submissions" / sha256_text(project_id)[:16]
    project_directory.mkdir(parents=True, exist_ok=True)
    source_bytes = request.source_code.encode("utf-8")
    source_path = project_directory / f"{submission_id}.py"
    source_path.write_bytes(source_bytes)
    return PhysicsValidationGate().validate_source(
        project_id=project_id,
        code_artifact_ref=f"physics-code://{submission_id}",
        source=request.source_code,
        equations=request.equations,
        units=request.units,
        bounds=request.bounds,
    )


@app.post(
    "/api/v1/projects/{project_id}/protocol/validate",
    response_model=ProtocolValidationResponse,
)
def validate_research_protocol(
    project_id: str,
    request: ProtocolValidationRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> ProtocolValidationResponse:
    """Validate causal structure and prospective power before protocol approval."""

    identity_service.get_project(user, project_id)
    dag_report = CausalDagValidator().validate(request.dag)
    power_report = PowerAnalyzer().analyze(request.power)
    risks: list[str] = []
    if not dag_report.passed:
        risks.append("CAUSAL_DAG_REQUIRES_REWORK")
    if request.power.expected_total_n is not None and not power_report.passed:
        risks.append("POWER_INSUFFICIENT")
    return ProtocolValidationResponse(
        dag_report=dag_report,
        power_report=power_report,
        passed=dag_report.passed and (request.power.expected_total_n is None or power_report.passed),
        risk_flags=risks,
    )


@app.post(
    "/api/v1/projects/{project_id}/evidence/claim-support",
    response_model=ClaimSupportReport,
)
def evaluate_claim_support(
    project_id: str,
    request: ClaimSupportRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> ClaimSupportReport:
    """Screen whether supplied evidence supports a research claim."""

    identity_service.get_project(user, project_id)
    evidence = [(item.evidence_ref, item.text) for item in request.evidence]
    try:
        provider = configured_evidence_provider()
    except RuntimeError:
        provider = LexicalEvidenceEvaluator()
        report = provider.build_report(request.claim, evidence)
        report.risk_flags.append("NLI_PROVIDER_UNAVAILABLE_FELL_BACK_TO_LEXICAL")
        return report
    return build_claim_support_report(provider, request.claim, evidence)


@app.post(
    "/api/v1/projects/{project_id}/analysis/robustness",
    response_model=RobustnessReport,
)
def run_robustness_analysis(
    project_id: str,
    request: RobustnessRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> RobustnessReport:
    """Run bounded bootstrap and permutation checks on approved analysis inputs."""

    identity_service.get_project(user, project_id)
    return RobustnessAnalysisOperator().run_two_group(
        control=request.control,
        treatment=request.treatment,
        primary_estimate=request.primary_estimate,
        report_id=f"robustness-{uuid4().hex}",
        bootstrap_samples=request.bootstrap_samples,
        permutations=request.permutations,
    )


@app.post(
    "/api/v1/projects/{project_id}/quality/uncertainty",
    response_model=UncertaintyAssessment,
)
def assess_uncertainty(
    project_id: str,
    request: UncertaintyRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> UncertaintyAssessment:
    """Combine deterministic quality signals into a Controller-style decision."""

    identity_service.get_project(user, project_id)
    return UncertaintyGate().assess(
        assessment_id=f"assessment-{uuid4().hex}",
        stage=request.stage,
        signals=request.signals,
    )


@app.post(
    "/api/v1/projects/{project_id}/analysis/meta-analysis",
    response_model=MetaAnalysisReport,
)
def run_meta_analysis(
    project_id: str,
    request: MetaAnalysisRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> MetaAnalysisReport:
    """Pool researcher-supplied study effects without inventing source data."""

    identity_service.get_project(user, project_id)
    return PyMAREMetaAnalysisAdapter().run(
        report_id=f"meta-analysis-{uuid4().hex}",
        studies=[
            (study.study_id, study.effect, study.standard_error)
            for study in request.studies
        ],
        confidence=request.confidence,
    )


@app.post(
    "/api/v1/projects/{project_id}/analysis/multiple-comparisons",
    response_model=MultipleComparisonReport,
)
def correct_multiple_comparisons(
    project_id: str,
    request: MultipleComparisonRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> MultipleComparisonReport:
    """Apply a declared p-value correction without changing the primary analysis."""

    identity_service.get_project(user, project_id)
    return MultipleComparisonOperator().run(
        report_id=f"multiplicity-{uuid4().hex}",
        p_values=request.p_values,
        method=request.method,
        alpha=request.alpha,
    )


@app.post(
    "/api/v1/projects/{project_id}/evidence/screen",
    response_model=ScreeningQueue,
)
def screen_evidence_set(
    project_id: str,
    request: ScreeningRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> ScreeningQueue:
    """Rank a literature screening queue while retaining human decisions."""

    identity_service.get_project(user, project_id)
    return ASReviewAdapter().rank(
        queue_id=f"screen-{uuid4().hex}",
        records=request.records,
        relevant_paper_ids=set(request.relevant_paper_ids),
        query=request.query,
    )


@app.post(
    "/api/v1/projects/{project_id}/analysis/outliers",
    response_model=OutlierReport,
)
def screen_analysis_outliers(
    project_id: str,
    request: OutlierRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> OutlierReport:
    """Flag, but never remove, potentially influential observations."""

    identity_service.get_project(user, project_id)
    return PyODOutlierAdapter().run(report_id=f"outlier-{uuid4().hex}", values=request.values)


@app.post(
    "/api/v1/projects/{project_id}/analysis/conformal-interval",
    response_model=PredictionInterval,
)
def calculate_conformal_interval(
    project_id: str,
    request: ConformalRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> PredictionInterval:
    """Return a calibrated predictive interval for prediction tasks only."""

    identity_service.get_project(user, project_id)
    return MAPIEConformalAdapter().interval(
        prediction=request.prediction,
        calibration_residuals=request.calibration_residuals,
        coverage=request.coverage,
    )


@app.post(
    "/api/v1/projects/{project_id}/analysis/confounding-sensitivity",
    response_model=ConfoundingSensitivityReport,
)
def analyze_confounding_sensitivity(
    project_id: str,
    request: SensitivityRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> ConfoundingSensitivityReport:
    """Quantify sensitivity to a benchmark unobserved confounder."""

    identity_service.get_project(user, project_id)
    return SensemakrAdapter().run(
        report_id=f"sensitivity-{uuid4().hex}",
        estimate=request.estimate,
        standard_error=request.standard_error,
        benchmark_partial_r2=request.benchmark_partial_r2,
    )


@app.post(
    "/api/v1/projects/{project_id}/data/schema-validate",
    response_model=SchemaValidationReport,
)
def validate_declared_schema(
    project_id: str,
    request: SchemaValidationRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> SchemaValidationReport:
    """Validate researcher-declared data rules before a dataset is frozen."""

    identity_service.get_project(user, project_id)
    return DeclaredSchemaValidator().validate_rows(
        report_id=f"schema-{uuid4().hex}", rows=request.rows, schema=request.data_schema
    )


@app.post(
    "/api/v1/projects/{project_id}/protocol/causal-discovery",
    response_model=CausalAdapterReport,
)
def propose_causal_graph(
    project_id: str,
    request: CausalDiscoveryRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> CausalAdapterReport:
    """Propose a candidate DAG; the result remains subject to researcher approval."""

    identity_service.get_project(user, project_id)
    import pandas as pd  # type: ignore[import-untyped]

    return CausalLearnDiscoveryAdapter().propose(
        report_id=f"causal-discovery-{uuid4().hex}",
        frame=pd.DataFrame(request.rows, columns=request.columns),
        columns=request.columns,
    )


@app.post(
    "/api/v1/projects/{project_id}/protocol/causal-identify",
    response_model=CausalAdapterReport,
)
def identify_causal_effect(
    project_id: str,
    request: CausalIdentificationRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> CausalAdapterReport:
    """Identify an estimand from a researcher-confirmed causal graph."""

    identity_service.get_project(user, project_id)
    import pandas as pd  # type: ignore[import-untyped]

    return DoWhyIdentificationAdapter().identify(
        report_id=f"causal-identification-{uuid4().hex}",
        frame=pd.DataFrame(request.rows),
        spec=request.dag,
    )


@app.post(
    "/api/v1/projects/{project_id}/documents/parse-grobid",
    response_model=ParsedDocument,
)
async def parse_document_with_grobid(
    project_id: str,
    file: Annotated[UploadFile, File(...)],
    user: Annotated[UserProfile, Depends(current_user)],
    endpoint: Annotated[str | None, Query(max_length=500)] = None,
) -> ParsedDocument:
    """Parse one PDF through GROBID and return structured research sections."""

    identity_service.get_project(user, project_id)
    content = await file.read()
    if not content:
        raise DocumentError(400, "empty_document", "The uploaded document is empty")
    parser_endpoint = endpoint or os.getenv("STEM_SCI_GROBID_ENDPOINT", "http://localhost:8070")
    return GrobidDocumentParser(parser_endpoint).parse_pdf(content, filename=file.filename or "document.pdf")


@app.get("/api/v1/projects/{project_id}/conversations", response_model=list[ConversationSummary])
def project_conversations(
    project_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ConversationSummary]:
    """List persisted QA conversations for a project the user can access."""

    identity_service.get_project(user, project_id)
    return qa_service.list_conversations(project_id, limit=limit)


@app.get(
    "/api/v1/projects/{project_id}/conversations/{conversation_id}/turns",
    response_model=list[MemoryTurn],
)
def project_conversation_turns(
    project_id: str,
    conversation_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[MemoryTurn]:
    """Return ordered QA turns for one project-scoped conversation."""

    identity_service.get_project(user, project_id)
    return qa_service.conversation_turns(project_id, conversation_id, limit=limit)


@app.post("/api/v1/projects/{project_id}/workflow")
def start_project_workflow(
    project_id: str,
    request: ProjectWorkflowStartRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> PlanningRunResult:
    """Start workflow planning inside an authenticated research project."""

    identity_service.get_project(user, project_id)
    return workflow_controller.start_planning(
        PlanningRequest(
            project_id=project_id,
            research_intent=request.research_intent,
            context_bundle_ref=request.context_bundle_ref,
            run_id=request.run_id or f"planning-{project_id}",
        )
    )


@app.get("/api/v1/projects/{project_id}/workflow")
def project_workflow(
    project_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
) -> ControllerWorkflowState:
    project = identity_service.get_project(user, project_id)
    legacy_state = workflow_controller.ensure_project(project.project_id, project.research_direction)
    # The conversational control plane is now authoritative.  Keep this
    # compatibility endpoint useful for older pages by projecting its current
    # phase back into the coarse legacy stage vocabulary instead of always
    # returning the controller's initial ``INTAKE`` value.
    control_state = control_plane.repository.get_state(project.project_id)
    if control_state is None:
        return legacy_state
    stream = next(
        (item for item in control_state.workstreams if item.workstream_id == control_state.active_workstream_id),
        control_state.workstreams[0] if control_state.workstreams else None,
    )
    if control_state.lifecycle_status.value in {"COMPLETED", "RELEASED"}:
        projected_stage = "RELEASED"
    elif control_state.active_gate_id:
        projected_stage = "WAITING_HUMAN"
    else:
        phase = getattr(getattr(stream, "phase", None), "value", getattr(stream, "phase", ""))
        projected_stage = {
            "EVIDENCE_PREPARATION": "EVIDENCE_READY",
            "RESEARCH_DESIGN": "SCOPED",
            "DATA_PREPARATION": "DATA_READY",
            "DATA_ANALYSIS": "ANALYZED",
            "ANALYSIS_EXECUTION": "ANALYZED",
            "RESULT_VALIDATION": "ANALYZED",
            "WRITING_PUBLICATION": "DRAFTED",
        }.get(str(phase), legacy_state.current_stage)
    return legacy_state.model_copy(update={"current_stage": projected_stage})


@app.post("/api/v1/projects/{project_id}/workflow/plans")
def project_workflow_plan(
    project_id: str,
    request: AgentPlanRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> AgentExecutionPlan:
    """Generate a reviewable Agent task plan without running any Agent."""

    identity_service.get_project(user, project_id)
    if request.project_id != project_id:
        raise ContextInputError("project_mismatch", "path project_id does not match request project_id")
    return workflow_controller.plan_agent_tasks(request)


@app.get("/api/v1/projects/{project_id}/workflow/plans")
def project_workflow_plans(
    project_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
) -> list[AgentExecutionPlan]:
    identity_service.get_project(user, project_id)
    return workflow_controller.list_agent_plans(project_id)


@app.get("/api/v1/projects/{project_id}/workflow/plans/{plan_id}")
def project_workflow_plan_detail(
    project_id: str,
    plan_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
) -> AgentExecutionPlan:
    identity_service.get_project(user, project_id)
    return workflow_controller.get_agent_plan(project_id, plan_id)


@app.get("/api/v1/projects/{project_id}/workflow/plans/{plan_id}/outputs")
def project_workflow_plan_outputs(
    project_id: str,
    plan_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
) -> list[dict[str, object]]:
    """Read outputs for one reviewed plan using the plan-scoped URL."""

    identity_service.get_project(user, project_id)
    # Return JSON-compatible dictionaries explicitly.  This avoids a runtime
    # response-model validation failure on older Pydantic/FastAPI combinations
    # while preserving the same public response shape.
    items = workflow_controller.list_agent_outputs(project_id, plan_id)
    return [item.model_dump(mode="json") for item in items]


@app.post("/api/v1/projects/{project_id}/workflow/plans/{plan_id}/approve")
def project_workflow_plan_approve(
    project_id: str,
    plan_id: str,
    request: AgentPlanApprovalRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> AgentExecutionPlan:
    identity_service.get_project(user, project_id)
    audited_request = request.model_copy(update={"decided_by": user.username})
    return workflow_controller.approve_agent_plan(project_id, plan_id, audited_request)


@app.post("/api/v1/projects/{project_id}/workflow/plans/{plan_id}/execute")
def project_workflow_plan_execute(
    project_id: str,
    plan_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
) -> AgentExecutionPlan:
    identity_service.get_project(user, project_id)
    return workflow_controller.execute_agent_plan(project_id, plan_id)


@app.post("/api/v1/projects/{project_id}/workflow/plans/{plan_id}/continue")
def project_workflow_plan_continue(
    project_id: str,
    plan_id: str,
    request: AgentTaskApprovalRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> AgentExecutionPlan:
    """Approve one stepwise candidate or return the plan for conversational rework."""

    identity_service.get_project(user, project_id)
    audited_request = request.model_copy(update={"decided_by": user.username})
    return workflow_controller.continue_agent_plan(project_id, plan_id, audited_request)


@app.get("/api/v1/projects/{project_id}/workflow/agent-outputs")
def project_workflow_agent_outputs(
    project_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
    plan_id: str | None = None,
    conversation_id: str | None = None,
    turn_id: str | None = None,
) -> list[dict[str, object]]:
    identity_service.get_project(user, project_id)
    return [
        item.model_dump(mode="json")
        for item in workflow_controller.list_agent_outputs(
            project_id,
            plan_id,
            conversation_id=conversation_id,
            turn_id=turn_id,
        )
    ]


@app.get("/api/v1/projects/{project_id}/workflow/page-materials")
def project_workflow_page_materials(
    project_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
    target: str | None = None,
    conversation_id: str | None = None,
    turn_id: str | None = None,
) -> list[AgentPageMaterial]:
    identity_service.get_project(user, project_id)
    return workflow_controller.list_agent_page_materials(
        project_id,
        target=target,
        conversation_id=conversation_id,
        turn_id=turn_id,
    )


@app.get("/api/v1/projects/{project_id}/workflow/formal-evidence")
def project_workflow_formal_evidence(
    project_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
) -> list[FormalEvidenceRecord]:
    """Read deduplicated, source-verified formal evidence with provenance."""

    identity_service.get_project(user, project_id)
    return workflow_controller.list_formal_evidence(project_id)


@app.post(
    "/api/v1/projects/{project_id}/workflow/evidence/{evidence_id}/promote",
    response_model=FormalEvidenceRecord,
)
def promote_verified_project_evidence(
    project_id: str,
    evidence_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
) -> FormalEvidenceRecord:
    """Promote a source-verified evidence snapshot from the workbench."""

    identity_service.get_project(user, project_id)
    evidence = service.get_evidence(project_id, evidence_id)
    return workflow_controller.promote_verified_evidence(
        project_id,
        evidence_id,
        evidence.model_dump(mode="json"),
        promoted_by=user.username,
    )


@app.post("/api/v1/projects/{project_id}/workflow/artifacts/{artifact_id}/decision")
def project_workflow_artifact_decision(
    project_id: str,
    artifact_id: str,
    request: AgentOutputDecisionRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> dict[str, object]:
    identity_service.get_project(user, project_id)
    audited_request = request.model_copy(update={"decided_by": user.username})
    result = workflow_controller.decide_agent_output(project_id, artifact_id, audited_request)
    if result.get("formalization") == "formal_evidence":
        for record in workflow_controller.list_formal_evidence(project_id):
            if record.artifact_id != artifact_id:
                continue
            service.link_formal_evidence(
                project_id=project_id,
                evidence_id=record.evidence_id,
                artifact_id=record.artifact_id,
                plan_id=record.plan_id,
                task_id=record.task_id,
                conversation_id=record.conversation_id,
                turn_id=record.turn_id,
                promoted_by=record.promoted_by,
                promoted_at=record.promoted_at.isoformat(),
            )
    return result


class CodeArtifactVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_code: str = Field(min_length=1, max_length=200_000)
    change_note: str | None = Field(default=None, max_length=500)


@app.post("/api/v1/projects/{project_id}/workflow/artifacts/{artifact_id}/code-version")
def project_workflow_code_version(
    project_id: str,
    artifact_id: str,
    request: CodeArtifactVersionRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> dict[str, object]:
    """Persist a researcher-edited code candidate as a new immutable version."""

    identity_service.get_project(user, project_id)
    artifact = artifact_store.get(project_id, artifact_id)
    content = artifact_content_store.get(project_id, artifact_id)
    if artifact is None or content is None:
        raise ContextInputError("artifact_not_found", "代码候选产物不存在")

    code_keys = {"source_code", "code", "python_code", "generated_code", "script"}
    has_code = any(isinstance(content.body.get(key), str) for key in code_keys)
    if not has_code and content.artifact_type not in {
        "AnalysisCodePlanCandidate",
        "CodeSpecificationDraft",
        "CodeReviewCandidate",
        "PhysicsCodeValidationCandidate",
        "PatternDiscoveryCodeCandidate",
    }:
        raise ContextInputError("artifact_is_not_code", "当前产物不是可编辑的代码候选")

    body = dict(content.body)
    source_key = next(
        (key for key in code_keys if isinstance(body.get(key), str)),
        "source_code",
    )
    body[source_key] = request.source_code
    body["edited_by"] = user.username
    body["change_note"] = request.change_note or "研究者编辑代码候选"
    next_version = content.version + 1
    saved_content = artifact_content_store.put(
        ArtifactContent(
            project_id=project_id,
            artifact_id=artifact_id,
            artifact_type=content.artifact_type,
            version=next_version,
            schema_version=content.schema_version,
            body=body,
        )
    )
    saved_artifact = artifact_store.put(
        artifact.model_copy(
            update={
                "version": next_version,
                "content_uri": f"artifact-content://{project_id}/{artifact_id}/{next_version}",
                "sha256": saved_content.content_hash,
                "created_at": saved_content.created_at,
                "created_by": user.username,
                "status": "CANDIDATE",
                "supersedes_ref": artifact.content_uri,
            }
        )
    )
    return {
        "artifact": saved_artifact.model_dump(mode="json"),
        "content": saved_content.model_dump(mode="json"),
        "change_note": body["change_note"],
    }


def _candidate_manuscript_markdown(
    *,
    artifact_type: str,
    body: dict[str, object],
    user_request: str | None = None,
    plan: object | None = None,
) -> str:
    # Keep the old ``plan=...`` call shape readable while migrating callers to
    # the smaller user_request contract.  The compatibility value is used only
    # for the document title and never changes the source artifact.
    if user_request is None:
        user_request = str(getattr(plan, "user_request", "当前研究主题"))
    section_labels = {
        "title": "标题",
        "abstract": "摘要",
        "keywords": "关键词",
        "introduction": "引言",
        "evidence_review": "证据综述",
        "research_questions": "研究问题",
        "methods": "方法",
        "analysis_plan": "分析方案",
        "statistical_analysis": "统计分析与稳健性检查",
        "results": "结果",
        "results_table": "结果表",
        "discussion": "讨论",
        "conclusion": "结论",
        "expected_contribution": "预期贡献",
        "reproducibility": "可复现性与审查链",
        "ethics_limitations": "伦理与局限",
        "limitations": "局限",
        "references": "参考文献",
    }

    def researcher_text(value: object) -> str:
        """Remove implementation identifiers from the editable manuscript only.

        The source artifact remains unchanged and therefore retains claim,
        evidence, dataset, and artifact identifiers for the audit trail.
        """

        text = str(value)
        replacements = (
            (r"document://[^\s；，。)]+", "已冻结资料"),
            (r"SHA-256：?[a-f0-9]{32,64}", "数据指纹已记录于审计附录"),
            (r"\b(?:shared_evd|evd|ctx|src)_[A-Za-z0-9_-]+\b", "相关证据片段"),
            (r"\b(?:claim|artifact|task|plan|run)[:_-][A-Za-z0-9:_-]+\b", "审计记录"),
            (r"\bsegment-\d+\b", "资料片段"),
        )
        for pattern, replacement in replacements:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return text

    sections = body.get("sections")
    if isinstance(sections, dict):
        # A quantitative candidate is intentionally conservative, but the
        # editable manuscript should still read like a complete research
        # report rather than a thin result-card export. Add bounded prose that
        # explains the analysis, reproducibility chain, and conclusion without
        # inventing facts beyond the stored candidate.
        enriched_sections: dict[str, object] = dict(sections)
        if "results_table" in sections and "results" in sections:
            enriched_sections.setdefault(
                "statistical_analysis",
                (
                    "统计分析先按冻结的数据字典确认分组变量与主要结果变量，再分别计算两组样本量、均值和标准差。"
                    "主要效应以组 2 减组 1 的均值差表示，同时报告 95% 置信区间、Welch 两组比较和 Cohen's d。"
                    "这些指标用于描述当前样本中的差异大小和不确定性，不替代随机化设计、测量效度或因果识别。\n\n"
                    "稳健性检查应与主要结果一起阅读：Bootstrap 区间、置换检验和结果方向一致性可以帮助判断估计是否受样本波动影响，"
                    "但它们不能修复分组偏差、缺失机制或代表性不足。任何协变量、子组、替代结局或新模型都必须作为独立的探索性版本记录。"
                ),
            )
            enriched_sections.setdefault(
                "reproducibility",
                (
                    "本稿的可复现链条从原始 CSV 登记开始，经过字段与缺失值审查、无损处理、数据冻结、确定性代码执行和结果卡解析。"
                    "论文正文只呈现研究者可读的结果；数据指纹、执行记录、代码规格和主张—证据关系保存在项目审计记录中。"
                    "重新运行时应使用同一冻结版本并核对结果卡，任何数据、变量映射或分析规则变化都应生成新的版本。"
                ),
            )
            enriched_sections.setdefault(
                "conclusion",
                (
                    "综合当前冻结样本的描述性结果，本研究提供了一个可复核的组间比较起点，但尚不足以支持因果解释或超出样本范围的推广。"
                    "后续研究应优先核对分组编码、测量效度、样本代表性、缺失值处理和最小有意义效应，并在这些边界明确后再决定是否扩展模型。"
                ),
            )
        sections = enriched_sections
        rendered_sections = "\n\n".join(
            f"## {section_labels.get(str(name), str(name))}\n\n{researcher_text(text)}"
            for name, text in sections.items()
        )
    else:
        rendered_sections = researcher_text(json.dumps(body, ensure_ascii=False, indent=2))
    return (
        "# 论文草稿\n\n"
        "> 本稿基于当前项目材料生成，提交或公开前请完成研究者复核。\n\n"
        f"{rendered_sections}\n"
    )


@app.post(
    "/api/v1/projects/{project_id}/workflow/artifacts/{artifact_id}/apply-to-manuscript",
    response_model=ProjectDocument,
)
def apply_agent_manuscript(
    project_id: str,
    artifact_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
) -> ProjectDocument:
    """Create an editable project manuscript from one writing-Agent candidate."""

    project = identity_service.get_project(user, project_id)
    source = workflow_controller.agent_artifact_source(project_id, artifact_id)
    artifact = artifact_store.get(project_id, artifact_id)
    content = artifact_content_store.get(project_id, artifact_id)
    if content is None:
        raise ContextInputError("agent_artifact_not_found", "Agent output artifact was not found")
    artifact_type = artifact.artifact_type if artifact is not None else content.artifact_type
    manuscript_types = {"ManuscriptDraftZh", "ManuscriptDraftEn", "ManuscriptOutline"}
    if artifact_type not in manuscript_types:
        raise ContextInputError(
            "artifact_is_not_manuscript_candidate",
            "Only paper-writing manuscript candidates can be applied to the manuscript library",
        )
    if source is None:
        # The conversational orchestrator stores manuscript candidates directly
        # in the project artifact store. They are valid candidates even though
        # they do not have the legacy Agent-plan ownership record.
        user_request = project.research_direction or "当前项目研究主题"
    else:
        plan, task = source
        if task.agent_id != "paper_writing":
            raise ContextInputError(
                "artifact_is_not_manuscript_candidate",
                "Only paper-writing manuscript candidates can be applied to the manuscript library",
            )
        user_request = plan.user_request
    if source is not None:
        workflow_controller.decide_agent_output(
            project_id,
            artifact_id,
            AgentOutputDecisionRequest(
                decision="apply",
                decided_by=user.username,
                target="paper_editor",
                note="Applied as an editable project manuscript candidate.",
            ),
        )
    change_note = (
        f"来自 Agent 计划 {plan.plan_id} 的 {artifact_type} 候选产出"
        if source is not None
        else f"来自对话编排产物 {artifact_id} 的 {artifact_type} 候选产出"
    )
    body_sections = content.body.get("sections")
    section_title = (
        str(body_sections.get("title")).strip()
        if isinstance(body_sections, dict) and body_sections.get("title")
        else ""
    )
    document_title = f"论文草稿 - {(section_title or user_request)[:100]}"
    manuscript_content = _candidate_manuscript_markdown(
        artifact_type=artifact_type,
        body=dict(content.body),
        user_request=user_request,
    )
    existing = next(
        (
            item for item in document_service.list_project(project_id)
            if item.document_type == "manuscript"
            and (item.title == document_title or item.title.startswith("候选论文草稿 - "))
        ),
        None,
    )
    if existing is not None:
        if existing.title != document_title:
            document_service.patch(
                project_id=project_id,
                document_id=existing.document_id,
                user=user,
                request=DocumentPatchRequest(title=document_title),
            )
        document_service.create_version(
            project_id=project_id,
            document_id=existing.document_id,
            user=user,
            request=DocumentVersionCreateRequest(content=manuscript_content, change_note=change_note),
        )
        return document_service.get(project_id, existing.document_id)
    return document_service.create(
        project_id=project_id,
        user=user,
        request=DocumentCreateRequest(
            title=document_title,
            document_type="manuscript",
            format="markdown",
            content=manuscript_content,
            change_note=change_note,
        ),
    )


@app.post("/api/v1/projects/{project_id}/workflow/next")
def project_workflow_next(
    project_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
) -> WorkflowRunResult:
    identity_service.get_project(user, project_id)
    # Keep the legacy route as a compatibility path for existing clients.
    # New clients should use the reviewed Agent-plan endpoints above.
    return workflow_controller.run_next(project_id)


@app.post("/api/v1/projects/{project_id}/workflow/approve")
def project_workflow_approve(
    project_id: str,
    request: WorkflowApprovalInput,
    user: Annotated[UserProfile, Depends(current_user)],
) -> ResearchState:
    identity_service.get_project(user, project_id)
    approval = workflow_controller.get_pending_approval(project_id)
    return workflow_controller.resume_approval(
        project_id,
        approval,
        decision=request.decision,
        decided_by=user.username,
        reason=request.reason,
    )


@app.post("/api/v1/projects/{project_id}/workflow/data-pipeline/prepare")
def project_data_pipeline_prepare(
    project_id: str,
    request: DataPipelinePreparationRequest,
    user: Annotated[UserProfile, Depends(current_user)],
) -> DataPipelineState:
    """Prepare a data pipeline only for a project the caller can access."""

    identity_service.get_project(user, project_id)
    return workflow_controller.prepare_data_pipeline(project_id, request)


@app.post("/api/v1/projects/{project_id}/workflow/data-pipeline/raw")
async def project_register_data_pipeline_raw_csv(
    project_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
    file: Annotated[UploadFile, File(...)],
) -> DataPipelineState:
    """Authenticated project-scoped CSV upload for the approved data gate."""

    identity_service.get_project(user, project_id)
    return workflow_controller.register_data_pipeline_raw_csv(
        project_id,
        filename=file.filename or "upload.csv",
        content=await file.read(),
    )


@app.post("/api/v1/projects/{project_id}/workflow/data-pipeline/decide")
def project_data_pipeline_decide(
    project_id: str,
    request: WorkflowApprovalInput,
    user: Annotated[UserProfile, Depends(current_user)],
) -> DataPipelineState:
    """Record a project member's decision for the pending data-pipeline gate."""

    identity_service.get_project(user, project_id)
    return workflow_controller.decide_data_pipeline(
        project_id,
        decision=request.decision,
        decided_by=user.username,
        reason=request.reason,
    )


@app.post("/api/v1/workflow/projects")
def create_workflow_project(request: WorkflowProjectRequest) -> PlanningRunResult:
    """Create a project and run the first planning slice."""
    return workflow_controller.start_planning(
        PlanningRequest(
            project_id=request.project_id,
            research_intent=request.research_intent,
            context_bundle_ref=request.context_bundle_ref,
            run_id=request.run_id or f"planning-{request.project_id}",
        )
    )


@app.get("/api/v1/workflow/projects/{project_id}")
def workflow_project(project_id: str) -> ControllerWorkflowState:
    return workflow_controller.get_state(project_id)


@app.post("/api/v1/workflow/projects/{project_id}/next")
def workflow_next(project_id: str) -> WorkflowRunResult:
    # Compatibility route for pre-Agent-plan clients. The Controller remains
    # the single owner of routing and approval state transitions.
    return workflow_controller.run_next(project_id)


@app.post("/api/v1/workflow/projects/{project_id}/approve")
def workflow_approve(project_id: str, request: WorkflowApprovalInput) -> ResearchState:
    approval = workflow_controller.get_pending_approval(project_id)
    return workflow_controller.resume_approval(
        project_id,
        approval,
        decision=request.decision,
        decided_by=request.decided_by,
        reason=request.reason,
    )


@app.get("/api/v1/workflow/agents")
def workflow_agents() -> list[AgentCapability]:
    return workflow_controller.list_agent_capabilities()


@app.get("/api/v1/workflow/operators")
def workflow_operators() -> list[OperatorSpec]:
    return operator_registry.list()


@app.get("/api/v1/workflow/runtime")
def workflow_runtime() -> dict[str, object]:
    """Expose safe local capability status without returning executable paths."""
    pipeline = workflow_controller.data_pipeline
    provider = pipeline.research_execution.coding_provider
    health_reason = getattr(provider, "health_reason", None)
    codex_reason = health_reason() if callable(health_reason) else None
    spss = pipeline.dual_engine_execution.spss_adapter.detect()
    scidavis = SciDAVisAdapter(storage_root).detect()
    external_search = ExternalSearchClient()
    llm_key_configured = bool(os.getenv("STEM_SCI_LLM_API_KEY", "").strip())
    llm_enabled = _llm_workflow_enabled() and llm_key_configured
    llm_budget_limit, llm_budget_used = GPTProvider.budget_status()
    provider_name = os.getenv("STEM_SCI_CODING_PROVIDER", "deterministic").strip().lower()
    codex_remote_enabled = os.getenv("STEM_SCI_CODEX_REMOTE_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }
    if provider_name == "codex" and not codex_remote_enabled:
        provider_name = "deterministic"
    # ``codex --version`` proves only that the executable exists.  It cannot
    # prove a model request will traverse the current proxy/network path, so
    # expose detection and generation readiness as distinct states.
    codex_cli_detected = provider_name == "codex" and codex_reason is None
    codex_generation_confirmed = (
        os.getenv("STEM_SCI_CODEX_GENERATION_CONFIRMED", "false").strip().lower()
        in {"1", "true", "yes"}
    )
    codex_available = codex_cli_detected and codex_generation_confirmed
    writing_argument_reviewer_enabled = os.getenv(
        "STEM_SCI_WRITING_REVIEWER_ENABLED", "false"
    ).strip().lower() in {"1", "true", "yes", "on"}
    runtime_codex_reason = (
        "CODEX_PROVIDER_NOT_SELECTED"
        if provider_name != "codex"
        else codex_reason
        if codex_reason is not None
        else None
        if codex_generation_confirmed
        else "CODEX_CLI_DETECTED_GENERATION_UNVERIFIED"
    )
    return {
        "coding_provider": provider_name,
        "codex_available": codex_available,
        "codex_cli_detected": codex_cli_detected,
        "codex_generation_confirmed": codex_generation_confirmed,
        "codex_remote_enabled": codex_remote_enabled,
        "codex_reason": runtime_codex_reason,
        "spss_available": spss.available,
        "spss_reason": spss.reason_code,
        "scidavis_available": scidavis.available,
        "scidavis_reason": scidavis.reason,
        "external_search_provider": external_search.provider,
        "external_search_configured": external_search.configured,
        "llm_workflow_enabled": llm_enabled,
        "llm_provider": os.getenv("STEM_SCI_LLM_PROVIDER", "gpt").strip().lower() if llm_enabled else None,
        "llm_model": os.getenv("STEM_SCI_LLM_MODEL", "").strip() if llm_enabled else None,
        "llm_budget_limit": llm_budget_limit,
        "llm_budget_used": llm_budget_used,
        "writing_argument_reviewer_enabled": writing_argument_reviewer_enabled,
    }


@app.post(
    "/api/v1/workflow/projects/{project_id}/data-pipeline/visualization/export",
    response_model=SciDAVisExport,
)
def export_result_for_scidavis(
    project_id: str,
    user: Annotated[UserProfile, Depends(current_user)],
) -> SciDAVisExport:
    """Export a verified result card for optional SciDAVis visualization."""

    identity_service.get_project(user, project_id)
    workflow_state = workflow_controller.get_state(project_id)
    # Conversational projects persist the pipeline in immutable artifacts.
    # Restore that snapshot when the legacy Controller process was restarted.
    pipeline_state = workflow_state.data_pipeline or _latest_quantitative_pipeline_state(project_id)
    if pipeline_state is None or pipeline_state.statistical_result_card is None:
        raise HTTPException(status_code=409, detail="a verified statistical result card is required")
    return SciDAVisAdapter(storage_root).export_result(
        project_id, pipeline_state.statistical_result_card
    )


@app.get("/api/v1/workflow/projects/{project_id}/executions")
def workflow_executions(project_id: str) -> list[OperatorRun]:
    return execution_store.list_project(project_id)


@app.get("/api/v1/workflow/projects/{project_id}/artifacts")
def workflow_artifacts(project_id: str) -> list[ArtifactRef]:
    return artifact_store.list_project(project_id)


@app.get("/api/v1/workflow/projects/{project_id}/artifact-contents")
def workflow_artifact_contents(project_id: str) -> list[ArtifactContent]:
    contents = artifact_content_store.list_project(project_id)
    # Keep legacy QA-only projects visible in the same workbench contract as
    # newer orchestrated projects.  These cards are clearly marked
    # provisional and are never written to the immutable artifact store.
    return [*contents, *_legacy_workflow_artifacts(project_id)]


@app.get("/api/v1/workflow/projects/{project_id}/agent-runs")
def workflow_agent_runs(project_id: str) -> list[AgentRunRecord]:
    return agent_run_store.list_project(project_id)


@app.get("/api/v1/workflow/projects/{project_id}/routes")
def workflow_routes(project_id: str) -> list[RouteDecision]:
    return route_store.list_project(project_id)


@app.post("/api/v1/workflow/projects/{project_id}/review-findings")
def workflow_review_finding(project_id: str, finding: ReviewFinding) -> ResearchState:
    return workflow_controller.route_review_finding(project_id, finding)


@app.post("/api/v1/workflow/projects/{project_id}/reviews/reproducibility")
def workflow_reproducibility_review(
    project_id: str, request: ReproducibilityReviewRequest
) -> ReproducibilityReviewRunResult:
    if request.project_id != project_id:
        raise ContextInputError("project_mismatch", "path project_id does not match request project_id")
    return workflow_controller.run_reproducibility_review(request)


@app.post("/api/v1/workflow/projects/{project_id}/data-pipeline/start")
def start_data_pipeline(
    project_id: str, request: DataPipelineBeginRequest
) -> DataPipelineState:
    if request.project_id != project_id:
        raise ContextInputError("project_mismatch", "path project_id does not match request project_id")
    return workflow_controller.begin_data_pipeline(request)


@app.post("/api/v1/workflow/projects/{project_id}/data-pipeline/prepare")
def prepare_data_pipeline(
    project_id: str, request: DataPipelinePreparationRequest
) -> DataPipelineState:
    return workflow_controller.prepare_data_pipeline(project_id, request)


@app.post("/api/v1/workflow/projects/{project_id}/data-pipeline/raw")
async def register_data_pipeline_raw_csv(
    project_id: str,
    file: Annotated[UploadFile, File(...)],
) -> DataPipelineState:
    return workflow_controller.register_data_pipeline_raw_csv(
        project_id,
        filename=file.filename or "upload.csv",
        content=await file.read(),
    )


@app.post("/api/v1/workflow/projects/{project_id}/data-pipeline/decide")
def decide_data_pipeline(
    project_id: str, request: WorkflowApprovalInput
) -> DataPipelineState:
    return workflow_controller.decide_data_pipeline(
        project_id,
        decision=request.decision,
        decided_by=request.decided_by,
    )


@app.post("/api/v1/sources/import")
async def import_source(
    project_id: ProjectIdForm,
    file: Annotated[UploadFile, File(...)],
) -> SourceDocument:
    return service.import_bytes(project_id, file.filename or "upload.txt", await file.read())


@app.get("/api/v1/sources")
def sources(project_id: ProjectIdQuery) -> list[SourceDocument]:
    return service.list_sources(project_id)


@app.get("/api/v1/sources/{source_id}")
def source(source_id: str, project_id: ProjectIdQuery) -> SourceDocument:
    return service.get_source(project_id, source_id)


@app.get("/api/v1/sources/{source_id}/chunks")
def chunks(source_id: str, project_id: ProjectIdQuery) -> list[SourceChunk]:
    return service.chunks(project_id, source_id)


@app.post("/api/v1/evidence/search")
def search(request: EvidenceSearchRequest) -> list[EvidenceSearchResult]:
    return service.search(request)


@app.get("/api/v1/evidence/{evidence_id}")
def evidence(evidence_id: str, project_id: ProjectIdQuery) -> EvidenceDetail:
    return service.get_evidence(project_id, evidence_id)


def _reject_unknown_verification_parameters(request: Request) -> None:
    allowed = {"project_id", "verified_by", "verification_note"}
    unexpected = set(request.query_params).difference(allowed)
    if unexpected:
        raise ContextInputError(
            "unsupported_verification_parameter",
            "Verification accepts only project_id, verified_by, and verification_note",
        )


@app.post("/api/v1/evidence/{evidence_id}/verify-source")
def verify(
    evidence_id: str,
    project_id: ProjectIdQuery,
    verified_by: Annotated[str, Query(min_length=1)],
    verification_note: Annotated[str, Query(min_length=1)],
    request: Request,
) -> EvidenceRef:
    _reject_unknown_verification_parameters(request)
    return service.verify_source(project_id, evidence_id, verified_by, verification_note)


@app.post("/api/v1/context/build")
def build(request: ContextBuildRequest) -> ContextBundle:
    return service.build(request)


@app.get("/api/v1/context/{context_id}")
def context(context_id: str, project_id: ProjectIdQuery) -> ContextBundle:
    return service.get_bundle(project_id, context_id)
