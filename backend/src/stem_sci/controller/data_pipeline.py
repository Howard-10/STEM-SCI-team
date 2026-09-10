"""Controller-owned CSV/PYTHON_ONLY data-analysis pipeline.

The DataAnalysisAgent supplies candidate specifications.  This module is the
separate deterministic path that applies approved operations and owns pipeline
state transitions.
"""

from __future__ import annotations

import csv
import os
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from stem_sci.agents.analysis_contracts import DataAnalysisPreAnalysisOutcome
from stem_sci.coding.providers import (
    CodeArtifactStore,
    CodexCliCodingProvider,
    CodingProvider,
    CodingProviderUnavailable,
    DeterministicTemplateCodingProvider,
)
from stem_sci.controller.analysis_execution import (
    ResearchAnalysisExecutionRequest,
    ResearchAnalysisExecutionService,
)
from stem_sci.controller.dual_engine_execution import (
    DualEngineExecutionRequest,
    DualEngineExecutionService,
)
from stem_sci.core.enums import DecisionScope, GateDecision, RunStatus
from stem_sci.core.models import GateResult
from stem_sci.operators.executor import OperatorExecutor
from stem_sci.physics import PhysicsValidationReport
from stem_sci.research_data.canonical import canonical_csv_bytes, read_csv_rows
from stem_sci.research_data.freeze import DataFreezeService
from stem_sci.research_data.models import FrozenDatasetRef, ProcessedDatasetRef, RawDatasetRef
from stem_sci.research_data.processing import DataProcessingService
from stem_sci.statistics.models import (
    AnalysisModelSpecification,
    ExecutableAnalysisPlan,
    ResultValidationReport,
    StatisticalResultCard,
)
from stem_sci.statistics.multiple_comparisons import (
    MultipleComparisonReport,
    MultiplicityMethod,
)
from stem_sci.statistics.robustness import RobustnessReport, RobustnessStatus
from stem_sci.utils.hash_utils import sha256_bytes, sha256_text


class DataPipelineStage(StrEnum):
    WAITING_ANALYSIS_PREPARATION_APPROVAL = "WAITING_ANALYSIS_PREPARATION_APPROVAL"
    WAITING_RAW_DATA = "WAITING_RAW_DATA"
    WAITING_PROCESSING_APPROVAL = "WAITING_PROCESSING_APPROVAL"
    REWORK = "REWORK"
    WAITING_FREEZE_APPROVAL = "WAITING_FREEZE_APPROVAL"
    WAITING_EXECUTION_APPROVAL = "WAITING_EXECUTION_APPROVAL"
    ANALYZED = "ANALYZED"
    BLOCKED = "BLOCKED"


class DataAuditReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    raw_dataset_ref: str = Field(min_length=1)
    passed: bool
    missing_required_variables: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    decision_scope: DecisionScope
    blocked_target_ids: list[str] = Field(default_factory=list)
    row_count: int = Field(default=0, ge=0)
    column_count: int = Field(default=0, ge=0)
    duplicate_row_count: int = Field(default=0, ge=0)
    missing_values_by_column: dict[str, int] = Field(default_factory=dict)
    numeric_ranges: dict[str, dict[str, float]] = Field(default_factory=dict)
    created_at: datetime


class DataPipelineApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    approval_type: str = Field(min_length=1)
    artifact_ref: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class DataPipelineState(BaseModel):
    """Reference-only state for Controller data operations; no file payloads."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)
    stage: DataPipelineStage
    preregistered_plan_ref: str = Field(min_length=1)
    preregistration_approval_ref: str = Field(min_length=1)
    pre_analysis: DataAnalysisPreAnalysisOutcome
    model_specification: AnalysisModelSpecification
    code_artifact_ref: str | None = None
    code_specification_ref: str | None = None
    code_review_ref: str | None = None
    code_generation_provider: str | None = None
    code_generation_fallback_reason: str | None = None
    spss_code_artifact_ref: str | None = None
    spss_execution_run_ref: str | None = None
    result_consistency_report_ref: str | None = None
    raw_dataset: RawDatasetRef | None = None
    data_audit_report: DataAuditReport | None = None
    processed_dataset: ProcessedDatasetRef | None = None
    frozen_dataset: FrozenDatasetRef | None = None
    executable_plan: ExecutableAnalysisPlan | None = None
    validation_report: ResultValidationReport | None = None
    statistical_result_card: StatisticalResultCard | None = None
    physics_validation_report: PhysicsValidationReport | None = None
    robustness_report: RobustnessReport | None = None
    multiple_comparison_report: MultipleComparisonReport | None = None
    gate_results: list[GateResult] = Field(default_factory=list)
    pending_approval: DataPipelineApproval | None = None
    rework_reason: str | None = None
    blocked_target_ids: list[str] = Field(default_factory=list)
    physics_validation: bool = False
    physics_equations: list[str] = Field(default_factory=list)
    physics_units: dict[str, str] = Field(default_factory=dict)
    physics_bounds: dict[str, dict[str, float]] = Field(default_factory=dict)
    robustness_analysis: bool = False
    robustness_group_column: str | None = None
    robustness_outcome_column: str | None = None
    robustness_primary_estimate: float | None = None
    robustness_bootstrap_samples: int = Field(default=2000, ge=200, le=20_000)
    robustness_permutations: int = Field(default=2000, ge=200, le=20_000)
    multiple_comparison_correction: bool = False
    multiple_comparison_method: MultiplicityMethod = MultiplicityMethod.HOLM
    multiple_comparison_alpha: float = Field(default=0.05, gt=0.0, lt=1.0)


class DataPipelineBeginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)
    preregistered_plan_ref: str = Field(min_length=1)
    preregistration_approval_ref: str = Field(min_length=1)
    pre_analysis: DataAnalysisPreAnalysisOutcome
    model_specification: AnalysisModelSpecification
    # Kept as a compatibility field for callers compiled before the
    # Controller-owned CodingProvider path.  A real artifact is created only
    # after FrozenDataset and ExecutableAnalysisPlan exist.
    code_artifact_ref: str | None = None
    physics_validation: bool = False
    physics_equations: list[str] = Field(default_factory=list)
    physics_units: dict[str, str] = Field(default_factory=dict)
    physics_bounds: dict[str, dict[str, float]] = Field(default_factory=dict)
    robustness_analysis: bool = False
    robustness_group_column: str | None = None
    robustness_outcome_column: str | None = None
    robustness_primary_estimate: float | None = None
    robustness_bootstrap_samples: int = Field(default=2000, ge=200, le=20_000)
    robustness_permutations: int = Field(default=2000, ge=200, le=20_000)
    multiple_comparison_correction: bool = False
    multiple_comparison_method: MultiplicityMethod = MultiplicityMethod.HOLM
    multiple_comparison_alpha: float = Field(default=0.05, gt=0.0, lt=1.0)


class DataPipelinePreparationRequest(BaseModel):
    """Bounded pre-data mapping supplied by a researcher through the UI.

    The Controller resolves every protocol and approval reference itself.  The
    request only declares the two CSV columns supported by the current
    deterministic analysis template and optional multiplicity handling.
    """

    model_config = ConfigDict(extra="forbid")

    outcome_variable: str = Field(min_length=1, max_length=128)
    group_variable: str = Field(min_length=1, max_length=128)
    model_family: Literal["group_mean_difference"] = "group_mean_difference"
    multiple_comparison_correction: bool = False
    multiple_comparison_method: MultiplicityMethod = MultiplicityMethod.HOLM
    multiple_comparison_alpha: float = Field(default=0.05, gt=0.0, lt=1.0)


T = TypeVar("T")


def _codex_timeout_seconds() -> int:
    """Keep optional remote generation bounded so analysis can fall back locally."""

    # Real code generation needs more time than a CLI health probe. The
    # caller still has a bounded upper limit and may fall back safely.
    raw = os.getenv("STEM_SCI_CODEX_TIMEOUT_SECONDS", "60")
    try:
        return max(15, min(int(raw), 120))
    except ValueError:
        return 60


class DataPipelineController:
    """Runs all approved data operations; it never asks an Agent to execute."""

    def __init__(self, *, storage_root: Path, operator_executor: OperatorExecutor) -> None:
        self.storage_root = storage_root
        self.operator_executor = operator_executor
        self.processing_service = DataProcessingService()
        self.freeze_service = DataFreezeService()
        coding_provider, self._configured_provider_fallback_reason = self._coding_provider(storage_root)
        self.research_execution = ResearchAnalysisExecutionService(
            coding_provider=coding_provider,
            output_root=storage_root / "research-execution-runs",
            execution_store=operator_executor.execution_store,
        )
        self.dual_engine_execution = DualEngineExecutionService(
            artifact_root=storage_root / "dual-engine-artifacts",
            output_root=storage_root / "dual-engine-runs",
            coding_provider=coding_provider,
            execution_store=operator_executor.execution_store,
        )

    @staticmethod
    def _coding_provider(storage_root: Path) -> tuple[CodingProvider, str | None]:
        configured = os.getenv("STEM_SCI_CODING_PROVIDER", "deterministic").strip().lower()
        artifact_store = CodeArtifactStore(storage_root / "code-artifacts")
        if configured == "deterministic":
            return DeterministicTemplateCodingProvider(artifact_store), None
        if configured == "codex":
            remote_enabled = os.getenv("STEM_SCI_CODEX_REMOTE_ENABLED", "false").strip().lower()
            if remote_enabled not in {"1", "true", "yes", "on"}:
                return (
                    DeterministicTemplateCodingProvider(artifact_store),
                    "CODEX_REMOTE_DISABLED; used deterministic_research_template:v1",
                )
            generation_confirmed = os.getenv("STEM_SCI_CODEX_GENERATION_CONFIRMED", "false").strip().lower()
            if generation_confirmed not in {"1", "true", "yes", "on"}:
                return (
                    DeterministicTemplateCodingProvider(artifact_store),
                    "CODEX_GENERATION_UNCONFIRMED; used deterministic_research_template:v1",
                )
            return (
                CodexCliCodingProvider(
                    artifact_store,
                    profile=os.getenv("STEM_SCI_CODEX_PROFILE", "").strip() or None,
                    timeout_seconds=_codex_timeout_seconds(),
                ),
                None,
            )
        raise ValueError("STEM_SCI_CODING_PROVIDER must be deterministic or codex")

    def begin(self, request: DataPipelineBeginRequest) -> DataPipelineState:
        if request.pre_analysis.readiness_report.status != "READY":
            raise ValueError("data pipeline requires a READY pre-analysis package")
        if request.pre_analysis.readiness_report.project_id != request.project_id:
            raise ValueError("pre-analysis project does not match data pipeline project")
        if request.model_specification.project_id != request.project_id:
            raise ValueError("model specification project does not match data pipeline project")
        if request.pre_analysis.executable_plan_candidate.preregistered_plan_ref != (
            request.preregistered_plan_ref
        ):
            raise ValueError("executable-plan candidate does not match preregistered plan")
        return DataPipelineState(
            project_id=request.project_id,
            stage=DataPipelineStage.WAITING_RAW_DATA,
            preregistered_plan_ref=request.preregistered_plan_ref,
            preregistration_approval_ref=request.preregistration_approval_ref,
            pre_analysis=request.pre_analysis,
            model_specification=request.model_specification,
            code_artifact_ref=request.code_artifact_ref,
            physics_validation=request.physics_validation,
            physics_equations=request.physics_equations,
            physics_units=request.physics_units,
            physics_bounds=request.physics_bounds,
            robustness_analysis=request.robustness_analysis,
            robustness_group_column=request.robustness_group_column,
            robustness_outcome_column=request.robustness_outcome_column,
            robustness_primary_estimate=request.robustness_primary_estimate,
            robustness_bootstrap_samples=request.robustness_bootstrap_samples,
            robustness_permutations=request.robustness_permutations,
            multiple_comparison_correction=request.multiple_comparison_correction,
            multiple_comparison_method=request.multiple_comparison_method,
            multiple_comparison_alpha=request.multiple_comparison_alpha,
        )

    def begin_prepared(self, request: DataPipelineBeginRequest) -> DataPipelineState:
        """Pause a Controller-built pre-analysis package for human confirmation."""

        state = self.begin(request)
        approval = DataPipelineApproval(
            request_id=f"data-approval-{uuid4().hex}",
            approval_type="analysis_preparation",
            artifact_ref=(
                "analysis-preparation://"
                f"{state.pre_analysis.agent_result.agent_run_id}"
            ),
            reason=(
                "Confirm the pre-data variable mapping and deterministic analysis "
                "template before registering a raw CSV."
            ),
        )
        return state.model_copy(
            update={
                "stage": DataPipelineStage.WAITING_ANALYSIS_PREPARATION_APPROVAL,
                "pending_approval": approval,
            }
        )

    def register_raw_csv(
        self, state: DataPipelineState, *, filename: str, content: bytes
    ) -> DataPipelineState:
        if state.stage is not DataPipelineStage.WAITING_RAW_DATA:
            raise ValueError("data pipeline is not accepting raw data")
        safe_name = Path(filename).name
        if not safe_name or safe_name != filename or Path(safe_name).suffix.lower() != ".csv":
            raise ValueError("MVP accepts a safe CSV filename only")
        if not content:
            raise ValueError("raw CSV must not be empty")
        project_directory = self._project_directory(state.project_id)
        raw_directory = project_directory / "raw"
        raw_directory.mkdir(parents=True, exist_ok=True)
        content_hash = sha256_bytes(content)
        raw_path = raw_directory / f"{content_hash}.csv"
        raw_path.write_bytes(content)
        now = datetime.now(UTC)
        raw = RawDatasetRef(
            dataset_id=f"raw-{content_hash[:16]}",
            project_id=state.project_id,
            version=1,
            content_uri=str(raw_path),
            sha256=content_hash,
            raw_bytes_sha256=content_hash,
            canonical_content_sha256=self._canonical_hash_or_raw_hash(content),
            created_at=now,
        )
        audit = self._audit_raw_csv(state, raw)
        audit_gate = GateResult(
            gate_id="DataAuditGate",
            gate_version="mvp-csv-v1",
            project_id=state.project_id,
            artifact_id=raw.dataset_id,
            decision=GateDecision.PASS if audit.passed else GateDecision.REWORK,
            decision_scope=audit.decision_scope,
            blocked_target_ids=audit.blocked_target_ids,
            risk_flags=audit.risk_flags,
            missing_fields=audit.missing_required_variables,
            next_action=(
                "Request human approval for the processing plan."
                if audit.passed
                else "Return the raw-data artifact for correction."
            ),
            created_at=datetime.now(UTC),
        )
        if not audit.passed:
            return state.model_copy(
                update={
                    "stage": DataPipelineStage.REWORK,
                    "raw_dataset": raw,
                    "data_audit_report": audit,
                    "rework_reason": "Raw CSV failed the deterministic data audit.",
                    "blocked_target_ids": audit.blocked_target_ids,
                    "gate_results": [*state.gate_results, audit_gate],
                }
            )
        approval = DataPipelineApproval(
            request_id=f"data-approval-{uuid4().hex}",
            approval_type="data_processing",
            artifact_ref=f"processing-plan-candidate://{state.pre_analysis.agent_result.agent_run_id}",
            reason="Approve the data-processing plan before creating ProcessedDataset.",
        )
        return state.model_copy(
            update={
                "stage": DataPipelineStage.WAITING_PROCESSING_APPROVAL,
                "raw_dataset": raw,
                "data_audit_report": audit,
                "pending_approval": approval,
                "gate_results": [*state.gate_results, audit_gate],
            }
        )

    def decide(
        self, state: DataPipelineState, *, decision: str) -> DataPipelineState:
        approval = state.pending_approval
        if approval is None:
            raise ValueError("data pipeline has no pending human approval")
        if decision not in {"approved", "rejected"}:
            raise ValueError("data pipeline approval decision must be approved or rejected")
        if decision == "rejected":
            return state.model_copy(
                update={
                    "stage": DataPipelineStage.REWORK,
                    "pending_approval": None,
                    "rework_reason": f"{approval.approval_type} was rejected by human review.",
                    "blocked_target_ids": [approval.artifact_ref],
                }
            )
        if approval.approval_type == "analysis_preparation":
            return state.model_copy(
                update={
                    "stage": DataPipelineStage.WAITING_RAW_DATA,
                    "pending_approval": None,
                }
            )
        if approval.approval_type == "data_processing":
            return self._process_approved_data(state)
        if approval.approval_type == "data_freeze":
            return self._freeze_approved_data(state)
        if approval.approval_type == "analysis_execution":
            return self._execute_approved_plan(state)
        raise ValueError(f"unsupported data pipeline approval type: {approval.approval_type}")

    def _process_approved_data(self, state: DataPipelineState) -> DataPipelineState:
        raw = self._require(state.raw_dataset, "raw dataset")
        processed = self.processing_service.process_csv_identity(
            raw_dataset=raw,
            processing_plan_ref=(
                f"processing-plan-candidate://{state.pre_analysis.agent_result.agent_run_id}"
            ),
            processing_approval_ref=self._require(state.pending_approval, "pending approval").request_id,
            destination_directory=self._project_directory(state.project_id) / "processed",
        )
        approval = DataPipelineApproval(
            request_id=f"data-approval-{uuid4().hex}",
            approval_type="data_freeze",
            artifact_ref=processed.ref,
            reason="Approve the processed data before creating FrozenDataset.",
        )
        return state.model_copy(
            update={
                "stage": DataPipelineStage.WAITING_FREEZE_APPROVAL,
                "processed_dataset": processed,
                "pending_approval": approval,
            }
        )

    def _freeze_approved_data(self, state: DataPipelineState) -> DataPipelineState:
        processed = self._require(state.processed_dataset, "processed dataset")
        frozen = self.freeze_service.freeze_csv(
            processed_dataset=processed,
            freeze_approval_ref=self._require(state.pending_approval, "pending approval").request_id,
            destination_directory=self._project_directory(state.project_id) / "frozen",
        )
        candidate = state.pre_analysis.executable_plan_candidate
        compatibility_gate = self._schema_compatibility_gate(state, frozen)
        if compatibility_gate.decision is GateDecision.REWORK:
            return state.model_copy(
                update={
                    "stage": DataPipelineStage.REWORK,
                    "frozen_dataset": frozen,
                    "pending_approval": None,
                    "rework_reason": "Frozen data schema is incompatible with the model specification.",
                    "blocked_target_ids": compatibility_gate.blocked_target_ids,
                    "gate_results": [*state.gate_results, compatibility_gate],
                }
            )
        executable_plan = ExecutableAnalysisPlan(
            executable_plan_id=f"executable-plan-{uuid4().hex}",
            project_id=state.project_id,
            preregistered_plan_ref=state.preregistered_plan_ref,
            frozen_dataset_ref=frozen.ref,
            frozen_dataset_sha256=frozen.sha256,
            dataset_schema_ref=frozen.schema_ref,
            variable_mapping=candidate.variable_mapping,
            type_confirmations=candidate.type_confirmations,
            software_configuration={
                **candidate.software_configuration,
                "engine": (
                    "python"
                    if candidate.analysis_mode.value == "PYTHON_ONLY"
                    else "spss_python_dual"
                ),
                "validation_mode": (
                    "SINGLE_ENGINE"
                    if candidate.analysis_mode.value == "PYTHON_ONLY"
                    else "CROSS_ENGINE"
                ),
            },
            analysis_mode=candidate.analysis_mode,
            model_specification_refs=candidate.model_specification_refs,
            compatibility_gate_ref=(
                f"gate://schema-compatibility/{frozen.schema_ref.rsplit('/', 1)[-1]}"
            ),
        )
        approval = DataPipelineApproval(
            request_id=f"data-approval-{uuid4().hex}",
            approval_type="analysis_execution",
            artifact_ref=f"executable-plan://{executable_plan.executable_plan_id}",
            reason="Approve the executable analysis plan and reviewed code before execution.",
        )
        return state.model_copy(
            update={
                "stage": DataPipelineStage.WAITING_EXECUTION_APPROVAL,
                "frozen_dataset": frozen,
                "executable_plan": executable_plan,
                "pending_approval": approval,
                "gate_results": [*state.gate_results, compatibility_gate],
            }
        )

    def _execute_approved_plan(self, state: DataPipelineState) -> DataPipelineState:
        frozen = self._require(state.frozen_dataset, "frozen dataset")
        executable_plan = self._require(state.executable_plan, "executable plan")
        approval_ref = self._require(state.pending_approval, "pending approval").request_id
        execution_request = ResearchAnalysisExecutionRequest(
            project_id=state.project_id,
            frozen_dataset=frozen,
            executable_plan=executable_plan,
            model_specification=state.model_specification,
            execution_approval_ref=approval_ref,
            code_human_approval_ref=approval_ref,
            physics_validation=state.physics_validation,
            physics_equations=state.physics_equations,
            physics_units=state.physics_units,
            physics_bounds=state.physics_bounds,
            robustness_analysis=state.robustness_analysis,
            robustness_group_column=state.robustness_group_column,
            robustness_outcome_column=state.robustness_outcome_column,
            robustness_primary_estimate=state.robustness_primary_estimate,
            robustness_bootstrap_samples=state.robustness_bootstrap_samples,
            robustness_permutations=state.robustness_permutations,
            multiple_comparison_correction=state.multiple_comparison_correction,
            multiple_comparison_method=state.multiple_comparison_method,
            multiple_comparison_alpha=state.multiple_comparison_alpha,
        )
        fallback_reason = self._configured_provider_fallback_reason
        try:
            if executable_plan.analysis_mode.value == "SPSS_PYTHON_DUAL":
                dual = self.dual_engine_execution.execute(
                    DualEngineExecutionRequest(
                        project_id=state.project_id,
                        frozen_dataset=frozen,
                        executable_plan=executable_plan,
                        model_specification=state.model_specification,
                        execution_approval_ref=approval_ref,
                        code_human_approval_ref=approval_ref,
                    )
                )
                if dual.spss_execution is None:
                    return state.model_copy(
                        update={
                            "stage": DataPipelineStage.BLOCKED,
                            "pending_approval": None,
                            "rework_reason": "Python execution failed before SPSS execution.",
                            "blocked_target_ids": [dual.python_execution.execution_run.operator_run_id]
                            if dual.python_execution is not None
                            else [],
                            "code_specification_ref": dual.python_code_specification.ref,
                            "code_artifact_ref": dual.python_code_artifact.ref,
                            "code_review_ref": dual.python_code_review.ref,
                        }
                    )
                if dual.validation_report is None or not dual.validation_report.passed:
                    return state.model_copy(
                        update={
                            "stage": DataPipelineStage.BLOCKED,
                            "pending_approval": None,
                            "validation_report": dual.validation_report,
                            "rework_reason": "SPSS/Python cross-engine validation failed or was blocked.",
                            "blocked_target_ids": [dual.spss_execution.execution_run.operator_run_id],
                            "code_specification_ref": dual.python_code_specification.ref,
                            "code_artifact_ref": dual.python_code_artifact.ref,
                            "code_review_ref": dual.python_code_review.ref,
                            "spss_code_artifact_ref": dual.spss_code_artifact.ref if dual.spss_code_artifact else None,
                            "spss_execution_run_ref": dual.spss_execution.execution_run.operator_run_id,
                            "result_consistency_report_ref": dual.consistency.consistency_report.ref if dual.consistency else None,
                        }
                    )
                return state.model_copy(
                    update={
                        "stage": DataPipelineStage.ANALYZED,
                        "pending_approval": None,
                        "validation_report": dual.validation_report,
                        "statistical_result_card": dual.statistical_result_card,
                        "code_specification_ref": dual.python_code_specification.ref,
                        "code_artifact_ref": dual.python_code_artifact.ref,
                        "code_review_ref": dual.python_code_review.ref,
                        "spss_code_artifact_ref": dual.spss_code_artifact.ref if dual.spss_code_artifact else None,
                        "spss_execution_run_ref": dual.spss_execution.execution_run.operator_run_id,
                        "result_consistency_report_ref": dual.consistency.consistency_report.ref if dual.consistency else None,
                    }
                )
            execution = self.research_execution.execute_python_only(execution_request)
        except CodingProviderUnavailable as error:
            if executable_plan.analysis_mode.value != "PYTHON_ONLY" or not isinstance(
                self.research_execution.coding_provider, CodexCliCodingProvider
            ):
                return state.model_copy(
                    update={
                        "stage": DataPipelineStage.BLOCKED,
                        "pending_approval": None,
                        "rework_reason": f"Coding provider unavailable: {error}",
                    }
                )
            # A failed optional CodeX call cannot alter an approved model. Re-run
            # the same compiled specification through the fixed local template.
            fallback = DeterministicTemplateCodingProvider(
                CodeArtifactStore(self.storage_root / "code-artifacts")
            )
            fallback_service = ResearchAnalysisExecutionService(
                coding_provider=fallback,
                output_root=self.storage_root / "research-execution-runs",
                execution_store=self.operator_executor.execution_store,
            )
            try:
                execution = fallback_service.execute_python_only(execution_request)
                fallback_reason = f"CODEX_UNAVAILABLE:{error}; used deterministic_research_template:v1"
            except CodingProviderUnavailable as fallback_error:
                return state.model_copy(
                    update={
                        "stage": DataPipelineStage.BLOCKED,
                        "pending_approval": None,
                        "rework_reason": f"Coding provider unavailable: {error}; deterministic fallback failed: {fallback_error}",
                    }
                )
        # A Codex process can exit successfully while returning code that is
        # rejected by the review gate or fails in the sandbox.  That is still
        # provider failure for this optional adapter: retry the exact approved
        # specification with the deterministic template before blocking the
        # research pipeline.
        if (
            execution.sandbox_outcome.execution_run.status is not RunStatus.SUCCEEDED
            and execution.code_artifact.provider_id == "codex_cli"
        ):
            fallback = DeterministicTemplateCodingProvider(
                CodeArtifactStore(self.storage_root / "code-artifacts")
            )
            fallback_service = ResearchAnalysisExecutionService(
                coding_provider=fallback,
                output_root=self.storage_root / "research-execution-runs",
                execution_store=self.operator_executor.execution_store,
            )
            try:
                execution = fallback_service.execute_python_only(execution_request)
                fallback_reason = (
                    "CODEX_CANDIDATE_REJECTED; used deterministic_research_template:v1"
                )
            except (CodingProviderUnavailable, ValueError) as fallback_error:
                fallback_reason = (
                    f"CODEX_CANDIDATE_REJECTED:{fallback_error}; deterministic fallback failed"
                )
        outcome = execution.sandbox_outcome
        if outcome.execution_run.status is not RunStatus.SUCCEEDED:
            return state.model_copy(
                update={
                    "stage": DataPipelineStage.BLOCKED,
                    "pending_approval": None,
                    "rework_reason": "Python execution was blocked or failed.",
                    "blocked_target_ids": [outcome.execution_run.operator_run_id],
                    "code_specification_ref": execution.code_specification.ref,
                    "code_artifact_ref": execution.code_artifact.ref,
                    "code_review_ref": execution.code_review.ref,
                    "code_generation_provider": execution.code_artifact.provider_id,
                    "code_generation_fallback_reason": fallback_reason,
                    "physics_validation_report": execution.physics_validation_report,
                    "robustness_report": execution.robustness_report,
                    "multiple_comparison_report": execution.multiple_comparison_report,
                }
            )
        validation = execution.validation_report
        if validation is None or not validation.passed:
            return state.model_copy(
                update={
                    "stage": DataPipelineStage.BLOCKED,
                    "pending_approval": None,
                    "validation_report": validation,
                    "rework_reason": "SINGLE_ENGINE result validation failed.",
                    "blocked_target_ids": [outcome.execution_run.operator_run_id],
                    "code_specification_ref": execution.code_specification.ref,
                    "code_artifact_ref": execution.code_artifact.ref,
                    "code_review_ref": execution.code_review.ref,
                    "code_generation_provider": execution.code_artifact.provider_id,
                    "code_generation_fallback_reason": fallback_reason,
                    "physics_validation_report": execution.physics_validation_report,
                    "robustness_report": execution.robustness_report,
                    "multiple_comparison_report": execution.multiple_comparison_report,
                }
            )
        if execution.robustness_report is not None and execution.robustness_report.status is not RobustnessStatus.PASS:
            return state.model_copy(
                update={
                    "stage": DataPipelineStage.BLOCKED,
                    "pending_approval": None,
                    "rework_reason": "Robustness and sensitivity checks require review.",
                    "blocked_target_ids": [outcome.execution_run.operator_run_id],
                    "validation_report": validation,
                    "code_specification_ref": execution.code_specification.ref,
                    "code_artifact_ref": execution.code_artifact.ref,
                    "code_review_ref": execution.code_review.ref,
                    "code_generation_provider": execution.code_artifact.provider_id,
                    "code_generation_fallback_reason": fallback_reason,
                    "physics_validation_report": execution.physics_validation_report,
                    "robustness_report": execution.robustness_report,
                }
            )
        result_card = self._require(execution.statistical_result_card, "statistical result card")
        return state.model_copy(
            update={
                "stage": DataPipelineStage.ANALYZED,
                "pending_approval": None,
                "validation_report": validation,
                "statistical_result_card": result_card,
                "code_specification_ref": execution.code_specification.ref,
                "code_artifact_ref": execution.code_artifact.ref,
                "code_review_ref": execution.code_review.ref,
                "code_generation_provider": execution.code_artifact.provider_id,
                "code_generation_fallback_reason": fallback_reason,
                "physics_validation_report": execution.physics_validation_report,
                "robustness_report": execution.robustness_report,
                "multiple_comparison_report": execution.multiple_comparison_report,
            }
        )

    def _audit_raw_csv(self, state: DataPipelineState, raw: RawDatasetRef) -> DataAuditReport:
        missing_variables: list[str] = []
        risk_flags: list[str] = []
        row_count = 0
        column_count = 0
        duplicate_row_count = 0
        missing_values_by_column: dict[str, int] = {}
        numeric_ranges: dict[str, dict[str, float]] = {}
        try:
            with Path(raw.content_uri).open("r", encoding="utf-8", newline="") as source:
                reader = csv.DictReader(source)
                header = list(reader.fieldnames or [])
                column_count = len(header)
                rows = list(reader)
                row_count = len(rows)
                duplicate_row_count = row_count - len({tuple((row.get(col) or "").strip() for col in header) for row in rows})
                missing_values_by_column = {
                    col: sum(1 for row in rows if not (row.get(col) or "").strip())
                    for col in header
                }
                for col in header:
                    values: list[float] = []
                    for row in rows:
                        value = (row.get(col) or "").strip()
                        if not value:
                            continue
                        try:
                            values.append(float(value))
                        except ValueError:
                            values = []
                            break
                    if values:
                        numeric_ranges[col] = {"min": min(values), "max": max(values)}
        except (OSError, UnicodeDecodeError, csv.Error):
            header = []
            risk_flags.append("RAW_CSV_UNREADABLE")
        required = set(state.pre_analysis.data_audit_specification.required_variables)
        missing_variables = sorted(required.difference(header))
        if missing_variables:
            risk_flags.append("REQUIRED_VARIABLES_MISSING")
        privacy_names = {"name", "email", "phone", "address", "id_number"}
        detected_privacy_columns = sorted(privacy_names.intersection({value.lower() for value in header}))
        if detected_privacy_columns:
            risk_flags.append("UNSANITIZED_DIRECT_IDENTIFIER")
        passed = not risk_flags
        return DataAuditReport(
            report_id=f"data-audit-report-{uuid4().hex}",
            project_id=state.project_id,
            raw_dataset_ref=raw.ref,
            passed=passed,
            missing_required_variables=missing_variables,
            risk_flags=risk_flags,
            decision_scope=DecisionScope.ARTIFACT if not passed else DecisionScope.TASK,
            blocked_target_ids=[raw.ref] if not passed else [],
            created_at=datetime.now(UTC),
            row_count=row_count,
            column_count=column_count,
            duplicate_row_count=duplicate_row_count,
            missing_values_by_column=missing_values_by_column,
            numeric_ranges=numeric_ranges,
        )

    def _schema_compatibility_gate(
        self, state: DataPipelineState, frozen: FrozenDatasetRef
    ) -> GateResult:
        try:
            with Path(frozen.content_uri).open("r", encoding="utf-8", newline="") as source:
                header = set(next(csv.reader(source), []))
        except (OSError, UnicodeDecodeError, csv.Error):
            header = set()
        required = {
            *state.model_specification.outcome_variables,
            *state.model_specification.predictor_variables,
            *state.model_specification.grouping_variables,
        }
        missing = sorted(required.difference(header))
        passed = not missing
        return GateResult(
            gate_id="SchemaCompatibilityGate",
            gate_version="mvp-csv-v1",
            project_id=state.project_id,
            artifact_id=frozen.dataset_id,
            decision=GateDecision.PASS if passed else GateDecision.REWORK,
            decision_scope=DecisionScope.ARTIFACT,
            blocked_target_ids=[] if passed else [frozen.ref],
            missing_fields=missing,
            next_action=(
                "Allow human approval of the executable analysis plan."
                if passed
                else "Return the executable analysis-plan candidate for schema correction."
            ),
            created_at=datetime.now(UTC),
        )

    def _project_directory(self, project_id: str) -> Path:
        return self.storage_root / "data-pipeline" / sha256_text(project_id)[:16]

    @staticmethod
    def _canonical_hash_or_raw_hash(content: bytes) -> str:
        """Keep the original bytes even when a malformed CSV must be reworked."""

        try:
            header, rows = read_csv_rows(content)
        except (UnicodeDecodeError, ValueError):
            return sha256_bytes(content)
        return sha256_bytes(canonical_csv_bytes(header, rows))

    @staticmethod
    def _require(value: T | None, label: str) -> T:
        if value is None:
            raise ValueError(f"data pipeline missing {label}")
        return value
