"""Typed contracts for research-state-aware conversation.

The collaboration layer describes epistemic state and the most useful next
research action.  It deliberately does not duplicate durable workflow state:
ControlPlane remains authoritative for execution, artifacts, and formal gates.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class CollaborationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InteractionMode(StrEnum):
    TEACH = "teach"
    CO_THINK = "co_think"
    EXECUTE = "execute"
    REVIEW = "review"
    SYNTHESIZE = "synthesize"
    DECIDE = "decide"


class ResearchAct(StrEnum):
    CLARIFY = "clarify"
    REFRAME = "reframe"
    EXPLORE = "explore"
    COMPARE = "compare"
    CHALLENGE = "challenge"
    EVIDENCE_SEEK = "evidence_seek"
    EXECUTE = "execute"
    REFLECT = "reflect"
    COMMIT = "commit"


class ResearchNode(CollaborationModel):
    node_id: str
    node_type: Literal[
        "objective",
        "question",
        "concept",
        "hypothesis",
        "assumption",
        "evidence",
        "design",
        "constraint",
        "decision",
        "uncertainty",
    ]
    content: str
    status: Literal["established", "tentative", "disputed", "rejected", "frozen"]
    confidence: Literal["low", "medium", "high"] = "medium"
    source_type: Literal["user", "literature", "analysis", "assumption", "reviewer"]
    source_turn_ids: list[str] = Field(default_factory=list)
    source_evidence_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ResearchEdge(CollaborationModel):
    source_id: str
    target_id: str
    relation: Literal[
        "supports",
        "contradicts",
        "depends_on",
        "tests",
        "operationalizes",
        "constrains",
        "chosen_over",
        "invalidates",
    ]


class BeliefRevision(CollaborationModel):
    node_id: str
    previous_status: Literal["established", "tentative", "disputed", "rejected", "frozen"]
    new_status: Literal["established", "tentative", "disputed", "rejected", "frozen"]
    trigger_type: Literal["evidence", "user", "analysis", "reviewer"]
    trigger_ids: list[str] = Field(default_factory=list)
    reason: str
    research_consequences: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class ResearchGraph(CollaborationModel):
    project_id: str
    version: int = Field(default=0, ge=0)
    nodes: list[ResearchNode] = Field(default_factory=list)
    edges: list[ResearchEdge] = Field(default_factory=list)
    revisions: list[BeliefRevision] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    guided_question_key: str | None = None


class ResearchBranch(CollaborationModel):
    """A reversible research route considered during deliberation."""

    branch_id: str
    project_id: str
    title: str
    description: str
    status: Literal["active", "parked", "selected", "rejected"] = "active"
    benefits: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    dependent_node_ids: list[str] = Field(default_factory=list)
    chosen_reason: str | None = None
    created_turn_id: str | None = None
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ResearchGraphPatch(CollaborationModel):
    base_version: int = Field(ge=0)
    new_version: int = Field(ge=0)
    upserted_nodes: list[ResearchNode] = Field(default_factory=list)
    upserted_edges: list[ResearchEdge] = Field(default_factory=list)
    revisions: list[BeliefRevision] = Field(default_factory=list)
    guided_question_key: str | None = None


class EvidenceObservation(CollaborationModel):
    evidence_id: str
    title: str
    excerpt: str
    verification_status: Literal[
        "demo_seed",
        "model_generated_unverified",
        "source_verified",
        "human_verified",
    ] = "model_generated_unverified"
    locator_status: Literal["RESOLVED", "UNRESOLVED"] = "UNRESOLVED"


class CollaborationProfile(CollaborationModel):
    default_mode: InteractionMode = InteractionMode.CO_THINK
    explanation_depth: Literal["brief", "balanced", "detailed"] = "balanced"
    autonomy_level: Literal["confirm_often", "balanced", "proactive"] = "proactive"


class DecisionRelevance(CollaborationModel):
    focal_unknown: str | None = None
    owner: Literal["context", "system_retrieval", "system_analysis", "user", "defer"] = "defer"
    route_impact: Literal["low", "medium", "high"] = "low"
    can_proceed_provisionally: bool = True
    rationale: str


class ToolPlan(CollaborationModel):
    capability: Literal[
        "search_evidence",
        "find_counterevidence",
        "compare_evidence",
        "start_research_run",
    ]
    reason: str
    bounded: bool = True


class TurnPlan(CollaborationModel):
    current_mode: InteractionMode
    research_acts: list[ResearchAct]
    decision_relevance: DecisionRelevance
    provisional_assumptions: list[str] = Field(default_factory=list)
    question_to_user: str | None = None
    tool_plan: list[ToolPlan] = Field(default_factory=list)
    should_start_workflow: bool = False
    exploration_sufficient: bool = False
    sufficiency_reason: str | None = None
    formal_gate_required: bool = False
    # Conversation is a research action, not a fixed response template.
    # These fields let clients explain why this turn exists and whether the
    # researcher actually needs to intervene.
    turn_role: Literal["answer", "ask_novel", "challenge", "summarize", "decide", "wait"] = "answer"
    why_now: str = ""
    novelty: list[str] = Field(default_factory=list)
    user_action_required: bool = False
    guided_question_key: str | None = None


class CollaborationDecision(CollaborationModel):
    profile: CollaborationProfile
    plan: TurnPlan
    graph_version: int
    graph_patch: ResearchGraphPatch
    belief_revisions: list[BeliefRevision] = Field(default_factory=list)
    waiting_reason: Literal[
        "none",
        "high_value_user_input",
        "background_research",
        "formal_confirmation",
    ] = "none"
