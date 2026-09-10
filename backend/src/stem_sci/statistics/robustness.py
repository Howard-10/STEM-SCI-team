"""Pre-specified, deterministic robustness checks for simple group effects."""

from __future__ import annotations

from enum import StrEnum

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field


class RobustnessStatus(StrEnum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    FAIL = "FAIL"


class RobustnessCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_id: str = Field(min_length=1)
    method: str = Field(min_length=1)
    estimate: float
    p_value: float | None = Field(default=None, ge=0.0, le=1.0)
    ci_lower: float | None = None
    ci_upper: float | None = None
    status: RobustnessStatus
    finding_codes: list[str] = Field(default_factory=list)


class RobustnessReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(min_length=1)
    operator_version: str = "robustness-v1"
    primary_estimate: float
    checks: list[RobustnessCheck]
    direction_consistent: bool
    status: RobustnessStatus
    risk_flags: list[str] = Field(default_factory=list)


class RobustnessAnalysisOperator:
    """Bootstrap and permutation checks without changing the primary model."""

    def run_two_group(
        self,
        *,
        control: list[float],
        treatment: list[float],
        primary_estimate: float,
        report_id: str,
        bootstrap_samples: int = 2000,
        permutations: int = 2000,
        seed: int = 20260826,
    ) -> RobustnessReport:
        if len(control) < 2 or len(treatment) < 2:
            raise ValueError("robustness checks require at least two observations per group")
        rng = np.random.default_rng(seed)
        control_array: NDArray[np.float64] = np.asarray(control, dtype=float)
        treatment_array: NDArray[np.float64] = np.asarray(treatment, dtype=float)
        if not np.isfinite(control_array).all() or not np.isfinite(treatment_array).all():
            raise ValueError("robustness checks require finite numeric observations")
        observed = float(np.mean(treatment_array) - np.mean(control_array))
        boot: NDArray[np.float64] = np.empty(bootstrap_samples, dtype=float)
        for index in range(bootstrap_samples):
            boot[index] = float(
                np.mean(rng.choice(treatment_array, len(treatment_array), replace=True))
                - np.mean(rng.choice(control_array, len(control_array), replace=True))
            )
        ci_lower, ci_upper = np.quantile(boot, [0.025, 0.975]).tolist()
        pooled = np.concatenate([control_array, treatment_array])
        observed_abs = abs(observed)
        extreme = 0
        for _ in range(permutations):
            shuffled = rng.permutation(pooled)
            difference = abs(float(np.mean(shuffled[: len(treatment_array)]) - np.mean(shuffled[len(treatment_array) :])))
            extreme += int(difference >= observed_abs)
        p_value = (extreme + 1) / (permutations + 1)
        interval_status = RobustnessStatus.PASS if ci_lower <= primary_estimate <= ci_upper else RobustnessStatus.REVIEW
        permutation_status = RobustnessStatus.PASS if np.sign(observed) == np.sign(primary_estimate) else RobustnessStatus.REVIEW
        checks = [
            RobustnessCheck(check_id=f"{report_id}:bootstrap", method="bootstrap_ci", estimate=observed, ci_lower=float(ci_lower), ci_upper=float(ci_upper), status=interval_status, finding_codes=[] if interval_status is RobustnessStatus.PASS else ["PRIMARY_OUTSIDE_BOOTSTRAP_INTERVAL"]),
            RobustnessCheck(check_id=f"{report_id}:permutation", method="permutation_test", estimate=observed, p_value=float(p_value), status=permutation_status, finding_codes=[] if permutation_status is RobustnessStatus.PASS else ["EFFECT_DIRECTION_CHANGED"]),
        ]
        direction_consistent = all(np.sign(item.estimate) == np.sign(primary_estimate) for item in checks)
        status = RobustnessStatus.PASS if all(item.status is RobustnessStatus.PASS for item in checks) else RobustnessStatus.REVIEW
        return RobustnessReport(
            report_id=report_id,
            primary_estimate=primary_estimate,
            checks=checks,
            direction_consistent=direction_consistent,
            status=status,
            risk_flags=[] if status is RobustnessStatus.PASS else ["ROBUSTNESS_REQUIRES_REVIEW"],
        )
