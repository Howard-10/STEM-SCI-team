import json
from pathlib import Path

from fastapi.testclient import TestClient

import stem_sci.api as api
from stem_sci.accounts import IdentityService
from stem_sci.artifacts.content_store import SQLiteArtifactContentStore
from stem_sci.context.service import ContextService
from stem_sci.collaboration import (
    CollaborationProfile,
    DecisionRelevance,
    InteractionMode,
    ResearchAct,
    ResearchNode,
    ResearchGraphPatch,
    BeliefRevision,
    TurnPlan,
)
from stem_sci.documents import DocumentService
from stem_sci.orchestration import ControlPlane, SQLiteControlPlaneRepository
from stem_sci.orchestration import ControlState, GateRecord


def test_evidence_gate_interprets_negated_transition_as_revision() -> None:
    assert api._conversation_gate_decision(
        "evidence_sufficiency_review",
        "当前结果不足以进入研究设计。请先筛除无关候选，不要进入研究设计。",
    ) == "revise"
    assert api._conversation_gate_decision(
        "evidence_sufficiency_review", "当前证据足够，请进入研究设计。"
    ) == "approve"
    assert api._conversation_gate_decision(
        "preregistration_freeze_approval", "先不要冻结，我还要修改变量定义。"
    ) == "revise"
    assert api._conversation_gate_decision(
        "manual_execution_approval_approval", "我不确认执行分析。"
    ) == "revise"


def test_explanation_turns_are_not_transition_commands() -> None:
    assert api._conversation_requests_explanation("为什么这篇论文不合格？")
    assert api._conversation_requests_explanation("请解释证据缺口")
    assert not api._conversation_requests_explanation("继续补充近五年实证研究")


def test_external_academic_request_uses_retrieval_path(tmp_path: Path, monkeypatch) -> None:
    """The Chinese phrase used by the UI must not fall into plain discussion."""

    monkeypatch.setattr(api, "storage_root", tmp_path / "storage")
    monkeypatch.setattr(api, "service", ContextService(tmp_path / "context"))
    monkeypatch.setattr(api, "identity_service", IdentityService(tmp_path / "identity.db"))
    monkeypatch.setattr(
        api,
        "control_plane",
        ControlPlane(SQLiteControlPlaneRepository(tmp_path / "control.db")),
    )

    class SearchAnswer:
        answer = "外部学术索引返回 1 条候选论文。"
        citations = []

        def model_dump(self, *, mode: str) -> dict[str, object]:
            return {"answer": self.answer, "citations": []}

    monkeypatch.setattr(api.qa_service, "answer", lambda request: SearchAnswer())
    monkeypatch.setattr(
        api.qa_service,
        "converse",
        lambda request: (_ for _ in ()).throw(AssertionError("external request used plain conversation")),
    )
    client = TestClient(api.app)
    registration = client.post(
        "/api/v1/auth/register",
        json={"username": "external-routing", "email": "external-routing@example.test", "password": "research-pass-123"},
    )
    headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}
    assert client.post(
        "/api/v1/projects",
        headers=headers,
        json={"project_id": "external-routing-project", "title": "外部检索", "research_direction": "本科物理教育"},
    ).status_code == 200

    response = client.post(
        "/api/v1/projects/external-routing-project/collaboration/turn",
        headers=headers,
        json={
            "project_id": "external-routing-project",
            "message": "请进行外部学术检索，找真实论文。",
            "interaction_mode": "discussion",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["message"] == SearchAnswer.answer


def test_auto_gate_router_accepts_clear_confirmations_but_not_questions() -> None:
    assert api._conversation_message_targets_gate(
        "dataset_freeze_hash_approval", "确认数据处理方案，继续。"
    )
    assert api._conversation_message_targets_gate(
        "manual_execution_approval_approval", "确认执行分析。"
    )
    assert not api._conversation_message_targets_gate(
        "dataset_freeze_hash_approval", "请解释数据风险？"
    )


def test_auto_mode_keeps_deliberation_as_discussion() -> None:
    state = ControlState(project_id="deliberation")
    assert not api._auto_requests_workflow(
        "我想比较这套论文和公开资料适合回答什么问题，请先讨论研究边界。",
        state,
    )
    assert not api._auto_requests_workflow(
        "我觉得这个研究方案的样本和结论范围还需要再想一想。",
        state,
    )
    assert api._auto_requests_workflow("直接检索近五年的物理教育实证研究。", state)


def test_information_request_about_upload_is_not_workflow_consent() -> None:
    message = "现有论文资料先作为研究背景。请告诉我下一步需要上传哪些数据、字段分别代表什么，以及数据上传后如何审查。暂时不要执行统计分析。"
    assert api._conversation_prefers_discussion(message)
    assert not api._auto_requests_workflow(message, ControlState(project_id="upload-question"))


def test_conversational_constraints_and_capabilities_are_extracted() -> None:
    message = "Check undergraduate sample missingness; descriptive only, no causal claims, preserve provenance."
    assert api._extract_research_constraints(message) == {
        "interpretation": "descriptive_only",
        "causal_claims": "forbidden",
        "population_priority": "undergraduate_students",
        "provenance": "required",
    }
    assert api._requested_research_capabilities(message) == ["data_analysis", "review"]


def test_conversational_feedback_merges_prior_constraints_and_capabilities() -> None:
    existing = {
        "research_constraints": '{"causal_claims":"forbidden","provenance":"required"}',
        "requested_capabilities": '["evidence"]',
    }
    merged = api._merge_conversational_feedback(
        existing,
        {"population_priority": "undergraduate_students"},
        ["data_analysis", "evidence"],
        "优先大学生样本，并检查缺失值",
    )
    assert json.loads(merged["research_constraints"]) == {
        "causal_claims": "forbidden",
        "provenance": "required",
        "population_priority": "undergraduate_students",
    }
    assert json.loads(merged["requested_capabilities"]) == ["evidence", "data_analysis"]
    history = json.loads(merged["research_constraint_history"])
    assert history[-1]["message"] == "优先大学生样本，并检查缺失值"


def test_new_project_material_understanding_stays_in_discussion() -> None:
    state = ControlState(project_id="new-task")
    assert not api._auto_requests_workflow(
        "\u6211\u60f3\u57fa\u4e8e\u5df2\u4e0a\u4f20\u8bba\u6587\u548c\u516c\u5f00\u6570\u636e\u505a\u4e00\u6b21\u7269\u7406\u6559\u80b2\u518d\u5206\u6790\uff0c\u5148\u5e2e\u6211\u7406\u89e3\u8d44\u6599\u548c\u7814\u7a76\u8fb9\u754c\u3002",
        state,
    )
    assert not api._auto_requests_workflow(
        "我想基于已有论文和公开数据，研究本科生物理概念理解与学习体验之间的关系。"
        "先帮我看看现有资料、可能的研究问题和证据缺口，不要急着开始正式分析。",
        state,
    )
    assert not api._auto_requests_workflow("请先逐步澄清研究设计，再讨论数据分析", state)


def test_checkpoint_and_gate_accept_natural_english_commands() -> None:
    state = ControlState(project_id="natural-english")
    assert api._checkpoint_response_is_action(
        "RESULT_INTERPRETATION_REVIEW",
        "confirm execution of the analysis and continue to writing",
    )
    assert api._checkpoint_response_is_action(
        "MANUSCRIPT_OUTLINE_REVIEW",
        "confirm the manuscript outline and generate the full text",
    )
    assert api._auto_requests_workflow("confirm the manuscript outline", state)


def test_flexible_memory_and_scope_revision_helpers() -> None:
    answers = api._extract_labelled_intake_answers(
        "研究目标：比较两组；研究对象：本科生；数据来源：去标识化问卷；研究方法：观察性比较"
    )
    assert answers == {
        "research_goal": "比较两组",
        "research_focus": "本科生",
        "data_source": "去标识化问卷",
        "method_boundary": "观察性比较",
    }
    assert api._scope_revision("研究范围改为：高中物理教师的在线专业学习") == "高中物理教师的在线专业学习"


def test_checkpoint_requires_an_explicit_choice_or_edit() -> None:
    assert api._checkpoint_response_is_action("RESEARCH_QUESTION_REVIEW", "我倾向第一个研究问题")
    assert api._checkpoint_response_is_action("RESEARCH_DESIGN_REVIEW", "请把样本范围调整为一年级学生")
    assert not api._checkpoint_response_is_action("RESEARCH_QUESTION_REVIEW", "这些想法很有意思")
    assert not api._checkpoint_response_is_action("RESEARCH_DESIGN_REVIEW", "我还需要想一想")


def test_manuscript_section_requests_are_bounded_and_ordered() -> None:
    assert api._manuscript_section_request("请先写数据与方法") == "methods"
    assert api._manuscript_section_request("请只依据冻结结果卡写‘结果’") == "results"
    assert api._manuscript_section_request("现在写引言和理论背景") == "introduction"
    assert api._manuscript_section_request("请根据本研究结果写讨论和局限") == "discussion"
    assert api._manuscript_section_request("合并为完整候选论文") == "full"
    assert api._checkpoint_response_is_action(
        api.MANUSCRIPT_SECTION_CHECKPOINT, "请先写数据与方法"
    )
    assert not api._checkpoint_response_is_action(
        api.MANUSCRIPT_SECTION_CHECKPOINT, "我还想先看看大纲"
    )


def test_discussion_mode_does_not_create_or_advance_a_workflow(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(api, "storage_root", tmp_path / "storage")
    monkeypatch.setattr(api, "service", ContextService(tmp_path / "context"))
    monkeypatch.setattr(api, "identity_service", IdentityService(tmp_path / "identity.db"))
    control = ControlPlane(SQLiteControlPlaneRepository(tmp_path / "control.db"))
    monkeypatch.setattr(api, "control_plane", control)

    class DiscussionAnswer:
        answer = "可以先比较两个研究问题的可行性，再决定是否启动检索。"
        conversation_id = "discussion-1"

        def model_dump(self, *, mode: str) -> dict[str, object]:
            return {
                "project_id": "discussion-project",
                "conversation_id": self.conversation_id,
                "mode": "discovery",
                "question": "如何比较这两个研究问题？",
                "rewritten_query": "比较两个研究问题",
                "route": {"route": "direct_answer", "reason": "discussion"},
                "answer": self.answer,
                "citations": [],
                "retrieval_status": "EMPTY",
                "retrieval_trace_ref": None,
                "context_bundle_ref": None,
                "memory_ref": "memory-1",
                "risk_flags": [],
                "answer_mode": "fallback",
                "confidence": 0.5,
                "needs_follow_up": False,
                "follow_up_question": None,
                "tool_calls": [],
                "workflow_action": None,
            }

    monkeypatch.setattr(api.qa_service, "converse", lambda request: DiscussionAnswer())
    client = TestClient(api.app)
    registered = client.post(
        "/api/v1/auth/register",
        json={"username": "discussion", "email": "discussion@example.test", "password": "research-pass-123"},
    )
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
    assert client.post(
        "/api/v1/projects",
        headers=headers,
        json={"project_id": "discussion-project", "title": "Discussion", "research_direction": "物理教学"},
    ).status_code == 200

    response = client.post(
        "/api/v1/projects/discussion-project/conversation/command",
        headers=headers,
        json={
            "project_id": "discussion-project",
            "message": "如何比较这两个研究问题？",
            "interaction_mode": "discussion",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["message"].startswith("可以先比较")
    assert body["waiting_for_user"] is True
    assert body["route_decision"] is None
    assert body["gate"] is None
    assert body["checkpoint"] is None
    state = control.ensure_project("discussion-project")
    assert state.route_decision is None
    assert state.state_revision == 1


def test_open_discussion_exits_an_accidental_active_intake(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(api, "storage_root", tmp_path / "storage")
    monkeypatch.setattr(api, "service", ContextService(tmp_path / "context"))
    monkeypatch.setattr(api, "identity_service", IdentityService(tmp_path / "identity.db"))
    control = ControlPlane(SQLiteControlPlaneRepository(tmp_path / "control.db"))
    monkeypatch.setattr(api, "control_plane", control)

    class DiscussionAnswer:
        answer = "我先比较现有资料、研究问题和证据缺口，不启动正式分析。"
        conversation_id = "discussion-exit-intake"

        def model_dump(self, *, mode: str) -> dict[str, object]:
            return {
                "project_id": "exit-intake", "conversation_id": self.conversation_id,
                "mode": "discovery", "question": "先看看资料", "rewritten_query": "资料概览",
                "route": {"route": "direct_answer", "reason": "discussion"}, "answer": self.answer,
                "citations": [], "retrieval_status": "EMPTY", "retrieval_trace_ref": None,
                "context_bundle_ref": None, "memory_ref": "memory-exit", "risk_flags": [],
                "answer_mode": "fallback", "confidence": 0.5, "needs_follow_up": False,
                "follow_up_question": None, "tool_calls": [], "workflow_action": None,
            }

    monkeypatch.setattr(api.qa_service, "answer", lambda request: DiscussionAnswer())
    client = TestClient(api.app)
    registered = client.post(
        "/api/v1/auth/register",
        json={"username": "exit-intake", "email": "exit-intake@example.test", "password": "research-pass-123"},
    )
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
    assert client.post(
        "/api/v1/projects", headers=headers,
        json={"project_id": "exit-intake", "title": "Exit intake", "research_direction": "本科物理教育"},
    ).status_code == 200
    user = api.identity_service.user_for_access_token(registered.json()["access_token"])
    api.identity_service.start_research_intake(
        user,
        "exit-intake",
        research_topic="本科物理教育",
        first_question_key="research_goal",
    )

    response = client.post(
        "/api/v1/projects/exit-intake/conversation/command", headers=headers,
        json={
            "project_id": "exit-intake",
            "message": "先帮我看看现有资料和证据缺口，不要急着开始正式分析。",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["kind"] == "qa"
    assert api.identity_service.get_research_intake(user, "exit-intake").status == "DEFERRED"
    memory = api.identity_service.get_research_memory(user, "exit-intake")
    assert memory is not None
    assert memory.facts["research_topic"] == "本科物理教育"


def test_dialogue_turn_exposes_a_human_question_and_canvas_focus() -> None:
    state = ControlState(project_id="dialogue-contract")
    gate = GateRecord(
        project_id="dialogue-contract",
        workstream_id="main",
        gate_type="evidence_sufficiency_review",
        level="G2",
        reason="Evidence package is ready for review.",
    )
    result = api.ConversationCommandResult(
        message="Evidence review completed.",
        control_state=state,
        route_decision=None,
        gate=gate,
    )

    assert result.dialogue is not None
    assert result.dialogue.mode == "evidence"
    assert result.dialogue.canvas_focus == "evidence"
    assert result.dialogue.question
    # Evidence review is conversational; the durable gate must not surface a
    # fixed three-button workflow to the researcher.
    assert result.dialogue.suggestions == []


def test_discussion_dialogue_is_grounded_in_the_planner_decision() -> None:
    decision = api.CollaborationDecision(
        profile=CollaborationProfile(),
        plan=TurnPlan(
            current_mode=InteractionMode.CO_THINK,
            research_acts=[ResearchAct.EVIDENCE_SEEK],
            decision_relevance=DecisionRelevance(
                focal_unknown="现有证据是否覆盖本科生样本",
                owner="system_retrieval",
                route_impact="medium",
                can_proceed_provisionally=True,
                rationale="可以通过有界检索回答。",
            ),
            provisional_assumptions=["暂按描述性关联处理"],
            question_to_user=None,
        ),
        graph_version=2,
        graph_patch=ResearchGraphPatch(base_version=1, new_version=2),
    )
    summary, question, choices = api._collaboration_dialogue(decision)
    assert "现有证据是否覆盖本科生样本" in summary
    assert "暂按描述性关联处理" in summary
    assert question is None
    assert any(choice.id == "evidence_gap" for choice in choices)
    assert all("下一步" not in choice.label for choice in choices)


def test_wait_turn_does_not_force_a_question_or_route_cards() -> None:
    decision = api.CollaborationDecision(
        profile=CollaborationProfile(),
        plan=TurnPlan(
            current_mode=InteractionMode.CO_THINK,
            research_acts=[ResearchAct.REFLECT],
            decision_relevance=DecisionRelevance(owner="defer", rationale="当前没有新的分叉。"),
            turn_role="wait",
            why_now="没有新的证据或冲突。",
        ),
        graph_version=3,
        graph_patch=ResearchGraphPatch(base_version=2, new_version=3),
    )

    summary, question, choices = api._collaboration_dialogue(decision)
    assert "没有发现" in summary
    assert question is None
    assert choices == []


def test_evidence_search_alone_does_not_create_fake_branches() -> None:
    decision = api.CollaborationDecision(
        profile=CollaborationProfile(),
        plan=TurnPlan(
            current_mode=InteractionMode.CO_THINK,
            research_acts=[ResearchAct.EVIDENCE_SEEK],
            decision_relevance=DecisionRelevance(
                focal_unknown="现有证据覆盖情况",
                owner="system_retrieval",
                rationale="系统可检索。",
            ),
            turn_role="ask_novel",
        ),
        graph_version=2,
        graph_patch=ResearchGraphPatch(base_version=1, new_version=2),
    )

    assert api._collaboration_branches(decision) == []


def test_dialogue_branches_expose_tradeoffs_without_faking_a_decision() -> None:
    decision = api.CollaborationDecision(
        profile=CollaborationProfile(),
        plan=TurnPlan(
            current_mode=InteractionMode.DECIDE,
            research_acts=[ResearchAct.COMPARE],
            decision_relevance=DecisionRelevance(
                focal_unknown="是否先补充反例证据",
                owner="user",
                route_impact="high",
                can_proceed_provisionally=False,
                rationale="不同选择会改变研究问题的边界。",
            ),
            question_to_user="是否先补充反例证据？",
        ),
        graph_version=1,
        graph_patch=ResearchGraphPatch(base_version=0, new_version=1),
    )
    branches = api._collaboration_branches(decision)
    assert len(branches) == 2
    assert {branch.id for branch in branches} == {"clarify_first", "bounded_assumption"}
    assert all(branch.benefits and branch.risks and branch.prerequisites for branch in branches)
    assert all("我选择" in branch.message for branch in branches)


def test_compare_turn_with_context_unknown_still_exposes_research_routes() -> None:
    decision = api.CollaborationDecision(
        profile=CollaborationProfile(),
        plan=TurnPlan(
            current_mode=InteractionMode.CO_THINK,
            research_acts=[ResearchAct.COMPARE],
            decision_relevance=DecisionRelevance(
                focal_unknown="公开文本的样本边界",
                owner="context",
                route_impact="medium",
                can_proceed_provisionally=True,
                rationale="两条路线都会改变后续研究设计。",
            ),
            provisional_assumptions=["暂按当前项目材料推进"],
        ),
        graph_version=2,
        graph_patch=ResearchGraphPatch(base_version=1, new_version=2),
    )

    branches = api._collaboration_branches(decision)
    assert {branch.id for branch in branches} == {"evidence_first", "provisional_design"}


def test_dialogue_version_change_reports_map_diff_and_implications() -> None:
    node = ResearchNode(
        node_id="question-1",
        node_type="question",
        content="本科生样本中的概念理解差异",
        status="tentative",
        source_type="user",
    )
    revision = BeliefRevision(
        node_id="design-1",
        previous_status="tentative",
        new_status="disputed",
        trigger_type="user",
        reason="研究者选择了更保守的解释边界。",
        research_consequences=["不能把组间差异解释为因果效果"],
    )
    decision = api.CollaborationDecision(
        profile=CollaborationProfile(),
        plan=TurnPlan(
            current_mode=InteractionMode.CO_THINK,
            research_acts=[ResearchAct.REFLECT],
            decision_relevance=DecisionRelevance(
                owner="defer", rationale="当前可以暂定。"
            ),
        ),
        graph_version=3,
        graph_patch=ResearchGraphPatch(
            base_version=2,
            new_version=3,
            upserted_nodes=[node],
            revisions=[revision],
        ),
    )
    change = api._dialogue_version_change(decision)
    assert change is not None
    assert (change.from_version, change.to_version) == (2, 3)
    assert "本科生样本" in change.added[0]
    assert "tentative → disputed" in change.changed[0]
    assert "不能把组间差异解释为因果效果" in change.implications


def test_conversation_pauses_only_at_meaningful_checkpoints(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(api, "storage_root", tmp_path / "storage")
    monkeypatch.setattr(api, "service", ContextService(tmp_path / "context"))
    monkeypatch.setattr(api, "identity_service", IdentityService(tmp_path / "identity.db"))
    monkeypatch.setattr(api, "document_service", DocumentService(tmp_path / "documents.db", tmp_path / "documents"))
    control = ControlPlane(SQLiteControlPlaneRepository(tmp_path / "control.db"))
    monkeypatch.setattr(api, "control_plane", control)
    monkeypatch.setattr(api, "artifact_content_store", SQLiteArtifactContentStore(tmp_path / "control.db"))

    client = TestClient(api.app)
    registered = client.post(
        "/api/v1/auth/register",
        json={"username": "gate-policy", "email": "gate-policy@example.test", "password": "research-pass-123"},
    )
    assert registered.status_code == 200
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
    assert client.post(
        "/api/v1/projects",
        headers=headers,
        json={"project_id": "gate-policy", "title": "Gate policy", "research_direction": "本科物理课程中 Python 计算建模对学生计算思维的影响，采用前测后测对照比较"},
    ).status_code == 200

    topic = client.post(
        "/api/v1/projects/gate-policy/conversation/command",
        headers=headers,
        json={
            "project_id": "gate-policy",
            "message": "直接检索：本科物理课程中 Python 计算建模对学生计算思维的影响，采用前测后测对照比较",
            "interaction_mode": "workflow",
        },
    )
    assert topic.status_code == 200
    first_gate = topic.json().get("gate")
    assert first_gate is None
    assert topic.json().get("checkpoint") == "RESEARCH_QUESTION_REVIEW"
    dialogue = topic.json().get("dialogue")
    assert dialogue is not None
    assert dialogue["mode"] == "question"
    assert dialogue["canvas_focus"] == "question"
    assert dialogue["question"]
    assert "判断文献是否足够" not in topic.json()["message"]
    assert "请批准" not in topic.json()["message"]

    # Evidence sufficiency is no longer a user approval. The first reversible
    # deliberation is selecting or revising the generated research question.
    decision = client.post(
        "/api/v1/projects/gate-policy/conversation/command",
        headers=headers,
        json={"project_id": "gate-policy", "message": "我倾向第一个研究问题，因为它更符合课程数据。"},
    )
    assert decision.status_code == 200
    assert decision.json()["kind"] == "orchestration"
    # The selected question advances to the next reversible design
    # deliberation rather than an evidence-approval Gate.
    assert decision.json().get("gate") is None
    assert decision.json().get("checkpoint") == "RESEARCH_DESIGN_REVIEW"
    assert decision.json()["dialogue"]["mode"] == "design"
    assert decision.json()["dialogue"]["canvas_focus"] == "design"
