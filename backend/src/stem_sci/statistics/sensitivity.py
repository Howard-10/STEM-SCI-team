"""Quantitative omitted-confounding sensitivity baseline.

This is a dependency-free sensitivity report with a Sensemakr-compatible
boundary. It does not claim to recover unobserved confounders.
"""

from __future__ import annotations

from math import sqrt

from pydantic import BaseModel, ConfigDict, Field


class ConfoundingSensitivityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(min_length=1)
    provider_id: str = "sensemakr-compatible-v1"
    estimate: float
    standard_error: float = Field(gt=0.0)
    benchmark_partial_r2: float = Field(ge=0.0, lt=1.0)
    robustness_value: float = Field(ge=0.0, le=1.0)
    adjusted_estimate_at_benchmark: float
    conclusion: str
    requires_human_review: bool = True


class SensemakrAdapter:
    """Compute an auditable omitted-confounding robustness value.

    The bound uses the standard t-statistic approximation: RV_q is the
    confounder partial-R2 required to reduce the estimate to zero at q=1.
    """

    def run(
        self,
        *,
        report_id: str,
        estimate: float,
        standard_error: float,
        benchmark_partial_r2: float = 0.0,
    ) -> ConfoundingSensitivityReport:
        if standard_error <= 0.0 or not 0.0 <= benchmark_partial_r2 < 1.0:
            raise ValueError("standard error must be positive and benchmark R2 must be in [0, 1)")
        t_value = abs(estimate / standard_error)
        robustness_value = t_value / (t_value + 1.0) if t_value else 0.0
        benchmark_adjustment = max(0.0, 1.0 - sqrt(benchmark_partial_r2))
        adjusted = estimate * benchmark_adjustment
        conclusion = (
            "Benchmark confounding does not eliminate the estimate."
            if abs(adjusted) > standard_error
            else "Benchmark confounding could materially weaken the estimate."
        )
        return ConfoundingSensitivityReport(
            report_id=report_id,
            estimate=estimate,
            standard_error=standard_error,
            benchmark_partial_r2=benchmark_partial_r2,
            robustness_value=robustness_value,
            adjusted_estimate_at_benchmark=adjusted,
            conclusion=conclusion,
        )
