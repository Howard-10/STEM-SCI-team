"""Regression coverage for the ordinary chat entry point."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import stem_sci.api as api


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
    assert response.startswith("这条路线适合")
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
                {"theme_id": "theme:a", "source_cluster": None},
                {"theme_id": "theme:b", "source_cluster": None},
            ]
        }
        if artifact_type == "CodebookCandidate"
        else None,
    )

    message = api._checkpoint_message_for_project("project-1", "CODEBOOK_REVIEW")

    assert "2 个理论驱动/关键词辅助" in message
    assert "没有任何一个来自已执行聚类" in message


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
