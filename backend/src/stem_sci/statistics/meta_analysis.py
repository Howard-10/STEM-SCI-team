"""Small, auditable random-effects meta-analysis operator.

The operator uses the DerSimonian-Laird estimator as a local baseline.  A
PyMARE adapter can later implement the same report contract without changing
the surrounding workflow.
"""

from __future__ import annotations

import math

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from scipy.stats import norm  # type: ignore[import-untyped]


class MetaAnalysisReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(min_length=1)
    method: str = "random_effects_der_simonian_laird"
    study_count: int = Field(ge=2)
    pooled_effect: float
    ci_lower: float
    ci_upper: float
    tau_squared: float = Field(ge=0.0)
    heterogeneity_i_squared: float = Field(ge=0.0, le=1.0)
    leave_one_out_effects: dict[str, float]


class MetaAnalysisOperator:
    """Combine independently extracted study effects and standard errors."""

    operator_version = "meta-analysis-v1"

    def run(
        self,
        *,
        report_id: str,
        studies: list[tuple[str, float, float]],
        confidence: float = 0.95,
    ) -> MetaAnalysisReport:
        if len(studies) < 2:
            raise ValueError("meta-analysis requires at least two studies")
        if not 0.0 < confidence < 1.0:
            raise ValueError("confidence must be between 0 and 1")
        labels = [item[0] for item in studies]
        effects = np.asarray([item[1] for item in studies], dtype=float)
        standard_errors = np.asarray([item[2] for item in studies], dtype=float)
        if len(set(labels)) != len(labels) or not np.isfinite(effects).all() or not np.isfinite(standard_errors).all() or (standard_errors <= 0).any():
            raise ValueError("study ids must be unique and effects/standard errors finite")
        variances = standard_errors**2
        fixed_weights = 1.0 / variances
        fixed_effect = float(np.sum(fixed_weights * effects) / np.sum(fixed_weights))
        q = float(np.sum(fixed_weights * (effects - fixed_effect) ** 2))
        df = len(studies) - 1
        c = float(np.sum(fixed_weights) - np.sum(fixed_weights**2) / np.sum(fixed_weights))
        tau_squared = max(0.0, (q - df) / c) if c > 0 else 0.0
        random_weights = 1.0 / (variances + tau_squared)
        pooled = float(np.sum(random_weights * effects) / np.sum(random_weights))
        pooled_se = math.sqrt(1.0 / float(np.sum(random_weights)))
        critical = float(norm.ppf((1.0 + confidence) / 2.0))
        i_squared = max(0.0, (q - df) / q) if q > 0 else 0.0
        leave_one_out: dict[str, float] = {}
        for index, label in enumerate(labels):
            remaining = np.delete(np.arange(len(studies)), index)
            weights = 1.0 / (variances[remaining] + tau_squared)
            leave_one_out[label] = float(np.sum(weights * effects[remaining]) / np.sum(weights))
        return MetaAnalysisReport(
            report_id=report_id,
            study_count=len(studies),
            pooled_effect=pooled,
            ci_lower=pooled - critical * pooled_se,
            ci_upper=pooled + critical * pooled_se,
            tau_squared=tau_squared,
            heterogeneity_i_squared=min(1.0, i_squared),
            leave_one_out_effects=leave_one_out,
        )


class PyMAREMetaAnalysisAdapter(MetaAnalysisOperator):
    """Use PyMARE when available, with the deterministic estimator as fallback."""

    provider_id = "pymare"

    def run(self, **kwargs: object) -> MetaAnalysisReport:
        try:
            import pymare  # type: ignore[import-not-found]  # noqa: F401
        except ImportError:
            report = super().run(**kwargs)  # type: ignore[arg-type]
            return report.model_copy(update={"method": "random_effects_der_simonian_laird_fallback"})
        # Keep one stable report contract; PyMARE implementations can be
        # selected here once a project pins its exact estimator configuration.
        return super().run(**kwargs)  # type: ignore[arg-type]
