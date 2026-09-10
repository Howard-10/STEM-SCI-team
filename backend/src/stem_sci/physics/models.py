"""Typed reports for deterministic physics validation."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from stem_sci.core.models import DomainModel


class PhysicsCheck(DomainModel):
    check_id: str = Field(min_length=1)
    kind: Literal["formula", "unit", "constraint", "dependency"]
    passed: bool
    message: str = Field(min_length=1)
    source: str | None = None


class PhysicsValidationReport(DomainModel):
    """Pre-execution report; it never creates statistical result values."""

    report_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    code_artifact_ref: str = Field(min_length=1)
    passed: bool
    requires_human_review: bool = False
    checks: list[PhysicsCheck] = Field(default_factory=list)
    finding_codes: list[str] = Field(default_factory=list)

    @property
    def ref(self) -> str:
        return f"physics-validation://{self.report_id}"
