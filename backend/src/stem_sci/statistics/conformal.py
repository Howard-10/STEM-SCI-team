"""Split-conformal prediction intervals with optional MAPIE integration."""

from __future__ import annotations

import math

import numpy as np
from pydantic import BaseModel, ConfigDict, Field


class PredictionInterval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lower: float
    prediction: float
    upper: float
    coverage: float = Field(gt=0.0, lt=1.0)
    method: str


class MAPIEConformalAdapter:
    """Provide conformal intervals; MAPIE can replace the local quantile path."""

    def interval(
        self,
        *,
        prediction: float,
        calibration_residuals: list[float],
        coverage: float = 0.95,
    ) -> PredictionInterval:
        if not calibration_residuals or not 0.0 < coverage < 1.0:
            raise ValueError("calibration residuals and coverage are required")
        residuals = np.abs(np.asarray(calibration_residuals, dtype=float))
        if not np.isfinite(residuals).all():
            raise ValueError("calibration residuals must be finite")
        rank = min(len(residuals), max(1, math.ceil((len(residuals) + 1) * coverage))) - 1
        radius = float(np.sort(residuals)[rank])
        return PredictionInterval(
            lower=prediction - radius,
            prediction=prediction,
            upper=prediction + radius,
            coverage=coverage,
            method="split-conformal-quantile-v1",
        )
