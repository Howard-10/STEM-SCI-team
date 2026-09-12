"""Regression coverage for the ordinary chat entry point."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

import stem_sci.api as api
from tools.cgt_blind_acceptance import MESSAGES


def test_command_request_defaults_to_discussion() -> None:
    request = api.ConversationCommandRequest(
        project_id="project-1",
        message="Can you explain the data analysis options?",
    )

    assert request.interaction_mode == "discussion"


def test_clear_start_and_retrieval_command_enters_workflow() -> None:
    state = SimpleNamespace(route_decision=None)

    assert api._auto_requests_workflow(
        "\u73b0\u5728\u5f00\u59cb\u5efa\u7acb\u7814\u7a76\u4efb\u52a1\uff1a\u8bf7\u68c0\u7d22\u5e76\u6574\u7406\u76f8\u5173\u6587\u732e\u3002",
        state,
    )


def test_declined_retrieval_remains_discussion() -> None:
    state = SimpleNamespace(route_decision=None)

    assert not api._auto_requests_workflow(
        "\u6211\u4e0d\u60f3\u5f00\u59cb\u68c0\u7d22\uff0c\u5148\u53ea\u8ba8\u8bba\u7814\u7a76\u8fb9\u754c\u3002",
        state,
    )


def test_background_recovery_does_not_race_a_newly_queued_task() -> None:
    assert not api._background_task_is_ready_for_recovery(
        SimpleNamespace(created_at=datetime.now(UTC))
    )
    assert api._background_task_is_ready_for_recovery(
        SimpleNamespace(created_at=datetime.now(UTC) - timedelta(seconds=6))
    )


def test_legacy_project_chat_uses_conversation_not_retrieval(monkeypatch) -> None:
    calls: list[str] = []

    class Answer:
        def model_dump(self, *, mode: str) -> dict[str, object]:
            return {}

    monkeypatch.setattr(api.identity_service, "get_project", lambda user, project_id: object())
    monkeypatch.setattr(api.qa_service, "converse", lambda request: calls.append("converse") or Answer())
    monkeypatch.setattr(api.qa_service, "answer", lambda request: calls.append("answer") or Answer())

    # The route dependencies are exercised independently elsewhere.  This
    # unit test locks the service selection made by the endpoint itself.
    result = api.project_chat_answer(
        "project-1",
        api.QAAnswerRequest(project_id="project-1", question="What is a CSV?"),
        object(),
    )

    assert isinstance(result, Answer)
    assert calls == ["converse"]


def test_cgt_guided_response_is_short_and_asks_one_question() -> None:
    collaboration = SimpleNamespace(
        plan=SimpleNamespace(guided_question_key="research_focus")
    )

    response = api._cgt_guided_response(
        "我想知道学生怎样组织物理解题思路，不关心得分。",
        collaboration,
    )

    assert response is not None
    assert response.count("？") == 1
    assert "真正" not in response
    assert "简谐振动" not in response


def test_layered_ai_guided_response_does_not_use_cgt_intake_copy() -> None:
    collaboration = SimpleNamespace(
        plan=SimpleNamespace(guided_question_key="research_goal")
    )
    context = (
        "项目名称：分层 AI 支架与无 AI 独立迁移案例\n"
        "研究方向：大一物理师范生 Python 物理建模中的分层生成式 AI 支架"
    )

    response = api._layered_ai_guided_response(collaboration, context)

    assert response is not None
    assert "撤除 AI" in response
    assert "学生文本" not in response
    assert api._cgt_guided_response("学生物理题", collaboration, context) is None


def test_layered_guided_envelope_keeps_question_and_collaboration(monkeypatch) -> None:
    """The domain fallback must expose the same next question as the graph."""

    collaboration = SimpleNamespace(
        plan=SimpleNamespace(
            guided_question_key="research_focus",
            question_to_user="对象和情境分别是什么？",
        ),
        model_dump=lambda mode: {
            "plan": {
                "guided_question_key": "research_focus",
                "question_to_user": "对象和情境分别是什么？",
            }
        },
    )
    state = SimpleNamespace(route_decision=None, model_dump=lambda mode: {})
    request = api.ConversationCommandRequest(
        project_id="project-1",
        message="我想研究撤除 AI 后的独立迁移。",
    )
    monkeypatch.setattr(
        api,
        "_cgt_analysis_instruction_response",
        lambda project_id, message: None,
    )
    monkeypatch.setattr(
        api,
        "_layered_ai_guided_response",
        lambda decision, context: "研究重点已经收窄到撤除 AI 后的独立迁移。",
    )

    result = api._discussion_response(
        project_id="project-1",
        request=request,
        state=state,
        project_context="项目名称：分层 AI 支架\n研究方向：物理建模中的支架渐隐",
        collaboration=collaboration,
    )

    assert result["waiting_for_user"] is True
    assert result["dialogue"]["question"] == collaboration.plan.question_to_user
    assert result["dialogue"]["turn_role"] == "ask_novel"
    assert result["collaboration"]["plan"]["guided_question_key"] == "research_focus"


def test_layered_reviewer_request_with_result_card_stays_in_discussion() -> None:
    """A read-only Reviewer request must not be rerouted as result-card execution."""

    message = "请让与写作角色隔离的 Reviewer 只读冻结稿、结果卡和证据表，列出 P0/P1/P2 问题。"
    context = (
        "项目名称：分层 AI 支架与无 AI 独立迁移案例\n"
        "研究方向：大一物理师范生 Python 物理建模中的分层生成式 AI 支架"
    )

    assert api._layered_ai_topic_response(message, context) is not None
    assert api._layered_ai_topic_question(message) == "当前是否已有冻结稿、结果卡和证据表可供 Reviewer 只读核验？"


def test_layered_quality_guard_restores_non_negotiable_boundaries() -> None:
    context = "项目名称：分层 AI 支架与无 AI 独立迁移案例\n研究方向：Python 物理建模中的支架渐隐"

    guarded = api._layered_ai_quality_guard(
        "请推荐 RQ2 的 estimand、固定效应和聚类层级。",
        "RQ2 的 estimand 是 Week 8 的调整差异。",
        context,
    )
    assert "CR2/Satterthwaite" in guarded
    assert "团队" in guarded

    process = api._layered_ai_quality_guard(
        "请解释 AI 日志指标能否称为学习机制。",
        "验证比例与迁移分数有关。",
        context,
    )
    assert "探索性关联" in process


def test_cgt_supervised_run_does_not_invent_performance(monkeypatch) -> None:
    monkeypatch.setattr(
        api,
        "_latest_artifact_body",
        lambda project_id, artifact_type: {
            "execution": {"performed": False, "reason": "人工标签尚未冻结"}
        }
        if artifact_type == "SupervisedConfirmationCandidate"
        else None,
    )

    response = api._cgt_analysis_instruction_response(
        "project-1",
        "批准执行模式确认。任何准确率都必须来自实际交叉验证输出。",
    )

    assert response is not None
    assert "未执行" in response
    assert "B=1000" not in response
    assert "真正的研究目的" not in response


def test_cgt_method_boundary_is_not_mistaken_for_code_generation() -> None:
    response = api._cgt_analysis_instruction_response(
        "project-1",
        "我想采用三阶段的人机协作流程，第三阶段再用监督模型和交叉验证。现在请判断这个路线是否适合。",
    )

    assert response is not None
    assert response.startswith("我建议采用")
    assert "accuracy" not in response


def test_cgt_group_field_definition_is_not_a_comparison_request() -> None:
    response = api._cgt_analysis_instruction_response(
        "project-1",
        "Control_group=0 表示物理奥赛参与者，Gender=0 表示男性。分组非随机，只能做描述性或关联性比较，不能写因果结论。",
    )

    assert response is not None
    assert response.startswith("已记录字段含义")
    assert "均标记为未执行" not in response


def test_manuscript_outline_request_is_distinct_from_result_card_confirmation() -> None:
    message = "我确认冻结结果卡。现在只生成论文结构和每节必须回答的问题。"

    assert api._conversation_requests_result_card(message.lower())
    assert api._manuscript_outline_request(message)


def test_cgt_group_comparison_does_not_invent_bootstrap_count(monkeypatch) -> None:
    monkeypatch.setattr(
        api,
        "_latest_artifact_body",
        lambda project_id, artifact_type: {
            "execution": {"performed": False, "reason": "人工标签尚未冻结"}
        }
        if artifact_type == "GroupComparisonCandidate"
        else None,
    )

    response = api._cgt_analysis_instruction_response(
        "project-1",
        "请比较奥赛参与者与非参与者的主题构成，并做按学生聚类的 bootstrap。",
    )

    assert response is not None
    assert "均标记为未执行" in response
    assert "不会自行补设重抽样次数" in response
    assert "1000" not in response


def test_execution_approval_request_is_not_execution_approval() -> None:
    message = "请先给审查结论和修改 diff，再请求执行批准。"

    assert api._conversation_gate_decision(
        "manual_execution_approval_approval", message.lower()
    ) is None
    assert api._conversation_gate_decision(
        "manual_execution_approval_approval",
        "批准只执行数据审计和预处理。",
    ) == "approve"
    assert api._conversation_gate_decision(
        "manual_execution_approval_approval",
        "批准只执行数据审计和预处理，不要下载模型、不要做嵌入和聚类。",
    ) == "approve"


def test_cgt_code_and_execution_checkpoints_do_not_collapse() -> None:
    assert not api._checkpoint_response_is_action(
        "ANALYSIS_CODE_REVIEW",
        "现在只生成分析代码规格，不写论文。",
    )
    assert api._checkpoint_response_is_action(
        "ANALYSIS_CODE_REVIEW",
        "请先生成第一个可运行代码候选，只完成数据审计和预处理。",
    )
    assert api._checkpoint_response_is_action(
        "CODE_REVIEW_REVIEW",
        "在执行前审查这段代码，请先给审查结论和修改 diff，再请求执行批准。",
    )
    assert not api._checkpoint_response_is_action(
        "PATTERN_CODE_REVIEW",
        "请生成模式发现代码，使用 UMAP 与 HDBSCAN。",
    )
    assert api._checkpoint_response_is_action(
        "PATTERN_CODE_REVIEW",
        "先批准 20 个随机种子的烟雾测试。",
    )
    assert api._checkpoint_response_is_action(
        "PATTERN_STABILITY_REVIEW",
        "请生成可供研究判断的模式审阅包，并展示代表证据和边界证据。",
    )
    assert api._checkpoint_response_is_action(
        "MANUSCRIPT_OUTLINE_REVIEW",
        "请写“数据与方法”，并先概括样本流转和分析单位。",
    )


@pytest.mark.parametrize(
    ("round_number", "checkpoint", "expected"),
    [
        (16, "ANALYSIS_CODE_REVIEW", False),
        (17, "ANALYSIS_CODE_REVIEW", True),
        (18, "CODE_REVIEW_REVIEW", True),
        (19, "CODE_REVIEW_REVIEW", True),
        (20, "PREPROCESSING_REVIEW", True),
        (21, "PATTERN_CODE_REVIEW", False),
        (22, "PATTERN_CODE_REVIEW", True),
        (23, "PATTERN_SMOKE_REVIEW", True),
        (24, "PATTERN_STABILITY_REVIEW", True),
        (25, "PATTERN_DISCOVERY_REVIEW", True),
        (26, "CODEBOOK_REVIEW", True),
        (27, "MANUAL_THEME_REVISION_REVIEW", True),
        (28, "SUPERVISED_CONFIRMATION_REVIEW", True),
        (29, "STUDENT_LEVEL_ROBUSTNESS_REVIEW", True),
        (30, "GROUP_COMPARISON_REVIEW", True),
        (31, "GROUP_COMPARISON_REVIEW", True),
        (31, "RESULT_CARD_REVIEW", True),
        (32, "RESULT_CARD_REVIEW", True),
        (33, "MANUSCRIPT_OUTLINE_REVIEW", True),
        (34, api.MANUSCRIPT_SECTION_CHECKPOINT, True),
        (35, api.MANUSCRIPT_SECTION_CHECKPOINT, True),
        (36, api.MANUSCRIPT_SECTION_CHECKPOINT, True),
        (37, api.MANUSCRIPT_SECTION_CHECKPOINT, True),
    ],
)
def test_current_blind_guide_messages_route_at_the_expected_checkpoint(
    round_number: int, checkpoint: str, expected: bool
) -> None:
    assert len(MESSAGES) == 39
    message = MESSAGES[round_number - 1][1].lower()

    assert api._checkpoint_response_is_action(checkpoint, message) is expected


def test_current_blind_guide_final_gate_messages_are_unambiguous() -> None:
    round_38 = MESSAGES[37][1].lower()
    round_39 = MESSAGES[38][1].lower()

    assert api._conversation_gate_decision(
        "manuscript_citation_verification_approval", round_38
    ) == "approve"
    assert api._conversation_gate_decision(
        "reviewer_final_confirmation_approval", round_39
    ) == "approve"


def test_current_blind_script_messages_match_the_guide_verbatim() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    guide = (
        repository_root
        / "docs"
        / "reports"
        / "CGT_BLIND_FULL_WORKFLOW_TEST_GUIDE_2026-09-10.md"
    ).read_text(encoding="utf-8")

    assert all(message in guide for _, message in MESSAGES)


def test_qualitative_preprocessing_executes_without_pattern_discovery(monkeypatch) -> None:
    monkeypatch.setattr(
        api,
        "_latest_project_reference_csv",
        lambda project_id, marker: [
            {"Stu_ID": "1"},
            {"Stu_ID": "2"},
        ],
    )
    candidate = api._qualitative_preprocessing_candidate(
        "project-1",
        {
            "segments": [
                {"segment_id": "segment-1", "participant_label": "stu_1", "text": "Zuerst wird die Energie berechnet. Dann gilt v^2=2gh."},
                {"segment_id": "segment-2", "participant_label": "stu_2", "text": "nan"},
                {"segment_id": "segment-3", "participant_label": "stu_3", "text": "This row is outside the joined sample."},
            ]
        },
    )

    execution = candidate["execution"]
    assert execution["performed"] is True
    assert execution["student_count"] == 2
    assert execution["embeddings_executed"] is False
    assert execution["clustering_executed"] is False
    assert execution["theme_labels_generated"] is False
    assert any(row["formula_like"] for row in candidate["derived_sentences"])


def test_codebook_checkpoint_names_theory_led_candidates_honestly(monkeypatch) -> None:
    monkeypatch.setattr(
        api,
        "_latest_artifact_body",
        lambda project_id, artifact_type: {
            "codebook": [
                {
                    "theme_id": "theme:conceptual_aspects",
                    "source_cluster": None,
                    "working_name": "概念理解",
                    "evidence_count": 12,
                    "definition": "调用物理规律解释过程。",
                    "positive_examples": ["Die Energie bleibt erhalten."],
                },
                {
                    "theme_id": "theme:quantitative_aspects",
                    "source_cluster": None,
                    "working_name": "定量处理",
                    "evidence_count": 7,
                    "definition": "实际实施公式或代数操作。",
                    "positive_examples": ["Dann setze ich v^2=2gh ein."],
                },
            ]
        }
        if artifact_type == "CodebookCandidate"
        else None,
    )

    message = api._checkpoint_message_for_project("project-1", "CODEBOOK_REVIEW")

    assert "2 个可回链候选" in message
    assert "概念理解：12 句" in message
    assert "Die Energie bleibt erhalten" in message
    assert "易混淆：定量处理" in message
    assert "不是正式主题频数" in message


def test_dataset_freeze_candidate_recomputes_the_joined_sample(monkeypatch) -> None:
    primary = {
        "artifact_id": "raw-1",
        "source_dataset_ref": "document://text/1",
        "content_sha256": "a" * 64,
        "document_version": 1,
        "record_count": 3,
        "segments": [
            {"participant_label": "stu_1", "text": "eins"},
            {"participant_label": "stu_2", "text": "zwei"},
            {"participant_label": "stu_3", "text": "drei"},
        ],
    }
    background = [
        {"Stu_ID": "1", "Control_group": "0", "Gender": "0"},
        {"Stu_ID": "2", "Control_group": "1", "Gender": "1"},
    ]
    monkeypatch.setattr(api, "_registered_qualitative_primary_data", lambda project_id: primary)
    monkeypatch.setattr(api, "_latest_project_reference_csv", lambda project_id, marker: background)
    monkeypatch.setattr(
        api,
        "_project_dataset_missingness",
        lambda project_id: {"rows": 3, "missing_text": 0, "nonempty_text": 3},
    )
    monkeypatch.setattr(api, "_latest_artifact_body", lambda project_id, artifact_type: None)

    candidate = api._dataset_freeze_candidate("project-1")

    assert candidate["selected_student_count"] == 2
    assert candidate["selected_student_ids"] == ["1", "2"]
    assert candidate["excluded_text_student_ids"] == ["3"]
    assert candidate["sample_flow"]["final_analysis_sample"] == 2
    assert candidate["sample_flow"]["text_students_without_background"] == 1
    assert candidate["group_counts"] == {"0": 1, "1": 1}
    assert candidate["field_dictionary"]["Control_group"].startswith("0=物理奥赛参与者")


def test_blocked_pattern_checkpoints_advance_the_conversation(monkeypatch) -> None:
    artifacts = {
        "PatternSmokeExecutionCandidate": {"execution": {"performed": False}},
        "PatternStabilityExecutionCandidate": {"execution": {"performed": False}},
        "ClusterReviewPacket": {"status": "CLUSTER_REVIEW_BLOCKED_NO_EXECUTION"},
    }
    monkeypatch.setattr(api, "_latest_artifact_body", lambda project_id, artifact_type: artifacts.get(artifact_type))

    smoke = api._checkpoint_message_for_project("project-1", "PATTERN_SMOKE_REVIEW")
    stability = api._checkpoint_message_for_project("project-1", "PATTERN_STABILITY_REVIEW")
    review = api._checkpoint_message_for_project("project-1", "PATTERN_DISCOVERY_REVIEW")

    assert "切换到透明的关键词辅助候选路线" in smoke
    assert "补齐模型后可从这里直接续跑" in stability
    assert "Stu_ID、Sentence_ID" in review
    assert len({smoke, stability, review}) == 3


def test_manuscript_section_chat_contains_research_substance(monkeypatch) -> None:
    artifacts = {
        "QualitativeResultCard": {"data_audit": {"raw_text_rows": 550, "joined_students": 417}},
        "PreprocessingExecutionCandidate": {
            "execution": {"candidate_sentence_count": 1223, "retained_sentence_count_at_20": 1168}
        },
        "CodebookCandidate": {"codebook": []},
    }
    monkeypatch.setattr(api, "_latest_artifact_body", lambda project_id, artifact_type: artifacts.get(artifact_type))

    message = api._manuscript_section_chat_message("project-1", "methods", "数据与方法", "正文")

    assert "550 条文本 → 417 名成功连接学生" in message
    assert "1223 个候选句段" in message
    assert "论文大纲已经确认" not in message


def test_publication_gate_messages_show_verification_and_review_findings(monkeypatch) -> None:
    artifacts = {
        "ManuscriptCitationVerification": {
            "citation_count": 10,
            "evidence_ref_count": 10,
            "unverified_citation_refs": [],
            "primary_data_ref_verified": True,
        },
        "FinalReviewPacket": {
            "findings": [
                {
                    "severity": "P1",
                    "location": "结果",
                    "excerpt": "五类关键词命中允许重叠",
                    "issue": "主题频数尚未冻结。",
                    "source": "CodebookCandidate.codebook[*].evidence_count",
                },
                {
                    "severity": "P2",
                    "location": "引言",
                    "excerpt": "物理问题解决研究",
                    "issue": "书目信息待核验。",
                    "source": "ManuscriptCitationVerification",
                },
            ],
            "sample_boundary_check": {
                "raw_text_rows": 550,
                "joined_students": 417,
                "status": "CONSISTENT_IN_CURRENT_MANUSCRIPT",
            },
        },
    }
    monkeypatch.setattr(api, "_latest_artifact_body", lambda project_id, artifact_type: artifacts.get(artifact_type))
    citation_gate = api.GateRecord(
        project_id="project-1", workstream_id="main", gate_type="manuscript_citation_verification_approval",
        level=api.GateLevel.G2, reason="review",
    )
    review_gate = api.GateRecord(
        project_id="project-1", workstream_id="main", gate_type="reviewer_final_confirmation_approval",
        level=api.GateLevel.G3, reason="review",
    )

    citation_message = api._gate_message_for_project("project-1", citation_gate)
    review_message = api._gate_message_for_project("project-1", review_gate)

    assert "正文内部引用 10 条" in citation_message
    assert "未匹配 0 条" in citation_message
    assert "共发现 2 项" in review_message
    assert "P1｜结果" in review_message
    assert "五类关键词命中允许重叠" in review_message
    assert "CodebookCandidate.codebook" in review_message
    assert "550→417" in review_message


def test_candidate_delivery_writes_real_files_and_matching_hashes(monkeypatch, tmp_path) -> None:
    artifacts = {
        "ManuscriptDraftZh": {
            "sections": {
                "title": "候选论文",
                "methods": "样本流转为550条文本到417名学生。",
                "results": "候选主题数字允许重叠。",
            }
        },
        "QualitativeResultCard": {"data_audit": {"raw_text_rows": 550, "joined_students": 417}},
        "ManuscriptCitationVerification": {"citation_count": 10, "unverified_citation_refs": []},
        "FinalReviewPacket": {"decision": "CANDIDATE_ANALYSIS_PACKAGE_ONLY", "findings": []},
        "AnalysisCodeSpecificationCandidate": {"modules": []},
        "AnalysisCodeReviewCandidate": {"status": "reviewed"},
    }
    repository = SimpleNamespace(
        list_claims=lambda project_id: [],
        list_artifacts=lambda project_id: [],
    )
    monkeypatch.setattr(api, "storage_root", tmp_path)
    monkeypatch.setattr(api, "control_plane", SimpleNamespace(repository=repository))
    monkeypatch.setattr(api, "_latest_artifact_body", lambda project_id, artifact_type: artifacts.get(artifact_type))
    monkeypatch.setattr(
        api,
        "_unperformed_candidate_actions",
        lambda project_id: ["模式发现", "监督确认", "学生层稳健性", "组间比较"],
    )

    manifest = api._freeze_candidate_delivery("project-1")
    delivery_dir = tmp_path / "candidate-deliveries" / api.sha256_text("project-1")[:16]
    generated = list(delivery_dir.rglob("*.*"))
    manuscript_path = next(path for path in generated if path.name == "manuscript.md")

    assert len(generated) == 7
    assert Path(str(manifest["manifest_path"])).is_file()
    assert sha256(manuscript_path.read_bytes()).hexdigest() == manifest["manuscript_sha256"]
    assert manifest["package_grade"] == "CANDIDATE_ANALYSIS_PACKAGE_ONLY"
    assert len(manifest["missing_outputs"]) == 3


def test_qualitative_results_manuscript_uses_executed_coding_input(monkeypatch) -> None:
    artifacts = {
        "DatasetFreezeHashCandidate": {
            "status": "FROZEN_VERSION_CANDIDATE",
            "sample_flow": {"final_analysis_sample": 2},
        },
        "PreprocessingExecutionCandidate": {
            "status": "PREPROCESSING_EXECUTED_REQUIRES_REVIEW",
            "execution": {
                "performed": True,
                "student_count": 2,
                "candidate_sentence_count": 3,
                "retained_sentence_count_at_20": 2,
            },
            "derived_sentences": [
                {
                    "sentence_id": "stu_1_sentence_0001",
                    "participant_label": "stu_1",
                    "text": "Die Annahme ist reibungsfrei und die Masse ist punktförmig.",
                },
                {
                    "sentence_id": "stu_2_sentence_0002",
                    "participant_label": "stu_2",
                    "text": "Die Energie wird berechnet und in eine Gleichung eingesetzt.",
                },
            ],
        },
        "PatternStabilityExecutionCandidate": {"execution": {"performed": False}},
    }
    monkeypatch.setattr(
        api,
        "_latest_artifact_body",
        lambda project_id, artifact_type: artifacts.get(artifact_type),
    )
    monkeypatch.setattr(
        api,
        "_latest_project_reference_csv",
        lambda project_id, marker: [{"Stu_ID": "1"}, {"Stu_ID": "2"}],
    )
    monkeypatch.setattr(
        api,
        "_project_dataset_missingness",
        lambda project_id: {"rows": 3, "missing_text": 0, "nonempty_text": 3, "unique_ids": 3},
    )
    primary = {
        "artifact_id": "raw-1",
        "source_dataset_ref": "document://doc-1/1",
        "content_sha256": "abc",
        "document_version": 1,
        "source_kind": "public_secondary_tsv",
        "segment_count": 3,
        "record_count": 3,
        "participant_labels": ["stu_1", "stu_2", "stu_3"],
        "segments": [
            {"segment_id": "segment-1", "participant_label": "stu_1", "text": "raw one"},
            {"segment_id": "segment-2", "participant_label": "stu_2", "text": "raw two"},
            {"segment_id": "segment-3", "participant_label": "stu_3", "text": "raw three"},
        ],
    }

    draft = api._deterministic_qualitative_results_manuscript(
        "project-1", "physics problem solving", None, primary
    )
    results = draft["sections"]["results"]
    discussion = draft["sections"]["discussion"]

    assert draft["sample_flow"]["final_analysis_sample"] == 2
    assert "最终分析样本为 2 名学生" in results
    assert "20 字符基线保留 2 个" in results
    assert "来源：透明关键词辅助候选" in results
    assert "来源：中性聚类候选" not in results
    assert "句子切分及 10/20/30 字符阈值敏感性已经执行" in discussion
    assert "文本尚未完成正式句子切分敏感性分析" not in discussion
