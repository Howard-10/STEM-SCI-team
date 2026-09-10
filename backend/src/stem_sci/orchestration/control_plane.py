"""Durable, condition-driven control plane for conversational research.

The control plane deliberately owns only workflow facts and governance. Domain
Agents produce candidates; this module decides whether those candidates can be
validated, approved, frozen, or invalidated.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Any, ClassVar, Literal, Protocol, TypeVar, cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResearchPhase(StrEnum):
    PROJECT_INGESTION = "PROJECT_INGESTION"
    EVIDENCE_PREPARATION = "EVIDENCE_PREPARATION"
    RESEARCH_DESIGN = "RESEARCH_DESIGN"
    DATA_PREPARATION = "DATA_PREPARATION"
    ANALYSIS_EXECUTION = "ANALYSIS_EXECUTION"
    RESULT_VALIDATION = "RESULT_VALIDATION"
    WRITING_PUBLICATION = "WRITING_PUBLICATION"


class ExecutionStatus(StrEnum):
    IDLE = "IDLE"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    WAITING_USER = "WAITING_USER"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    STALE = "STALE"
    CANCELLED = "CANCELLED"


class ProjectLifecycleStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    TERMINATED = "TERMINATED"
    ARCHIVED = "ARCHIVED"
    COMPLETED = "COMPLETED"


class WorkstreamStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"


class GateLevel(StrEnum):
    G0 = "G0"
    G1 = "G1"
    G2 = "G2"
    G3 = "G3"


class GateStatus(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ArtifactLifecycle(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    FROZEN = "FROZEN"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    SUPERSEDED = "SUPERSEDED"


class ValidationStatus(StrEnum):
    NOT_RUN = "NOT_RUN"
    PASSED = "PASSED"
    WARNING = "WARNING"
    FAILED = "FAILED"


class ApprovalStatus(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReviewPolicy(StrEnum):
    REVIEWER_REQUIRED = "REVIEWER_REQUIRED"
    SELF_REVIEW_ALLOWED = "SELF_REVIEW_ALLOWED"
    REHEARSAL_ONLY = "REHEARSAL_ONLY"


class ResearchRouteDecision(_Model):
    decision_id: str = Field(default_factory=lambda: f"route-{uuid4().hex}")
    project_id: str
    primary_route: str
    research_scope: str = ""
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)
    applicable_modules: list[str] = Field(default_factory=list)
    skipped_modules: list[str] = Field(default_factory=list)
    skip_reasons: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    requires_user_confirmation: bool = True
    policy_version: str = "route-policy-v1"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BlockingIssueRecord(_Model):
    issue_id: str = Field(default_factory=lambda: f"blocker-{uuid4().hex}")
    project_id: str
    workstream_id: str
    code: str
    message: str
    priority: int = Field(ge=1, le=100)
    status: str = "OPEN"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None
    resolution_ref: str | None = None


class GateRecord(_Model):
    gate_id: str = Field(default_factory=lambda: f"gate-{uuid4().hex}")
    project_id: str
    workstream_id: str
    gate_type: str
    level: GateLevel
    status: GateStatus = GateStatus.PENDING
    artifact_ids: list[str] = Field(default_factory=list)
    reason: str
    warnings: list[str] = Field(default_factory=list)
    risk_acceptance: list[str] = Field(default_factory=list)
    requested_by: str = "orchestrator"
    decided_by: str | None = None
    decision_reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    decided_at: datetime | None = None


class ArtifactRecord(_Model):
    artifact_id: str = Field(default_factory=lambda: f"artifact-{uuid4().hex}")
    project_id: str
    workstream_id: str
    artifact_type: str
    version: int = Field(ge=1)
    lifecycle_status: ArtifactLifecycle = ArtifactLifecycle.DRAFT
    validation_status: ValidationStatus = ValidationStatus.NOT_RUN
    approval_status: ApprovalStatus = ApprovalStatus.NOT_REQUIRED
    content_uri: str
    content_sha256: str = Field(min_length=64, max_length=64)
    created_by: str
    parent_artifact_ids: list[str] = Field(default_factory=list)
    source_evidence_ids: list[str] = Field(default_factory=list)
    source_dataset_ids: list[str] = Field(default_factory=list)
    source_code_ids: list[str] = Field(default_factory=list)
    source_result_ids: list[str] = Field(default_factory=list)
    supersedes_artifact_id: str | None = None
    superseded_by: str | None = None
    synthetic_data: bool = False
    effective: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ClaimRecord(_Model):
    claim_id: str = Field(default_factory=lambda: f"claim-{uuid4().hex}")
    project_id: str
    manuscript_artifact_id: str
    section: str
    claim_text: str
    claim_type: str
    support_type: str
    support_evidence_ids: list[str] = Field(default_factory=list)
    support_result_ids: list[str] = Field(default_factory=list)
    support_artifact_ids: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    verification_status: ValidationStatus = ValidationStatus.NOT_RUN
    reviewer_status: GateStatus = GateStatus.NOT_REQUIRED


class WorkstreamControlState(_Model):
    workstream_id: str
    name: str
    route: str
    status: WorkstreamStatus = WorkstreamStatus.ACTIVE
    phase: ResearchPhase = ResearchPhase.PROJECT_INGESTION
    execution_status: ExecutionStatus = ExecutionStatus.IDLE
    current_action: str | None = None
    artifact_ids: list[str] = Field(default_factory=list)
    gate_ids: list[str] = Field(default_factory=list)
    blocker_ids: list[str] = Field(default_factory=list)
    state_revision: int = 0
    workflow_steps: list[str] = Field(default_factory=list)
    current_step_index: int = 0
    completed_step_ids: list[str] = Field(default_factory=list)
    skipped_step_ids: list[str] = Field(default_factory=list)
    # Conversational pauses are durable checkpoints, not implementation
    # details exposed as a Gate card.  The chat layer consumes this value and
    # resumes orchestration only after the researcher responds.
    conversation_checkpoint: str | None = None
    # Researcher language collected at a checkpoint is an input to the next
    # candidate version.  It must not be concatenated into the canonical
    # project title/scope, which is reused in manuscript headings.
    conversation_feedback: dict[str, str] = Field(default_factory=dict)


class ControlState(_Model):
    project_id: str
    lifecycle_status: ProjectLifecycleStatus = ProjectLifecycleStatus.ACTIVE
    review_policy: ReviewPolicy = ReviewPolicy.REVIEWER_REQUIRED
    state_revision: int = 0
    target_journal: str | None = None
    article_type: str | None = None
    workstreams: list[WorkstreamControlState] = Field(default_factory=list)
    route_decision: ResearchRouteDecision | None = None
    active_workstream_id: str | None = None
    active_gate_id: str | None = None
    active_blocking_issue_id: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TaskLease(_Model):
    task_id: str = Field(default_factory=lambda: f"task-{uuid4().hex}")
    project_id: str
    workstream_id: str
    action: str
    status: ExecutionStatus = ExecutionStatus.QUEUED
    claimed_by: str | None = None
    lease_until: datetime | None = None
    heartbeat_at: datetime | None = None
    attempt: int = 0
    max_attempts: int = Field(default=3, ge=1, le=10)
    idempotency_key: str
    input_hash: str
    expected_state_revision: int
    output_artifact_ids: list[str] = Field(default_factory=list)
    error: str | None = None
    next_attempt_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ResearchRun(_Model):
    """User-facing view of a long-running research task.

    A run is intentionally separate from the chat thread. The existing task
    lease remains the execution primitive and audit record; this stable view is
    what clients can show as progress without exposing workflow gates.
    """

    run_id: str
    project_id: str
    run_type: Literal["literature", "analysis", "writing", "workflow"]
    action: str
    status: ExecutionStatus
    output_artifact_ids: list[str] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class AuditEvent(_Model):
    event_id: str = Field(default_factory=lambda: f"event-{uuid4().hex}")
    project_id: str
    event_type: str
    actor: str
    state_revision: int
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ConcurrentStateError(RuntimeError):
    """Raised when a worker tries to write against an old state revision."""


class ControlPlaneRepository(Protocol):
    def get_state(self, project_id: str) -> ControlState | None: ...

    def save_state(self, state: ControlState, expected_revision: int) -> ControlState: ...

    def save_state_and_event(
        self,
        state: ControlState,
        expected_revision: int,
        *,
        event_type: str,
        actor: str,
        payload: dict[str, Any] | None = None,
    ) -> ControlState: ...

    def put_gate(self, gate: GateRecord) -> GateRecord: ...

    def get_gate(self, project_id: str, gate_id: str) -> GateRecord | None: ...

    def put_blocker(self, blocker: BlockingIssueRecord) -> BlockingIssueRecord: ...

    def get_blocker(self, project_id: str, issue_id: str) -> BlockingIssueRecord | None: ...

    def list_blockers(self, project_id: str) -> list[BlockingIssueRecord]: ...

    def put_artifact(self, artifact: ArtifactRecord) -> ArtifactRecord: ...

    def update_artifact(self, artifact: ArtifactRecord) -> ArtifactRecord: ...

    def list_artifacts(self, project_id: str) -> list[ArtifactRecord]: ...

    def put_claim(self, claim: ClaimRecord) -> ClaimRecord: ...

    def list_claims(self, project_id: str, manuscript_artifact_id: str | None = None) -> list[ClaimRecord]: ...

    def add_event(self, event: AuditEvent) -> AuditEvent: ...

    def list_events(self, project_id: str, after_id: str | None = None) -> list[AuditEvent]: ...

    def enqueue(self, task: TaskLease) -> TaskLease: ...

    def get_task(self, project_id: str, task_id: str) -> TaskLease | None: ...

    def claim(
        self, worker_id: str, lease_seconds: int = 60, *, project_id: str | None = None
    ) -> TaskLease | None: ...

    def heartbeat(self, task_id: str, worker_id: str, lease_seconds: int = 60) -> TaskLease | None: ...

    def update_task(self, task: TaskLease) -> TaskLease: ...

    def list_tasks(self, project_id: str) -> list[TaskLease]: ...

    def list_pending_tasks(self) -> list[TaskLease]: ...


def _json(model: BaseModel) -> str:
    return model.model_dump_json()


ModelT = TypeVar("ModelT", bound=BaseModel)


def _model(cls: type[ModelT], value: str) -> ModelT:
    return cls.model_validate_json(value)


def _string_list(value: object) -> list[str]:
    """Normalize untyped claim payload lists at the API boundary."""

    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value]


class SQLiteControlPlaneRepository:
    """SQLite repository with optimistic revision checks and WAL mode."""

    def __init__(self, database: Path) -> None:
        self.database = database
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        with self._connect() as connection:
            connection.executescript(
                """
                pragma journal_mode = wal;
                create table if not exists orchestration_states (
                    project_id text primary key,
                    state_revision integer not null,
                    body text not null,
                    updated_at text not null
                );
                create table if not exists orchestration_gates (
                    project_id text not null,
                    gate_id text not null,
                    body text not null,
                    primary key (project_id, gate_id)
                );
                create table if not exists orchestration_blockers (
                    project_id text not null,
                    issue_id text not null,
                    body text not null,
                    primary key (project_id, issue_id)
                );
                create table if not exists orchestration_artifacts (
                    project_id text not null,
                    artifact_id text not null,
                    version integer not null,
                    body text not null,
                    primary key (project_id, artifact_id, version)
                );
                create table if not exists orchestration_claims (
                    project_id text not null,
                    claim_id text not null,
                    manuscript_artifact_id text not null,
                    body text not null,
                    primary key (project_id, claim_id)
                );
                create table if not exists orchestration_events (
                    event_id text primary key,
                    project_id text not null,
                    created_at text not null,
                    body text not null
                );
                create table if not exists orchestration_outbox (
                    event_id text primary key,
                    project_id text not null,
                    delivered integer not null default 0,
                    body text not null
                );
                create table if not exists orchestration_tasks (
                    task_id text primary key,
                    project_id text not null,
                    status text not null,
                    lease_until text,
                    idempotency_key text,
                    body text not null
                );
                """
            )
            # Older development databases predate the explicit idempotency
            # column.  Migrate them in place and recover keys from the durable
            # task JSON before creating the uniqueness constraint.
            task_columns = {
                str(row[1])
                for row in connection.execute("pragma table_info(orchestration_tasks)").fetchall()
            }
            if "idempotency_key" not in task_columns:
                connection.execute("alter table orchestration_tasks add column idempotency_key text")
                rows = connection.execute("select task_id,body from orchestration_tasks").fetchall()
                for row in rows:
                    try:
                        key = str(json.loads(row[1]).get("idempotency_key") or "")
                    except (TypeError, json.JSONDecodeError):
                        key = ""
                    connection.execute(
                        "update orchestration_tasks set idempotency_key=? where task_id=?",
                        (key or None, row[0]),
                    )
            connection.execute(
                "create unique index if not exists orchestration_tasks_idempotency"
                " on orchestration_tasks(project_id,idempotency_key)"
                " where idempotency_key is not null and idempotency_key <> ''"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("pragma busy_timeout = 30000")
        return connection

    def get_state(self, project_id: str) -> ControlState | None:
        with self._connect() as connection:
            row = connection.execute(
                "select body from orchestration_states where project_id=?", (project_id,)
            ).fetchone()
        return _model(ControlState, row[0]) if row else None

    def save_state(self, state: ControlState, expected_revision: int) -> ControlState:
        state = state.model_copy(
            update={"state_revision": expected_revision + 1, "updated_at": datetime.now(UTC)}
        )
        with self._lock, self._connect() as connection:
            if expected_revision == 0:
                cursor = connection.execute(
                    "insert or ignore into orchestration_states(project_id,state_revision,body,updated_at) values (?,?,?,?)",
                    (state.project_id, state.state_revision, _json(state), state.updated_at.isoformat()),
                )
                if cursor.rowcount == 0:
                    raise ConcurrentStateError(f"state already exists: {state.project_id}")
            else:
                cursor = connection.execute(
                    "update orchestration_states set state_revision=?, body=?, updated_at=? where project_id=? and state_revision=?",
                    (state.state_revision, _json(state), state.updated_at.isoformat(), state.project_id, expected_revision),
                )
                if cursor.rowcount != 1:
                    raise ConcurrentStateError(f"state revision mismatch: {state.project_id}")
        return state

    def save_state_and_event(
        self,
        state: ControlState,
        expected_revision: int,
        *,
        event_type: str,
        actor: str,
        payload: dict[str, Any] | None = None,
    ) -> ControlState:
        """Commit the authoritative snapshot and its SSE/audit outbox atomically."""

        saved = state.model_copy(
            update={"state_revision": expected_revision + 1, "updated_at": datetime.now(UTC)}
        )
        event = AuditEvent(
            project_id=saved.project_id,
            event_type=event_type,
            actor=actor,
            state_revision=saved.state_revision,
            payload=payload or {},
        )
        with self._lock, self._connect() as connection:
            if expected_revision == 0:
                cursor = connection.execute(
                    "insert or ignore into orchestration_states(project_id,state_revision,body,updated_at) values (?,?,?,?)",
                    (saved.project_id, saved.state_revision, _json(saved), saved.updated_at.isoformat()),
                )
                if cursor.rowcount == 0:
                    raise ConcurrentStateError(f"state already exists: {saved.project_id}")
            else:
                cursor = connection.execute(
                    "update orchestration_states set state_revision=?, body=?, updated_at=? where project_id=? and state_revision=?",
                    (saved.state_revision, _json(saved), saved.updated_at.isoformat(), saved.project_id, expected_revision),
                )
                if cursor.rowcount != 1:
                    raise ConcurrentStateError(f"state revision mismatch: {saved.project_id}")
            body = _json(event)
            connection.execute(
                "insert into orchestration_events(event_id,project_id,created_at,body) values (?,?,?,?)",
                (event.event_id, event.project_id, event.created_at.isoformat(), body),
            )
            connection.execute(
                "insert into orchestration_outbox(event_id,project_id,body) values (?,?,?)",
                (event.event_id, event.project_id, body),
            )
        return saved

    def put_gate(self, gate: GateRecord) -> GateRecord:
        with self._connect() as connection:
            connection.execute(
                "insert into orchestration_gates(project_id,gate_id,body) values (?,?,?) on conflict(project_id,gate_id) do update set body=excluded.body",
                (gate.project_id, gate.gate_id, _json(gate)),
            )
        return gate

    def get_gate(self, project_id: str, gate_id: str) -> GateRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "select body from orchestration_gates where project_id=? and gate_id=?",
                (project_id, gate_id),
            ).fetchone()
        return _model(GateRecord, row[0]) if row else None

    def put_blocker(self, blocker: BlockingIssueRecord) -> BlockingIssueRecord:
        with self._connect() as connection:
            connection.execute(
                "insert into orchestration_blockers(project_id,issue_id,body) values (?,?,?) on conflict(project_id,issue_id) do update set body=excluded.body",
                (blocker.project_id, blocker.issue_id, _json(blocker)),
            )
        return blocker

    def get_blocker(self, project_id: str, issue_id: str) -> BlockingIssueRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "select body from orchestration_blockers where project_id=? and issue_id=?",
                (project_id, issue_id),
            ).fetchone()
        return _model(BlockingIssueRecord, row[0]) if row else None

    def list_blockers(self, project_id: str) -> list[BlockingIssueRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "select body from orchestration_blockers where project_id=? order by rowid",
                (project_id,),
            ).fetchall()
        return [_model(BlockingIssueRecord, row[0]) for row in rows]

    def put_artifact(self, artifact: ArtifactRecord) -> ArtifactRecord:
        with self._connect() as connection:
            connection.execute(
                "insert into orchestration_artifacts(project_id,artifact_id,version,body) values (?,?,?,?)",
                (artifact.project_id, artifact.artifact_id, artifact.version, _json(artifact)),
            )
        return artifact

    def update_artifact(self, artifact: ArtifactRecord) -> ArtifactRecord:
        with self._connect() as connection:
            connection.execute(
                "update orchestration_artifacts set body=? where project_id=? and artifact_id=? and version=?",
                (_json(artifact), artifact.project_id, artifact.artifact_id, artifact.version),
            )
        return artifact

    def list_artifacts(self, project_id: str) -> list[ArtifactRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "select body from orchestration_artifacts where project_id=? order by json_extract(body, '$.created_at'), artifact_id,version",
                (project_id,),
            ).fetchall()
        return [_model(ArtifactRecord, row[0]) for row in rows]

    def put_claim(self, claim: ClaimRecord) -> ClaimRecord:
        with self._connect() as connection:
            connection.execute(
                "insert into orchestration_claims(project_id,claim_id,manuscript_artifact_id,body) values (?,?,?,?) "
                "on conflict(project_id,claim_id) do update set manuscript_artifact_id=excluded.manuscript_artifact_id,body=excluded.body",
                (claim.project_id, claim.claim_id, claim.manuscript_artifact_id, _json(claim)),
            )
        return claim

    def list_claims(self, project_id: str, manuscript_artifact_id: str | None = None) -> list[ClaimRecord]:
        query = "select body from orchestration_claims where project_id=?"
        params: list[object] = [project_id]
        if manuscript_artifact_id is not None:
            query += " and manuscript_artifact_id=?"
            params.append(manuscript_artifact_id)
        query += " order by rowid"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_model(ClaimRecord, row[0]) for row in rows]

    def add_event(self, event: AuditEvent) -> AuditEvent:
        with self._connect() as connection:
            body = _json(event)
            connection.execute(
                "insert into orchestration_events(event_id,project_id,created_at,body) values (?,?,?,?)",
                (event.event_id, event.project_id, event.created_at.isoformat(), body),
            )
            connection.execute(
                "insert into orchestration_outbox(event_id,project_id,body) values (?,?,?)",
                (event.event_id, event.project_id, body),
            )
        return event

    def list_events(self, project_id: str, after_id: str | None = None) -> list[AuditEvent]:
        query = "select body from orchestration_events where project_id=?"
        params: list[object] = [project_id]
        if after_id:
            # Several events can share the same SQLite timestamp precision.
            # Use the event id as a deterministic tie-breaker for resuming.
            query += (
                " and (created_at > (select created_at from orchestration_events where event_id=?) "
                "or (created_at = (select created_at from orchestration_events where event_id=?) "
                "and event_id > ?))"
            )
            params.extend([after_id, after_id, after_id])
        query += " order by created_at,event_id"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_model(AuditEvent, row[0]) for row in rows]

    def enqueue(self, task: TaskLease) -> TaskLease:
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                "select body from orchestration_tasks where project_id=? and idempotency_key=?",
                (task.project_id, task.idempotency_key),
            ).fetchone()
            if existing:
                return _model(TaskLease, existing[0])
            connection.execute(
                "insert into orchestration_tasks(task_id,project_id,status,lease_until,idempotency_key,body) values (?,?,?,?,?,?)",
                (task.task_id, task.project_id, task.status.value, None, task.idempotency_key, _json(task)),
            )
        return task

    def claim(
        self, worker_id: str, lease_seconds: int = 60, *, project_id: str | None = None
    ) -> TaskLease | None:
        now = datetime.now(UTC)
        until = now + timedelta(seconds=lease_seconds)
        with self._lock, self._connect() as connection:
            if project_id is None:
                rows = connection.execute(
                    "select task_id,body from orchestration_tasks where status in ('QUEUED','RUNNING') order by rowid"
                ).fetchall()
            else:
                rows = connection.execute(
                    "select task_id,body from orchestration_tasks "
                    "where project_id=? and status in ('QUEUED','RUNNING') order by rowid",
                    (project_id,),
                ).fetchall()
            for row in rows:
                task = _model(TaskLease, row[1])
                if task.next_attempt_at is not None and task.next_attempt_at > now:
                    continue
                if task.status is ExecutionStatus.RUNNING and task.lease_until and task.lease_until > now:
                    continue
                task = task.model_copy(
                    update={
                        "status": ExecutionStatus.RUNNING,
                        "claimed_by": worker_id,
                        "lease_until": until,
                        "heartbeat_at": now,
                        "attempt": task.attempt + 1,
                    }
                )
                connection.execute(
                    "update orchestration_tasks set status=?,lease_until=?,body=? where task_id=?",
                    (task.status.value, until.isoformat(), _json(task), task.task_id),
                )
                return task
        return None

    def update_task(self, task: TaskLease) -> TaskLease:
        with self._connect() as connection:
            connection.execute(
                "update orchestration_tasks set status=?,lease_until=?,body=? where task_id=?",
                (task.status.value, task.lease_until.isoformat() if task.lease_until else None, _json(task), task.task_id),
            )
        return task

    def heartbeat(self, task_id: str, worker_id: str, lease_seconds: int = 60) -> TaskLease | None:
        now = datetime.now(UTC)
        until = now + timedelta(seconds=max(1, lease_seconds))
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "select body from orchestration_tasks where task_id=?", (task_id,)
            ).fetchone()
            if not row:
                return None
            task = _model(TaskLease, row[0])
            if task.status is not ExecutionStatus.RUNNING or task.claimed_by != worker_id:
                return None
            refreshed = task.model_copy(update={"lease_until": until, "heartbeat_at": now})
            connection.execute(
                "update orchestration_tasks set lease_until=?,body=? where task_id=?",
                (until.isoformat(), _json(refreshed), task_id),
            )
            return refreshed

    def list_tasks(self, project_id: str) -> list[TaskLease]:
        with self._connect() as connection:
            rows = connection.execute(
                "select body from orchestration_tasks where project_id=? order by rowid",
                (project_id,),
            ).fetchall()
        return [_model(TaskLease, row[0]) for row in rows]

    def list_pending_tasks(self) -> list[TaskLease]:
        """Return queued or expired-running tasks for process recovery."""

        now = datetime.now(UTC)
        with self._connect() as connection:
            rows = connection.execute(
                "select body from orchestration_tasks where status in ('QUEUED','RUNNING') order by rowid"
            ).fetchall()
        pending: list[TaskLease] = []
        for row in rows:
            task = _model(TaskLease, row[0])
            if task.next_attempt_at is not None and task.next_attempt_at > now:
                continue
            if task.status is ExecutionStatus.QUEUED or task.lease_until is None or task.lease_until <= now:
                pending.append(task)
        return pending

    def get_task(self, project_id: str, task_id: str) -> TaskLease | None:
        with self._connect() as connection:
            row = connection.execute(
                "select body from orchestration_tasks where project_id=? and task_id=?",
                (project_id, task_id),
            ).fetchone()
        return _model(TaskLease, row[0]) if row else None


class ControlPlane:
    """Condition-driven state transitions used by API and workers."""

    def __init__(self, repository: ControlPlaneRepository) -> None:
        self.repository = repository
        self._lock = RLock()

    def _save_state_event(
        self,
        state: ControlState,
        *,
        event_type: str,
        actor: str,
        payload: dict[str, Any] | None = None,
    ) -> ControlState:
        """Use the atomic repository path while retaining test-double compatibility."""

        commit = cast(
            Callable[..., ControlState] | None,
            getattr(self.repository, "save_state_and_event", None),
        )
        if callable(commit):
            return commit(
                state,
                state.state_revision,
                event_type=event_type,
                actor=actor,
                payload=payload,
            )
        saved = self.repository.save_state(state, expected_revision=state.state_revision)
        self.repository.add_event(
            AuditEvent(
                project_id=saved.project_id,
                event_type=event_type,
                actor=actor,
                state_revision=saved.state_revision,
                payload=payload or {},
            )
        )
        return saved

    def _active_blocker_id(self, project_id: str) -> str | None:
        """Choose one UI-facing blocker while retaining every open record."""

        open_blockers = [
            item for item in self.repository.list_blockers(project_id)
            if item.status == "OPEN"
        ]
        if not open_blockers:
            return None
        selected = min(
            open_blockers,
            key=lambda item: (-item.priority, item.created_at, item.issue_id),
        )
        return selected.issue_id

    def record_manuscript_claims(
        self,
        project_id: str,
        manuscript_artifact_id: str,
        claim_payloads: list[dict[str, object]],
    ) -> list[ClaimRecord]:
        """Persist the candidate's atomic claims beside its immutable artifact.

        The candidate writer supplies explicit support references.  This method
        stores provenance only; it intentionally does not certify a claim as
        supported, because certification remains the citation/reviewer Gate.
        """

        stored: list[ClaimRecord] = []
        for item in claim_payloads:
            claim_id = str(item.get("claim_id") or "").strip()
            claim_text = str(item.get("claim_text") or "").strip()
            section = str(item.get("section") or "").strip()
            claim_type = str(item.get("claim_type") or "").strip()
            support_type = str(item.get("support_type") or "").strip()
            if not all((claim_id, claim_text, section, claim_type, support_type)):
                raise ValueError("manuscript claim payload is incomplete")
            record = ClaimRecord(
                claim_id=claim_id,
                project_id=project_id,
                manuscript_artifact_id=manuscript_artifact_id,
                section=section,
                claim_text=claim_text,
                claim_type=claim_type,
                support_type=support_type,
                support_evidence_ids=_string_list(item.get("support_evidence_ids")),
                support_result_ids=_string_list(item.get("support_result_ids")),
                support_artifact_ids=_string_list(item.get("support_artifact_ids")),
            )
            stored.append(self.repository.put_claim(record))
        return stored

    _WORKFLOW_STEPS: tuple[str, ...] = (
        "create_project",
        "import_materials",
        "evidence_normalization",
        "hybrid_retrieval",
        "rrf_fusion",
        "cross_encoder_rerank",
        "claim_evidence_support",
        "research_question_design",
        "causal_DAG",
        "power_analysis",
        "preregistration_freeze",
        "raw_data_import",
        "data_audit",
        "data_processing_approval",
        "dataset_freeze_hash",
        "analysis_code_generation",
        "physics_code_validation",
        "code_review",
        "manual_execution_approval",
        "sandbox_analysis_execution",
        "pattern_code_generation",
        "pattern_smoke_execution",
        "pattern_stability_execution",
        "pattern_discovery_review",
        "codebook_review",
        "manual_theme_revision",
        "supervised_confirmation",
        "student_level_robustness",
        "group_comparison",
        "result_card_review",
        "statistical_result_validation",
        "bootstrap_robustness",
        "permutation_test",
        "result_direction_consistency",
        "uncertainty_gate",
        "statistical_result_card",
        "manuscript_citation_verification",
        "reviewer_final_confirmation",
    )

    _STEP_PHASES: ClassVar[dict[str, ResearchPhase]] = {
        "evidence_normalization": ResearchPhase.EVIDENCE_PREPARATION,
        "hybrid_retrieval": ResearchPhase.EVIDENCE_PREPARATION,
        "rrf_fusion": ResearchPhase.EVIDENCE_PREPARATION,
        "cross_encoder_rerank": ResearchPhase.EVIDENCE_PREPARATION,
        "claim_evidence_support": ResearchPhase.EVIDENCE_PREPARATION,
        "research_question_design": ResearchPhase.RESEARCH_DESIGN,
        "research_design": ResearchPhase.RESEARCH_DESIGN,
        "causal_DAG": ResearchPhase.RESEARCH_DESIGN,
        "power_analysis": ResearchPhase.RESEARCH_DESIGN,
        "preregistration_freeze": ResearchPhase.RESEARCH_DESIGN,
        "raw_data_import": ResearchPhase.DATA_PREPARATION,
        "data_audit": ResearchPhase.DATA_PREPARATION,
        "data_processing_approval": ResearchPhase.DATA_PREPARATION,
        "dataset_freeze_hash": ResearchPhase.DATA_PREPARATION,
        "analysis_code_generation": ResearchPhase.ANALYSIS_EXECUTION,
        "physics_code_validation": ResearchPhase.ANALYSIS_EXECUTION,
        "code_review": ResearchPhase.ANALYSIS_EXECUTION,
        "manual_execution_approval": ResearchPhase.ANALYSIS_EXECUTION,
        "sandbox_analysis_execution": ResearchPhase.ANALYSIS_EXECUTION,
        "pattern_code_generation": ResearchPhase.ANALYSIS_EXECUTION,
        "pattern_smoke_execution": ResearchPhase.ANALYSIS_EXECUTION,
        "pattern_stability_execution": ResearchPhase.ANALYSIS_EXECUTION,
        "pattern_discovery_review": ResearchPhase.ANALYSIS_EXECUTION,
        "codebook_review": ResearchPhase.ANALYSIS_EXECUTION,
        "manual_theme_revision": ResearchPhase.RESULT_VALIDATION,
        "supervised_confirmation": ResearchPhase.RESULT_VALIDATION,
        "student_level_robustness": ResearchPhase.RESULT_VALIDATION,
        "group_comparison": ResearchPhase.RESULT_VALIDATION,
        "result_card_review": ResearchPhase.RESULT_VALIDATION,
        "statistical_result_validation": ResearchPhase.RESULT_VALIDATION,
        "thematic_analysis": ResearchPhase.ANALYSIS_EXECUTION,
        "bootstrap_robustness": ResearchPhase.RESULT_VALIDATION,
        "permutation_test": ResearchPhase.RESULT_VALIDATION,
        "result_direction_consistency": ResearchPhase.RESULT_VALIDATION,
        "uncertainty_gate": ResearchPhase.RESULT_VALIDATION,
        "statistical_result_card": ResearchPhase.RESULT_VALIDATION,
        "qualitative_validation": ResearchPhase.RESULT_VALIDATION,
        "manuscript_citation_verification": ResearchPhase.WRITING_PUBLICATION,
        "writing": ResearchPhase.WRITING_PUBLICATION,
        "journal_style_revision": ResearchPhase.WRITING_PUBLICATION,
        "reviewer_final_confirmation": ResearchPhase.WRITING_PUBLICATION,
    }

    @classmethod
    def workflow_steps_for_route(cls, route: str, *, computational_qualitative: bool = False) -> tuple[str, ...]:
        """Return the route-specific ordered workflow while retaining auditability."""

        common = cls._WORKFLOW_STEPS[:8]
        if route in {"QUALITATIVE", "MIXED_QUALITATIVE"}:
            qualitative_tail = ("qualitative_design", "raw_data_import", "data_audit", "data_processing_approval", "dataset_freeze_hash")
            if computational_qualitative:
                qualitative_tail += (
                    "analysis_code_generation", "code_review", "manual_execution_approval",
                    "sandbox_analysis_execution", "pattern_code_generation", "pattern_smoke_execution",
                    "pattern_stability_execution", "pattern_discovery_review", "codebook_review",
                    "manual_theme_revision", "supervised_confirmation", "student_level_robustness",
                    "group_comparison", "result_card_review",
                )
            qualitative_tail += ("thematic_analysis", "qualitative_validation", "writing", "manuscript_citation_verification", "reviewer_final_confirmation")
            return (*common, *qualitative_tail)
        quantitative_tail = (
            "research_design", "causal_DAG", "power_analysis", "preregistration_freeze",
            "raw_data_import", "data_audit", "data_processing_approval", "dataset_freeze_hash",
            "analysis_code_generation", "physics_code_validation", "code_review",
            "manual_execution_approval", "sandbox_analysis_execution", "statistical_result_validation",
            "bootstrap_robustness", "permutation_test", "result_direction_consistency",
            "uncertainty_gate", "statistical_result_card", "writing",
            "manuscript_citation_verification", "reviewer_final_confirmation",
        )
        if route in {"EXPERIMENTAL", "OBSERVATIONAL_QUANTITATIVE", "PREDICTIVE"}:
            return (*common, *quantitative_tail)
        return (*common, *quantitative_tail)

    @classmethod
    def _step_phase(cls, step_id: str) -> ResearchPhase:
        return cls._STEP_PHASES.get(step_id, ResearchPhase.PROJECT_INGESTION)

    def ensure_project(self, project_id: str, *, review_policy: ReviewPolicy = ReviewPolicy.REVIEWER_REQUIRED) -> ControlState:
        existing = self.repository.get_state(project_id)
        if existing:
            return existing
        stream = WorkstreamControlState(workstream_id=f"ws-{project_id}-main", name="主研究线", route="UNCLASSIFIED", workflow_steps=list(self._WORKFLOW_STEPS))
        state = ControlState(
            project_id=project_id,
            review_policy=review_policy,
            workstreams=[stream],
            active_workstream_id=stream.workstream_id,
        )
        try:
            return self.repository.save_state(state, expected_revision=0)
        except ConcurrentStateError:
            return self.repository.get_state(project_id) or state

    def _classify_route(self, project_id: str, intent: str) -> ResearchRouteDecision:
        text = intent.lower()
        mixed_markers = (
            "混合方法", "混合研究", "定性和定量", "定量和定性", "量化和质性", "质性和量化",
            "同时访谈", "访谈并", "并访谈", "mixed methods", "mixed-methods", "qualitative and quantitative",
            "quantitative and qualitative", "survey and interview", "experiment and interview",
        )
        # ``编码`` is ambiguous in Chinese research descriptions: it often
        # means a qualitative coding scheme, but phrases such as ``性别编码组``
        # are ordinary quantitative group labels.  Keep strong qualitative
        # signals here and handle standalone coding terms only when they are
        # accompanied by an analysis/interview context below.
        # Match explicit qualitative-method phrases.  A bare ``定性`` also
        # appears inside ordinary risk language such as ``不确定性说明`` and
        # must not reroute an otherwise quantitative project.
        qualitative_markers = (
            "定性研究", "定性分析", "定性资料", "定性方法", "访谈", "主题分析", "qualitative", "教师如何", "教师需求",
            "专业学习需求", "课堂实践", "教学实践", "实施经历", "观点", "经验", "如何整合",
            "how do teachers", "teacher experience", "professional learning needs",
        )
        qualitative_coding = (
            "编码分析", "编码框架", "编码一致性", "开放式编码", "轴心编码", "选择性编码",
            "coding analysis", "coding framework", "inter-coder", "intercoder",
        )
        quantitative_markers = (
            "观察性", "描述性差异", "两组比较", "组间差异", "定量", "量化",
            "统计分析", "统计比较", "group", "transfer_score", "p 值", "置信区间",
            "observational", "quantitative", "descriptive comparison",
        )
        # Explicitly declining quantitative/statistical work must override a
        # nearby mention such as “不是定量实验” or “不要执行统计分析”.
        # Without this guard, the substring “定量” wins before the strong
        # qualitative markers and routes text re-analysis into the CSV-only
        # quantitative pipeline.
        quantitative_negation = any(
            phrase in text
            for phrase in (
                "不是定量", "非定量", "不做定量", "不要定量", "暂不定量",
                "不执行统计", "不要执行统计", "不作统计", "不做统计",
            )
        )
        # Public text re-analysis is often described compactly as
        # “定性主题再分析” rather than the longer “定性研究/定性分析”.
        # Treat that explicit combination as qualitative evidence before the
        # generic comparison vocabulary can route it to the quantitative
        # pipeline.
        explicit_qualitative_reanalysis = (
            "定性" in text
            and any(term in text for term in ("主题", "文本", "语料", "再分析", "计算扎根", "质性"))
        )
        # Computational grounded-theory descriptions commonly mention
        # supervision, cross-validation, code and random seeds.  Those terms
        # describe the *validation stage* of a qualitative workflow; they do
        # not make the study experimental.  Require the surrounding text to
        # contain unmistakable sentence/topic review signals before allowing
        # the experimental branch to see those words.
        cgt_qualitative_signals = (
            "计算扎根理论", "计算扎根", "计算辅助定性", "主题候选", "主题分析",
            "句子级编码", "句子为单位", "代表句", "边界句", "噪声句",
            "人工修订主题", "人工解释", "聚类审阅", "文本主题", "语料主题",
            "学生问题解决文本", "解题描述",
            "qualitative coding", "computational grounded", "thematic analysis",
        )
        explicit_cgt_qualitative = any(term in text for term in cgt_qualitative_signals)
        if any(term in text for term in mixed_markers):
            route = "MIXED_METHODS"
            skipped: list[str] = []
            reasons: list[str] = []
            modules = [
                "literature_evidence", "research_design", "qualitative_design",
                "causal_DAG", "power_analysis", "preregistration", "data_analysis",
                "thematic_analysis", "qualitative_validation", "result_validation", "writing",
            ]
        elif (explicit_qualitative_reanalysis or explicit_cgt_qualitative) and not any(term in text for term in mixed_markers):
            route = "QUALITATIVE"
            skipped = ["causal_DAG", "power_analysis", "bootstrap_hypothesis_test", "permutation_test", "statistical_result_validation", "result_direction_consistency", "uncertainty_gate", "statistical_result_card"]
            reasons = ["研究目标是解释性主题归纳，不适用因果、功效或统计结果稳健性检验。"] * len(skipped)
            modules = ["literature_evidence", "qualitative_design", "coding_framework", "thematic_analysis", "qualitative_validation", "writing"]
        elif any(term in text for term in quantitative_markers) and not quantitative_negation and not explicit_qualitative_reanalysis and not explicit_cgt_qualitative:
            route = "OBSERVATIONAL_QUANTITATIVE"
            skipped = []
            reasons = []
            modules = ["literature_evidence", "research_design", "causal_DAG", "sensitivity_analysis", "data_analysis", "result_validation", "writing"]
        elif explicit_qualitative_reanalysis or any(term in text for term in qualitative_markers) or any(term in text for term in qualitative_coding):
            route = "QUALITATIVE"
            skipped = ["causal_DAG", "power_analysis", "bootstrap_hypothesis_test", "permutation_test", "statistical_result_validation", "result_direction_consistency", "uncertainty_gate", "statistical_result_card"]
            reasons = ["研究目标是解释性主题归纳，不适用因果、功效或统计结果稳健性检验。"] * len(skipped)
            modules = ["literature_evidence", "qualitative_design", "coding_framework", "thematic_analysis", "qualitative_validation", "writing"]
        elif any(term in text for term in ("实验", "干预", "对照", "随机", "experiment", "intervention")):
            route = "EXPERIMENTAL"
            skipped = []
            reasons = []
            modules = ["literature_evidence", "research_design", "causal_DAG", "power_analysis", "preregistration", "data_analysis", "result_validation", "writing"]
        elif any(term in text for term in ("预测", "分类", "回归预测", "predictive", "machine learning")):
            route = "PREDICTIVE"
            skipped = []
            reasons = []
            modules = ["literature_evidence", "research_design", "data_analysis", "mapie_uncertainty", "result_validation", "writing"]
        else:
            route = "OBSERVATIONAL_QUANTITATIVE"
            skipped = []
            reasons = []
            modules = ["literature_evidence", "research_design", "causal_DAG", "sensitivity_analysis", "data_analysis", "result_validation", "writing"]
        return ResearchRouteDecision(project_id=project_id, primary_route=route, research_scope=intent, confidence=0.85, evidence=["conversation_intent"], applicable_modules=modules, skipped_modules=skipped, skip_reasons=reasons, uncertainties=["路线判断来自用户描述，需在研究设计阶段进一步细化。"])

    def choose_route(self, project_id: str, intent: str, *, actor: str = "orchestrator") -> tuple[ControlState, ResearchRouteDecision, GateRecord | None]:
        with self._lock:
            state = self.ensure_project(project_id)
            route = self._classify_route(project_id, intent)
            stream = state.workstreams[0]
            skipped_step_ids = {
                "causal_DAG" if item == "causal_DAG" else
                "power_analysis" if item == "power_analysis" else
                "bootstrap_robustness" if item in {"bootstrap_hypothesis_test", "bootstrap_robustness"} else
                "permutation_test" if item == "permutation_test" else item
                for item in route.skipped_modules
            }
            stream_routes = (
                ("QUALITATIVE", "定性研究线"), ("EXPERIMENTAL", "定量/实验研究线")
            ) if route.primary_route == "MIXED_METHODS" else ((route.primary_route, "主研究线"),)
            streams: list[WorkstreamControlState] = []
            for stream_route, stream_name in stream_routes:
                computational_qualitative = (
                    stream_route == "QUALITATIVE"
                    and any(
                        marker in route.research_scope.lower()
                        for marker in ("计算扎根", "句子级编码", "句子为单位", "学生问题解决文本", "主题候选", "文本主题", "代表句", "边界句")
                    )
                )
                route_steps = list(self.workflow_steps_for_route(stream_route, computational_qualitative=computational_qualitative))
                if state.target_journal and "journal_style_revision" not in route_steps:
                    route_steps.insert(route_steps.index("writing") + 1, "journal_style_revision")
                existing_stream_id = stream.workstream_id if len(stream_routes) == 1 else f"ws-{project_id}-{'qual' if stream_route == 'QUALITATIVE' else 'quant'}"
                streams.append(stream.model_copy(update={
                    "workstream_id": existing_stream_id,
                    "name": stream_name,
                    "route": stream_route,
                    "phase": ResearchPhase.EVIDENCE_PREPARATION,
                    "current_action": "文献整理和证据规范化",
                    "workflow_steps": route_steps,
                    "current_step_index": 2,
                    "skipped_step_ids": sorted(skipped_step_ids if stream_route == "QUALITATIVE" else set()),
                    "status": WorkstreamStatus.ACTIVE,
                    "execution_status": ExecutionStatus.QUEUED,
                }))
            next_state = state.model_copy(update={"route_decision": route, "workstreams": streams, "active_workstream_id": streams[0].workstream_id})
            # Route selection is an internal planning operation. The first
            # researcher decision happens only after the evidence review
            # package has made the available and missing evidence inspectable.
            gate = None
            next_state = next_state.model_copy(update={"active_gate_id": None})
            saved = self._save_state_event(
                next_state,
                event_type="ROUTE_PROPOSED",
                actor=actor,
                payload={"route": route.model_dump(mode="json")},
            )
            return saved, route, gate

    def set_publication_target(
        self,
        project_id: str,
        *,
        target_journal: str,
        article_type: str | None = None,
        actor: str = "researcher",
    ) -> ControlState:
        """Persist a journal target and add its optional formatting stage."""
        normalized_target = target_journal.strip()
        if not normalized_target:
            raise ValueError("target journal must not be empty")
        with self._lock:
            state = self.ensure_project(project_id)
            updated_streams: list[WorkstreamControlState] = []
            for stream in state.workstreams:
                steps = list(stream.workflow_steps)
                if "journal_style_revision" not in steps:
                    insert_at = steps.index("writing") + 1 if "writing" in steps else len(steps)
                    steps.insert(insert_at, "journal_style_revision")
                updated_streams.append(stream.model_copy(update={"workflow_steps": steps}))
            next_state = state.model_copy(update={
                "target_journal": normalized_target,
                "article_type": article_type.strip() if isinstance(article_type, str) and article_type.strip() else None,
                "workstreams": updated_streams,
            })
            saved = self._save_state_event(
                next_state,
                event_type="PUBLICATION_TARGET_SET",
                actor=actor,
                payload={"target_journal": normalized_target, "article_type": next_state.article_type},
            )
            return saved

    def create_artifact(
        self,
        project_id: str,
        *,
        workstream_id: str,
        artifact_type: str,
        content_uri: str,
        content_sha256: str,
        created_by: str,
        parent_artifact_ids: list[str] | None = None,
        source_evidence_ids: list[str] | None = None,
        source_dataset_ids: list[str] | None = None,
        source_code_ids: list[str] | None = None,
        source_result_ids: list[str] | None = None,
        supersedes_artifact_id: str | None = None,
        synthetic_data: bool = False,
    ) -> ArtifactRecord:
        """Create an immutable candidate or a new revision of an artifact."""

        previous = None
        if supersedes_artifact_id:
            previous = next(
                (item for item in self.repository.list_artifacts(project_id) if item.artifact_id == supersedes_artifact_id),
                None,
            )
            if previous is None:
                raise ValueError("superseded artifact was not found")
            if previous.lifecycle_status is not ArtifactLifecycle.FROZEN:
                raise ValueError("only a frozen artifact can be revised")
            version = previous.version + 1
        else:
            version = 1
        artifact = ArtifactRecord(
            project_id=project_id,
            workstream_id=workstream_id,
            artifact_type=artifact_type,
            version=version,
            content_uri=content_uri,
            content_sha256=content_sha256,
            created_by=created_by,
            parent_artifact_ids=parent_artifact_ids or [],
            source_evidence_ids=source_evidence_ids or [],
            source_dataset_ids=source_dataset_ids or [],
            source_code_ids=source_code_ids or [],
            source_result_ids=source_result_ids or [],
            supersedes_artifact_id=supersedes_artifact_id,
            synthetic_data=synthetic_data,
        )
        self.repository.put_artifact(artifact)
        if previous:
            self.repository.update_artifact(
                previous.model_copy(update={"superseded_by": artifact.artifact_id, "effective": False, "lifecycle_status": ArtifactLifecycle.SUPERSEDED})
            )
        return artifact

    @staticmethod
    def _primary_dataset_type(route: str) -> str:
        return "RawQualitativeDataset" if route == "QUALITATIVE" else "RawQuantitativeDataset"

    def has_usable_primary_data(self, project_id: str, route: str) -> bool:
        """Whether this route has a real, validated, effective raw-data record.

        Literature and synthetic demonstration datasets intentionally cannot
        satisfy this check.  The gate is about the researcher-supplied primary
        material whose immutable document hash is recorded as a source dataset.
        """

        required_type = self._primary_dataset_type(route)
        return any(
            artifact.artifact_type == required_type
            and artifact.effective
            and not artifact.synthetic_data
            and artifact.validation_status is ValidationStatus.PASSED
            and bool(artifact.source_dataset_ids)
            for artifact in self.repository.list_artifacts(project_id)
        )

    def register_primary_data(
        self,
        project_id: str,
        *,
        content_uri: str,
        content_sha256: str,
        source_dataset_id: str,
        actor: str,
    ) -> tuple[ControlState, ArtifactRecord]:
        """Record a user-uploaded primary dataset and resolve its data blocker.

        This method deliberately stores only a reference and SHA-256 in the
        control plane.  Participant material remains in the project document
        store and is never indexed as literature evidence.
        """

        with self._lock:
            state = self.ensure_project(project_id)
            stream = next(
                (item for item in state.workstreams if item.workstream_id == state.active_workstream_id),
                state.workstreams[0],
            )
            # A mixed-method project stores its route at project level, but the
            # dataset artifact type must follow the active workstream.
            route = stream.route if stream.route != "UNCLASSIFIED" else (
                state.route_decision.primary_route if state.route_decision else stream.route
            )
            artifact_type = self._primary_dataset_type(route)
            existing = next(
                (
                    item for item in self.repository.list_artifacts(project_id)
                    if item.artifact_type == artifact_type
                    and item.effective
                    and source_dataset_id in item.source_dataset_ids
                ),
                None,
            )
            artifact = existing
            if artifact is None:
                artifact = self.create_artifact(
                    project_id,
                    workstream_id=stream.workstream_id,
                    artifact_type=artifact_type,
                    content_uri=content_uri,
                    content_sha256=content_sha256,
                    created_by=actor,
                    source_dataset_ids=[source_dataset_id],
                )
                artifact = self.validate_artifact(
                    project_id, artifact.artifact_id, status=ValidationStatus.PASSED
                )

            resolved_ids: list[str] = []
            for blocker in self.repository.list_blockers(project_id):
                if (
                    blocker.workstream_id == stream.workstream_id
                    and blocker.code == "MISSING_PRIMARY_DATA"
                    and blocker.status == "OPEN"
                ):
                    self.repository.put_blocker(
                        blocker.model_copy(
                            update={
                                "status": "RESOLVED",
                                "resolved_at": datetime.now(UTC),
                                "resolution_ref": artifact.artifact_id,
                            }
                        )
                    )
                    resolved_ids.append(blocker.issue_id)
            updated_stream = stream.model_copy(
                update={
                    "artifact_ids": list(dict.fromkeys([*stream.artifact_ids, artifact.artifact_id])),
                    "status": WorkstreamStatus.ACTIVE,
                    "execution_status": ExecutionStatus.WAITING_USER,
                    "current_action": "原始研究数据已导入，等待研究者确认",
                }
            )
            next_state = state.model_copy(
                update={
                    "active_blocking_issue_id": self._active_blocker_id(project_id),
                    "workstreams": [
                        updated_stream if item.workstream_id == stream.workstream_id else item
                        for item in state.workstreams
                    ],
                }
            )
            saved = self._save_state_event(
                next_state,
                event_type="PRIMARY_DATA_REGISTERED",
                actor=actor,
                payload={
                    "artifact_id": artifact.artifact_id,
                    "artifact_type": artifact.artifact_type,
                    "source_dataset_id": source_dataset_id,
                    "resolved_blocker_ids": resolved_ids,
                },
            )
            return saved, artifact

    def _block_missing_primary_data(
        self, state: ControlState, stream: WorkstreamControlState, *, actor: str
    ) -> None:
        """Persist the data prerequisite before declining an invalid approval."""

        existing = next(
            (
                item for item in self.repository.list_blockers(state.project_id)
                if item.workstream_id == stream.workstream_id
                and item.code == "MISSING_PRIMARY_DATA"
                and item.status == "OPEN"
            ),
            None,
        )
        blocker = existing or BlockingIssueRecord(
            project_id=state.project_id,
            workstream_id=stream.workstream_id,
            code="MISSING_PRIMARY_DATA",
            message=(
                "请先上传去标识化的原始研究数据。文献、外部检索候选和合成演示数据"
                "不能替代参与者原始资料。"
            ),
            priority=100,
        )
        self.repository.put_blocker(blocker)
        updated_stream = stream.model_copy(
            update={
                "status": WorkstreamStatus.ACTIVE,
                "execution_status": ExecutionStatus.BLOCKED,
                "current_action": "等待上传原始研究数据",
                "blocker_ids": list(dict.fromkeys([*stream.blocker_ids, blocker.issue_id])),
            }
        )
        next_state = state.model_copy(
            update={
                "active_blocking_issue_id": self._active_blocker_id(state.project_id),
                "workstreams": [
                    updated_stream if item.workstream_id == stream.workstream_id else item
                    for item in state.workstreams
                ],
            }
        )
        self._save_state_event(
            next_state,
            event_type="PRIMARY_DATA_REQUIRED",
            actor=actor,
            payload={"blocker_id": blocker.issue_id, "workstream_id": stream.workstream_id},
        )

    def validate_artifact(self, project_id: str, artifact_id: str, *, status: ValidationStatus, warnings: list[str] | None = None) -> ArtifactRecord:
        artifact = next((item for item in self.repository.list_artifacts(project_id) if item.artifact_id == artifact_id), None)
        if artifact is None:
            raise ValueError("artifact was not found")
        if artifact.lifecycle_status in {ArtifactLifecycle.FROZEN, ArtifactLifecycle.SUPERSEDED}:
            raise ValueError("frozen artifacts are immutable")
        lifecycle = ArtifactLifecycle.VALIDATED if status in {ValidationStatus.PASSED, ValidationStatus.WARNING} else ArtifactLifecycle.BLOCKED
        updated = artifact.model_copy(update={"validation_status": status, "lifecycle_status": lifecycle})
        self.repository.update_artifact(updated)
        return updated

    def freeze_artifact(self, project_id: str, artifact_id: str, *, actor: str, risk_acceptance: list[str] | None = None) -> ArtifactRecord:
        artifact = next((item for item in self.repository.list_artifacts(project_id) if item.artifact_id == artifact_id), None)
        if artifact is None:
            raise ValueError("artifact was not found")
        if artifact.validation_status is ValidationStatus.FAILED:
            raise ValueError("failed validation cannot be frozen")
        if artifact.validation_status is ValidationStatus.NOT_RUN:
            raise ValueError("artifact must be validated before freezing")
        if artifact.validation_status is ValidationStatus.WARNING and not risk_acceptance:
            raise ValueError("risk acceptance is required for validation warnings")
        updated = artifact.model_copy(update={"lifecycle_status": ArtifactLifecycle.FROZEN, "approval_status": ApprovalStatus.APPROVED})
        self.repository.update_artifact(updated)
        self.repository.add_event(AuditEvent(project_id=project_id, event_type="ARTIFACT_FROZEN", actor=actor, state_revision=self.ensure_project(project_id).state_revision, payload={"artifact_id": artifact_id, "risk_acceptance": risk_acceptance or []}))
        return updated

    def decide_gate(self, project_id: str, gate_id: str, *, decision: str, actor: str, role: str = "researcher", risk_acceptance: list[str] | None = None, reason: str | None = None) -> ControlState:
        with self._lock:
            state = self.ensure_project(project_id)
            gate = self.repository.get_gate(project_id, gate_id)
            if gate is None or gate.status is not GateStatus.PENDING:
                raise ValueError("gate is not pending")
            if state.active_gate_id != gate_id:
                raise ValueError("gate is not active")
            if decision not in {"approve", "reject", "revise", "stop"}:
                raise ValueError("unsupported gate decision")
            is_final_reviewer_gate = gate.gate_type == "reviewer_final_confirmation_approval"
            is_mixed_merge_gate = gate.gate_type == "mixed_methods_merge_approval"
            if gate.level is GateLevel.G3 and not is_final_reviewer_gate and role not in {"researcher", "admin"}:
                raise PermissionError("G3 decision requires researcher or admin role")
            if (
                decision == "approve"
                and is_final_reviewer_gate
                and state.review_policy is ReviewPolicy.REVIEWER_REQUIRED
            ):
                if role != "reviewer":
                    raise PermissionError(
                        "独立审稿为必需条件。请由项目所有者添加具备 reviewer 角色的独立审稿人完成最终确认，"
                        "或在项目开始前明确采用允许自审的审稿政策。"
                    )
                if actor == gate.requested_by:
                    raise PermissionError("审稿人不能批准自己生成的审稿包。请由另一位独立审稿人确认。")
            elif decision == "approve" and is_final_reviewer_gate and role not in {"researcher", "admin", "reviewer"}:
                raise PermissionError("最终审稿确认需要 researcher、admin 或 reviewer 角色")
            if gate.warnings and not risk_acceptance and decision == "approve":
                raise ValueError("risk acceptance is required for warnings")
            stream = next(
                (item for item in state.workstreams if item.workstream_id == gate.workstream_id),
                None,
            )
            if stream is None:
                raise ValueError("gate workstream no longer exists")
            if (
                decision == "approve"
                and gate.gate_type == "raw_data_import_approval"
                and not self.has_usable_primary_data(project_id, stream.route)
            ):
                self._block_missing_primary_data(state, stream, actor=actor)
                raise ValueError(
                    "原始研究数据尚未上传。请先上传去标识化的原始资料；文献和演示数据不能通过该 Gate。"
                )
            if decision == "approve":
                failed_artifact = next(
                    (
                        artifact
                        for artifact in self.repository.list_artifacts(project_id)
                        if artifact.artifact_id in gate.artifact_ids
                        and artifact.validation_status is ValidationStatus.FAILED
                    ),
                    None,
                )
                if failed_artifact is not None:
                    raise ValueError(
                        f"{failed_artifact.artifact_type} 未通过验证，不能通过该 Gate。请先修正并创建新版本。"
                    )
            now = datetime.now(UTC)
            if decision == "stop":
                new_gate = gate.model_copy(update={"status": GateStatus.REJECTED, "decided_by": actor, "decision_reason": reason or "project terminated", "decided_at": now})
                next_state = state.model_copy(update={"lifecycle_status": ProjectLifecycleStatus.TERMINATED, "active_gate_id": None})
            elif decision in {"reject", "revise"}:
                new_gate = gate.model_copy(update={"status": GateStatus.REJECTED, "decided_by": actor, "decision_reason": reason or decision, "decided_at": now})
                if decision == "revise" and gate.gate_type == "evidence_sufficiency_review" and stream is not None:
                    # Keep the prior package immutable for audit, then rebuild
                    # the evidence chain against the user's revised scope or
                    # newly added materials.
                    reset_index = stream.workflow_steps.index("evidence_normalization")
                    updated_stream = stream.model_copy(update={
                        "phase": ResearchPhase.EVIDENCE_PREPARATION,
                        "execution_status": ExecutionStatus.QUEUED,
                        "current_action": "等待重新整理文献与证据",
                        "current_step_index": reset_index,
                    })
                    next_state = state.model_copy(update={
                        "active_gate_id": None,
                        "workstreams": [
                            updated_stream if item.workstream_id == gate.workstream_id else item
                            for item in state.workstreams
                        ],
                    })
                elif (
                    decision == "revise"
                    and gate.gate_type == "manuscript_citation_verification_approval"
                    and stream is not None
                ):
                    # A failed citation-linkage check must regenerate the
                    # manuscript before verification is attempted again. The
                    # failed verification artifact and prior manuscript remain
                    # immutable audit records; only the active step moves back
                    # to writing for a new candidate version.
                    reset_index = stream.workflow_steps.index("writing")
                    updated_stream = stream.model_copy(update={
                        "phase": ResearchPhase.WRITING_PUBLICATION,
                        "execution_status": ExecutionStatus.QUEUED,
                        "current_action": "等待重新生成论文草稿",
                        "current_step_index": reset_index,
                        "conversation_checkpoint": None,
                    })
                    next_state = state.model_copy(update={
                        "active_gate_id": None,
                        "workstreams": [
                            updated_stream if item.workstream_id == stream.workstream_id else item
                            for item in state.workstreams
                        ],
                    })
                else:
                    next_state = state.model_copy(update={"active_gate_id": None})
            else:
                new_gate = gate.model_copy(update={"status": GateStatus.APPROVED, "decided_by": actor, "decision_reason": reason, "risk_acceptance": risk_acceptance or [], "decided_at": now})
                if gate.gate_type == "research_route":
                    # Route confirmation closes the intake/evidence decision
                    # boundary while preserving the explicit evidence steps.
                    next_index = max(stream.current_step_index, 2)
                    completed = [
                        *stream.completed_step_ids,
                        *[step for step in stream.workflow_steps[:next_index] if step not in stream.completed_step_ids],
                    ]
                else:
                    next_index = stream.current_step_index + 1
                    completed = stream.completed_step_ids
                    if gate.gate_type == "qualitative_design_approval":
                        next_index = max(next_index, stream.workflow_steps.index("raw_data_import") if "raw_data_import" in stream.workflow_steps else next_index)
                    elif gate.gate_type == "qualitative_data_preparation_approval":
                        # Compatibility with the original coarse qualitative
                        # workflow: preparation approval opens thematic analysis.
                        next_index = max(next_index, stream.workflow_steps.index("thematic_analysis") if "thematic_analysis" in stream.workflow_steps else next_index)
                    skipped = set(stream.skipped_step_ids)
                    while next_index < len(stream.workflow_steps) and stream.workflow_steps[next_index] in skipped:
                        self.repository.add_event(AuditEvent(project_id=project_id, event_type="STEP_SKIPPED", actor="orchestrator", state_revision=state.state_revision, payload={"step_id": stream.workflow_steps[next_index], "reason": "route_policy"}))
                        next_index += 1
                finished = next_index >= len(stream.workflow_steps)
                next_step = None if finished else stream.workflow_steps[next_index]
                phase = (ResearchPhase.RESEARCH_DESIGN if gate.gate_type == "research_route" else self._step_phase(next_step)) if next_step else ResearchPhase.WRITING_PUBLICATION
                if gate.gate_type != "research_route" and stream.current_step_index < len(stream.workflow_steps):
                    completed = [*completed, stream.workflow_steps[stream.current_step_index]]
                updated_stream = stream.model_copy(update={"phase": phase, "current_action": "流程完成" if finished else "等待编排器生成下一步候选", "execution_status": ExecutionStatus.COMPLETED if finished else ExecutionStatus.QUEUED, "current_step_index": next_index, "completed_step_ids": list(dict.fromkeys(completed)), "status": WorkstreamStatus.COMPLETED if finished else stream.status})
                updated_workstreams = [
                    updated_stream if item.workstream_id == gate.workstream_id else item
                    for item in state.workstreams
                ]
                all_workstreams_finished = bool(updated_workstreams) and all(
                    item.status is WorkstreamStatus.COMPLETED
                    for item in updated_workstreams
                )
                mixed_project = bool(
                    state.route_decision
                    and state.route_decision.primary_route == "MIXED_METHODS"
                )
                next_active_workstream_id = next(
                    (
                        item.workstream_id
                        for item in updated_workstreams
                        if item.status is not WorkstreamStatus.COMPLETED
                    ),
                    None,
                )
                next_state = state.model_copy(update={
                    "active_gate_id": None,
                    # Mixed-methods projects have one additional project-level
                    # merge Gate after both independent workstreams finish.
                    # Do not report the project complete before that merged
                    # manuscript has been reviewed and explicitly accepted.
                    "lifecycle_status": (
                        ProjectLifecycleStatus.COMPLETED
                        if (all_workstreams_finished and (not mixed_project or is_mixed_merge_gate))
                        else state.lifecycle_status
                    ),
                    "workstreams": updated_workstreams,
                    "active_workstream_id": next_active_workstream_id or updated_stream.workstream_id,
                })
            if is_mixed_merge_gate:
                # The merge candidate becomes the immutable project-level
                # manuscript only after its explicit approval.  A rejected or
                # revised candidate remains auditable but cannot block a new
                # merge attempt.
                for artifact in self.repository.list_artifacts(project_id):
                    if artifact.artifact_id not in gate.artifact_ids:
                        continue
                    if decision == "approve":
                        self.repository.update_artifact(artifact.model_copy(update={
                            "lifecycle_status": ArtifactLifecycle.FROZEN,
                            "approval_status": ApprovalStatus.APPROVED,
                        }))
                    elif decision in {"reject", "revise"}:
                        self.repository.update_artifact(artifact.model_copy(update={
                            "lifecycle_status": ArtifactLifecycle.REJECTED,
                            "effective": False,
                        }))
            self.repository.put_gate(new_gate)
            saved = self._save_state_event(
                next_state,
                event_type="GATE_DECIDED",
                actor=actor,
                payload={"gate_id": gate_id, "decision": decision},
            )
            return saved

    def enqueue_next_action(self, project_id: str, *, action: str, input_hash: str, actor: str = "orchestrator") -> TaskLease:
        """Create one idempotent background action against the current revision."""

        state = self.ensure_project(project_id)
        workstream = next(
            (item for item in state.workstreams if item.workstream_id == state.active_workstream_id),
            state.workstreams[0],
        )
        task = TaskLease(
            project_id=project_id,
            workstream_id=workstream.workstream_id,
            action=action,
            idempotency_key=f"{project_id}:{workstream.workstream_id}:{action}:{state.state_revision}:{input_hash}",
            input_hash=input_hash,
            expected_state_revision=state.state_revision,
        )
        enqueue = cast(Callable[[TaskLease], TaskLease] | None, getattr(self.repository, "enqueue", None))
        if not callable(enqueue):
            raise TypeError("control-plane repository does not support task queue")
        persisted = enqueue(task)
        # A browser retry may hit the same revision while the original task is
        # still queued. Reuse the durable task and avoid emitting a misleading
        # second queue event for a task that was not newly created.
        if persisted.task_id == task.task_id:
            self.repository.add_event(
                AuditEvent(
                    project_id=project_id,
                    event_type="TASK_QUEUED",
                    actor=actor,
                    state_revision=state.state_revision,
                    payload={"task_id": persisted.task_id, "action": action},
                )
            )
        return persisted

    def validate_worker_revision(self, project_id: str, expected_revision: int) -> bool:
        """Return whether a worker may still commit against the project."""

        state = self.ensure_project(project_id)
        return state.state_revision == expected_revision

    def retry_task(self, project_id: str, task_id: str, *, actor: str = "researcher") -> TaskLease:
        """Requeue one terminal task only when it still represents the active action.

        A retry is deliberately a new lease at the current state revision.  This
        prevents a stale worker result from being accepted after the project has
        moved on, while retaining the original task as an audit record.
        """
        with self._lock:
            state = self.ensure_project(project_id)
            if state.lifecycle_status is not ProjectLifecycleStatus.ACTIVE:
                raise ValueError("project is not active")
            getter = getattr(self.repository, "get_task", None)
            task = getter(project_id, task_id) if callable(getter) else next(
                (item for item in self.repository.list_tasks(project_id) if item.task_id == task_id),
                None,
            )
            if task is None:
                raise ValueError("task was not found")
            if task.status not in {ExecutionStatus.FAILED, ExecutionStatus.STALE, ExecutionStatus.CANCELLED}:
                raise ValueError("only failed, stale, or cancelled tasks can be retried")
            stream = next(
                (item for item in state.workstreams if item.workstream_id == task.workstream_id),
                None,
            )
            if stream is None:
                raise ValueError("task workstream no longer exists")
            if state.active_gate_id:
                raise ValueError("project is waiting for a Gate decision")
            current_action = (
                stream.workflow_steps[stream.current_step_index]
                if stream.current_step_index < len(stream.workflow_steps)
                else None
            )
            if current_action != task.action and stream.current_action != task.action:
                raise ValueError("task is no longer the active orchestration action")
            # Keep the failed task immutable as history; enqueue_next_action is
            # idempotent for repeated clicks at the same revision.
            retried = self.enqueue_next_action(
                project_id,
                action=task.action,
                input_hash=sha256(
                    f"{project_id}:{state.state_revision}:{task.action}:retry".encode()
                ).hexdigest(),
                actor=actor,
            )
            self.repository.add_event(
                AuditEvent(
                    project_id=project_id,
                    event_type="TASK_RETRY_QUEUED",
                    actor=actor,
                    state_revision=state.state_revision,
                    payload={"task_id": task_id, "retry_task_id": retried.task_id, "action": task.action},
                )
            )
            return retried

    def complete_action_with_candidate(
        self,
        project_id: str,
        *,
        action: str,
        content: dict[str, Any],
        actor: str = "orchestrator",
        gate_type: str | None = None,
        gate_level: GateLevel = GateLevel.G2,
        artifact_type: str | None = None,
        source_evidence_ids: list[str] | None = None,
        source_artifact_ids: list[str] | None = None,
        require_human_gate: bool = True,
        gate_reason: str | None = None,
        validation_status: ValidationStatus = ValidationStatus.PASSED,
        validation_warnings: list[str] | None = None,
        conversation_checkpoint: str | None = None,
        resume_action: str | None = None,
        expected_state_revision: int | None = None,
    ) -> tuple[ControlState, ArtifactRecord, GateRecord | None]:
        """Persist a validated candidate and pause at the next human Gate.

        This is the compatibility boundary used while domain Agents are being
        migrated to the control-plane worker. Candidate content is immutable
        once frozen and the state transition is protected by state_revision.
        """
        with self._lock:
            state = self.ensure_project(project_id)
            # A long-running worker may finish after a recovery worker or a
            # researcher action has already advanced this project.  Its
            # candidate is no longer for the active action and must never
            # overwrite a later conversational checkpoint.
            if (
                expected_state_revision is not None
                and state.state_revision != expected_state_revision
            ):
                raise ConcurrentStateError(
                    f"state revision changed while executing {action}: "
                    f"expected {expected_state_revision}, got {state.state_revision}"
                )
            stream = next((item for item in state.workstreams if item.workstream_id == state.active_workstream_id), state.workstreams[0])
            raw = json.dumps(content, ensure_ascii=True, sort_keys=True)
            artifact = self.create_artifact(
                project_id,
                workstream_id=stream.workstream_id,
                artifact_type=artifact_type or f"{action.title().replace('_', '')}Candidate",
                content_uri=f"candidate://{project_id}/{action}/{uuid4().hex}",
                content_sha256=sha256(raw.encode("utf-8")).hexdigest(),
                created_by=actor,
                source_evidence_ids=source_evidence_ids,
                parent_artifact_ids=source_artifact_ids,
            )
            artifact = self.validate_artifact(
                project_id, artifact.artifact_id, status=validation_status
            )
            gate = None
            if require_human_gate:
                gate = GateRecord(
                    project_id=project_id,
                    workstream_id=stream.workstream_id,
                    gate_type=gate_type or f"{action}_approval",
                    level=gate_level,
                    artifact_ids=[artifact.artifact_id],
                    reason=gate_reason or f"请审核 {action} 候选产物后继续下一阶段。",
                    warnings=validation_warnings or [],
                    requested_by=actor,
                )
                self.repository.put_gate(gate)
            next_index = stream.current_step_index
            if not require_human_gate and next_index < len(stream.workflow_steps):
                next_index += 1
            if conversation_checkpoint == "RESEARCH_QUESTION_REVIEW":
                # The question review sits between question generation and
                # the design chain.  Resume at the design action, not at the
                # intervening DAG/power operators.
                next_index = (
                    stream.workflow_steps.index("qualitative_design")
                    if "qualitative_design" in stream.workflow_steps
                    else stream.workflow_steps.index("research_design")
                    if "research_design" in stream.workflow_steps
                    else next_index
                )
            elif conversation_checkpoint == "RESEARCH_DESIGN_REVIEW":
                next_index = (
                    stream.workflow_steps.index("preregistration_freeze")
                    if "preregistration_freeze" in stream.workflow_steps
                    else next_index
                )
            elif resume_action and resume_action in stream.workflow_steps:
                next_index = stream.workflow_steps.index(resume_action)
            next_action = (
                stream.workflow_steps[next_index]
                if next_index < len(stream.workflow_steps)
                else "流程完成"
            )
            checkpoint_action = ({
                "RESEARCH_QUESTION_REVIEW": "等待研究者确认研究问题",
                "RESEARCH_DESIGN_REVIEW": "等待研究者确认研究方案",
                "RESULT_INTERPRETATION_REVIEW": "等待研究者确认结果解释边界",
                "MANUSCRIPT_OUTLINE_REVIEW": "等待研究者确认论文大纲",
                "MANUSCRIPT_SECTION_REVIEW": "等待研究者指定论文章节",
                "MANUSCRIPT_REVISION_REVIEW": "等待研究者确认论文修订方案",
            }.get(conversation_checkpoint) if conversation_checkpoint else None)
            updated_stream = stream.model_copy(update={
                "execution_status": ExecutionStatus.WAITING_USER if (require_human_gate or conversation_checkpoint) else ExecutionStatus.QUEUED,
                "current_action": action if require_human_gate else checkpoint_action or next_action,
                "phase": self._step_phase(action),
                "artifact_ids": [*stream.artifact_ids, artifact.artifact_id],
                "gate_ids": [*stream.gate_ids, *([gate.gate_id] if gate else [])],
                "current_step_index": next_index,
                "conversation_checkpoint": conversation_checkpoint,
            })
            next_state = state.model_copy(update={
                "workstreams": [updated_stream if item.workstream_id == stream.workstream_id else item for item in state.workstreams],
                "active_gate_id": gate.gate_id if gate else None,
            })
            saved = self._save_state_event(
                next_state,
                event_type="CANDIDATE_READY" if gate else "AUTOMATIC_ACTION_COMPLETED",
                actor=actor,
                payload={"action": action, "artifact_id": artifact.artifact_id, "gate_id": gate.gate_id if gate else None},
            )
            return saved, artifact, gate


class ControlPlaneWorker:
    """Small lease-aware worker adapter for local SQLite deployments."""

    def __init__(self, repository: ControlPlaneRepository, control_plane: ControlPlane, worker_id: str) -> None:
        self.repository = repository
        self.control_plane = control_plane
        self.worker_id = worker_id

    def run_once(
        self, handlers: dict[str, Any], *, project_id: str | None = None
    ) -> TaskLease | None:
        """Claim and execute one task, optionally scoped to one project.

        An API conversation turn must not consume a queued task belonging to
        another project just because it was inserted earlier in SQLite.
        Background workers retain the unscoped default.
        """

        # Retrieval and model-backed actions can legitimately exceed a
        # minute.  A longer lease plus heartbeat prevents the durable
        # recovery loop from claiming the same still-running task.
        lease_seconds = 300
        task = self.repository.claim(
            self.worker_id,
            lease_seconds=lease_seconds,
            project_id=project_id,
        )
        if task is None:
            return None
        if not self.control_plane.validate_worker_revision(task.project_id, task.expected_state_revision):
            stale = task.model_copy(update={"status": ExecutionStatus.STALE, "error": "state revision changed before execution"})
            return self.repository.update_task(stale)
        handler = handlers.get(task.action)
        if handler is None:
            failed = task.model_copy(update={"status": ExecutionStatus.FAILED, "error": f"no handler for action: {task.action}"})
            return self.repository.update_task(failed)
        heartbeat_stop = Event()

        def renew_lease() -> None:
            while not heartbeat_stop.wait(30):
                refreshed = self.repository.heartbeat(
                    task.task_id,
                    self.worker_id,
                    lease_seconds=lease_seconds,
                )
                if refreshed is None:
                    return

        heartbeat_thread = Thread(
            target=renew_lease,
            name=f"stem-sci-task-heartbeat-{task.task_id}",
            daemon=True,
        )
        heartbeat_thread.start()
        try:
            output_ids = handler(task)
            completed = task.model_copy(update={
                "status": ExecutionStatus.COMPLETED,
                "output_artifact_ids": list(output_ids or []),
                "next_attempt_at": None,
            })
        except ConcurrentStateError as error:
            # The handler finished against a state which has already moved on
            # (for example after a lease recovery).  Retrying that candidate
            # would let an obsolete action race with the active checkpoint.
            completed = task.model_copy(update={
                "status": ExecutionStatus.STALE,
                "lease_until": None,
                "error": str(error),
                "next_attempt_at": None,
            })
        except Exception as error:  # noqa: BLE001  # pragma: no cover - handler boundary
            # Transient provider and filesystem failures are retried under the
            # same idempotency key; only the final attempt becomes terminal.
            completed = task.model_copy(update={
                "status": ExecutionStatus.QUEUED if task.attempt < task.max_attempts else ExecutionStatus.FAILED,
                "lease_until": None,
                "error": str(error),
                "next_attempt_at": (
                    datetime.now(UTC) + timedelta(seconds=min(60, 2 ** max(0, task.attempt - 1)))
                    if task.attempt < task.max_attempts else None
                ),
            })
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=1)
        return self.repository.update_task(completed)
