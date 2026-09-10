"""Deterministic multiple-comparison correction for research result cards."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class MultiplicityMethod(StrEnum):
    HOLM = "holm"
    BONFERRONI = "bonferroni"
    FDR_BH = "fdr_bh"


class AdjustedPValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_key: str = Field(min_length=1)
    raw_p_value: float = Field(ge=0.0, le=1.0)
    adjusted_p_value: float = Field(ge=0.0, le=1.0)
    rejected: bool


class MultipleComparisonReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(min_length=1)
    method: MultiplicityMethod
    alpha: float = Field(gt=0.0, lt=1.0)
    results: list[AdjustedPValue] = Field(min_length=1)
    significant_count: int = Field(ge=0)


class MultipleComparisonOperator:
    """Apply a pre-specified correction without changing effect estimates."""

    operator_version = "multiple-comparison-v1"

    def run(
        self,
        *,
        report_id: str,
        p_values: dict[str, float],
        method: MultiplicityMethod = MultiplicityMethod.HOLM,
        alpha: float = 0.05,
    ) -> MultipleComparisonReport:
        if not p_values:
            raise ValueError("at least one p-value is required")
        if not 0.0 < alpha < 1.0:
            raise ValueError("alpha must be between 0 and 1")
        keys = list(p_values)
        values = [float(p_values[key]) for key in keys]
        if any(value < 0.0 or value > 1.0 for value in values):
            raise ValueError("p-values must be between 0 and 1")
        from statsmodels.stats.multitest import multipletests

        rejected, adjusted, _, _ = multipletests(values, alpha=alpha, method=method.value)
        results = [
            AdjustedPValue(
                result_key=key,
                raw_p_value=value,
                adjusted_p_value=float(adjusted[index]),
                rejected=bool(rejected[index]),
            )
            for index, (key, value) in enumerate(zip(keys, values, strict=True))
        ]
        return MultipleComparisonReport(
            report_id=report_id,
            method=method,
            alpha=alpha,
            results=results,
            significant_count=sum(item.rejected for item in results),
        )
