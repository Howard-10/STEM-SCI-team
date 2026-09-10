"""Auditable outlier screening with optional PyOD integration."""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, ConfigDict, Field


class OutlierFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_index: int = Field(ge=0)
    score: float
    flagged: bool
    reason: str


class OutlierReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str
    detector_id: str
    findings: list[OutlierFinding]
    requires_human_review: bool = True


class PyODOutlierAdapter:
    """Use PyOD when installed, otherwise a conservative MAD fallback."""

    def run(self, *, report_id: str, values: list[float]) -> OutlierReport:
        array = np.asarray(values, dtype=float)
        if array.size == 0 or not np.isfinite(array).all():
            raise ValueError("outlier screening requires finite numeric values")
        try:
            from pyod.models.ecod import ECOD  # type: ignore[import-not-found]
        except ImportError:
            median = float(np.median(array))
            mad = float(np.median(np.abs(array - median)))
            scale = max(mad * 1.4826, np.finfo(float).eps)
            scores = np.abs(array - median) / scale
            detector_id = "mad-outlier-screen-v1"
        else:
            # PyOD 2.x removed the string ``"auto"`` threshold mode.  A
            # conservative 5% contamination value keeps the detector's
            # labels valid while the report still exposes scores and leaves
            # the inclusion decision to the researcher.
            detector = ECOD(contamination=0.05)
            detector.fit(array.reshape(-1, 1))
            scores = np.asarray(detector.decision_scores_, dtype=float)
            detector_id = "pyod-ecod"
        return OutlierReport(
            report_id=report_id,
            detector_id=detector_id,
            findings=[
                OutlierFinding(
                    row_index=index,
                    score=float(score),
                    flagged=bool(score >= 3.5 if detector_id.startswith("mad") else score > np.quantile(scores, 0.95)),
                    reason="Flag only; exclusion requires researcher decision.",
                )
                for index, score in enumerate(scores)
            ],
        )
