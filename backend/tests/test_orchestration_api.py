from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from stem_sci import api
from stem_sci.accounts import IdentityService
from stem_sci.artifacts.content_store import ArtifactContent, SQLiteArtifactContentStore
from stem_sci.context.models import ContextBundle, EvidenceRef, SourceLocation, VerificationStatus
from stem_sci.context.provider import LocalContextProvider
from stem_sci.context.service import ContextService
from stem_sci.documents import DocumentService
from stem_sci.orchestration import BlockingIssueRecord, ControlPlane, ExecutionStatus, SQLiteControlPlaneRepository


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_observational_ai_use_requires_an_observable_exposure_field() -> None:
    scope = "研究大学生实际使用生成式人工智能与大学物理计算思维成绩的关联"

    assert api._requires_observed_ai_usage(scope) is True
    assert api._ai_schema_alignment_warning(scope, {"experience_group", "ct_capacity_score"})
    assert api._ai_schema_alignment_warning(scope, {"primary_use", "ct_score"}) is None

    # An assigned intervention may legitimately encode exposure as a group.
    assigned_scope = "比较引入生成式人工智能教学支持的实验组与对照组物理成绩"
    assert api._requires_observed_ai_usage(assigned_scope) is False


def _complete_research_intake(client: TestClient, project_id: str, headers: dict[str, str]) -> dict:
    """Start evidence work with a complete natural-language instruction."""

    confirmed = client.post(
        f"/api/v1/projects/{project_id}/conversation/command",
        headers=headers,
        json={
            "project_id": project_id,
            "message": (
                "直接检索：关注本科物理学生、计算建模和物理概念理解；"
                "使用已上传论文和公开数据，采用观察性描述和两组比较，不作因果结论；"
                "保留来源定位、已知局限和不确定性说明。"
            ),
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()


def test_offline_qualitative_proposal_is_scope_aware_and_traceable() -> None:
    package = {
        "evidence_matrix": [
            {
                "finding": "教师需要把计算知识、物理应用和教学法联系起来。",
                "source_ref": "src_lane",
            }
        ],
        "paper_cards": [{"source_ref": "src_lane", "title": "Lane, Galanti, and Rozas (2023)"}],
        "used_evidence_refs": ["src_lane"],
    }
    draft = api._deterministic_manuscript_candidate(
        "proposal-quality",
        "高中物理教师整合计算思维与 Python 教学的专业学习需求",
        package,
    )

    sections = draft["sections"]
    assert "访谈围绕" in sections["methods"]
    assert "主动检索反例" in sections["analysis_plan"]
    assert "知情同意/伦理审查" in sections["ethics_limitations"]
    assert "[E1]" in sections["evidence_review"]
    assert draft["claim_evidence_map"]["claim:proposal-quality:scope"] == ["src_lane"]
    assert "n = 24" not in "\n".join(str(value) for value in sections.values())
    assert draft["status"] == "CANDIDATE_GROUNDED_DRAFT"

    generic = api._deterministic_manuscript_candidate(
        "generic-quality", "医护人员远程协作的工作经验", package
    )
    assert "高中物理教师" not in "\n".join(str(value) for value in generic["sections"].values())
    assert "医护人员远程协作的工作经验" in generic["sections"]["title"]


def test_canonical_scope_excludes_retrieval_commands_and_superseded_prepost_plan() -> None:
    legacy_scope = (
        "我想研究本科物理课程中的 Python 计算建模是否影响迁移成绩，计划采用前测—后测比较。\n"
        "补充检索要求：继续搜索近五年的实证研究\n"
        "研究澄清记录：改为横断面两组比较"
    )

    canonical = api._canonical_research_scope(legacy_scope)
    quantitative_context = api._quantitative_report_context(legacy_scope)

    assert "补充检索要求" not in canonical
    assert "继续搜索" not in canonical
    assert "研究澄清记录" not in canonical
    assert "Python 计算建模" in quantitative_context
    assert "前测" not in quantitative_context
    assert "后测" not in quantitative_context
    assert api._requests_prepost_design(legacy_scope) is True
    assert api._requests_prepost_design(
        legacy_scope,
        {"DATA_DESIGN_REVIEW": "按当前 CSV 改为横断面两组比较，不做前测后测分析。"},
    ) is False


def test_quantitative_manuscript_does_not_merge_unverified_llm_prose_or_critique() -> None:
    deterministic = {
        "sections": {
            "title": "Controller title",
            "results": "mean_difference=11",
            "introduction": "短的确定性引言",
        },
        "claim_ids": ["claim-result"],
        "citation_refs": ["evd-1"],
        "result_card_ref": "result-card://1",
        "quality_flags": ["FROZEN_DATASET_REFERENCED"],
    }
    llm = {
        "sections": {
            "title": "模型试图改标题",
            "results": "模型试图改数字",
            "introduction": ("这是足够长的模型引言，用于说明研究背景、现有证据和本研究的观察性边界。"
            "它不应替换系统掌握的结果数字、引用列表或主张图。" * 3),
            "discussion": "这是足够长的模型讨论，用于解释结果的可能意义、替代解释和后续研究方向。" * 5,
        },
        "claim_ids": ["invented-claim"],
        "citation_refs": ["invented-evidence"],
        "writing_critique": {
            "report_id": "writing-critique:project",
            "project_id": "project",
            "status": "NEEDS_REVISION",
            "score": 62,
            "findings": [{
                "finding_id": "finding-1",
                "severity": "WARNING",
                "code": "CAUSAL_LANGUAGE",
                "section": "discussion",
                "message": "Avoid causal wording for an observational comparison.",
                "suggested_action": "Use bounded associative language.",
                "claim_ids": [],
            }],
        },
    }

    merged = api._merge_llm_prose_into_quantitative_draft(deterministic, llm)

    assert merged["sections"]["title"] == "Controller title"
    assert merged["sections"]["results"] == "mean_difference=11"
    assert merged["sections"]["introduction"] == "短的确定性引言"
    assert "discussion" not in merged["sections"]
    assert merged["claim_ids"] == ["claim-result"]
    assert merged["citation_refs"] == ["evd-1"]
    assert "writing_critique" not in merged
    assert merged["quality_flags"] == ["FROZEN_DATASET_REFERENCED"]


def test_quantitative_manuscript_ignores_llm_critique_without_prose() -> None:
    deterministic = {
        "sections": {"results": "mean_difference=11"},
        "quality_flags": ["FROZEN_DATASET_REFERENCED"],
    }
    critique = {
        "report_id": "writing-critique:project",
        "project_id": "project",
        "status": "PASS",
        "score": 91,
        "findings": [],
    }

    merged = api._merge_llm_prose_into_quantitative_draft(
        deterministic, {"writing_critique": critique, "sections": {}}
    )

    assert "writing_critique" not in merged
    assert merged["sections"]["results"] == "mean_difference=11"
    assert "claim_ids" not in merged


def test_editable_manuscript_hides_internal_ids_but_source_artifact_keeps_them() -> None:
    body = {
        "sections": {
            "title": "可追溯论文",
            "methods": (
                "分析输入 document://doc-secret/1；SHA-256："
                + "a" * 64
                + "；证据 shared_evd_secret、src_secret，主张 claim:project:result，"
                "产物 artifact-secret。"
            ),
            "references": "[1] 可读来源名称",
        },
        "citation_refs": ["shared_evd_secret"],
        "claim_ids": ["claim:project:result"],
    }
    plan = type("Plan", (), {"user_request": "研究问题"})()

    rendered = api._candidate_manuscript_markdown(
        artifact_type="ManuscriptDraftZh",
        body=body,
        plan=plan,
    )

    assert "## 标题" in rendered
    assert "## 方法" in rendered
    assert "## 参考文献" in rendered
    assert "shared_evd_secret" not in rendered
    assert "src_secret" not in rendered
    assert "claim:project:result" not in rendered
    assert "artifact-secret" not in rendered
    assert "document://" not in rendered
    assert "a" * 64 not in rendered
    assert body["citation_refs"] == ["shared_evd_secret"]
    assert body["claim_ids"] == ["claim:project:result"]


def test_quantitative_manuscript_records_result_numbers_and_direction() -> None:
    values = {
        "analysis_sample_size": 10,
        "group_1_n": 4,
        "group_2_n": 6,
        "group_1_score_mean": 8.5,
        "group_2_score_mean": 7.25,
        "score_mean_difference_group_2_minus_group_1": -1.25,
        "score_mean_difference_ci_lower": -2.5,
        "score_mean_difference_ci_upper": 0.0,
        "cohens_d_group_2_minus_group_1": -0.2,
        "two_group_welch_p": 0.4,
    }
    pipeline = SimpleNamespace(
        model_specification=SimpleNamespace(
            outcome_variables={"score"}, grouping_variables={"group"}
        ),
        frozen_dataset=SimpleNamespace(ref="dataset://frozen-data/1"),
        statistical_result_card=SimpleNamespace(
            ref="result-card://result-card-1", values=values
        ),
    )

    draft = api._deterministic_quantitative_results_manuscript(
        "quant-audit", "两组成绩差异", None, pipeline
    )

    assert draft["numeric_literals"] == [
        "10", "4", "6", "8.5", "7.25", "-1.25", "-2.5", "0", "-0.2", "0.4"
    ]
    assert draft["result_directions"] == {"claim:quant-audit:result": "negative"}
    assert draft["result_card_ref"] == "result-card://result-card-1"


def test_evidence_review_counts_verified_nested_locations_and_blocks_unverified_only() -> None:
    verified = EvidenceRef(
        evidence_id="evd-verified",
        project_id="coverage-project",
        source_id="shared:physics_stem_v1:paper-1",
        chunk_id="chunk-1",
        excerpt="可定位的原文证据。",
        location=SourceLocation(chunk_index=0, char_start=12, char_end=24, page_start=2, page_end=2),
        verification_status=VerificationStatus.SOURCE_VERIFIED,
    )
    unverified = EvidenceRef(
        evidence_id="evd-unverified",
        project_id="coverage-project",
        source_id="src-uploaded",
        chunk_id="chunk-2",
        excerpt="尚未核验的上传片段。",
        location=SourceLocation(chunk_index=0, char_start=0, char_end=10),
        verification_status=VerificationStatus.MODEL_GENERATED_UNVERIFIED,
    )
    package = api._build_evidence_review_package(
        "coverage-project",
        "物理教育中的计算建模",
        [],
        context_bundle=ContextBundle(
            context_id="ctx-coverage",
            project_id="coverage-project",
            task_ref="coverage",
            query="计算建模",
            evidence_refs=[verified, unverified],
            source_refs=[verified.source_id, unverified.source_id],
            verification_summary={"source_verified": 1, "model_generated_unverified": 1},
            token_budget=1000,
            estimated_tokens=40,
            context_hash="coverage-context",
            generated_at="2026-09-03T00:00:00+00:00",
        ),
    )
    assert package["coverage"]["verified_source_count"] == 1
    assert package["coverage"]["formal_evidence_ready"] is True

    unverified_only = api._build_evidence_review_package(
        "coverage-project-unverified",
        "物理教育中的计算建模",
        [],
        context_bundle=ContextBundle(
            context_id="ctx-unverified",
            project_id="coverage-project-unverified",
            task_ref="coverage",
            query="计算建模",
            evidence_refs=[unverified.model_copy(update={"project_id": "coverage-project-unverified"})],
            source_refs=[unverified.source_id],
            verification_summary={"model_generated_unverified": 1},
            token_budget=1000,
            estimated_tokens=20,
            context_hash="unverified-context",
            generated_at="2026-09-03T00:00:00+00:00",
        ),
    )
    assert unverified_only["coverage"]["verified_source_count"] == 0
    assert unverified_only["coverage"]["formal_evidence_ready"] is False
    assert any("已核验来源" in item for item in unverified_only["coverage"]["missing_requirements"])


def test_runtime_separates_detected_codex_cli_from_confirmed_generation(monkeypatch) -> None:
    class DetectedCodex:
        def health_reason(self) -> None:
            return None

    monkeypatch.setenv("STEM_SCI_CODING_PROVIDER", "codex")
    monkeypatch.setenv("STEM_SCI_CODEX_REMOTE_ENABLED", "true")
    monkeypatch.delenv("STEM_SCI_CODEX_GENERATION_CONFIRMED", raising=False)
    monkeypatch.setattr(
        api.workflow_controller.data_pipeline.research_execution,
        "coding_provider",
        DetectedCodex(),
    )
    client = TestClient(api.app)

    unconfirmed = client.get("/api/v1/workflow/runtime")
    assert unconfirmed.status_code == 200
    assert unconfirmed.json()["codex_cli_detected"] is True
    assert unconfirmed.json()["codex_generation_confirmed"] is False
    assert unconfirmed.json()["codex_available"] is False
    assert unconfirmed.json()["codex_reason"] == "CODEX_CLI_DETECTED_GENERATION_UNVERIFIED"

    monkeypatch.setenv("STEM_SCI_CODEX_GENERATION_CONFIRMED", "true")
    confirmed = client.get("/api/v1/workflow/runtime")
    assert confirmed.json()["codex_available"] is True
    assert confirmed.json()["codex_reason"] is None


def test_journal_target_adds_a_reviewed_formatting_stage(tmp_path: Path, monkeypatch) -> None:
    control = ControlPlane(SQLiteControlPlaneRepository(tmp_path / "control.db"))
    monkeypatch.setattr(api, "identity_service", IdentityService(tmp_path / "identity.db"))
    monkeypatch.setattr(api, "control_plane", control)
    monkeypatch.setattr(api, "artifact_content_store", SQLiteArtifactContentStore(tmp_path / "control.db"))
    client = TestClient(api.app)

    registered = client.post(
        "/api/v1/auth/register",
        json={"username": "journaluser", "email": "journal@example.test", "password": "research-pass-123"},
    )
    headers = _auth(registered.json()["access_token"])
    assert client.post(
        "/api/v1/projects",
        headers=headers,
        json={"project_id": "journal-project", "title": "Journal flow", "research_direction": "两组干预实验与迁移成绩"},
    ).status_code == 200

    missing_type = client.put(
        "/api/v1/projects/journal-project/publication-target",
        headers=headers,
        json={"target_journal": "International Journal of STEM Education"},
    )
    assert missing_type.status_code == 400
    assert missing_type.json()["error"]["code"] == "article_type_required"

    configured = client.put(
        "/api/v1/projects/journal-project/publication-target",
        headers=headers,
        json={
            "target_journal": "International Journal of STEM Education",
            "article_type": "Research Article",
        },
    )
    assert configured.status_code == 200, configured.text
    assert configured.json()["target_journal"] == "International Journal of STEM Education"

    state, _, _ = control.choose_route("journal-project", "两组干预实验与迁移成绩")
    stream = state.workstreams[0]
    journal_index = stream.workflow_steps.index("journal_style_revision")
    control.repository.save_state(
        state.model_copy(update={"workstreams": [stream.model_copy(update={"current_step_index": journal_index})]}),
        expected_revision=state.state_revision,
    )
    advanced = client.post(
        "/api/v1/projects/journal-project/orchestration/continue", headers=headers
    )
    assert advanced.status_code == 200, advanced.text
    gate = advanced.json()["gate"]
    assert gate["gate_type"] == "journal_style_revision_approval"
    contents = client.get(
        "/api/v1/workflow/projects/journal-project/artifact-contents", headers=headers
    ).json()
    created = next(item for item in contents if item["artifact_id"] == gate["artifact_ids"][0])
    assert created["artifact_type"] == "JournalStyleRevision"
    assert created["body"]["status"] == "ENGLISH_MANUSCRIPT_REQUIRED"


def test_guided_clarification_remains_an_open_conversation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(api, "identity_service", IdentityService(tmp_path / "identity.db"))
    monkeypatch.setattr(api, "control_plane", ControlPlane(SQLiteControlPlaneRepository(tmp_path / "control.db")))
    monkeypatch.setattr(api, "artifact_content_store", SQLiteArtifactContentStore(tmp_path / "control.db"))
    client = TestClient(api.app)

    registered = client.post(
        "/api/v1/auth/register",
        json={"username": "routeuser", "email": "route@example.test", "password": "research-pass-123"},
    )
    assert registered.status_code == 200, registered.text
    token = registered.json()["access_token"]
    created = client.post(
        "/api/v1/projects",
        headers=_auth(token),
        json={"project_id": "route-project", "title": "定性研究", "research_direction": "教师问卷主题分析"},
    )
    assert created.status_code == 200, created.text

    unauthenticated = client.get("/api/v1/projects/route-project/control-state")
    assert unauthenticated.status_code == 401
    command = client.post(
        "/api/v1/projects/route-project/conversation/command",
        headers=_auth(token),
        json={"project_id": "route-project", "message": "请先逐步澄清研究设计，再做定性问卷编码和主题分析"},
    )
    assert command.status_code == 200, command.text
    body = command.json()
    assert body["kind"] == "qa"
    assert body["route_decision"] is None
    assert body["gate"] is None
    assert body["waiting_for_user"] is True
    assert body.get("intake") is None

    state = client.get("/api/v1/projects/route-project/control-state", headers=_auth(token))
    assert state.status_code == 200
    assert state.json()["state_revision"] == body["control_state"]["state_revision"]
    events = client.get("/api/v1/projects/route-project/orchestration/events", headers=_auth(token))
    assert events.status_code == 200
    assert events.json() == []


def test_conversation_does_not_start_a_second_chain_while_a_task_is_active(tmp_path: Path, monkeypatch) -> None:
    control = ControlPlane(SQLiteControlPlaneRepository(tmp_path / "control.db"))
    monkeypatch.setattr(api, "identity_service", IdentityService(tmp_path / "identity.db"))
    monkeypatch.setattr(api, "control_plane", control)
    client = TestClient(api.app)

    registered = client.post(
        "/api/v1/auth/register",
        json={"username": "singleflight", "email": "singleflight@example.test", "password": "research-pass-123"},
    )
    headers = _auth(registered.json()["access_token"])
    assert client.post(
        "/api/v1/projects",
        headers=headers,
        json={"project_id": "single-flight-project", "title": "Single flight", "research_direction": "高中物理教师计算思维整合"},
    ).status_code == 200
    control.enqueue_next_action(
        "single-flight-project", action="hybrid_retrieval", input_hash="test-single-flight"
    )

    response = client.post(
        "/api/v1/projects/single-flight-project/conversation/command",
        headers=headers,
        json={"project_id": "single-flight-project", "message": "继续搜索：补充教师专业学习文献"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "orchestration"
    assert body["execution_started"] is True
    assert "无需重复发送" in body["message"]
    assert len(control.repository.list_tasks("single-flight-project")) == 1


def test_project_blockers_tasks_and_controlled_retry_are_visible_via_api(tmp_path: Path, monkeypatch) -> None:
    control = ControlPlane(SQLiteControlPlaneRepository(tmp_path / "control.db"))
    monkeypatch.setattr(api, "identity_service", IdentityService(tmp_path / "identity.db"))
    monkeypatch.setattr(api, "control_plane", control)
    client = TestClient(api.app)

    registered = client.post(
        "/api/v1/auth/register",
        json={"username": "observeuser", "email": "observe@example.test", "password": "research-pass-123"},
    )
    assert registered.status_code == 200, registered.text
    headers = _auth(registered.json()["access_token"])
    created = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"project_id": "observe-project", "title": "观察测试", "research_direction": "定性主题分析"},
    )
    assert created.status_code == 200, created.text
    state, _, _ = control.choose_route("observe-project", "定性主题分析")
    stream = state.workstreams[0]
    control.repository.put_blocker(BlockingIssueRecord(
        project_id="observe-project", workstream_id=stream.workstream_id,
        code="MISSING_PRIMARY_DATA", message="请上传原始资料", priority=90,
    ))
    task = control.enqueue_next_action(
        "observe-project", action="evidence_normalization", input_hash="observe-input"
    )
    control.repository.update_task(task.model_copy(update={"status": ExecutionStatus.FAILED, "error": "provider timeout"}))

    blockers = client.get("/api/v1/projects/observe-project/blockers", headers=headers)
    tasks = client.get("/api/v1/projects/observe-project/orchestration/tasks", headers=headers)
    assert blockers.status_code == 200
    assert blockers.json()[0]["code"] == "MISSING_PRIMARY_DATA"
    assert tasks.status_code == 200
    assert tasks.json()[0]["status"] == "FAILED"

    retried = client.post(
        f"/api/v1/projects/observe-project/orchestration/tasks/{task.task_id}/retry",
        headers=headers,
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "QUEUED"
    assert retried.json()["expected_state_revision"] == state.state_revision


def test_primary_data_upload_is_private_and_unblocks_raw_data_gate(
    tmp_path: Path, monkeypatch
) -> None:
    context_service = ContextService(tmp_path / "context")
    control = ControlPlane(SQLiteControlPlaneRepository(tmp_path / "control.db"))
    monkeypatch.setattr(api, "service", context_service)
    monkeypatch.setattr(api, "identity_service", IdentityService(tmp_path / "identity.db"))
    monkeypatch.setattr(api, "document_service", DocumentService(tmp_path / "documents.db", tmp_path / "documents"))
    monkeypatch.setattr(api, "control_plane", control)
    monkeypatch.setattr(api, "artifact_content_store", SQLiteArtifactContentStore(tmp_path / "control.db"))
    client = TestClient(api.app)

    registered = client.post(
        "/api/v1/auth/register",
        json={"username": "primaryuser", "email": "primary@example.test", "password": "research-pass-123"},
    )
    headers = _auth(registered.json()["access_token"])
    assert client.post(
        "/api/v1/projects",
        headers=headers,
        json={"project_id": "primary-project", "title": "Primary materials", "research_direction": "教师访谈主题分析"},
    ).status_code == 200
    control.choose_route("primary-project", "教师访谈主题分析")
    _, _, gate = control.complete_action_with_candidate(
        "primary-project",
        action="raw_data_import",
        content={"status": "WAITING_PRIMARY_DATA"},
        require_human_gate=True,
    )
    assert gate is not None

    blocked = client.post(
        f"/api/v1/projects/primary-project/gates/{gate.gate_id}/decision",
        headers=headers,
        json={"decision": "approve"},
    )
    assert blocked.status_code == 409, blocked.text
    assert "原始研究数据尚未上传" in blocked.json()["error"]["message"]

    text = "\n".join([
        "参与者 P01：我理解 Python 可以帮助学生用模型检验物理规律，但备课时间很紧。",
        "研究者追问：什么支持会帮助你在课堂中使用它？",
        "参与者 P01：需要可直接修改的示例和同伴共同备课。",
    ])
    receipt = client.post(
        "/api/v1/projects/primary-project/primary-data/upload",
        headers=headers,
        files={"file": ("deidentified-interview.txt", text.encode("utf-8"), "text/plain")},
    )
    assert receipt.status_code == 200, receipt.text
    assert receipt.json()["document"]["document_type"] == "dataset"
    assert receipt.json()["artifact"]["artifact_type"] == "RawQualitativeDataset"
    assert context_service.list_sources("primary-project") == []

    approved = client.post(
        f"/api/v1/projects/primary-project/gates/{gate.gate_id}/decision",
        headers=headers,
        json={"decision": "approve"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["active_gate_id"] is None


@pytest.mark.slow
def test_qualitative_data_actions_use_registered_primary_material_end_to_end(
    tmp_path: Path, monkeypatch
) -> None:
    context_service = ContextService(tmp_path / "context")
    control = ControlPlane(SQLiteControlPlaneRepository(tmp_path / "control.db"))
    monkeypatch.setattr(api, "service", context_service)
    monkeypatch.setattr(api, "identity_service", IdentityService(tmp_path / "identity.db"))
    monkeypatch.setattr(api, "document_service", DocumentService(tmp_path / "documents.db", tmp_path / "documents"))
    monkeypatch.setattr(api, "control_plane", control)
    monkeypatch.setattr(api, "artifact_content_store", SQLiteArtifactContentStore(tmp_path / "control.db"))
    client = TestClient(api.app)

    registered = client.post(
        "/api/v1/auth/register",
        json={"username": "qualuser", "email": "qual@example.test", "password": "research-pass-123"},
    )
    headers = _auth(registered.json()["access_token"])
    assert client.post(
        "/api/v1/projects",
        headers=headers,
        json={"project_id": "qual-project", "title": "Qualitative flow", "research_direction": "高中物理教师访谈主题分析"},
    ).status_code == 200
    state, _, _ = control.choose_route("qual-project", "高中物理教师访谈主题分析")
    stream = state.workstreams[0]
    raw_index = stream.workflow_steps.index("raw_data_import")
    control.repository.save_state(
        state.model_copy(update={"workstreams": [stream.model_copy(update={"current_step_index": raw_index})]}),
        expected_revision=state.state_revision,
    )

    raw_gate_response = client.post(
        "/api/v1/projects/qual-project/orchestration/continue", headers=headers
    )
    assert raw_gate_response.status_code == 200, raw_gate_response.text
    raw_gate = raw_gate_response.json()["gate"]
    assert raw_gate["gate_type"] == "raw_data_import_approval"
    assert client.post(
        f"/api/v1/projects/qual-project/gates/{raw_gate['gate_id']}/decision",
        headers=headers,
        json={"decision": "approve"},
    ).status_code == 409

    primary_text = "\n".join([
        "参与者 P01：我认为计算思维帮助学生把物理规律转成可检验的模型，但 Python 语法需要示例支持。",
        "参与者 P02：备课时间和课堂设备会限制编程活动，我希望和同伴共同备课。",
        "参与者 P03：工作坊的可修改案例能帮助我把模拟活动迁移到日常物理课堂。",
    ])
    uploaded = client.post(
        "/api/v1/projects/qual-project/primary-data/upload",
        headers=headers,
        files={"file": ("deidentified-interviews.txt", primary_text.encode("utf-8"), "text/plain")},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert client.post(
        f"/api/v1/projects/qual-project/gates/{raw_gate['gate_id']}/decision",
        headers=headers,
        json={"decision": "approve"},
    ).status_code == 200

    expected_steps = [
        ("data_audit_approval", "DataAuditCandidate", "PASSED"),
        ("data_processing_approval_approval", "DataProcessingApprovalCandidate", "PENDING_USER_APPROVAL"),
        ("dataset_freeze_hash_approval", "DatasetFreezeHashCandidate", "FROZEN_VERSION_CANDIDATE"),
        ("thematic_analysis_approval", "ThematicAnalysisCandidate", "CANDIDATE_THEME_MAP_READY"),
        ("qualitative_validation_approval", "QualitativeValidationCandidate", "REVIEW_REQUIRED"),
        ("writing_approval", "ManuscriptDraftZh", "CANDIDATE_RESULTS_DRAFT_REQUIRES_QUALITATIVE_REVIEW"),
    ]
    for gate_type, artifact_type, status in expected_steps:
        advanced = client.post(
            "/api/v1/projects/qual-project/orchestration/continue", headers=headers
        )
        assert advanced.status_code == 200, advanced.text
        gate = advanced.json()["gate"]
        assert gate is not None
        assert gate["gate_type"] == gate_type
        content = client.get("/api/v1/workflow/projects/qual-project/artifact-contents").json()
        current = next(item for item in content if item["artifact_id"] == gate["artifact_ids"][0])
        assert current["artifact_type"] == artifact_type
        assert current["body"]["status"] == status
        if artifact_type == "DataAuditCandidate":
            assert current["body"]["data_manifest"]["content_sha256"] == uploaded.json()["artifact"]["content_sha256"]
        if artifact_type == "ThematicAnalysisCandidate":
            assert current["body"]["themes"]
            assert all(theme["evidence_segment_ids"] for theme in current["body"]["themes"])
        approval_payload: dict[str, object] = {"decision": "approve"}
        if gate["warnings"]:
            approval_payload["risk_acceptance"] = ["研究者已查看自动化编码或验证边界"]
        approved = client.post(
            f"/api/v1/projects/qual-project/gates/{gate['gate_id']}/decision",
            headers=headers,
            json=approval_payload,
        )
        assert approved.status_code == 200, approved.text

    claims = client.get("/api/v1/projects/qual-project/claims", headers=headers)
    assert claims.status_code == 200, claims.text
    theme_claims = [item for item in claims.json() if item["claim_type"] == "RESULT"]
    assert theme_claims
    assert all(uploaded.json()["artifact"]["artifact_id"] in item["support_artifact_ids"] for item in theme_claims)
    assert all(item["support_type"] == "candidate_qualitative_data" for item in theme_claims)


@pytest.mark.slow
def test_quantitative_orchestration_reuses_verified_csv_pipeline(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STEM_SCI_CODING_PROVIDER", "deterministic")
    context_service = ContextService(tmp_path / "context")
    control = ControlPlane(SQLiteControlPlaneRepository(tmp_path / "control.db"))
    monkeypatch.setattr(api, "storage_root", tmp_path / "storage")
    monkeypatch.setattr(api, "service", context_service)
    monkeypatch.setattr(api, "identity_service", IdentityService(tmp_path / "identity.db"))
    monkeypatch.setattr(api, "document_service", DocumentService(tmp_path / "documents.db", tmp_path / "documents"))
    monkeypatch.setattr(api, "control_plane", control)
    monkeypatch.setattr(api, "artifact_content_store", SQLiteArtifactContentStore(tmp_path / "control.db"))
    client = TestClient(api.app)
    registration = client.post(
        "/api/v1/auth/register",
        json={"username": "quantuser", "email": "quant@example.test", "password": "research-pass-123"},
    )
    headers = _auth(registration.json()["access_token"])
    assert client.post(
        "/api/v1/projects", headers=headers,
        json={"project_id": "quant-project", "title": "Quantitative flow", "research_direction": "两组物理学习迁移成绩实验"},
    ).status_code == 200
    state, _, _ = control.choose_route("quant-project", "两组物理学习迁移成绩实验")
    stream = state.workstreams[0]
    raw_index = stream.workflow_steps.index("raw_data_import")
    control.repository.save_state(
        state.model_copy(update={"workstreams": [stream.model_copy(update={"current_step_index": raw_index})]}),
        expected_revision=state.state_revision,
    )
    raw = client.post("/api/v1/projects/quant-project/orchestration/continue", headers=headers).json()["gate"]
    csv_text = "group,transfer_score\ncontrol,70\ncontrol,73\ncontrol,69\ntreatment,80\ntreatment,82\ntreatment,79\n"
    assert client.post(
        "/api/v1/projects/quant-project/primary-data/upload", headers=headers,
        files={"file": ("scores.csv", csv_text.encode("utf-8"), "text/csv")},
    ).status_code == 200
    assert client.post(
        f"/api/v1/projects/quant-project/gates/{raw['gate_id']}/decision", headers=headers, json={"decision": "approve"}
    ).status_code == 200
    actions = [
        "data_audit_approval", "data_processing_approval_approval", "dataset_freeze_hash_approval",
        "analysis_code_generation_approval", "physics_code_validation_approval", "code_review_approval",
        "manual_execution_approval_approval", "sandbox_analysis_execution_approval",
        "statistical_result_validation_approval", "bootstrap_robustness_approval",
        "permutation_test_approval", "result_direction_consistency_approval",
        "uncertainty_gate_approval", "statistical_result_card_approval",
    ]
    last_content: dict[str, object] | None = None
    for expected_gate in actions:
        response = client.post("/api/v1/projects/quant-project/orchestration/continue", headers=headers)
        assert response.status_code == 200, response.text
        gate = response.json()["gate"]
        assert gate is not None and gate["gate_type"] == expected_gate, response.json()["task"].get("error")
        content = client.get("/api/v1/workflow/projects/quant-project/artifact-contents").json()
        last_content = next(item for item in content if item["artifact_id"] == gate["artifact_ids"][0])
        approval: dict[str, object] = {"decision": "approve"}
        if gate["warnings"]:
            approval["risk_acceptance"] = ["研究者已确认延后到受控执行阶段的代码检查边界"]
        approved = client.post(
            f"/api/v1/projects/quant-project/gates/{gate['gate_id']}/decision", headers=headers, json=approval
        )
        assert approved.status_code == 200, approved.text
    assert last_content is not None
    body = last_content["body"]
    assert isinstance(body, dict)
    assert body["status"] == "EXECUTION_VERIFIED"
    assert body["statistical_result_card"] is not None
    writing = client.post("/api/v1/projects/quant-project/orchestration/continue", headers=headers)
    assert writing.status_code == 200, writing.text
    writing_gate = writing.json()["gate"]
    assert writing_gate is not None and writing_gate["gate_type"] == "writing_approval"
    contents = client.get("/api/v1/workflow/projects/quant-project/artifact-contents").json()
    manuscript = next(item for item in contents if item["artifact_id"] == writing_gate["artifact_ids"][0])
    assert manuscript["body"]["status"] == "CANDIDATE_RESULTS_DRAFT_REQUIRES_STATISTICAL_REVIEW"
    assert "transfer_mean_difference" in manuscript["body"]["sections"]["results"]
    assert "高中物理教师" not in manuscript["body"]["sections"]["introduction"]
    assert "RQ1：在冻结样本中" in manuscript["body"]["sections"]["research_questions"]
    assert manuscript["body"]["claim_strengths"]["causal_interpretation"] == "not_established"


def test_experimental_route_generates_a_study_design_before_dag(tmp_path: Path, monkeypatch) -> None:
    control = ControlPlane(SQLiteControlPlaneRepository(tmp_path / "control.db"))
    content_store = SQLiteArtifactContentStore(tmp_path / "control.db")
    monkeypatch.setattr(api, "identity_service", IdentityService(tmp_path / "identity.db"))
    monkeypatch.setattr(api, "control_plane", control)
    monkeypatch.setattr(api, "artifact_content_store", content_store)
    client = TestClient(api.app)
    registration = client.post(
        "/api/v1/auth/register",
        json={"username": "designuser", "email": "design@example.test", "password": "research-pass-123"},
    )
    headers = _auth(registration.json()["access_token"])
    assert client.post(
        "/api/v1/projects", headers=headers,
        json={"project_id": "design-project", "title": "Design", "research_direction": "两组物理学习迁移干预实验"},
    ).status_code == 200
    state, route, _ = control.choose_route("design-project", "两组物理学习迁移干预实验")
    assert route.primary_route == "EXPERIMENTAL"
    stream = state.workstreams[0]
    design_index = stream.workflow_steps.index("research_design")
    control.repository.save_state(
        state.model_copy(update={"workstreams": [stream.model_copy(update={"current_step_index": design_index})]}),
        expected_revision=state.state_revision,
    )

    response = client.post("/api/v1/projects/design-project/orchestration/continue", headers=headers)
    assert response.status_code == 200, response.text
    gate = response.json()["gate"]
    assert gate is not None and gate["gate_type"] == "research_design_approval"
    content = client.get("/api/v1/workflow/projects/design-project/artifact-contents").json()
    candidate = next(item for item in content if item["artifact_id"] == gate["artifact_ids"][0])
    assert candidate["artifact_type"] == "StudyProtocolCandidate"
    assert candidate["body"]["design_type"] == "randomized_parallel_repeated_measures"
    assert "Randomly allocate" in candidate["body"]["allocation_description"]


def test_first_substantive_topic_remains_open_discussion(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(api, "identity_service", IdentityService(tmp_path / "identity.db"))
    monkeypatch.setattr(api, "control_plane", ControlPlane(SQLiteControlPlaneRepository(tmp_path / "control.db")))
    client = TestClient(api.app)

    registered = client.post(
        "/api/v1/auth/register",
        json={"username": "topicuser", "email": "topic@example.test", "password": "research-pass-123"},
    )
    headers = _auth(registered.json()["access_token"])
    created = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"project_id": "topic-project", "title": "主题入口", "research_direction": "大学物理教育"},
    )
    assert created.status_code == 200, created.text

    command = client.post(
        "/api/v1/projects/topic-project/conversation/command",
        headers=headers,
        json={
            "project_id": "topic-project",
            "message": "生成式人工智能对大学物理学生计算思维学习成效的影响",
        },
    )
    assert command.status_code == 200, command.text
    body = command.json()
    assert body["kind"] == "qa"
    assert body["route_decision"] is None
    assert body["gate"] is None
    assert body["waiting_for_user"] is True
    assert body.get("intake") is None


def test_evidence_processing_runs_after_a_concrete_topic_without_intermediate_conversation_gates(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(api, "identity_service", IdentityService(tmp_path / "identity.db"))
    monkeypatch.setattr(api, "control_plane", ControlPlane(SQLiteControlPlaneRepository(tmp_path / "control.db")))
    monkeypatch.setattr(api, "artifact_content_store", SQLiteArtifactContentStore(tmp_path / "control.db"))
    client = TestClient(api.app)

    registered = client.post(
        "/api/v1/auth/register",
        json={"username": "evidenceuser", "email": "evidence@example.test", "password": "research-pass-123"},
    )
    token = registered.json()["access_token"]
    headers = _auth(token)
    client.post(
        "/api/v1/projects",
        headers=headers,
        json={"project_id": "evidence-project", "title": "证据流程", "research_direction": "物理教育"},
    )
    intake_started = client.post(
        "/api/v1/projects/evidence-project/conversation/command",
        headers=headers,
        json={"project_id": "evidence-project", "message": "研究本科物理课程 Python 计算建模对学生计算思维测验总分的影响，采用前测后测对照比较。"},
    )
    assert intake_started.status_code == 200, intake_started.text
    command = _complete_research_intake(client, "evidence-project", headers)
    # Evidence review is now a reversible research-question checkpoint, not
    # a formal approval Gate. The package remains available for inspection.
    assert command["gate"] is None, command
    assert command["checkpoint"] == "RESEARCH_QUESTION_REVIEW"
    assert command["waiting_for_user"] is True
    contents = client.get("/api/v1/workflow/projects/evidence-project/artifact-contents").json()
    assert any(item["artifact_type"] == "EvidenceReviewPackage" for item in contents)
    package = client.get("/api/v1/projects/evidence-project/evidence-review", headers=headers)
    assert package.status_code == 200, package.text
    assert package.json()["artifact_type"] == "EvidenceReviewPackage"
    assert package.json()["body"]["schema"] == "evidence-review-package-v1"


def test_conversation_response_consumes_research_question_checkpoint_without_gate(tmp_path: Path, monkeypatch) -> None:
    control = ControlPlane(SQLiteControlPlaneRepository(tmp_path / "control.db"))
    monkeypatch.setattr(api, "identity_service", IdentityService(tmp_path / "identity.db"))
    monkeypatch.setattr(api, "control_plane", control)
    client = TestClient(api.app)
    registered = client.post(
        "/api/v1/auth/register",
        json={"username": "checkpointuser", "email": "checkpoint@example.test", "password": "research-pass-123"},
    )
    headers = _auth(registered.json()["access_token"])
    assert client.post(
        "/api/v1/projects", headers=headers,
        json={"project_id": "checkpoint-project", "title": "对话检查点", "research_direction": "大学物理 Python 建模"},
    ).status_code == 200
    state, _, _ = control.choose_route("checkpoint-project", "两组干预实验与迁移成绩")
    stream = state.workstreams[0]
    question_index = stream.workflow_steps.index("research_question_design")
    state = control.repository.save_state(
        state.model_copy(update={
            "workstreams": [stream.model_copy(update={"current_step_index": question_index})]
        }),
        expected_revision=state.state_revision,
    )
    control.complete_action_with_candidate(
        "checkpoint-project",
        action="research_question_design",
        content={"research_questions": ["问题一", "问题二"]},
        artifact_type="ResearchQuestionTree",
        require_human_gate=False,
        conversation_checkpoint="RESEARCH_QUESTION_REVIEW",
    )

    def continue_stub(project_id: str, user, conversational: bool = False):
        latest = control.ensure_project(project_id)
        return {
            "task": None,
            "control_state": latest.model_dump(mode="json"),
            "gate": None,
            "execution_started": False,
        }

    monkeypatch.setattr(api, "continue_project_orchestration", continue_stub)
    response = client.post(
        "/api/v1/projects/checkpoint-project/conversation/command",
        headers=headers,
        json={"project_id": "checkpoint-project", "message": "选第 2 个，重点比较前后测变化"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["gate"] is None
    assert body.get("checkpoint") is None
    latest = control.ensure_project("checkpoint-project")
    assert latest.workstreams[0].conversation_checkpoint is None
    assert latest.workstreams[0].current_step_index == latest.workstreams[0].workflow_steps.index("research_design")
    assert latest.workstreams[0].conversation_feedback["RESEARCH_QUESTION_REVIEW"] == "选第 2 个，重点比较前后测变化"
    assert any(event.event_type == "CONVERSATION_CHECKPOINT_RESPONDED" for event in control.repository.list_events("checkpoint-project"))


def test_citation_verification_blocks_a_manuscript_without_traceable_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    control = ControlPlane(SQLiteControlPlaneRepository(tmp_path / "control.db"))
    content_store = SQLiteArtifactContentStore(tmp_path / "control.db")
    monkeypatch.setattr(api, "identity_service", IdentityService(tmp_path / "identity.db"))
    monkeypatch.setattr(api, "control_plane", control)
    monkeypatch.setattr(api, "artifact_content_store", content_store)
    client = TestClient(api.app)
    registration = client.post(
        "/api/v1/auth/register",
        json={"username": "citeuser", "email": "cite@example.test", "password": "research-pass-123"},
    )
    headers = _auth(registration.json()["access_token"])
    assert client.post(
        "/api/v1/projects", headers=headers,
        json={"project_id": "citation-project", "title": "Citation", "research_direction": "课堂物理教学"},
    ).status_code == 200
    state, _, _ = control.choose_route("citation-project", "教师访谈主题分析")
    stream = state.workstreams[0]
    citation_index = stream.workflow_steps.index("manuscript_citation_verification")
    control.repository.save_state(
        state.model_copy(update={"workstreams": [stream.model_copy(update={"current_step_index": citation_index})]}),
        expected_revision=state.state_revision,
    )
    content_store.put(ArtifactContent(
        project_id="citation-project", artifact_id="uncited-draft", version=1,
        artifact_type="ManuscriptDraftZh", schema_version="test",
        body={"citation_refs": [], "sections": {"introduction": "没有可追溯文献的草稿"}},
    ))

    response = client.post("/api/v1/projects/citation-project/orchestration/continue", headers=headers)
    assert response.status_code == 200, response.text
    gate = response.json()["gate"]
    assert gate is not None
    content = client.get("/api/v1/workflow/projects/citation-project/artifact-contents").json()
    verification = next(item for item in content if item["artifact_id"] == gate["artifact_ids"][0])
    assert verification["body"]["status"] == "FAILED_TRACEABILITY_CHECK"
    blocked = client.post(
        f"/api/v1/projects/citation-project/gates/{gate['gate_id']}/decision",
        headers=headers, json={"decision": "approve"},
    )
    assert blocked.status_code == 409


def test_citation_verification_requires_manual_review_after_linkage_passes(
    tmp_path: Path, monkeypatch
) -> None:
    control = ControlPlane(SQLiteControlPlaneRepository(tmp_path / "control.db"))
    content_store = SQLiteArtifactContentStore(tmp_path / "control.db")
    monkeypatch.setattr(api, "identity_service", IdentityService(tmp_path / "identity.db"))
    monkeypatch.setattr(api, "control_plane", control)
    monkeypatch.setattr(api, "artifact_content_store", content_store)
    client = TestClient(api.app)
    registration = client.post(
        "/api/v1/auth/register",
        json={"username": "linkeduser", "email": "linked@example.test", "password": "research-pass-123"},
    )
    headers = _auth(registration.json()["access_token"])
    assert client.post(
        "/api/v1/projects", headers=headers,
        json={"project_id": "linked-project", "title": "Linked", "research_direction": "课堂物理教学"},
    ).status_code == 200
    state, _, _ = control.choose_route("linked-project", "教师访谈主题分析")
    stream = state.workstreams[0]
    citation_index = stream.workflow_steps.index("manuscript_citation_verification")
    control.repository.save_state(
        state.model_copy(update={"workstreams": [stream.model_copy(update={"current_step_index": citation_index})]}),
        expected_revision=state.state_revision,
    )
    content_store.put(ArtifactContent(
        project_id="linked-project", artifact_id="evidence-package", version=1,
        artifact_type="EvidenceReviewPackage", schema_version="test",
        body={"used_evidence_refs": ["evidence://local-paper/1"]},
    ))
    content_store.put(ArtifactContent(
        project_id="linked-project", artifact_id="linked-draft", version=1,
        artifact_type="ManuscriptDraftZh", schema_version="test",
        body={"citation_refs": ["evidence://local-paper/1"], "sections": {"introduction": "有可追溯文献的草稿"}},
    ))

    response = client.post("/api/v1/projects/linked-project/orchestration/continue", headers=headers)
    assert response.status_code == 200, response.text
    gate = response.json()["gate"]
    assert gate is not None and gate["warnings"]
    content = client.get("/api/v1/workflow/projects/linked-project/artifact-contents").json()
    verification = next(item for item in content if item["artifact_id"] == gate["artifact_ids"][0])
    assert verification["body"]["status"] == "LINKAGE_CHECKED_REQUIRES_HUMAN_VERIFICATION"
    assert client.post(
        f"/api/v1/projects/linked-project/gates/{gate['gate_id']}/decision",
        headers=headers,
        json={"decision": "approve", "risk_acceptance": ["已人工核对文献作者、年份、页码和主张范围"]},
    ).status_code == 200
    # Citation linkage approval advances to final review; it must never mark
    # a project published merely because its internal links were valid.
    assert control.ensure_project("linked-project").lifecycle_status.value == "ACTIVE"


def test_research_message_does_not_reset_an_existing_orchestration(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(api, "identity_service", IdentityService(tmp_path / "identity.db"))
    monkeypatch.setattr(api, "control_plane", ControlPlane(SQLiteControlPlaneRepository(tmp_path / "control.db")))
    client = TestClient(api.app)
    registered = client.post(
        "/api/v1/auth/register",
        json={"username": "stableuser", "email": "stable@example.test", "password": "research-pass-123"},
    )
    headers = _auth(registered.json()["access_token"])
    client.post(
        "/api/v1/projects",
        headers=headers,
        json={"project_id": "stable-project", "title": "稳定编排", "research_direction": "物理教育"},
    )
    first = client.post(
        "/api/v1/projects/stable-project/conversation/command",
        headers=headers,
        json={"project_id": "stable-project", "message": "请研究物理建模学习效果"},
    ).json()
    repeated = client.post(
        "/api/v1/projects/stable-project/conversation/command",
        headers=headers,
        json={"project_id": "stable-project", "message": "请核查当前研究证据"},
    ).json()
    assert repeated["control_state"]["state_revision"] == first["control_state"]["state_revision"]
    assert repeated["gate"] is None


def test_uploaded_project_material_and_external_candidates_feed_evidence_review(
    tmp_path: Path, monkeypatch
) -> None:
    class StubExternalSearch:
        provider = "openalex"

        def search(self, query: str, max_results: int = 8) -> dict[str, object]:
            assert "physics" in query.lower() and "model" in query.lower()
            assert max_results == 8
            return {
                "ok": True,
                "status": "OK",
                "provider": "openalex",
                "message": "candidate discovery",
                "risk_flags": ["external_metadata_only"],
                "results": [
                    {
                        "title": "External physics modelling candidate",
                        "doi": "10.1000/example",
                        "authors": ["Researcher"],
                        "journal": "Physics Education",
                        "publication_year": 2025,
                        "landing_page_url": "https://doi.org/10.1000/example",
                        "full_text_url": None,
                    }
                ],
            }

        def save_candidates(self, **_: object) -> list[str]:
            return ["ext-test-1"]

    context_service = ContextService(tmp_path / "context")
    monkeypatch.setattr(api, "service", context_service)
    monkeypatch.setattr(api, "identity_service", IdentityService(tmp_path / "identity.db"))
    monkeypatch.setattr(api, "document_service", DocumentService(tmp_path / "documents.db", tmp_path / "documents"))
    monkeypatch.setattr(api, "control_plane", ControlPlane(SQLiteControlPlaneRepository(tmp_path / "control.db")))
    monkeypatch.setattr(api, "artifact_content_store", SQLiteArtifactContentStore(tmp_path / "control.db"))
    monkeypatch.setattr(api.workflow_controller, "context_provider", LocalContextProvider(context_service))
    monkeypatch.setattr(api, "ExternalSearchClient", StubExternalSearch)
    client = TestClient(api.app)

    registered = client.post(
        "/api/v1/auth/register",
        json={"username": "materialuser", "email": "material@example.test", "password": "research-pass-123"},
    )
    headers = _auth(registered.json()["access_token"])
    assert client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "project_id": "material-project",
            "title": "Material evidence",
            "research_direction": "physics modelling",
        },
    ).status_code == 200
    document = client.post(
        "/api/v1/projects/material-project/documents",
        headers=headers,
        json={
            "title": "Local physics modelling paper",
            "document_type": "reference",
            "format": "text",
            "content": "Research shows generative AI supports physics modelling learning in university courses.",
        },
    )
    assert document.status_code == 200, document.text
    assert len(context_service.list_sources("material-project")) == 1

    intake_started = client.post(
        "/api/v1/projects/material-project/conversation/command",
        headers=headers,
        json={
            "project_id": "material-project",
            "message": "Research undergraduate physics students using generative AI support for computational modelling learning with a pretest posttest comparison.",
        },
    )
    assert intake_started.status_code == 200, intake_started.text
    next_step = _complete_research_intake(client, "material-project", headers)
    assert next_step["gate"] is None, next_step
    assert next_step["checkpoint"] == "RESEARCH_QUESTION_REVIEW"
    assert next_step["waiting_for_user"] is True
    package = client.get(
        "/api/v1/projects/material-project/evidence-review", headers=headers
    )
    assert package.status_code == 200, package.text
    body = package.json()["body"]
    assert body["status"] == "READY"
    assert body["coverage"]["source_count"] >= 2
    assert body["coverage"]["evidence_count"] >= 1
    assert body["evidence_matrix"]
    assert any(card["source_ref"] == "external:ext-test-1" for card in body["paper_cards"])
