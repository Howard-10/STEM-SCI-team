"""Deterministic policy shell for research-state-aware collaboration.

Language models may compose the final prose, but this module owns the bounded
decision: ask the researcher, use existing context, perform a small evidence
search, or hand an explicit execution request to ControlPlane.
"""

from __future__ import annotations

import logging
from hashlib import sha256
from typing import Literal, cast

from pydantic import Field

from stem_sci.agents.runtime import StructuredGenerator

from .models import (
    BeliefRevision,
    CollaborationDecision,
    CollaborationModel,
    CollaborationProfile,
    DecisionRelevance,
    EvidenceObservation,
    InteractionMode,
    ResearchAct,
    ResearchEdge,
    ResearchGraph,
    ResearchGraphPatch,
    ResearchNode,
    ToolPlan,
    TurnPlan,
    utc_now,
)
from .store import SQLiteResearchGraphStore

logger = logging.getLogger(__name__)


class _SemanticTurnDraft(CollaborationModel):
    """Model-proposed cognition; execution authority remains deterministic."""

    current_mode: InteractionMode
    research_acts: list[ResearchAct]
    focal_unknown: str | None = None
    unknown_owner: Literal["context", "system_retrieval", "system_analysis", "user", "defer"] = (
        "defer"
    )
    route_impact: Literal["low", "medium", "high"] = "low"
    can_proceed_provisionally: bool = True
    rationale: str
    question_to_user: str | None = None
    provisional_assumptions: list[str] = Field(default_factory=list)
    exploration_sufficient: bool = False
    sufficiency_reason: str | None = None


class _EvidenceImpactItem(CollaborationModel):
    evidence_node_id: str
    target_node_id: str
    relation: Literal["supports", "contradicts"]
    reason: str
    research_consequences: list[str] = Field(default_factory=list)


class _EvidenceImpactDraft(CollaborationModel):
    impacts: list[_EvidenceImpactItem] = Field(default_factory=list)


_MODE_MARKERS: dict[InteractionMode, tuple[str, ...]] = {
    InteractionMode.TEACH: ("讲懂", "解释一下", "教我", "什么意思", "通俗", "explain", "teach me"),
    InteractionMode.EXECUTE: (
        "直接做",
        "替我做",
        "开始执行",
        "执行分析",
        "直接检索",
        "开始检索",
        "run it",
        "do it",
    ),
    InteractionMode.REVIEW: (
        "硬伤", "挑问题", "挑战", "反驳", "挑刺", "审查", "批判", "哪里不对",
        "检查四类", "互斥", "优化题目", "题目结构", "review", "critique",
    ),
    InteractionMode.SYNTHESIZE: (
        "帮我理",
        "整理一下",
        "总结一下",
        "归纳",
        "我很乱",
        "synthesize",
        "summarize",
    ),
    InteractionMode.DECIDE: ("帮我选", "怎么选", "比较方案", "权衡", "哪个更", "decide", "compare"),
    InteractionMode.CO_THINK: (
        "一起想",
        "和我讨论",
        "共同思考",
        "怎么看",
        "co-think",
        "brainstorm",
    ),
}

_EVIDENCE_MARKERS = (
    "查文献",
    "查一下",
    "检索",
    "搜索",
    "近五年",
    "研究证据",
    "反方证据",
    "反证",
    "文献怎么说",
    "find papers",
    "search",
    "evidence",
    "literature",
)
_WORKFLOW_MARKERS = (
    "直接检索",
    "继续搜索",
    "建立研究任务",
    "启动研究任务",
    "正式开始研究",
    "执行分析",
    "生成分析代码",
    "冻结数据",
    "开始写作",
    "提交论文",
    # Conversation affordances must be executable in auto mode as well as
    # explicit workflow mode.  Without these markers, the "continue" button
    # was rendered as a suggestion but routed back to ordinary discussion.
    "继续推进下一步",
    "继续推进",
    "开始有界证据检索",
    "start research run",
    "execute analysis",
)
_DIRECTIONAL_MARKERS = (
    "应该提高",
    "应该降低",
    "肯定会",
    "必然",
    "正面影响",
    "负面影响",
    "一定会",
    "obviously",
    "must improve",
    "must reduce",
)
_EXPLORE_MARKERS = (
    "有哪些方向",
    "几个方向",
    "研究切口",
    "选题",
    "发散",
    "brainstorm",
    "alternatives",
)
_COMPARE_MARKERS = ("比较", "权衡", "区别", "优缺点", "哪个更", "路线", "compare", "trade-off")
_COMMIT_MARKERS = ("我接受", "接受这个建议", "暂时把", "先把", "就按这个", "同意这个方案", "采用这个")
_OPERATIONALIZE_MARKERS = (
    "具体操作化", "怎么操作化", "操作化方案", "调整操作化", "如何测量",
    "测量方式", "指标定义", "自报偏差", "自报使用方式",
)
_AMBIGUOUS_CONCEPTS: dict[str, str] = {
    "学习能力": "你真正关心的是学习结果，还是学生自主完成任务的能力？",
    "学习效果": "你所说的“学习效果”更接近成绩表现、概念理解，还是迁移能力？",
    "学习效率": "你更想把“学习效率”定义为完成任务所需时间，还是单位时间内的学习成效？",
    "心理健康": "你当前最希望解释的是焦虑、抑郁、主观幸福感，还是更广义的心理困扰？",
    "影响": "这里的“影响”可能指相关关系，也可能指因果效应；哪一种会改变你最终想得到的结论？",
    "效果": "这里的“效果”需要先落到可观察结果上；哪一种结果最接近你的真实研究目的？",
}

_GUIDED_QUESTION_ORDER = (
    "research_goal", "research_focus", "expected_contribution",
    "data_source", "method_boundary", "constraints",
)
_GUIDED_QUESTIONS: dict[str, str] = {
    "research_goal": "我们先把目标说清楚：你最想弄清的是一个现象、一个群体差异、一个教学问题，还是复现已有研究？请先用自己的话说你最想得到什么答案。",
    "research_focus": "接着收窄对象：你具体想关注谁、什么场景或哪类材料？目前最重要的变量、经验或文本是什么？不确定的地方可以直接说不确定。",
    "expected_contribution": "如果这项研究顺利完成，你希望它对谁有用？是澄清争议、帮助改进教学、提供描述性证据，还是提出一个值得后续验证的假设？",
    "data_source": "现在盘点材料：你手头已经有什么论文、数据、访谈、问卷或公开资料？哪些已经上传、哪些还没有？请也说说是否去标识化。",
    "method_boundary": "在方法上你有什么倾向或禁区？例如只做定性理解、观察性比较、教学干预或混合方法；哪些结论你明确不希望系统声称？",
    "constraints": "最后确认现实边界：时间、样本、伦理或课程许可、投稿目标，以及你特别希望我避免的做法或表述分别是什么？",
}


def _stable_id(prefix: str, value: str) -> str:
    digest = sha256(value.strip().encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _contains_any(message: str, markers: tuple[str, ...]) -> bool:
    return any(marker in message for marker in markers)


def _negates_evidence_request(message: str) -> bool:
    """Detect explicit refusals/deferments such as '先不检索'."""

    return any(
        phrase in message
        for phrase in (
            "先不检索", "暂不检索", "不要检索", "不检索", "先别检索",
            "先不搜索", "暂不搜索", "不要搜索", "不搜索", "先别搜索",
            "不用查", "无需查", "不需要查", "do not search", "don't search",
        )
    )


class ResearchCollaborationEngine:
    def __init__(
        self,
        store: SQLiteResearchGraphStore,
        *,
        generator: StructuredGenerator | None = None,
        model: str | None = None,
    ) -> None:
        self.store = store
        self._generator = generator
        self._model = model

    def graph(self, project_id: str) -> ResearchGraph:
        return self.store.get(project_id)

    def prepare_turn(
        self,
        *,
        project_id: str,
        message: str,
        project_title: str,
        research_direction: str,
        memory_facts: dict[str, str] | None = None,
        requested_mode: str = "auto",
        source_turn_id: str | None = None,
    ) -> CollaborationDecision:
        graph = self.store.get(project_id)
        patch = self._observe_context(
            graph,
            message=message,
            project_title=project_title,
            research_direction=research_direction,
            memory_facts=memory_facts or {},
            source_turn_id=source_turn_id,
        )
        plan = self._plan(
            message,
            graph,
            requested_mode=requested_mode,
            memory_facts=memory_facts or {},
        )
        if plan.guided_question_key and plan.guided_question_key != graph.guided_question_key:
            patch = patch.model_copy(update={"guided_question_key": plan.guided_question_key})
        if patch.upserted_nodes or patch.upserted_edges or patch.revisions or patch.guided_question_key:
            graph = self._apply_patch(graph, patch)
            self.store.save(graph, expected_version=patch.base_version)
            patch = patch.model_copy(update={"new_version": graph.version})
        waiting_reason: Literal[
            "none",
            "high_value_user_input",
            "background_research",
            "formal_confirmation",
        ] = (
            "formal_confirmation"
            if plan.formal_gate_required
            else "background_research"
            if plan.should_start_workflow
            else "high_value_user_input"
            if plan.question_to_user
            else "none"
        )
        return CollaborationDecision(
            profile=CollaborationProfile(),
            plan=plan,
            graph_version=graph.version,
            graph_patch=patch,
            belief_revisions=patch.revisions,
            waiting_reason=waiting_reason,
        )

    def prompt_context(self, project_id: str, decision: CollaborationDecision) -> str:
        graph = self.store.get(project_id)
        active = [node for node in graph.nodes if node.status not in {"rejected"}][-12:]
        state_lines = [
            f"- [{node.status}/{node.confidence}] {node.node_type}: {node.content}"
            for node in active
        ] or ["- 尚未形成结构化研究判断"]
        acts = ", ".join(act.value for act in decision.plan.research_acts)
        question_rule = (
            f"如需提问，只问这一项：{decision.plan.question_to_user}"
            if decision.plan.question_to_user
            else "本轮不要为了补全表单而追问；可以明示暂定假设后继续。"
        )
        return (
            "\n研究协作决策：\n"
            f"- 当前交互模式：{decision.plan.current_mode.value}\n"
            f"- 本轮研究动作：{acts}\n"
            f"- 关键未知归属：{decision.plan.decision_relevance.owner}\n"
            f"- 决策理由：{decision.plan.decision_relevance.rationale}\n"
            f"- {question_rule}\n"
            "当前研究信念图摘要：\n" + "\n".join(state_lines)
        )

    def integrate_evidence(
        self,
        *,
        project_id: str,
        decision: CollaborationDecision,
        observations: list[EvidenceObservation],
        answer_summary: str,
    ) -> CollaborationDecision:
        """Link retrieved evidence and apply only validated belief revisions."""

        if not observations:
            return decision
        graph = self.store.get(project_id)
        evidence_nodes = [self._evidence_node(item) for item in observations]
        existing_nodes = {node.node_id: node for node in graph.nodes}
        new_evidence_nodes = [
            node
            for node in evidence_nodes
            if node.node_id not in existing_nodes
            or existing_nodes[node.node_id].content != node.content
            or existing_nodes[node.node_id].status != node.status
        ]
        impacts = self._evidence_impacts(graph, evidence_nodes, answer_summary)
        evidence_node_ids = {node.node_id for node in evidence_nodes}
        target_nodes = {
            node.node_id: node
            for node in graph.nodes
            if node.node_type in {"hypothesis", "assumption", "question", "design"}
        }
        edges: list[ResearchEdge] = []
        impact_reasons: dict[tuple[str, str], _EvidenceImpactItem] = {}
        for impact in impacts:
            if (
                impact.evidence_node_id not in evidence_node_ids
                or impact.target_node_id not in target_nodes
            ):
                continue
            edge = ResearchEdge(
                source_id=impact.evidence_node_id,
                target_id=impact.target_node_id,
                relation=impact.relation,
            )
            edges.append(edge)
            impact_reasons[(impact.evidence_node_id, impact.target_node_id)] = impact

        all_nodes = {**existing_nodes, **{node.node_id: node for node in evidence_nodes}}
        all_edges = {(edge.source_id, edge.target_id, edge.relation): edge for edge in graph.edges}
        for edge in edges:
            all_edges[(edge.source_id, edge.target_id, edge.relation)] = edge

        revised_nodes: list[ResearchNode] = []
        revisions: list[BeliefRevision] = []
        for target_id, target in target_nodes.items():
            if target.status in {"frozen", "rejected"}:
                continue
            trustworthy_edges = [
                edge
                for edge in all_edges.values()
                if edge.target_id == target_id
                and all_nodes.get(edge.source_id) is not None
                and all_nodes[edge.source_id].node_type == "evidence"
                and all_nodes[edge.source_id].status == "established"
            ]
            contradicting = [edge for edge in trustworthy_edges if edge.relation == "contradicts"]
            supporting = [edge for edge in trustworthy_edges if edge.relation == "supports"]
            new_status = target.status
            if contradicting:
                new_status = "disputed"
            elif len(supporting) >= 2 and target.status == "tentative":
                new_status = "established"
            if new_status == target.status:
                continue
            triggers = contradicting or supporting
            trigger_ids = [
                evidence_id
                for edge in triggers
                for evidence_id in all_nodes[edge.source_id].source_evidence_ids
            ]
            related_impacts: list[_EvidenceImpactItem] = []
            for edge in triggers:
                related_impact = impact_reasons.get((edge.source_id, target_id))
                if related_impact is not None:
                    related_impacts.append(related_impact)
            reason = (
                related_impacts[0].reason
                if related_impacts
                else "可定位证据改变了当前判断的支持结构。"
            )
            consequences = list(
                dict.fromkeys(
                    consequence
                    for impact in related_impacts
                    for consequence in impact.research_consequences
                )
            )
            revised_nodes.append(target.model_copy(update={"status": new_status}))
            revisions.append(
                BeliefRevision(
                    node_id=target_id,
                    previous_status=target.status,
                    new_status=new_status,
                    trigger_type="evidence",
                    trigger_ids=list(dict.fromkeys(trigger_ids)),
                    reason=reason,
                    research_consequences=consequences,
                )
            )

        existing_edge_keys = {
            (edge.source_id, edge.target_id, edge.relation) for edge in graph.edges
        }
        new_edges = [
            edge
            for edge in edges
            if (edge.source_id, edge.target_id, edge.relation) not in existing_edge_keys
        ]
        patch = ResearchGraphPatch(
            base_version=graph.version,
            new_version=graph.version,
            upserted_nodes=[*new_evidence_nodes, *revised_nodes],
            upserted_edges=new_edges,
            revisions=revisions,
        )
        if patch.upserted_nodes or patch.upserted_edges or patch.revisions:
            graph = self._apply_patch(graph, patch)
            self.store.save(graph, expected_version=patch.base_version)
            patch = patch.model_copy(update={"new_version": graph.version})

        initial = decision.graph_patch
        combined_patch = ResearchGraphPatch(
            base_version=initial.base_version,
            new_version=graph.version,
            upserted_nodes=[*initial.upserted_nodes, *patch.upserted_nodes],
            upserted_edges=[*initial.upserted_edges, *patch.upserted_edges],
            revisions=[*initial.revisions, *patch.revisions],
        )
        return decision.model_copy(
            update={
                "graph_version": graph.version,
                "graph_patch": combined_patch,
                "belief_revisions": [*decision.belief_revisions, *revisions],
            }
        )

    def integrate_evidence_package(
        self,
        *,
        project_id: str,
        package: dict[str, object],
        research_scope: str,
        source_turn_id: str | None = None,
    ) -> ResearchGraph:
        """Project a completed evidence-review package onto the belief graph.

        This path is deliberately deterministic: matrix relations are already
        part of the reviewed package, so the collaboration layer must not ask
        a model to reinterpret them. Provenance and locator state still gate
        belief changes exactly as they do for chat citations.
        """

        graph = self.store.get(project_id)
        def dict_items(value: object) -> list[dict[str, object]]:
            return [cast(dict[str, object], item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []

        def string_items(value: object) -> list[str]:
            return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []

        snapshots = {
            str(item.get("evidence_id")): item
            for item in dict_items(package.get("evidence_snapshots"))
            if isinstance(item.get("evidence_id"), str)
        }
        cards = dict_items(package.get("paper_cards"))
        rows = dict_items(package.get("evidence_matrix"))
        observations: dict[str, EvidenceObservation] = {}
        card_by_source = {
            str(card.get("source_ref")): card
            for card in cards
            if isinstance(card.get("source_ref"), str) and card.get("source_ref")
        }
        for card in cards:
            source_ref = str(card.get("source_ref") or "")
            refs = string_items(card.get("evidence_refs"))
            if not refs:
                refs = [source_ref] if source_ref else []
            findings = card.get("main_findings", [])
            fallback_excerpt = next((str(item) for item in findings if item), "") if isinstance(findings, list) else ""
            for evidence_id in refs:
                snapshot = snapshots.get(evidence_id, {})
                verification = str(snapshot.get("verification_status") or "model_generated_unverified").lower()
                if verification not in {"demo_seed", "model_generated_unverified", "source_verified", "human_verified"}:
                    verification = "model_generated_unverified"
                location = snapshot.get("location")
                resolved = str(snapshot.get("locator_status") or "").upper() == "RESOLVED"
                if isinstance(location, dict):
                    char_start = location.get("char_start")
                    char_end = location.get("char_end")
                    resolved = resolved or (
                        isinstance(char_start, int)
                        and isinstance(char_end, int)
                        and char_end > char_start
                    )
                observations.setdefault(
                    evidence_id,
                    EvidenceObservation(
                        evidence_id=evidence_id,
                        title=str(card.get("title") or source_ref or evidence_id),
                        excerpt=str(snapshot.get("excerpt") or fallback_excerpt or card.get("title") or evidence_id),
                        verification_status=verification,  # type: ignore[arg-type]
                        locator_status="RESOLVED" if resolved else "UNRESOLVED",
                    ),
                )
        for row in rows:
            row_refs = row.get("evidence_refs", [])
            for evidence_id in string_items(row_refs):
                if evidence_id in observations:
                    continue
                snapshot = snapshots.get(evidence_id, {})
                source_ref = str(row.get("source_ref") or "")
                card = card_by_source.get(source_ref, {})
                verification = str(snapshot.get("verification_status") or "model_generated_unverified").lower()
                if verification not in {"demo_seed", "model_generated_unverified", "source_verified", "human_verified"}:
                    verification = "model_generated_unverified"
                observations[evidence_id] = EvidenceObservation(
                    evidence_id=evidence_id,
                    title=str(card.get("title") or source_ref or evidence_id),
                    excerpt=str(snapshot.get("excerpt") or row.get("finding") or evidence_id),
                    verification_status=verification,  # type: ignore[arg-type]
                    locator_status="RESOLVED" if str(snapshot.get("locator_status") or "").upper() == "RESOLVED" else "UNRESOLVED",
                )
        # External bibliographic candidates have no evidence refs. Keep them
        # visible as tentative nodes so discovery is not confused with proof.
        for source_ref, card in card_by_source.items():
            if not source_ref or not source_ref.startswith("external:") or source_ref in observations:
                continue
            observations[source_ref] = EvidenceObservation(
                evidence_id=source_ref,
                title=str(card.get("title") or source_ref),
                excerpt="外部题录候选，尚未定位或核验原文。",
                verification_status="model_generated_unverified",
                locator_status="UNRESOLVED",
            )
        evidence_nodes = [self._evidence_node(item) for item in observations.values()]
        existing_nodes = {node.node_id: node for node in graph.nodes}
        all_nodes = {**existing_nodes, **{node.node_id: node for node in evidence_nodes}}
        upserted_nodes = [
            node for node in evidence_nodes
            if node.node_id not in existing_nodes
            or existing_nodes[node.node_id].content != node.content
            or existing_nodes[node.node_id].status != node.status
        ]

        targets = [
            node for node in graph.nodes
            if node.node_type in {"hypothesis", "assumption", "design"} and node.status != "rejected"
        ]
        if not targets:
            question_id = _stable_id("question", research_scope)
            question = existing_nodes.get(question_id) or ResearchNode(
                node_id=question_id,
                node_type="question",
                content=research_scope.strip()[:2000],
                status="tentative",
                confidence="medium",
                source_type="user",
                source_turn_ids=[source_turn_id] if source_turn_id else [],
            )
            if question_id not in existing_nodes:
                upserted_nodes.append(question)
            targets = [question]

        node_by_evidence = {node.source_evidence_ids[0]: node for node in evidence_nodes if node.source_evidence_ids}
        edges: list[ResearchEdge] = []
        for row in rows:
            relation = str(row.get("relation") or "").upper()
            edge_relation = {"SUPPORTING": "supports", "CONTRASTING": "contradicts"}.get(relation)
            if edge_relation is None:
                continue
            evidence_ids = string_items(row.get("evidence_refs"))
            target = next((item for item in targets if item.node_type != "question"), targets[0])
            for evidence_id in evidence_ids:
                evidence_node = node_by_evidence.get(evidence_id)
                if evidence_node is not None:
                    edges.append(ResearchEdge(source_id=evidence_node.node_id, target_id=target.node_id, relation=cast(Literal["supports", "contradicts"], edge_relation)))

        all_edges = {(edge.source_id, edge.target_id, edge.relation): edge for edge in graph.edges}
        for edge in edges:
            all_edges[(edge.source_id, edge.target_id, edge.relation)] = edge
        revisions: list[BeliefRevision] = []
        revised_nodes: list[ResearchNode] = []
        for target in targets:
            if target.node_type == "question" or target.status in {"frozen", "rejected"}:
                continue
            trustworthy = [
                edge for edge in all_edges.values()
                if edge.target_id == target.node_id
                and all_nodes.get(edge.source_id) is not None
                and all_nodes[edge.source_id].node_type == "evidence"
                and all_nodes[edge.source_id].status == "established"
            ]
            contradicting = [edge for edge in trustworthy if edge.relation == "contradicts"]
            supporting = [edge for edge in trustworthy if edge.relation == "supports"]
            new_status = "disputed" if contradicting else "established" if len(supporting) >= 2 and target.status == "tentative" else target.status
            if new_status == target.status:
                continue
            trigger_edges = contradicting or supporting
            trigger_ids = [
                evidence_id
                for edge in trigger_edges
                for evidence_id in all_nodes[edge.source_id].source_evidence_ids
            ]
            revised_nodes.append(target.model_copy(update={"status": new_status}))
            revisions.append(BeliefRevision(
                node_id=target.node_id,
                previous_status=target.status,
                new_status=new_status,
                trigger_type="evidence",
                trigger_ids=list(dict.fromkeys(trigger_ids)),
                reason="证据审阅包中的可定位来源改变了当前支持结构。",
                research_consequences=["研究路线应重新检查与该判断相关的关键前提。"],
            ))
        existing_edge_keys = {(edge.source_id, edge.target_id, edge.relation) for edge in graph.edges}
        new_edges = [edge for edge in edges if (edge.source_id, edge.target_id, edge.relation) not in existing_edge_keys]
        gap_report = package.get("research_gap_report")
        gaps = gap_report.get("gaps", []) if isinstance(gap_report, dict) else []
        for gap in gaps if isinstance(gaps, list) else []:
            if not isinstance(gap, dict):
                continue
            gap_id = str(gap.get("gap_id") or gap.get("description") or "gap")
            node_id = _stable_id("uncertainty", gap_id)
            if node_id not in all_nodes:
                upserted_nodes.append(ResearchNode(
                    node_id=node_id,
                    node_type="uncertainty",
                    content=str(gap.get("description") or "未说明的研究缺口")[:2000],
                    status="tentative",
                    confidence="low",
                    source_type="literature",
                    source_evidence_ids=string_items(gap.get("evidence_refs")),
                ))
        patch = ResearchGraphPatch(
            base_version=graph.version,
            new_version=graph.version,
            upserted_nodes=[*upserted_nodes, *revised_nodes],
            upserted_edges=new_edges,
            revisions=revisions,
        )
        if patch.upserted_nodes or patch.upserted_edges or patch.revisions:
            graph = self._apply_patch(graph, patch)
            self.store.save(graph, expected_version=patch.base_version)
        return graph

    def _evidence_node(self, observation: EvidenceObservation) -> ResearchNode:
        verified = observation.verification_status in {"source_verified", "human_verified"}
        located = observation.locator_status == "RESOLVED"
        status: Literal["established", "tentative"] = (
            "established" if verified and located else "tentative"
        )
        confidence: Literal["low", "medium", "high"] = (
            "high"
            if observation.verification_status == "human_verified" and located
            else "medium"
            if verified and located
            else "low"
        )
        return ResearchNode(
            node_id=_stable_id("evidence", observation.evidence_id),
            node_type="evidence",
            content=f"{observation.title}: {observation.excerpt}"[:4000],
            status=status,
            confidence=confidence,
            source_type="literature",
            source_evidence_ids=[observation.evidence_id],
        )

    def _evidence_impacts(
        self,
        graph: ResearchGraph,
        evidence_nodes: list[ResearchNode],
        answer_summary: str,
    ) -> list[_EvidenceImpactItem]:
        generator = self._generator
        model = self._model
        targets = [
            node
            for node in graph.nodes
            if node.node_type in {"hypothesis", "assumption", "question", "design"}
            and node.status != "rejected"
        ]
        if generator is None or not model or not targets:
            return []
        target_text = "\n".join(
            f"- {node.node_id}: {node.node_type} [{node.status}] {node.content}"
            for node in targets[-20:]
        )
        evidence_text = "\n".join(
            f"- {node.node_id} [{node.status}/{node.confidence}]: {node.content}"
            for node in evidence_nodes[:20]
        )
        try:
            result = generator.generate(
                system_prompt=(
                    "判断新证据与现有研究节点之间是否存在直接支持或直接冲突。"
                    "只使用给出的 node_id，不得创建目标。相关、提及或背景相似不等于 supports。"
                    "contradicts 必须挑战核心方向、机制、可检验预测或设计识别能力。"
                    "如果证据不足以建立直接关系，返回空 impacts。每个关系说明研究后果。"
                ),
                user_prompt=(
                    f"当前研究节点：\n{target_text}\n\n"
                    f"新证据：\n{evidence_text}\n\n"
                    f"本轮证据摘要：{answer_summary[:4000]}"
                ),
                response_model=_EvidenceImpactDraft,
                model=model,
                prompt_version="belief-impact-v1",
            )
            return _EvidenceImpactDraft.model_validate(result.parsed_output).impacts[:40]
        except Exception as error:  # noqa: BLE001 - providers expose heterogeneous failures
            logger.warning(
                "Evidence impact analysis unavailable; evidence retained without revision: %s",
                error,
            )
            return []

    def _observe_context(
        self,
        graph: ResearchGraph,
        *,
        message: str,
        project_title: str,
        research_direction: str,
        memory_facts: dict[str, str],
        source_turn_id: str | None,
    ) -> ResearchGraphPatch:
        turn_ids = [source_turn_id] if source_turn_id else []
        candidates: list[ResearchNode] = [
            ResearchNode(
                node_id="objective-project",
                node_type="objective",
                content=research_direction.strip() or project_title.strip(),
                status="tentative",
                confidence="medium",
                source_type="user",
                source_turn_ids=turn_ids,
            )
        ]
        fact_types: dict[str, str] = {
            "research_goal": "objective",
            "research_topic": "question",
            "research_focus": "concept",
            "expected_contribution": "objective",
            "data_source": "constraint",
            "method_boundary": "constraint",
            "constraints": "constraint",
        }
        for key, value in memory_facts.items():
            clean = value.strip()
            if not clean or key not in fact_types:
                continue
            candidates.append(
                ResearchNode(
                    node_id=f"memory-{key.replace('_', '-')}",
                    node_type=fact_types[key],  # type: ignore[arg-type]
                    content=clean,
                    status="established",
                    confidence="high",
                    source_type="user",
                    source_turn_ids=turn_ids,
                )
            )
        normalized = message.strip().lower()
        if _contains_any(normalized, _DIRECTIONAL_MARKERS):
            candidates.append(
                ResearchNode(
                    node_id=_stable_id("assumption", message),
                    node_type="assumption",
                    content=message.strip()[:2000],
                    status="tentative",
                    confidence="low",
                    source_type="assumption",
                    source_turn_ids=turn_ids,
                )
            )

        existing = {node.node_id: node for node in graph.nodes}
        changed: list[ResearchNode] = []
        for candidate in candidates:
            previous = existing.get(candidate.node_id)
            if previous is None:
                changed.append(candidate)
            elif previous.content != candidate.content or previous.status != candidate.status:
                changed.append(candidate.model_copy(update={"created_at": previous.created_at}))
        return ResearchGraphPatch(
            base_version=graph.version,
            new_version=graph.version,
            upserted_nodes=changed,
        )

    def _apply_patch(self, graph: ResearchGraph, patch: ResearchGraphPatch) -> ResearchGraph:
        nodes = {node.node_id: node for node in graph.nodes}
        for node in patch.upserted_nodes:
            nodes[node.node_id] = node.model_copy(update={"updated_at": utc_now()})
        edge_keys = {(edge.source_id, edge.target_id, edge.relation): edge for edge in graph.edges}
        for edge in patch.upserted_edges:
            edge_keys[(edge.source_id, edge.target_id, edge.relation)] = edge
        return graph.model_copy(
            update={
                "version": graph.version + 1,
                "nodes": list(nodes.values()),
                "edges": list(edge_keys.values()),
                "revisions": [*graph.revisions, *patch.revisions][-200:],
                "updated_at": utc_now(),
                "guided_question_key": patch.guided_question_key or graph.guided_question_key,
            }
        )

    def _plan(
        self,
        message: str,
        graph: ResearchGraph,
        *,
        requested_mode: str,
        memory_facts: dict[str, str] | None = None,
    ) -> TurnPlan:
        normalized = message.strip().lower()
        mode = self._mode(normalized, requested_mode)
        acts: list[ResearchAct] = []

        evidence_requested = _contains_any(normalized, _EVIDENCE_MARKERS) and not _negates_evidence_request(normalized)
        workflow_requested = requested_mode == "workflow" or _contains_any(
            normalized, _WORKFLOW_MARKERS
        )
        directional = _contains_any(normalized, _DIRECTIONAL_MARKERS)
        if directional:
            acts.extend([ResearchAct.REFRAME, ResearchAct.CHALLENGE])
        if mode is InteractionMode.REVIEW and ResearchAct.CHALLENGE not in acts:
            acts.append(ResearchAct.CHALLENGE)
        if mode is InteractionMode.DECIDE or _contains_any(normalized, _COMPARE_MARKERS):
            acts.append(ResearchAct.COMPARE)
        if _contains_any(normalized, _EXPLORE_MARKERS):
            acts.append(ResearchAct.EXPLORE)
        if _contains_any(normalized, _COMMIT_MARKERS):
            acts.append(ResearchAct.COMMIT)
        operationalize_requested = _contains_any(normalized, _OPERATIONALIZE_MARKERS)
        if operationalize_requested:
            acts.append(ResearchAct.CLARIFY)
        if evidence_requested:
            acts.append(ResearchAct.EVIDENCE_SEEK)
        if workflow_requested:
            acts.append(ResearchAct.EXECUTE)

        ambiguous_term = next((term for term in _AMBIGUOUS_CONCEPTS if term in normalized), None)
        question: str | None = None
        if operationalize_requested:
            # Data-source constraints are durable conversational memory. Once
            # the researcher has said that platform logs are unavailable, do
            # not ask the same question again on every operationalization
            # turn; move to the next design decision instead.
            known_source = (memory_facts or {}).get("data_source", "").lower()
            source_is_self_report = any(
                marker in known_source
                for marker in ("问卷", "自报", "公开数据", "访谈", "实验数据")
            )
            if source_is_self_report:
                question = "每个情境题允许学生选择多种使用方式，还是只记录最主要的一种？"
            else:
                question = "你能取得平台交互日志，还是只能通过问卷让学生自报使用方式？"
        if (
            ambiguous_term
            and not evidence_requested
            and question is None
            and mode not in {InteractionMode.EXECUTE, InteractionMode.REVIEW}
        ):
            question = _AMBIGUOUS_CONCEPTS[ambiguous_term]
            acts.append(ResearchAct.CLARIFY)

        if not acts:
            acts.append(ResearchAct.REFLECT if graph.version > 1 else ResearchAct.EXPLORE)
        acts = list(dict.fromkeys(acts))

        # Fresh projects use a conversational brief. Ask one concrete
        # question per turn and advance after its answer is persisted.
        guided_key: str | None = None
        if (
            not workflow_requested
            and not evidence_requested
            and mode not in {InteractionMode.REVIEW, InteractionMode.EXECUTE}
            and not _contains_any(normalized, _COMMIT_MARKERS)
        ):
            known = memory_facts or {}
            current_key = graph.guided_question_key
            guided_key = (
                current_key if current_key and not known.get(current_key)
                else next((key for key in _GUIDED_QUESTION_ORDER if not known.get(key)), None)
            )
            if guided_key and question is None:
                question = _GUIDED_QUESTIONS[guided_key]
                if ResearchAct.CLARIFY not in acts:
                    acts.append(ResearchAct.CLARIFY)
            # A recognized ambiguous concept is a real researcher decision,
            # even when the guided brief has a next unanswered field.  Keep
            # the legacy decision semantics for that case.
            if ambiguous_term and question is not None and not operationalize_requested:
                guided_key = None

        if question:
            relevance = DecisionRelevance(
                focal_unknown=guided_key or ambiguous_term,
                owner="user",
                route_impact="high",
                can_proceed_provisionally=False,
                rationale="该核心概念的定义会改变研究问题、测量方式和可支持的结论。",
            )
        elif evidence_requested:
            relevance = DecisionRelevance(
                focal_unknown="现有证据如何支持或挑战当前判断",
                owner="system_retrieval",
                route_impact="medium",
                can_proceed_provisionally=True,
                rationale="这一信息可由系统通过有界检索获得，不应转嫁给研究者回答。",
            )
        else:
            relevance = DecisionRelevance(
                owner="defer",
                route_impact="low",
                can_proceed_provisionally=True,
                rationale="没有发现必须阻塞当前讨论的用户专属信息，可在明确暂定边界后继续。",
            )

        tools: list[ToolPlan] = []
        if evidence_requested and not workflow_requested:
            tools.append(ToolPlan(capability="search_evidence", reason=relevance.rationale))
        if mode is InteractionMode.REVIEW and evidence_requested:
            tools.append(
                ToolPlan(capability="find_counterevidence", reason="审查请求需要主动寻找反例。")
            )
        if workflow_requested:
            tools.append(
                ToolPlan(
                    capability="start_research_run",
                    reason="用户明确要求启动正式研究执行。",
                    bounded=False,
                )
            )

        option_nodes = [
            node
            for node in graph.nodes
            if node.node_type in {"design", "question"} and node.status != "rejected"
        ]
        uncertainty_nodes = [
            node for node in graph.nodes
            if node.node_type == "uncertainty" and node.status not in {"rejected", "frozen"}
        ]
        has_competing_edges = any(edge.relation == "chosen_over" for edge in graph.edges)
        sufficient = (
            len(option_nodes) >= 3
            and not evidence_requested
            and (has_competing_edges or len(uncertainty_nodes) <= 2)
        )
        deterministic_plan = TurnPlan(
            current_mode=mode,
            research_acts=acts,
            decision_relevance=relevance,
            question_to_user=question,
            tool_plan=tools,
            should_start_workflow=workflow_requested,
            exploration_sufficient=sufficient,
            sufficiency_reason=(
                "已有至少三个仍可行的候选，主要权衡已覆盖，继续寻找新路线的边际价值较低；下一步应验证最可能改变选择的关键前提。"
                if sufficient
                else None
            ),
            formal_gate_required=False,
            guided_question_key=guided_key,
        )
        # Select the discourse move from the actual research state.  This is
        # intentionally orthogonal to interaction mode: a review request can
        # still be answered directly, while a genuine route fork is the only
        # case that should interrupt the researcher with a decision.
        novel_nodes = [
            node.content[:240]
            for node in graph.nodes[-8:]
            if node.source_type in {"user", "literature", "analysis"}
        ]
        if question and guided_key:
            # Guided intake is a conversation, not a decision gate.  Ask one
            # natural follow-up and let the researcher answer in their own
            # words; route comparisons only belong to genuine trade-offs.
            role = "ask_novel"
            why_now = "上一轮已经提供了部分研究意图，现在只追问一个会影响后续方向的新细节。"
            needs_user = True
        elif question and relevance.owner == "user":
            role = "decide"
            why_now = "这项信息只能由研究者确定，并且会改变研究问题或测量边界。"
            needs_user = True
        elif ResearchAct.CHALLENGE in acts:
            role = "challenge"
            why_now = "当前判断存在方向性或审查请求，需要先检查反例和替代解释。"
            needs_user = False
        elif ResearchAct.EVIDENCE_SEEK in acts:
            role = "ask_novel" if question is None else "answer"
            why_now = "当前缺口可以由有界检索和来源核验推进，不把检索任务转给研究者。"
            needs_user = False
        elif ResearchAct.COMMIT in acts or ResearchAct.REFLECT in acts:
            role = "summarize"
            why_now = "本轮输入改变了研究地图，需要先汇总新增判断及其下游影响。"
            needs_user = False
        else:
            role = "wait" if graph.version > 1 else "answer"
            why_now = "没有发现必须打断研究者的分叉，可以按暂定边界继续。"
            needs_user = False
        deterministic_plan = deterministic_plan.model_copy(update={
            "turn_role": role,
            "why_now": why_now,
            "novelty": novel_nodes[-4:],
            "user_action_required": needs_user,
        })
        if self._generator is None or not self._model or workflow_requested:
            return deterministic_plan
        return self._semantic_plan(message, graph, deterministic_plan)

    def _semantic_plan(
        self,
        message: str,
        graph: ResearchGraph,
        fallback: TurnPlan,
    ) -> TurnPlan:
        """Use semantic planning when available, preserving deterministic authority."""

        generator = self._generator
        model = self._model
        if generator is None or not model:
            return fallback
        graph_summary = (
            "\n".join(
                f"- {node.node_type} [{node.status}/{node.confidence}]: {node.content}"
                for node in graph.nodes[-16:]
            )
            or "- 尚无结构化研究状态"
        )
        try:
            result = generator.generate(
                system_prompt=(
                    "你负责选择本轮最有价值的研究认知动作，不负责生成最终回复。"
                    "current_mode 表示用户此刻希望怎样协作；research_acts 表示系统应采取的动作，"
                    "两者是独立维度。先判断未知能否从上下文、系统分析或检索得到；"
                    "只有信息只能由用户提供、会显著改变研究路线且不能安全暂定时，"
                    "才设置一个 question_to_user。不要为了补全研究表单而提问。"
                    "EVIDENCE_SEEK 表示有界证据探索，不等于启动完整研究工作流。"
                    "最多选择四个 research_acts，并给出简洁 rationale。"
                ),
                user_prompt=(
                    f"用户消息：{message}\n\n"
                    f"当前研究信念图：\n{graph_summary}\n\n"
                    "请选择当前交互模式、研究动作、最关键未知及其归属。"
                ),
                response_model=_SemanticTurnDraft,
                model=model,
                prompt_version="collaboration-planner-v1",
            )
            draft = _SemanticTurnDraft.model_validate(result.parsed_output)
        except Exception as error:  # noqa: BLE001 - providers expose heterogeneous failures
            logger.warning(
                "Semantic collaboration planning unavailable; using policy fallback: %s", error
            )
            return fallback

        # Explicit language such as "挑战一下" or "直接执行" is a user
        # decision, not a suggestion for the semantic planner to override.
        # Keep the planner for nuance, but preserve deterministic intent acts
        # and mode whenever the policy shell found one.
        explicit_mode = fallback.current_mode
        mode = explicit_mode if explicit_mode is not InteractionMode.CO_THINK else draft.current_mode
        fallback_is_default = fallback.research_acts in (
            [ResearchAct.EXPLORE],
            [ResearchAct.REFLECT],
        ) and explicit_mode is InteractionMode.CO_THINK
        explicit_acts = [] if fallback_is_default else fallback.research_acts
        merged_acts = list(dict.fromkeys([*explicit_acts, *draft.research_acts]))
        # A semantic review/evidence classification supersedes the generic
        # first-turn clarification that the deterministic shell may have
        # prepared before it had the model's broader intent signal.
        if ResearchAct.CHALLENGE in draft.research_acts or ResearchAct.EVIDENCE_SEEK in draft.research_acts:
            merged_acts = [
                act for act in merged_acts
                if act not in {ResearchAct.EXPLORE, ResearchAct.CLARIFY}
            ]
        if _negates_evidence_request(message.lower()):
            merged_acts = [act for act in merged_acts if act is not ResearchAct.EVIDENCE_SEEK]
        acts = merged_acts[:4] or fallback.research_acts
        # Deterministic policy questions encode explicit user intent and
        # durable memory (for example, a confirmed self-report data source).
        # Keep them authoritative even when an optional semantic planner is
        # enabled; otherwise the model can accidentally resurrect an already
        # answered question.
        question = fallback.question_to_user or (
            draft.question_to_user.strip()[:2000]
            if (
                draft.question_to_user
                and draft.unknown_owner == "user"
                and draft.route_impact == "high"
                and not draft.can_proceed_provisionally
            )
            else None
        )
        relevance = DecisionRelevance(
            focal_unknown=draft.focal_unknown,
            owner=draft.unknown_owner,
            route_impact=draft.route_impact,
            can_proceed_provisionally=draft.can_proceed_provisionally,
            rationale=draft.rationale,
        )
        tools: list[ToolPlan] = []
        if ResearchAct.EVIDENCE_SEEK in acts:
            tools.append(
                ToolPlan(
                    capability="search_evidence",
                    reason="该未知可由系统进行有界证据探索，不需要研究者代为回答。",
                )
            )
        if mode is InteractionMode.REVIEW and ResearchAct.CHALLENGE in acts:
            tools.append(
                ToolPlan(
                    capability="find_counterevidence",
                    reason="审查当前判断时主动寻找反例和替代解释。",
                )
            )
        semantic_role = fallback.turn_role
        semantic_question = question if relevance.owner == "user" else None
        if ResearchAct.CHALLENGE in acts:
            semantic_role = "challenge"
        elif ResearchAct.EVIDENCE_SEEK in acts and relevance.owner != "user":
            semantic_role = "ask_novel"
        elif semantic_question:
            semantic_role = "decide"
        return TurnPlan(
            current_mode=mode,
            research_acts=acts,
            decision_relevance=relevance,
            provisional_assumptions=[
                value.strip()[:1000] for value in draft.provisional_assumptions if value.strip()
            ][:6],
            question_to_user=semantic_question,
            tool_plan=tools,
            should_start_workflow=False,
            exploration_sufficient=draft.exploration_sufficient,
            sufficiency_reason=draft.sufficiency_reason,
            formal_gate_required=False,
            turn_role=semantic_role,
            why_now=fallback.why_now,
            novelty=fallback.novelty,
            user_action_required=(semantic_question is not None),
            guided_question_key=(fallback.guided_question_key if semantic_question else None),
        )

    def _mode(self, message: str, requested_mode: str) -> InteractionMode:
        if requested_mode == "workflow":
            return InteractionMode.EXECUTE
        for mode in (
            InteractionMode.EXECUTE,
            InteractionMode.REVIEW,
            InteractionMode.SYNTHESIZE,
            InteractionMode.DECIDE,
            InteractionMode.TEACH,
            InteractionMode.CO_THINK,
        ):
            if _contains_any(message, _MODE_MARKERS[mode]):
                return mode
        return InteractionMode.CO_THINK
