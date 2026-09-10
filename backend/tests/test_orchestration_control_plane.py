from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

from stem_sci.orchestration import (
    ArtifactLifecycle,
    AuditEvent,
    BlockingIssueRecord,
    ControlPlane,
    ControlPlaneWorker,
    ExecutionStatus,
    GateStatus,
    ResearchPhase,
    ReviewPolicy,
    SQLiteControlPlaneRepository,
    TaskLease,
    ValidationStatus,
)
from stem_sci.orchestration.control_plane import ConcurrentStateError, ControlState


def _digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def test_route_starts_evidence_automation_and_skips_inapplicable_qualitative_modules(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    control = ControlPlane(repository)

    state, route, gate = control.choose_route("qual-1", "请做定性问卷编码和主题分析")

    assert route.primary_route == "QUALITATIVE"
    assert "causal_DAG" in route.skipped_modules
    assert gate is None
    assert state.active_gate_id is None
    assert state.workstreams[0].phase is ResearchPhase.EVIDENCE_PREPARATION


def test_pending_task_scan_returns_queued_and_expired_leases(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    control = ControlPlane(repository)
    control.ensure_project("recovery")
    queued = control.enqueue_next_action("recovery", action="hybrid_retrieval", input_hash="queued")
    assert [item.task_id for item in repository.list_pending_tasks()] == [queued.task_id]
    claimed = repository.claim("test-worker", lease_seconds=1, project_id="recovery")
    assert claimed is not None
    assert repository.list_pending_tasks() == []
    expired = claimed.model_copy(update={"lease_until": claimed.lease_until - timedelta(seconds=2)})
    repository.update_task(expired)
    assert [item.task_id for item in repository.list_pending_tasks()] == [claimed.task_id]


def test_event_cursor_keeps_same_timestamp_events(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "events.db")
    timestamp = datetime.now(UTC)
    repository.add_event(AuditEvent(
        event_id="event-a", project_id="cursor", event_type="A", actor="test", state_revision=1,
        created_at=timestamp,
    ))
    repository.add_event(AuditEvent(
        event_id="event-b", project_id="cursor", event_type="B", actor="test", state_revision=1,
        created_at=timestamp,
    ))
    assert [event.event_id for event in repository.list_events("cursor", "event-a")] == ["event-b"]


def test_failed_task_uses_backoff_before_retry(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "backoff.db")
    control = ControlPlane(repository)
    control.enqueue_next_action("backoff", action="hybrid_retrieval", input_hash="backoff")

    worker = ControlPlaneWorker(repository, control, "backoff-worker")
    result = worker.run_once({"hybrid_retrieval": lambda _task: (_ for _ in ()).throw(RuntimeError("temporary"))}, project_id="backoff")
    assert result is not None
    assert result.status is ExecutionStatus.QUEUED
    assert result.next_attempt_at is not None and result.next_attempt_at > datetime.now(UTC)
    assert repository.claim("second-worker", project_id="backoff") is None


def test_worker_marks_late_state_conflict_stale_without_retrying(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "stale-worker.db")
    control = ControlPlane(repository)
    control.ensure_project("stale-worker")
    task = control.enqueue_next_action("stale-worker", action="hybrid_retrieval", input_hash="stale-worker")

    def late_handler(_task: TaskLease) -> list[str]:
        raise ConcurrentStateError("state revision changed while executing hybrid_retrieval")

    result = ControlPlaneWorker(repository, control, "stale-worker").run_once(
        {"hybrid_retrieval": late_handler}, project_id="stale-worker"
    )

    assert result is not None
    assert result.task_id == task.task_id
    assert result.status is ExecutionStatus.STALE
    assert result.next_attempt_at is None
    assert repository.claim("replacement-worker", project_id="stale-worker") is None


def test_quantitative_routes_require_a_study_design_before_dag_and_end_in_publication_review(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    control = ControlPlane(repository)

    state, route, _ = control.choose_route("experimental-design", "两组干预实验与迁移成绩")
    steps = state.workstreams[0].workflow_steps
    assert route.primary_route == "EXPERIMENTAL"
    assert steps.index("research_question_design") < steps.index("research_design") < steps.index("causal_DAG")
    assert steps[-3:] == ["writing", "manuscript_citation_verification", "reviewer_final_confirmation"]

    state, route, _ = control.choose_route("observational-design", "调查大学物理学习迁移成绩")
    steps = state.workstreams[0].workflow_steps
    assert route.primary_route == "OBSERVATIONAL_QUANTITATIVE"
    assert "research_design" in steps
    assert steps[-1] == "reviewer_final_confirmation"


def test_quantitative_group_coding_is_not_misclassified_as_qualitative(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    control = ControlPlane(repository)

    _, route, _ = control.choose_route(
        "sphere-reanalysis",
        "公开二手资料再分析：比较 SPHERE 数据中不同性别编码组的 FCI 物理概念理解得分，进行描述性关联分析。",
    )

    assert route.primary_route == "OBSERVATIONAL_QUANTITATIVE"


def test_teacher_practice_topic_defaults_to_qualitative_route(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    control = ControlPlane(repository)

    state, route, _ = control.choose_route(
        "teacher-topic",
        "高中物理教师如何把计算思维和 Python 融入课堂，重点了解教师的专业学习需求",
    )

    assert route.primary_route == "QUALITATIVE"
    assert state.workstreams[0].route == "QUALITATIVE"
    assert "causal_DAG" in route.skipped_modules


def test_computational_grounded_theory_validation_language_stays_qualitative(tmp_path) -> None:
    """CGT validation terms must not trigger the experimental route."""

    control = ControlPlane(SQLiteControlPlaneRepository(tmp_path / "control.db"))
    _, route, _ = control.choose_route(
        "cgt-route",
        (
            "学生问题解决文本的计算扎根理论再分析：以句子级编码发现主题，"
            "研究者审阅代表句、边界句和噪声句，再用监督模型和交叉验证检查主题覆盖；"
            "保存随机种子和代码版本。"
        ),
    )

    assert route.primary_route == "QUALITATIVE"
    assert "thematic_analysis" in route.applicable_modules
    assert "power_analysis" in route.skipped_modules


def test_mixed_methods_creates_independent_qualitative_and_quantitative_workstreams(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    control = ControlPlane(repository)

    state, route, _ = control.choose_route(
        "mixed-route",
        "研究 Python 教学对学生计算思维表现的影响，并访谈教师了解实施过程",
    )

    assert route.primary_route == "MIXED_METHODS"
    assert len(state.workstreams) == 2
    assert {stream.route for stream in state.workstreams} == {"QUALITATIVE", "EXPERIMENTAL"}
    assert state.active_workstream_id == state.workstreams[0].workstream_id
    assert all(stream.current_action == "文献整理和证据规范化" for stream in state.workstreams)
    assert "causal_DAG" not in state.workstreams[0].workflow_steps
    assert "causal_DAG" in state.workstreams[1].workflow_steps


def test_mixed_methods_switches_to_next_workstream_and_completes_only_after_both(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    control = ControlPlane(repository)
    control.ensure_project("mixed-completion", review_policy=ReviewPolicy.SELF_REVIEW_ALLOWED)
    state, _, _ = control.choose_route(
        "mixed-completion",
        "混合方法：两组 Python 教学比较并访谈教师实施经验",
    )
    prepared = state.model_copy(update={
        "review_policy": ReviewPolicy.SELF_REVIEW_ALLOWED,
        "workstreams": [
            stream.model_copy(update={
                "workflow_steps": ["reviewer_final_confirmation"],
                "current_step_index": 0,
            })
            for stream in state.workstreams
        ],
    })
    repository.save_state(prepared, expected_revision=state.state_revision)

    _, _, first_gate = control.complete_action_with_candidate(
        "mixed-completion",
        action="reviewer_final_confirmation",
        content={"status": "SELF_REVIEW"},
        gate_type="reviewer_final_confirmation_approval",
        gate_level="G3",
    )
    assert first_gate is not None
    after_first = control.decide_gate(
        "mixed-completion", first_gate.gate_id, decision="approve", actor="author", role="researcher"
    )
    assert after_first.lifecycle_status.value == "ACTIVE"
    assert len(after_first.workstreams) == 2
    assert after_first.active_workstream_id == after_first.workstreams[1].workstream_id
    assert after_first.workstreams[0].status.value == "COMPLETED"

    _, _, second_gate = control.complete_action_with_candidate(
        "mixed-completion",
        action="reviewer_final_confirmation",
        content={"status": "SELF_REVIEW"},
        gate_type="reviewer_final_confirmation_approval",
        gate_level="G3",
    )
    assert second_gate is not None
    after_second = control.decide_gate(
        "mixed-completion", second_gate.gate_id, decision="approve", actor="author", role="researcher"
    )
    assert after_second.lifecycle_status.value == "ACTIVE"
    assert all(stream.status.value == "COMPLETED" for stream in after_second.workstreams)

    _, _, merge_gate = control.complete_action_with_candidate(
        "mixed-completion",
        action="mixed_methods_merge",
        content={"status": "MIXED_METHODS_MANUSCRIPT_CANDIDATE_REQUIRES_REVIEW"},
        gate_type="mixed_methods_merge_approval",
        gate_level="G3",
        validation_status=ValidationStatus.WARNING,
        validation_warnings=["reviewed"],
    )
    assert merge_gate is not None
    completed = control.decide_gate(
        "mixed-completion", merge_gate.gate_id, decision="approve", actor="author", role="researcher",
        risk_acceptance=["reviewed"],
    )
    assert completed.lifecycle_status.value == "COMPLETED"
    assert all(stream.status.value == "COMPLETED" for stream in completed.workstreams)


def test_publication_target_inserts_journal_formatting_after_writing(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    control = ControlPlane(repository)

    configured = control.set_publication_target(
        "journal-flow",
        target_journal="International Journal of STEM Education",
        article_type="Research Article",
    )
    assert configured.target_journal == "International Journal of STEM Education"
    assert configured.article_type == "Research Article"

    state, _, _ = control.choose_route("journal-flow", "两组干预实验与迁移成绩")
    steps = state.workstreams[0].workflow_steps
    assert steps[steps.index("writing") + 1] == "journal_style_revision"
    assert steps[steps.index("journal_style_revision") + 1] == "manuscript_citation_verification"


def test_evidence_review_warning_requires_explicit_risk_acceptance(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    control = ControlPlane(repository)
    control.choose_route("qual-2", "定性主题分析")
    for action in ("evidence_normalization", "hybrid_retrieval", "rrf_fusion", "cross_encoder_rerank"):
        control.complete_action_with_candidate(
            "qual-2", action=action, content={"action": action}, require_human_gate=False
        )
    _, _, gate = control.complete_action_with_candidate(
        "qual-2",
        action="claim_evidence_support",
        content={"schema": "evidence-review-package-v1"},
        gate_type="evidence_sufficiency_review",
        gate_level="G1",
        gate_reason="请审阅证据包。",
    )
    assert gate is not None
    repository.put_gate(gate.model_copy(update={"warnings": ["来源覆盖仍需研究者确认"]}))

    with pytest.raises(ValueError, match="risk acceptance"):
        control.decide_gate("qual-2", gate.gate_id, decision="approve", actor="researcher")

    state = control.decide_gate("qual-2", gate.gate_id, decision="approve", actor="researcher", risk_acceptance=["路线判断已由研究者确认"])
    assert state.active_gate_id is None
    assert state.workstreams[0].phase is ResearchPhase.RESEARCH_DESIGN


def test_revising_evidence_review_restarts_only_the_evidence_stage(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    control = ControlPlane(repository)
    control.choose_route("evidence-rework", "研究物理建模学习效果")
    for action in ("evidence_normalization", "hybrid_retrieval", "rrf_fusion", "cross_encoder_rerank"):
        control.complete_action_with_candidate(
            "evidence-rework", action=action, content={"action": action}, require_human_gate=False
        )
    _, package, gate = control.complete_action_with_candidate(
        "evidence-rework",
        action="claim_evidence_support",
        content={"schema": "evidence-review-package-v1"},
        artifact_type="EvidenceReviewPackage",
        gate_type="evidence_sufficiency_review",
        gate_level="G1",
    )
    assert gate is not None

    state = control.decide_gate(
        "evidence-rework", gate.gate_id, decision="revise", actor="researcher", reason="补充文献"
    )
    stream = state.workstreams[0]
    assert state.active_gate_id is None
    assert stream.phase is ResearchPhase.EVIDENCE_PREPARATION
    assert stream.current_step_index == stream.workflow_steps.index("evidence_normalization")
    assert package.artifact_id in stream.artifact_ids


def test_revising_failed_citation_verification_returns_to_writing(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    control = ControlPlane(repository)
    state, _, _ = control.choose_route("citation-rework", "两组物理学习成绩比较")
    stream = state.workstreams[0]
    citation_index = stream.workflow_steps.index("manuscript_citation_verification")
    repository.save_state(
        state.model_copy(update={
            "workstreams": [stream.model_copy(update={"current_step_index": citation_index})]
        }),
        expected_revision=state.state_revision,
    )
    _, artifact, gate = control.complete_action_with_candidate(
        "citation-rework",
        action="manuscript_citation_verification",
        content={"status": "FAILED_TRACEABILITY_CHECK"},
        artifact_type="ManuscriptCitationVerification",
        gate_type="manuscript_citation_verification_approval",
        gate_level="G2",
        validation_status=ValidationStatus.FAILED,
        validation_warnings=["缺少可追溯结果卡"],
    )
    assert gate is not None

    revised = control.decide_gate(
        "citation-rework",
        gate.gate_id,
        decision="revise",
        actor="researcher",
        reason="重新生成论文并补齐结果链接",
    )

    revised_stream = revised.workstreams[0]
    assert revised.active_gate_id is None
    assert revised_stream.current_step_index == revised_stream.workflow_steps.index("writing")
    assert revised_stream.phase is ResearchPhase.WRITING_PUBLICATION
    assert revised_stream.execution_status is ExecutionStatus.QUEUED
    assert artifact.artifact_id in revised_stream.artifact_ids


def test_research_question_and_design_checkpoints_pause_without_creating_gates(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    control = ControlPlane(repository)
    state, _, _ = control.choose_route("conversation-checkpoints", "两组干预实验与迁移成绩")
    stream = state.workstreams[0]
    question_index = stream.workflow_steps.index("research_question_design")
    state = repository.save_state(
        state.model_copy(update={
            "workstreams": [stream.model_copy(update={"current_step_index": question_index})]
        }),
        expected_revision=state.state_revision,
    )

    question_state, _, question_gate = control.complete_action_with_candidate(
        "conversation-checkpoints",
        action="research_question_design",
        content={"research_questions": ["候选问题一", "候选问题二"]},
        artifact_type="ResearchQuestionTree",
        require_human_gate=False,
        conversation_checkpoint="RESEARCH_QUESTION_REVIEW",
    )
    question_stream = question_state.workstreams[0]
    assert question_gate is None
    assert question_state.active_gate_id is None
    assert question_stream.conversation_checkpoint == "RESEARCH_QUESTION_REVIEW"
    assert question_stream.execution_status is ExecutionStatus.WAITING_USER
    assert question_stream.current_step_index == question_stream.workflow_steps.index("research_design")

    repository.save_state(
        question_state.model_copy(update={
            "workstreams": [question_stream.model_copy(update={
                "conversation_checkpoint": None,
                "execution_status": ExecutionStatus.QUEUED,
            })]
        }),
        expected_revision=question_state.state_revision,
    )
    design_state, _, design_gate = control.complete_action_with_candidate(
        "conversation-checkpoints",
        action="power_analysis",
        content={"status": "PLANNING_ASSUMPTIONS_REQUIRE_CONFIRMATION"},
        artifact_type="PowerAnalysisCandidate",
        require_human_gate=False,
        conversation_checkpoint="RESEARCH_DESIGN_REVIEW",
    )
    final_stream = design_state.workstreams[0]
    assert design_gate is None
    assert final_stream.conversation_checkpoint == "RESEARCH_DESIGN_REVIEW"
    assert final_stream.execution_status is ExecutionStatus.WAITING_USER
    assert final_stream.current_step_index == final_stream.workflow_steps.index("preregistration_freeze")

    writing_index = final_stream.workflow_steps.index("writing")
    repository.save_state(
        design_state.model_copy(update={
            "workstreams": [final_stream.model_copy(update={"current_step_index": writing_index})]
        }),
        expected_revision=design_state.state_revision,
    )
    outline_state, _, outline_gate = control.complete_action_with_candidate(
        "conversation-checkpoints",
        action="writing",
        content={"status": "OUTLINE_REQUIRES_RESEARCHER_REVIEW"},
        artifact_type="ManuscriptOutline",
        require_human_gate=False,
        conversation_checkpoint="MANUSCRIPT_OUTLINE_REVIEW",
        resume_action="writing",
    )
    outline_stream = outline_state.workstreams[0]
    assert outline_gate is None
    assert outline_stream.conversation_checkpoint == "MANUSCRIPT_OUTLINE_REVIEW"
    assert outline_stream.current_step_index == writing_index


def test_state_revision_rejects_stale_writer(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    first = ControlState(project_id="revision-1")
    saved = repository.save_state(first, expected_revision=0)
    repository.save_state(saved, expected_revision=saved.state_revision)

    with pytest.raises(ConcurrentStateError):
        repository.save_state(saved, expected_revision=saved.state_revision)


def test_stale_worker_cannot_commit_candidate_over_newer_checkpoint(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    control = ControlPlane(repository)
    initial = control.ensure_project("stale-candidate")
    advanced = repository.save_state(initial, expected_revision=initial.state_revision)

    with pytest.raises(ConcurrentStateError, match="state revision changed"):
        control.complete_action_with_candidate(
            "stale-candidate",
            action="evidence_normalization",
            content={"status": "late result"},
            require_human_gate=False,
            expected_state_revision=initial.state_revision,
        )

    assert advanced.state_revision > initial.state_revision
    assert repository.list_artifacts("stale-candidate") == []


def test_state_and_audit_event_commit_as_one_outbox_unit(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    state = ControlState(project_id="atomic-1")

    saved = repository.save_state_and_event(
        state,
        expected_revision=0,
        event_type="TEST_COMMITTED",
        actor="tester",
        payload={"ok": True},
    )

    events = repository.list_events("atomic-1")
    assert saved.state_revision == 1
    assert len(events) == 1
    assert events[0].state_revision == saved.state_revision
    with repository._connect() as connection:
        outbox = connection.execute(
            "select count(*) from orchestration_outbox where project_id=?", ("atomic-1",)
        ).fetchone()[0]
    assert outbox == 1


def test_frozen_artifact_requires_new_revision_and_failed_validation_cannot_freeze(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    control = ControlPlane(repository)
    state = control.ensure_project("artifact-1")
    stream_id = state.workstreams[0].workstream_id
    candidate = control.create_artifact("artifact-1", workstream_id=stream_id, artifact_type="ResearchDesign", content_uri="memory://v1", content_sha256=_digest("v1"), created_by="agent")
    with pytest.raises(ValueError, match="validated"):
        control.freeze_artifact("artifact-1", candidate.artifact_id, actor="researcher")
    control.validate_artifact("artifact-1", candidate.artifact_id, status=ValidationStatus.PASSED)
    frozen = control.freeze_artifact("artifact-1", candidate.artifact_id, actor="researcher")
    assert frozen.lifecycle_status is ArtifactLifecycle.FROZEN

    with pytest.raises(ValueError, match="frozen"):
        control.validate_artifact("artifact-1", candidate.artifact_id, status=ValidationStatus.PASSED)

    revision = control.create_artifact("artifact-1", workstream_id=stream_id, artifact_type="ResearchDesign", content_uri="memory://v2", content_sha256=_digest("v2"), created_by="researcher", supersedes_artifact_id=candidate.artifact_id)
    assert revision.version == 2
    old = next(item for item in repository.list_artifacts("artifact-1") if item.artifact_id == candidate.artifact_id)
    assert old.lifecycle_status is ArtifactLifecycle.SUPERSEDED
    assert old.effective is False


def test_expired_worker_lease_can_be_reclaimed_without_duplicate_task(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    task = TaskLease(
        project_id="worker-1",
        workstream_id="ws-worker-1-main",
        action="parse_pdf",
        idempotency_key="parse:pdf:1",
        input_hash=_digest("pdf"),
        expected_state_revision=1,
    )
    repository.enqueue(task)
    claimed = repository.claim("worker-a", lease_seconds=0)
    assert claimed is not None
    assert claimed.claimed_by == "worker-a"
    reclaimed = repository.claim("worker-b", lease_seconds=60)
    assert reclaimed is not None
    assert reclaimed.task_id == claimed.task_id
    assert reclaimed.claimed_by == "worker-b"
    assert reclaimed.attempt == 2


def test_project_scoped_worker_does_not_claim_another_projects_task(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    control = ControlPlane(repository)
    control.ensure_project("first-project")
    control.ensure_project("active-project")
    first = control.enqueue_next_action("first-project", action="parse_pdf", input_hash=_digest("first"))
    active = control.enqueue_next_action("active-project", action="parse_pdf", input_hash=_digest("active"))

    result = ControlPlaneWorker(repository, control, "api-active").run_once(
        {"parse_pdf": lambda _: []}, project_id="active-project"
    )

    assert result is not None
    assert result.task_id == active.task_id
    assert result.status is ExecutionStatus.COMPLETED
    assert repository.get_task("first-project", first.task_id).status is ExecutionStatus.QUEUED


def test_worker_heartbeat_extends_active_lease(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    task = TaskLease(
        project_id="heartbeat-1", workstream_id="ws-heartbeat-1-main", action="parse_pdf",
        idempotency_key="heartbeat:1", input_hash=_digest("pdf"), expected_state_revision=1,
    )
    repository.enqueue(task)
    claimed = repository.claim("worker-a", lease_seconds=1)
    assert claimed is not None
    refreshed = repository.heartbeat(claimed.task_id, "worker-a", lease_seconds=60)
    assert refreshed is not None
    assert refreshed.heartbeat_at is not None
    assert refreshed.lease_until is not None
    assert refreshed.lease_until > claimed.lease_until


def test_worker_requeues_transient_failure_before_terminal_failure(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    control = ControlPlane(repository)
    control.ensure_project("retry-1")
    control.enqueue_next_action("retry-1", action="parse_pdf", input_hash=_digest("pdf"))
    worker = ControlPlaneWorker(repository, control, "worker-a")

    first = worker.run_once({"parse_pdf": lambda _: (_ for _ in ()).throw(RuntimeError("temporary"))})
    assert first is not None
    assert first.status is ExecutionStatus.QUEUED
    # The worker deliberately applies exponential backoff.  Move the
    # scheduled retry into the past instead of bypassing that production
    # contract with an immediate second claim.
    ready = first.model_copy(update={"next_attempt_at": datetime.now(UTC) - timedelta(seconds=1)})
    repository.update_task(ready)
    second = worker.run_once({"parse_pdf": lambda _: (_ for _ in ()).throw(RuntimeError("temporary"))})
    assert second is not None
    assert second.status is ExecutionStatus.QUEUED
    ready = second.model_copy(update={"next_attempt_at": datetime.now(UTC) - timedelta(seconds=1)})
    repository.update_task(ready)
    third = worker.run_once({"parse_pdf": lambda _: (_ for _ in ()).throw(RuntimeError("temporary"))})
    assert third is not None
    assert third.status is ExecutionStatus.FAILED


def test_enqueue_is_idempotent_by_project_and_key(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    first = TaskLease(
        project_id="idempotent-1",
        workstream_id="ws-idempotent-1-main",
        action="parse_pdf",
        idempotency_key="parse:pdf:revision-1",
        input_hash=_digest("pdf"),
        expected_state_revision=1,
    )
    second = first.model_copy(update={"task_id": "task-retry", "input_hash": _digest("same-input")})

    assert repository.enqueue(first).task_id == first.task_id
    retry = repository.enqueue(second)

    assert retry.task_id == first.task_id
    assert len(repository.list_tasks("idempotent-1")) == 1


def test_control_plane_reuses_queued_task_on_retry(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    control = ControlPlane(repository)
    control.ensure_project("control-retry")

    first = control.enqueue_next_action("control-retry", action="parse_pdf", input_hash=_digest("pdf"))
    second = control.enqueue_next_action("control-retry", action="parse_pdf", input_hash=_digest("pdf"))

    assert second.task_id == first.task_id
    assert len(repository.list_tasks("control-retry")) == 1
    assert len([event for event in repository.list_events("control-retry") if event.event_type == "TASK_QUEUED"]) == 1


def test_worker_marks_task_stale_when_state_revision_changed(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    control = ControlPlane(repository)
    control.ensure_project("worker-2")
    task = control.enqueue_next_action("worker-2", action="parse_pdf", input_hash=_digest("pdf"))
    state = repository.get_state("worker-2")
    assert state is not None
    repository.save_state(state, expected_revision=state.state_revision)
    result = ControlPlaneWorker(repository, control, "worker-a").run_once({"parse_pdf": lambda _: []})
    assert result is not None
    assert result.task_id == task.task_id
    assert result.status.value == "STALE"


def test_approved_candidate_advances_the_current_workstream_phase(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    control = ControlPlane(repository)
    state, _, route_gate = control.choose_route("qual-flow", "定性访谈主题分析")
    assert route_gate is None
    for action in ("evidence_normalization", "hybrid_retrieval", "rrf_fusion", "cross_encoder_rerank"):
        state, _, _ = control.complete_action_with_candidate(
            "qual-flow", action=action, content={"action": action}, require_human_gate=False
        )
    _, _, evidence_gate = control.complete_action_with_candidate(
        "qual-flow",
        action="claim_evidence_support",
        content={"schema": "evidence-review-package-v1"},
        gate_type="evidence_sufficiency_review",
        gate_level="G1",
    )
    assert evidence_gate is not None
    state = control.decide_gate(
        "qual-flow",
        evidence_gate.gate_id,
        decision="approve",
        actor="researcher",
    )
    _, _, question_gate = control.complete_action_with_candidate(
        "qual-flow", action="research_question_design", content={"question": "candidate"}
    )
    assert question_gate is not None
    state = control.decide_gate("qual-flow", question_gate.gate_id, decision="approve", actor="researcher")
    stream_id = state.workstreams[0].workstream_id
    _, _, design_gate = control.complete_action_with_candidate(
        "qual-flow",
        action="qualitative_design",
        content={"method": "thematic_analysis"},
    )
    state = control.decide_gate("qual-flow", design_gate.gate_id, decision="approve", actor="researcher")
    assert state.workstreams[0].workstream_id == stream_id
    assert state.workstreams[0].phase is ResearchPhase.DATA_PREPARATION

    _, _, data_gate = control.complete_action_with_candidate(
        "qual-flow",
        action="qualitative_data_preparation",
        content={"data": "open-ended responses"},
    )
    state = control.decide_gate("qual-flow", data_gate.gate_id, decision="approve", actor="researcher")
    assert state.workstreams[0].phase is ResearchPhase.ANALYSIS_EXECUTION


def test_raw_data_gate_blocks_until_a_real_primary_dataset_is_registered(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    control = ControlPlane(repository)
    control.choose_route("raw-data-gate", "教师访谈主题分析")
    _, _, gate = control.complete_action_with_candidate(
        "raw-data-gate",
        action="raw_data_import",
        content={"status": "WAITING_PRIMARY_DATA"},
        require_human_gate=True,
    )
    assert gate is not None

    with pytest.raises(ValueError, match="原始研究数据尚未上传"):
        control.decide_gate("raw-data-gate", gate.gate_id, decision="approve", actor="researcher")

    blocked = control.ensure_project("raw-data-gate")
    assert blocked.active_gate_id == gate.gate_id
    assert blocked.active_blocking_issue_id is not None
    assert blocked.workstreams[0].execution_status.value == "BLOCKED"
    blockers = repository.list_blockers("raw-data-gate")
    assert len(blockers) == 1
    assert blockers[0].code == "MISSING_PRIMARY_DATA"

    registered, dataset = control.register_primary_data(
        "raw-data-gate",
        content_uri="document://private/teacher-interviews.txt",
        content_sha256=_digest("deidentified interview material"),
        source_dataset_id="document://private/1",
        actor="researcher",
    )
    assert dataset.artifact_type == "RawQualitativeDataset"
    assert registered.active_blocking_issue_id is None
    assert repository.list_blockers("raw-data-gate")[0].status == "RESOLVED"

    approved = control.decide_gate("raw-data-gate", gate.gate_id, decision="approve", actor="researcher")
    assert approved.active_gate_id is None


def test_active_blocker_selects_highest_priority_open_issue(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    control = ControlPlane(repository)
    state = control.ensure_project("blocker-priority")
    stream = state.workstreams[0]
    repository.put_blocker(BlockingIssueRecord(
        project_id="blocker-priority", workstream_id=stream.workstream_id,
        code="LOW", message="low", priority=10,
    ))
    repository.put_blocker(BlockingIssueRecord(
        project_id="blocker-priority", workstream_id=stream.workstream_id,
        code="HIGH", message="high", priority=90,
    ))

    next_state = state.model_copy(update={
        "active_blocking_issue_id": control._active_blocker_id("blocker-priority")
    })
    saved = control._save_state_event(
        next_state, event_type="BLOCKER_SELECTED", actor="orchestrator"
    )
    selected = repository.get_blocker("blocker-priority", saved.active_blocking_issue_id or "")
    assert selected is not None
    assert selected.code == "HIGH"


def test_retry_task_requeues_only_the_current_failed_action(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    control = ControlPlane(repository)
    state, _, _ = control.choose_route("retry-current", "定性主题分析")
    task = control.enqueue_next_action(
        "retry-current", action="evidence_normalization", input_hash=_digest("evidence")
    )
    repository.update_task(task.model_copy(update={
        "status": ExecutionStatus.FAILED, "error": "temporary provider failure"
    }))

    retried = control.retry_task("retry-current", task.task_id)

    assert retried.status is ExecutionStatus.QUEUED
    assert retried.expected_state_revision == state.state_revision
    assert retried.task_id != task.task_id
    assert len(repository.list_tasks("retry-current")) == 2


def test_retry_task_rejects_terminal_task_that_is_no_longer_current(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    control = ControlPlane(repository)
    control.choose_route("retry-stale", "定性主题分析")
    task = control.enqueue_next_action(
        "retry-stale", action="evidence_normalization", input_hash=_digest("evidence")
    )
    repository.update_task(task.model_copy(update={"status": ExecutionStatus.STALE}))
    state = control.ensure_project("retry-stale")
    stream = state.workstreams[0]
    advanced = state.model_copy(update={
        "workstreams": [stream.model_copy(update={"current_step_index": stream.current_step_index + 1})],
    })
    repository.save_state(advanced, expected_revision=state.state_revision)

    with pytest.raises(ValueError, match="no longer the active"):
        control.retry_task("retry-stale", task.task_id)


def test_required_independent_reviewer_can_close_final_gate_but_author_cannot(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    control = ControlPlane(repository)
    _, _, gate = control.complete_action_with_candidate(
        "final-review",
        action="reviewer_final_confirmation",
        content={"status": "INDEPENDENT_REVIEW_REQUIRED"},
        actor="author",
        gate_type="reviewer_final_confirmation_approval",
        gate_level="G3",
    )
    assert gate is not None

    with pytest.raises(PermissionError, match="独立审稿"):
        control.decide_gate("final-review", gate.gate_id, decision="approve", actor="author", role="researcher")

    approved = control.decide_gate(
        "final-review", gate.gate_id, decision="approve", actor="independent-reviewer", role="reviewer"
    )
    assert approved.active_gate_id is None
    assert repository.get_gate("final-review", gate.gate_id).status is GateStatus.APPROVED


def test_self_review_policy_keeps_auditable_final_gate_for_single_researcher(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    control = ControlPlane(repository)
    control.ensure_project("self-review", review_policy=ReviewPolicy.SELF_REVIEW_ALLOWED)
    _, _, gate = control.complete_action_with_candidate(
        "self-review",
        action="reviewer_final_confirmation",
        content={"status": "SELF_REVIEW"},
        actor="author",
        gate_type="reviewer_final_confirmation_approval",
        gate_level="G3",
    )
    assert gate is not None

    approved = control.decide_gate("self-review", gate.gate_id, decision="approve", actor="author", role="researcher")
    assert approved.active_gate_id is None


def test_final_gate_marks_single_project_completed(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    control = ControlPlane(repository)
    state = control.ensure_project("completion-1", review_policy=ReviewPolicy.SELF_REVIEW_ALLOWED)
    stream = state.workstreams[0]
    prepared = state.model_copy(update={
        "route_decision": None,
        "workstreams": [stream.model_copy(update={
            "workflow_steps": ["reviewer_final_confirmation"],
            "current_step_index": 0,
        })],
    })
    repository.save_state(prepared, expected_revision=state.state_revision)
    _, _, gate = control.complete_action_with_candidate(
        "completion-1",
        action="reviewer_final_confirmation",
        content={"status": "SELF_REVIEW"},
        actor="author",
        gate_type="reviewer_final_confirmation_approval",
        gate_level="G3",
    )
    assert gate is not None

    completed = control.decide_gate(
        "completion-1", gate.gate_id, decision="approve", actor="author", role="researcher"
    )

    assert completed.lifecycle_status.value == "COMPLETED"
    assert completed.workstreams[0].status.value == "COMPLETED"
    assert completed.workstreams[0].execution_status.value == "COMPLETED"


def test_mixed_methods_requires_project_level_merge_before_completion(tmp_path) -> None:
    repository = SQLiteControlPlaneRepository(tmp_path / "control.db")
    control = ControlPlane(repository)
    state, route, _ = control.choose_route("mixed-merge", "混合方法研究 Python 教学并访谈教师")
    assert route.primary_route == "MIXED_METHODS"

    # Reduce the fixture to the two final route gates so this contract test
    # isolates the project-level completion rule.
    prepared_streams = [
        stream.model_copy(update={
            "workflow_steps": ["reviewer_final_confirmation"],
            "current_step_index": 0,
        })
        for stream in state.workstreams
    ]
    prepared = state.model_copy(update={
        "review_policy": ReviewPolicy.SELF_REVIEW_ALLOWED,
        "workstreams": prepared_streams,
        "active_workstream_id": prepared_streams[0].workstream_id,
    })
    repository.save_state(prepared, expected_revision=state.state_revision)

    _, _, first_gate = control.complete_action_with_candidate(
        "mixed-merge",
        action="reviewer_final_confirmation",
        content={"status": "reviewed"},
        actor="reviewer-1",
        gate_type="reviewer_final_confirmation_approval",
        gate_level="G3",
        validation_status=ValidationStatus.WARNING,
        validation_warnings=["reviewed"],
    )
    assert first_gate is not None
    after_first = control.decide_gate(
        "mixed-merge", first_gate.gate_id, decision="approve", actor="reviewer-1",
        role="reviewer", risk_acceptance=["reviewed"],
    )
    assert after_first.lifecycle_status.value == "ACTIVE"

    _, _, second_gate = control.complete_action_with_candidate(
        "mixed-merge",
        action="reviewer_final_confirmation",
        content={"status": "reviewed"},
        actor="reviewer-2",
        gate_type="reviewer_final_confirmation_approval",
        gate_level="G3",
        validation_status=ValidationStatus.WARNING,
        validation_warnings=["reviewed"],
    )
    assert second_gate is not None
    after_second = control.decide_gate(
        "mixed-merge", second_gate.gate_id, decision="approve", actor="reviewer-2",
        role="reviewer", risk_acceptance=["reviewed"],
    )
    assert after_second.lifecycle_status.value == "ACTIVE"
    assert all(item.status.value == "COMPLETED" for item in after_second.workstreams)

    _, _, merge_gate = control.complete_action_with_candidate(
        "mixed-merge",
        action="mixed_methods_merge",
        content={"status": "MIXED_METHODS_MANUSCRIPT_CANDIDATE_REQUIRES_REVIEW"},
        actor="orchestrator",
        gate_type="mixed_methods_merge_approval",
        gate_level="G3",
        validation_status=ValidationStatus.WARNING,
        validation_warnings=["reviewed"],
    )
    assert merge_gate is not None
    completed = control.decide_gate(
        "mixed-merge", merge_gate.gate_id, decision="approve", actor="researcher",
        role="researcher", risk_acceptance=["reviewed"],
    )
    assert completed.lifecycle_status.value == "COMPLETED"


def test_computational_qualitative_workflow_has_human_review_chain() -> None:
    steps = ControlPlane.workflow_steps_for_route("QUALITATIVE", computational_qualitative=True)
    expected = [
        "analysis_code_generation",
        "code_review",
        "manual_execution_approval",
        "sandbox_analysis_execution",
        "pattern_discovery_review",
        "codebook_review",
        "manual_theme_revision",
        "supervised_confirmation",
        "student_level_robustness",
        "group_comparison",
        "result_card_review",
    ]
    positions = [steps.index(item) for item in expected]
    assert positions == sorted(positions)
    assert "writing" in steps and steps.index("result_card_review") < steps.index("writing")
