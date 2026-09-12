"""Behavioral tests for research-state-aware turn planning."""

from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from stem_sci import api
from stem_sci.accounts import IdentityService
from stem_sci.artifacts.content_store import SQLiteArtifactContentStore
from stem_sci.collaboration import (
    EvidenceObservation,
    InteractionMode,
    ResearchAct,
    ResearchCollaborationEngine,
    ResearchBranch,
    SQLiteResearchGraphStore,
)
from stem_sci.context import ContextService
from stem_sci.context.provider import LocalContextProvider
from stem_sci.knowledge.qa_models import QAAnswerResponse, QAReference, QARouteDecision
from stem_sci.orchestration import ControlPlane, SQLiteControlPlaneRepository


def _engine(tmp_path: Path) -> ResearchCollaborationEngine:
    return ResearchCollaborationEngine(SQLiteResearchGraphStore(tmp_path / "dialogue.db"))


def _turn(
    engine: ResearchCollaborationEngine,
    message: str,
    *,
    requested_mode: str = "auto",
):
    return engine.prepare_turn(
        project_id="project-1",
        message=message,
        project_title="生成式 AI 与学习",
        research_direction="研究大学生使用生成式 AI 对学习的影响",
        requested_mode=requested_mode,
        source_turn_id="turn-1",
    )


def test_only_a_direction_changing_ambiguity_is_asked(tmp_path: Path) -> None:
    decision = _turn(
        _engine(tmp_path),
        "我想研究大学生使用生成式 AI 对学习能力的影响。",
    )

    assert decision.plan.current_mode is InteractionMode.CO_THINK
    assert decision.plan.research_acts == [ResearchAct.CLARIFY]
    assert decision.plan.decision_relevance.owner == "user"
    assert decision.plan.decision_relevance.route_impact == "high"
    assert decision.plan.question_to_user == "你真正关心的是学习结果，还是学生自主完成任务的能力？"
    assert decision.plan.turn_role == "decide"
    assert decision.plan.user_action_required is True


def test_challenge_turn_is_not_rendered_as_a_route_decision(tmp_path: Path) -> None:
    decision = _turn(_engine(tmp_path), "请挑战一下这个判断，找最可能的反例。")

    assert decision.plan.turn_role == "challenge"
    assert decision.plan.user_action_required is False
    assert "反例" in decision.plan.why_now


def test_retrievable_unknown_is_not_turned_into_a_user_question(tmp_path: Path) -> None:
    decision = _turn(
        _engine(tmp_path),
        "帮我查一下近五年纵向研究有没有反方证据。",
    )

    assert decision.plan.current_mode is InteractionMode.CO_THINK
    assert ResearchAct.EVIDENCE_SEEK in decision.plan.research_acts
    assert decision.plan.decision_relevance.owner == "system_retrieval"
    assert decision.plan.question_to_user is None
    assert decision.plan.should_start_workflow is False
    assert {tool.capability for tool in decision.plan.tool_plan} == {"search_evidence"}


def test_negated_search_stays_in_comparison_discussion(tmp_path: Path) -> None:
    decision = _turn(
        _engine(tmp_path),
        "先不检索。请比较刚才列出的三类生成式人工智能使用指标。",
    )

    assert ResearchAct.COMPARE in decision.plan.research_acts
    assert ResearchAct.EVIDENCE_SEEK not in decision.plan.research_acts
    assert decision.plan.tool_plan == []


def test_accept_and_operationalize_produces_commit_and_one_data_question(tmp_path: Path) -> None:
    decision = _turn(
        _engine(tmp_path),
        "我接受这个建议。请帮我把这两个指标具体操作化，并指出现在还需要我决定的一个关键问题。",
    )

    assert ResearchAct.COMMIT in decision.plan.research_acts
    assert ResearchAct.CLARIFY in decision.plan.research_acts
    assert decision.plan.question_to_user == "你能取得平台交互日志，还是只能通过问卷让学生自报使用方式？"


def test_operationalize_does_not_repeat_confirmed_self_report_source(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    decision = engine.prepare_turn(
        project_id="project-1",
        message="目前拿不到平台交互日志，只能通过问卷让学生自报使用方式。请据此调整操作化方案。",
        project_title="生成式 AI 与学习",
        research_direction="研究大学生使用生成式 AI 对学习的影响",
        memory_facts={"data_source": "只能通过问卷"},
        source_turn_id="turn-self-report",
    )

    assert decision.plan.question_to_user == "每个情境题允许学生选择多种使用方式，还是只记录最主要的一种？"
    assert "平台交互日志" not in decision.plan.question_to_user


def test_guided_brief_advances_one_unanswered_detail_at_a_time(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    first = engine.prepare_turn(
        project_id="guided-project",
        message="我想研究公开物理问题解决文本中的语义主题。",
        project_title="物理文本再分析",
        research_direction="公开物理问题解决文本再分析",
        memory_facts={"research_goal": "识别稳定语义主题"},
        source_turn_id="turn-1",
    )
    second = engine.prepare_turn(
        project_id="guided-project",
        message="关注本科生的开放题文字回答。",
        project_title="物理文本再分析",
        research_direction="公开物理问题解决文本再分析",
        memory_facts={
            "research_goal": "识别稳定语义主题",
            "research_focus": "本科生的开放题文字回答",
        },
        source_turn_id="turn-2",
    )

    assert first.plan.guided_question_key == "research_focus"
    assert "关注谁" in first.plan.question_to_user
    assert second.plan.guided_question_key == "expected_contribution"
    assert "对谁有用" in second.plan.question_to_user
    assert engine.graph("guided-project").guided_question_key == "expected_contribution"


def test_turn_mode_and_research_act_are_independent(tmp_path: Path) -> None:
    decision = _turn(
        _engine(tmp_path),
        "你先帮我审查这个方案有什么硬伤，并查找反证。",
    )

    assert decision.plan.current_mode is InteractionMode.REVIEW
    assert ResearchAct.CHALLENGE in decision.plan.research_acts
    assert ResearchAct.EVIDENCE_SEEK in decision.plan.research_acts
    assert {tool.capability for tool in decision.plan.tool_plan} == {
        "search_evidence",
        "find_counterevidence",
    }


def test_plain_challenge_request_is_a_review_action(tmp_path: Path) -> None:
    decision = _turn(_engine(tmp_path), "请挑战一下这个判断。")

    assert decision.plan.current_mode is InteractionMode.REVIEW
    assert ResearchAct.CHALLENGE in decision.plan.research_acts


def test_only_explicit_formal_execution_starts_workflow(tmp_path: Path) -> None:
    natural_search = _turn(_engine(tmp_path), "帮我查一下近五年的相关研究。")
    formal_run = _turn(_engine(tmp_path), "现在建立研究任务并正式开始研究。")

    assert natural_search.plan.should_start_workflow is False
    assert formal_run.plan.should_start_workflow is True
    assert ResearchAct.EXECUTE in formal_run.plan.research_acts


def test_directional_assumption_is_persisted_as_tentative(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    decision = _turn(engine, "很多学生都用 ChatGPT，所以它应该提高学习效率。")
    graph = engine.graph("project-1")

    assert ResearchAct.REFRAME in decision.plan.research_acts
    assert ResearchAct.CHALLENGE in decision.plan.research_acts
    assumptions = [node for node in graph.nodes if node.node_type == "assumption"]
    assert len(assumptions) == 1
    assert assumptions[0].status == "tentative"
    assert assumptions[0].confidence == "low"


def test_graph_updates_are_versioned_and_idempotent_for_same_context(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    first = _turn(engine, "先帮我理一下这个研究。")
    second = _turn(engine, "先帮我理一下这个研究。")

    assert first.graph_version == 1
    assert second.graph_version == 1
    assert second.graph_patch.upserted_nodes == []


def test_store_rejects_a_stale_graph_write(tmp_path: Path) -> None:
    store = SQLiteResearchGraphStore(tmp_path / "dialogue.db")
    graph = store.get("project-1")
    advanced = graph.model_copy(update={"version": 1})
    store.save(advanced, expected_version=0)

    with pytest.raises(ValueError, match="revision conflict"):
        store.save(advanced.model_copy(update={"version": 1}), expected_version=0)


def test_semantic_planner_can_recognize_intent_beyond_fallback_markers(tmp_path: Path) -> None:
    class FakeGenerator:
        def generate(self, **_: object) -> SimpleNamespace:
            return SimpleNamespace(
                parsed_output={
                    "current_mode": "review",
                    "research_acts": ["challenge", "evidence_seek"],
                    "focal_unknown": "当前结论是否忽略了反向因果",
                    "unknown_owner": "system_retrieval",
                    "route_impact": "high",
                    "can_proceed_provisionally": True,
                    "rationale": "可以先由系统查找反证和替代解释。",
                    "question_to_user": "请补充更多信息",
                    "provisional_assumptions": [],
                    "exploration_sufficient": False,
                    "sufficiency_reason": None,
                }
            )

    engine = ResearchCollaborationEngine(
        SQLiteResearchGraphStore(tmp_path / "dialogue.db"),
        generator=FakeGenerator(),  # type: ignore[arg-type]
        model="test-model",
    )
    decision = _turn(
        engine,
        "请站在一个非常苛刻的期刊评议人角度看这条思路。",
    )

    assert decision.plan.current_mode is InteractionMode.REVIEW
    assert decision.plan.research_acts == [
        ResearchAct.CHALLENGE,
        ResearchAct.EVIDENCE_SEEK,
    ]
    assert decision.plan.decision_relevance.owner == "system_retrieval"
    assert decision.plan.question_to_user is None
    assert {tool.capability for tool in decision.plan.tool_plan} == {
        "search_evidence",
        "find_counterevidence",
    }


def test_verified_counterevidence_revises_a_tentative_assumption(tmp_path: Path) -> None:
    store = SQLiteResearchGraphStore(tmp_path / "dialogue.db")
    setup_engine = ResearchCollaborationEngine(store)
    decision = _turn(
        setup_engine,
        "很多学生都用 ChatGPT，所以它应该提高学习效率。",
    )
    assumption = next(
        node for node in setup_engine.graph("project-1").nodes if node.node_type == "assumption"
    )
    evidence_id = "verified-chunk-1"
    evidence_node_id = f"evidence-{sha256(evidence_id.encode('utf-8')).hexdigest()[:16]}"

    class ImpactGenerator:
        def generate(self, **_: object) -> SimpleNamespace:
            return SimpleNamespace(
                parsed_output={
                    "impacts": [
                        {
                            "evidence_node_id": evidence_node_id,
                            "target_node_id": assumption.node_id,
                            "relation": "contradicts",
                            "reason": "纵向结果更支持学习困难预测后续 AI 使用。",
                            "research_consequences": [
                                "因果方向需要双向检验",
                                "纵向设计优先级上升",
                            ],
                        }
                    ]
                }
            )

    engine = ResearchCollaborationEngine(
        store,
        generator=ImpactGenerator(),  # type: ignore[arg-type]
        model="test-model",
    )
    updated = engine.integrate_evidence(
        project_id="project-1",
        decision=decision,
        observations=[
            EvidenceObservation(
                evidence_id=evidence_id,
                title="一项纵向研究",
                excerpt="基线学习困难预测后续生成式 AI 使用，反向路径不显著。",
                verification_status="source_verified",
                locator_status="RESOLVED",
            )
        ],
        answer_summary="新证据挑战了原来的单向促进假设。",
    )

    revised = next(
        node for node in engine.graph("project-1").nodes if node.node_id == assumption.node_id
    )
    assert revised.status == "disputed"
    assert updated.graph_version == 2
    assert updated.belief_revisions[0].previous_status == "tentative"
    assert updated.belief_revisions[0].new_status == "disputed"
    assert updated.belief_revisions[0].research_consequences == [
        "因果方向需要双向检验",
        "纵向设计优先级上升",
    ]


def test_unverified_candidate_cannot_change_a_belief(tmp_path: Path) -> None:
    store = SQLiteResearchGraphStore(tmp_path / "dialogue.db")
    setup_engine = ResearchCollaborationEngine(store)
    decision = _turn(setup_engine, "它应该提高学习效率。")
    assumption = next(
        node for node in setup_engine.graph("project-1").nodes if node.node_type == "assumption"
    )
    evidence_id = "unverified-paper-1"
    evidence_node_id = f"evidence-{sha256(evidence_id.encode('utf-8')).hexdigest()[:16]}"

    class ImpactGenerator:
        def generate(self, **_: object) -> SimpleNamespace:
            return SimpleNamespace(
                parsed_output={
                    "impacts": [
                        {
                            "evidence_node_id": evidence_node_id,
                            "target_node_id": assumption.node_id,
                            "relation": "contradicts",
                            "reason": "外部题录似乎给出相反结果。",
                            "research_consequences": ["需要获取原文核验"],
                        }
                    ]
                }
            )

    engine = ResearchCollaborationEngine(
        store,
        generator=ImpactGenerator(),  # type: ignore[arg-type]
        model="test-model",
    )
    updated = engine.integrate_evidence(
        project_id="project-1",
        decision=decision,
        observations=[
            EvidenceObservation(
                evidence_id=evidence_id,
                title="尚未核验的论文候选",
                excerpt="仅有题录摘要。",
                verification_status="model_generated_unverified",
                locator_status="UNRESOLVED",
            )
        ],
        answer_summary="这是尚未核验的候选。",
    )

    unchanged = next(
        node for node in engine.graph("project-1").nodes if node.node_id == assumption.node_id
    )
    assert unchanged.status == "tentative"
    assert updated.belief_revisions == []


def test_evidence_review_package_projects_matrix_and_gaps(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    _turn(engine, "它应该提高学习效率。")
    assumption = next(node for node in engine.graph("project-1").nodes if node.node_type == "assumption")
    package = {
        "paper_cards": [{
            "source_ref": "src-1",
            "title": "已核验研究",
            "main_findings": ["结果支持该方向"],
            "evidence_refs": ["ev-1"],
        }],
        "evidence_snapshots": [{
            "evidence_id": "ev-1",
            "source_id": "src-1",
            "excerpt": "结果支持该方向",
            "verification_status": "source_verified",
            "locator_status": "RESOLVED",
        }],
        "evidence_matrix": [{
            "source_ref": "src-1",
            "relation": "SUPPORTING",
            "finding": "结果支持该方向",
            "evidence_refs": ["ev-1"],
        }],
        "research_gap_report": {"gaps": [{"gap_id": "gap-1", "description": "缺少长期追踪证据", "evidence_refs": ["ev-1"]}]},
    }
    engine.integrate_evidence_package(
        project_id="project-1", package=package, research_scope="生成式 AI 与学习效率", source_turn_id="turn-2"
    )
    graph = engine.graph("project-1")
    assert any(node.node_type == "evidence" and node.status == "established" for node in graph.nodes)
    assert any(node.node_type == "uncertainty" for node in graph.nodes)
    assert any(edge.target_id == assumption.node_id and edge.relation == "supports" for edge in graph.edges)


def test_research_branch_is_reversible_and_durable(tmp_path: Path) -> None:
    store = SQLiteResearchGraphStore(tmp_path / "dialogue.db")
    branch = ResearchBranch(
        branch_id="branch-1",
        project_id="project-1",
        title="纵向研究",
        description="追踪时间变化",
    )
    store.save_branch(branch)
    assert store.get_branch("project-1", "branch-1").status == "active"
    store.save_branch(branch.model_copy(update={"status": "selected", "chosen_reason": "更能识别时间顺序"}))
    store.save_branch(branch.model_copy(update={"status": "parked"}))
    assert store.get_branch("project-1", "branch-1").status == "parked"


def test_research_branch_api_supports_select_and_park(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = IdentityService(tmp_path / "identity.db")
    monkeypatch.setattr(api, "identity_service", identity)
    monkeypatch.setattr(
        api,
        "control_plane",
        ControlPlane(SQLiteControlPlaneRepository(tmp_path / "control.db")),
    )
    client = TestClient(api.app)
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "username": "branchuser",
            "email": "branch@example.test",
            "password": "research-pass-123",
        },
    )
    headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}
    assert client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "project_id": "branch-project",
            "title": "路线分支测试",
            "research_direction": "比较两种研究路线",
        },
    ).status_code == 200
    created = client.post(
        "/api/v1/projects/branch-project/research-branches",
        headers=headers,
        json={
            "title": "路线 A",
            "description": "先做纵向证据梳理",
            "benefits": ["时间顺序更清楚"],
            "risks": ["成本较高"],
        },
    )
    assert created.status_code == 200, created.text
    branch_id = created.json()["branch_id"]
    selected = client.post(
        f"/api/v1/projects/branch-project/research-branches/{branch_id}/activate",
        headers=headers,
        json={"reason": "更能回答核心问题"},
    )
    assert selected.status_code == 200
    assert selected.json()["status"] == "selected"
    parked = client.post(
        f"/api/v1/projects/branch-project/research-branches/{branch_id}/park",
        headers=headers,
        json={"reason": "先保留为备选"},
    )
    assert parked.status_code == 200
    assert parked.json()["status"] == "parked"
    listed = client.get(
        "/api/v1/projects/branch-project/research-branches", headers=headers
    )
    assert listed.status_code == 200
    assert listed.json()[0]["status"] == "parked"


def test_collaboration_api_returns_plan_and_durable_canvas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context_service = ContextService(tmp_path / "context")
    identity = IdentityService(tmp_path / "identity.db")
    monkeypatch.setattr(api, "service", context_service)
    monkeypatch.setattr(
        api.workflow_controller,
        "context_provider",
        LocalContextProvider(context_service),
    )
    monkeypatch.setattr(api, "identity_service", identity)
    monkeypatch.setattr(
        api,
        "control_plane",
        ControlPlane(SQLiteControlPlaneRepository(tmp_path / "control.db")),
    )
    monkeypatch.setattr(
        api,
        "artifact_content_store",
        SQLiteArtifactContentStore(tmp_path / "control.db"),
    )
    monkeypatch.setattr(api.qa_service, "_generator", None)
    client = TestClient(api.app)

    registration = client.post(
        "/api/v1/auth/register",
        json={
            "username": "collaborator",
            "email": "collaborator@example.test",
            "password": "research-pass-123",
        },
    )
    headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}
    assert (
        client.post(
            "/api/v1/projects",
            headers=headers,
            json={
                "project_id": "collaboration-project",
                "title": "生成式 AI 与学习",
                "research_direction": "研究大学生使用生成式 AI 对学习的影响",
            },
        ).status_code
        == 200
    )

    response = client.post(
        "/api/v1/projects/collaboration-project/collaboration/turn",
        headers=headers,
        json={
            "project_id": "collaboration-project",
            "message": "我想研究大学生使用生成式 AI 对学习能力的影响。",
            "interaction_mode": "auto",
            "client_turn_id": "turn-api-1",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "qa"
    assert body["gate"] is None
    assert body["collaboration"]["plan"]["research_acts"] == ["clarify"]
    assert body["collaboration"]["plan"]["question_to_user"] == (
        "你真正关心的是学习结果，还是学生自主完成任务的能力？"
    )
    assert "你真正关心的是学习结果" in body["message"]

    canvas = client.get(
        "/api/v1/projects/collaboration-project/research-canvas",
        headers=headers,
    )
    assert canvas.status_code == 200, canvas.text
    assert canvas.json()["version"] == 1
    assert any(node["node_type"] == "objective" for node in canvas.json()["nodes"])


def test_collaboration_api_turns_verified_counterevidence_into_a_visible_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context_service = ContextService(tmp_path / "context")
    identity = IdentityService(tmp_path / "identity.db")
    monkeypatch.setattr(api, "service", context_service)
    monkeypatch.setattr(
        api.workflow_controller,
        "context_provider",
        LocalContextProvider(context_service),
    )
    monkeypatch.setattr(api, "identity_service", identity)
    monkeypatch.setattr(
        api,
        "control_plane",
        ControlPlane(SQLiteControlPlaneRepository(tmp_path / "control.db")),
    )
    monkeypatch.setattr(
        api,
        "artifact_content_store",
        SQLiteArtifactContentStore(tmp_path / "control.db"),
    )
    monkeypatch.setattr(api.qa_service, "_generator", None)
    client = TestClient(api.app)
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "username": "beliefrevision",
            "email": "beliefrevision@example.test",
            "password": "research-pass-123",
        },
    )
    headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}
    assert (
        client.post(
            "/api/v1/projects",
            headers=headers,
            json={
                "project_id": "belief-project",
                "title": "AI 与学习效率",
                "research_direction": "研究生成式 AI 使用与学习效率的关系",
            },
        ).status_code
        == 200
    )
    first = client.post(
        "/api/v1/projects/belief-project/collaboration/turn",
        headers=headers,
        json={
            "project_id": "belief-project",
            "message": "它应该提高学习效率。",
            "interaction_mode": "auto",
            "client_turn_id": "belief-turn-1",
        },
    )
    assert first.status_code == 200, first.text
    canvas = client.get(
        "/api/v1/projects/belief-project/research-canvas",
        headers=headers,
    ).json()
    assumption = next(node for node in canvas["nodes"] if node["node_type"] == "assumption")
    evidence_id = "api-verified-chunk"
    evidence_node_id = f"evidence-{sha256(evidence_id.encode('utf-8')).hexdigest()[:16]}"

    class CollaborationGenerator:
        def generate(self, **kwargs: object) -> SimpleNamespace:
            response_model = kwargs["response_model"]
            if getattr(response_model, "__name__", "") == "_SemanticTurnDraft":
                return SimpleNamespace(
                    parsed_output={
                        "current_mode": "review",
                        "research_acts": ["challenge", "evidence_seek"],
                        "focal_unknown": "是否存在反向路径",
                        "unknown_owner": "system_retrieval",
                        "route_impact": "high",
                        "can_proceed_provisionally": True,
                        "rationale": "可以由系统检索反证。",
                        "question_to_user": None,
                    }
                )
            return SimpleNamespace(
                parsed_output={
                    "impacts": [
                        {
                            "evidence_node_id": evidence_node_id,
                            "target_node_id": assumption["node_id"],
                            "relation": "contradicts",
                            "reason": "纵向证据显示学习困难更可能预测后续 AI 使用。",
                            "research_consequences": ["需要检验反向因果"],
                        }
                    ]
                }
            )

    monkeypatch.setattr(api.qa_service, "_generator", CollaborationGenerator())
    monkeypatch.setattr(api.qa_service, "_model", "test-model")
    monkeypatch.setattr(
        api.qa_service,
        "answer",
        lambda request: QAAnswerResponse(
            project_id="belief-project",
            conversation_id="belief-conversation",
            question=request.question,
            rewritten_query=request.question,
            route=QARouteDecision(route="hybrid_search", reason="测试检索"),
            answer="一项纵向研究对当前单向促进假设提出了挑战。",
            citations=[
                QAReference(
                    citation_index=1,
                    paper_title="生成式 AI 使用的纵向预测因素",
                    source_filename="verified.pdf",
                    canonical_paper_id="paper-verified",
                    canonical_chunk_id=evidence_id,
                    chunk_index=1,
                    excerpt="基线学习困难预测后续 AI 使用，反向路径不显著。",
                    verification_status="source_verified",
                    locator_status="RESOLVED",
                )
            ],
            retrieval_status="READY",
        ),
    )
    second = client.post(
        "/api/v1/projects/belief-project/collaboration/turn",
        headers=headers,
        json={
            "project_id": "belief-project",
            "message": "帮我查一下是否有反证。",
            "interaction_mode": "auto",
            "client_turn_id": "belief-turn-2",
        },
    )

    assert second.status_code == 200, second.text
    body = second.json()
    assert body["collaboration"]["belief_revisions"][0]["new_status"] == "disputed"
    assert "新证据改变了当前研究判断" in body["message"]
    updated_canvas = client.get(
        "/api/v1/projects/belief-project/research-canvas",
        headers=headers,
    ).json()
    updated_assumption = next(
        node for node in updated_canvas["nodes"] if node["node_id"] == assumption["node_id"]
    )
    assert updated_assumption["status"] == "disputed"
