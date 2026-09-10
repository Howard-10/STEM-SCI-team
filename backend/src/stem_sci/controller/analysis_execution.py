"""Controller-owned, traceable research-code execution service.

This service does not advance ``ResearchState.current_stage``.  It is a
deterministic operation invoked by a future Controller transition after the
required approvals have already been recorded.  Agents neither call it nor
receive permission to change any artifact it creates.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pandas as pd  # type: ignore[import-untyped]
from pydantic import Field

from stem_sci.artifacts.execution_store import ExecutionStore, InMemoryExecutionStore
from stem_sci.coding.compiler import CodeSpecificationCompiler
from stem_sci.coding.models import CodeArtifact, CodeSpecification
from stem_sci.coding.providers import CodeGenerationRequest, CodingProvider
from stem_sci.coding.review import CodeReviewGate, CodeReviewResult
from stem_sci.coding.sandbox import ResearchCodeSandbox, SandboxExecutionOutcome
from stem_sci.core.enums import RunStatus
from stem_sci.core.models import DomainModel
from stem_sci.physics import PhysicsValidationGate, PhysicsValidationReport
from stem_sci.research_data.models import FrozenDatasetRef
from stem_sci.statistics.mode_policy import AnalysisMode
from stem_sci.statistics.models import (
    AnalysisModelSpecification,
    ExecutableAnalysisPlan,
    ResultValidationReport,
    StatisticalResultCard,
)
from stem_sci.statistics.python_operator import PythonExecutionOutcome
from stem_sci.statistics.robustness import (
    RobustnessAnalysisOperator,
    RobustnessReport,
    RobustnessStatus,
)
from stem_sci.statistics.multiple_comparisons import (
    MultipleComparisonOperator,
    MultipleComparisonReport,
    MultiplicityMethod,
)
from stem_sci.statistics.validation import SingleEngineResultValidator


class ResearchAnalysisExecutionRequest(DomainModel):
    project_id: str = Field(min_length=1)
    frozen_dataset: FrozenDatasetRef
    executable_plan: ExecutableAnalysisPlan
    model_specification: AnalysisModelSpecification
    execution_approval_ref: str = Field(min_length=1)
    code_human_approval_ref: str | None = None
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


class ResearchAnalysisExecutionResult(DomainModel):
    """All deterministic artifacts from one Python-only execution attempt."""

    code_specification: CodeSpecification
    code_artifact: CodeArtifact
    code_review: CodeReviewResult
    sandbox_outcome: SandboxExecutionOutcome
    physics_validation_report: PhysicsValidationReport | None = None
    robustness_report: RobustnessReport | None = None
    multiple_comparison_report: MultipleComparisonReport | None = None
    validation_report: ResultValidationReport | None = None
    statistical_result_card: StatisticalResultCard | None = None


class ResearchAnalysisExecutionService:
    """Build, review and execute an approved Python-only analysis artifact."""

    def __init__(
        self,
        *,
        coding_provider: CodingProvider,
        output_root: Path,
        execution_store: ExecutionStore | None = None,
        compiler: CodeSpecificationCompiler | None = None,
        code_review_gate: CodeReviewGate | None = None,
        sandbox: ResearchCodeSandbox | None = None,
        result_validator: SingleEngineResultValidator | None = None,
        physics_validator: PhysicsValidationGate | None = None,
    ) -> None:
        self.coding_provider = coding_provider
        self.output_root = output_root
        self.execution_store = execution_store or InMemoryExecutionStore()
        self.compiler = compiler or CodeSpecificationCompiler()
        self.code_review_gate = code_review_gate or CodeReviewGate()
        self.sandbox = sandbox or ResearchCodeSandbox()
        self.result_validator = result_validator or SingleEngineResultValidator(
            freeze_service=self.sandbox.freeze_service
        )
        self.physics_validator = physics_validator or PhysicsValidationGate()
        self.robustness_operator = RobustnessAnalysisOperator()
        self.multiple_comparison_operator = MultipleComparisonOperator()

    def execute_python_only(
        self, request: ResearchAnalysisExecutionRequest
    ) -> ResearchAnalysisExecutionResult:
        """Run the actual MVP chain after a Controller-owned approval.

        A dual-engine plan is intentionally rejected here.  Downgrading a
        preregistered dual plan to Python-only would be a substantive workflow
        decision, not an implementation convenience.
        """

        if request.executable_plan.analysis_mode is not AnalysisMode.PYTHON_ONLY:
            raise ValueError("dual-engine plans require the SPSS/Python execution service")
        specification = self.compiler.compile_python(
            specification_id=f"code-spec-{uuid4().hex}",
            executable_plan=request.executable_plan,
            frozen_dataset=request.frozen_dataset,
            model_specification=request.model_specification,
        )
        artifact = self.coding_provider.generate(
            CodeGenerationRequest(project_id=request.project_id, specification=specification)
        )
        physics_report = None
        physics_findings: list[str] = []
        if request.physics_validation:
            physics_report = self.physics_validator.validate(
                project_id=request.project_id,
                artifact=artifact,
                equations=request.physics_equations,
                units=request.physics_units,
                bounds=request.physics_bounds,
            )
            physics_findings = physics_report.finding_codes
        review = self.code_review_gate.review(
            review_id=f"code-review-{uuid4().hex}",
            specification=specification,
            artifact=artifact,
            additional_findings=physics_findings,
        )
        sandbox_outcome = self.sandbox.execute(
            project_id=request.project_id,
            frozen_dataset=request.frozen_dataset,
            specification=specification,
            artifact=artifact,
            review=review,
            output_root=self.output_root,
            human_approval_ref=request.code_human_approval_ref,
        )
        self.execution_store.put(sandbox_outcome.execution_run)
        if sandbox_outcome.execution_run.status is not RunStatus.SUCCEEDED:
            return ResearchAnalysisExecutionResult(
                code_specification=specification,
                code_artifact=artifact,
                code_review=review,
                sandbox_outcome=sandbox_outcome,
                physics_validation_report=physics_report,
            )
        python_outcome = PythonExecutionOutcome(
            execution_run=sandbox_outcome.execution_run,
            frozen_dataset=request.frozen_dataset,
            executable_plan=request.executable_plan,
            model_specification=request.model_specification,
            result_values=sandbox_outcome.result_values,
            result_payload_sha256=sandbox_outcome.result_payload_sha256,
        )
        validation = self.result_validator.validate(
            python_outcome, report_id=f"result-validation-{uuid4().hex}"
        )
        if not validation.passed:
            return ResearchAnalysisExecutionResult(
                code_specification=specification,
                code_artifact=artifact,
                code_review=review,
                sandbox_outcome=sandbox_outcome,
                physics_validation_report=physics_report,
                validation_report=validation,
            )
        multiple_comparison_report = None
        result_values = dict(sandbox_outcome.result_values)
        if request.multiple_comparison_correction:
            p_values = {
                key: value
                for key, value in result_values.items()
                if key.endswith("_p") and 0.0 <= value <= 1.0
            }
            if not p_values:
                raise ValueError("multiple-comparison correction requires p-value result keys")
            multiple_comparison_report = self.multiple_comparison_operator.run(
                report_id=f"multiplicity-{uuid4().hex}",
                p_values=p_values,
                method=request.multiple_comparison_method,
                alpha=request.multiple_comparison_alpha,
            )
            result_values.update(
                {
                    f"adjusted_{item.result_key}": item.adjusted_p_value
                    for item in multiple_comparison_report.results
                }
            )
        robustness_report = None
        if request.robustness_analysis:
            if not request.robustness_group_column or not request.robustness_outcome_column:
                raise ValueError("robustness analysis requires group and outcome columns")
            if request.robustness_primary_estimate is None:
                raise ValueError("robustness analysis requires the pre-specified primary estimate")
            frame = pd.read_csv(request.frozen_dataset.content_uri)
            group_column = request.robustness_group_column
            outcome_column = request.robustness_outcome_column
            if group_column not in frame.columns or outcome_column not in frame.columns:
                raise ValueError("robustness columns are absent from the frozen dataset")
            groups = list(frame[group_column].dropna().astype(str).unique())
            if len(groups) != 2:
                raise ValueError("the first robustness operator supports exactly two groups")
            control = frame.loc[frame[group_column].astype(str) == groups[0], outcome_column].dropna().tolist()
            treatment = frame.loc[frame[group_column].astype(str) == groups[1], outcome_column].dropna().tolist()
            robustness_report = self.robustness_operator.run_two_group(
                control=[float(value) for value in control],
                treatment=[float(value) for value in treatment],
                primary_estimate=request.robustness_primary_estimate,
                report_id=f"robustness-{uuid4().hex}",
                bootstrap_samples=request.robustness_bootstrap_samples,
                permutations=request.robustness_permutations,
            )
            if robustness_report.status is not RobustnessStatus.PASS:
                return ResearchAnalysisExecutionResult(
                    code_specification=specification,
                    code_artifact=artifact,
                    code_review=review,
                    sandbox_outcome=sandbox_outcome,
                    physics_validation_report=physics_report,
                    validation_report=validation,
                    robustness_report=robustness_report,
                    multiple_comparison_report=multiple_comparison_report,
                )
        result_card = StatisticalResultCard.build_from_validation(
            result_id=f"result-card-{uuid4().hex}",
            project_id=request.project_id,
            execution_run_ref=sandbox_outcome.execution_run.operator_run_id,
            analysis_plan_ref=f"executable-plan://{request.executable_plan.executable_plan_id}",
            validation_report=validation,
            parsed_values=result_values,
            deterministic_parser_version="research-python-result-v1",
        )
        return ResearchAnalysisExecutionResult(
            code_specification=specification,
            code_artifact=artifact,
            code_review=review,
            sandbox_outcome=sandbox_outcome,
            physics_validation_report=physics_report,
            validation_report=validation,
            robustness_report=robustness_report,
            multiple_comparison_report=multiple_comparison_report,
            statistical_result_card=result_card,
        )
