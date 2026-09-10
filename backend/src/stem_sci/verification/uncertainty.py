"""Cross-stage uncertainty assessment and fail-closed routing."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from stem_sci.core.enums import GateDecision


class SignalStatus(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    BLOCK = "BLOCK"


class QualitySignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)
    status: SignalStatus
    reason: str = Field(min_length=1)
    refs: list[str] = Field(default_factory=list)


class UncertaintyAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_id: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    decision: GateDecision
    signals: list[QualitySignal]
    risk_flags: list[str] = Field(default_factory=list)


class UncertaintyGate:
    """Combine deterministic quality signals without asking an LLM to self-score."""

    def assess(self, *, assessment_id: str, stage: str, signals: list[QualitySignal]) -> UncertaintyAssessment:
        if any(signal.status is SignalStatus.BLOCK for signal in signals):
            decision = GateDecision.BLOCKED
        elif any(signal.status is SignalStatus.WARNING for signal in signals):
            decision = GateDecision.PASS_WITH_WARNING
        else:
            decision = GateDecision.PASS
        risk_flags = [
            f"{signal.category.upper()}_UNCERTAINTY"
            for signal in signals
            if signal.status is not SignalStatus.PASS
        ]
        return UncertaintyAssessment(
            assessment_id=assessment_id,
            stage=stage,
            decision=decision,
            signals=signals,
            risk_flags=sorted(set(risk_flags)),
        )
