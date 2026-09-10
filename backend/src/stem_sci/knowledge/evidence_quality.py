"""Claim-to-evidence screening contracts.

The default evaluator is a lexical screening layer.  It is intentionally
labelled as such and must not be presented as an NLI model.  A production NLI
provider can implement ``EvidenceEntailmentProvider`` without changing the
Evidence Gate contract.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class ClaimSupportStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    CONTRADICTED = "CONTRADICTED"
    UNKNOWN = "UNKNOWN"


class EvidenceEntailmentProvider(Protocol):
    model_id: str

    def evaluate(self, claim: str, evidence: str) -> tuple[ClaimSupportStatus, float, str]:
        ...


class ClaimSupportEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_ref: str = Field(min_length=1)
    status: ClaimSupportStatus
    score: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1)


class ClaimSupportReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str = Field(min_length=1)
    evaluator_id: str = Field(min_length=1)
    evaluations: list[ClaimSupportEvaluation]
    overall_status: ClaimSupportStatus
    risk_flags: list[str] = Field(default_factory=list)


def _tokens(value: str) -> set[str]:
    lowered = value.casefold()
    words = set(re.findall(r"[a-z0-9_]+", lowered))
    cjk = {char for char in lowered if "\u4e00" <= char <= "\u9fff"}
    return words | cjk


class LexicalEvidenceEvaluator:
    """Offline screening baseline with conservative support labels."""

    model_id = "lexical-evidence-screen-v1"

    def evaluate(self, claim: str, evidence: str) -> tuple[ClaimSupportStatus, float, str]:
        claim_tokens = _tokens(claim)
        evidence_tokens = _tokens(evidence)
        overlap = len(claim_tokens & evidence_tokens) / max(1, len(claim_tokens))
        negated = any(marker in evidence.casefold() for marker in ("not", "no effect", "无显著", "未发现"))
        if negated and overlap >= 0.35:
            return ClaimSupportStatus.CONTRADICTED, round(overlap, 4), "Evidence contains a negation marker."
        if overlap >= 0.70:
            return ClaimSupportStatus.SUPPORTED, round(overlap, 4), "High lexical claim-evidence overlap; semantic verification is still required."
        if overlap >= 0.35:
            return ClaimSupportStatus.PARTIAL, round(overlap, 4), "Evidence overlaps the claim but may not entail the full statement."
        return ClaimSupportStatus.UNKNOWN, round(overlap, 4), "Insufficient lexical overlap for a safe support decision."

    def build_report(
        self, claim: str, evidence: list[tuple[str, str]]
    ) -> ClaimSupportReport:
        return build_claim_support_report(self, claim, evidence)


def build_claim_support_report(
    provider: EvidenceEntailmentProvider,
    claim: str,
    evidence: list[tuple[str, str]],
) -> ClaimSupportReport:
    evaluations = [
        ClaimSupportEvaluation(
            evidence_ref=ref,
            status=status,
            score=score,
            rationale=rationale,
        )
        for ref, text in evidence
        for status, score, rationale in [provider.evaluate(claim, text)]
    ]
    statuses = {item.status for item in evaluations}
    risks: list[str] = []
    if ClaimSupportStatus.SUPPORTED in statuses and ClaimSupportStatus.CONTRADICTED in statuses:
        overall = ClaimSupportStatus.PARTIAL
        risks.append("CONFLICTING_EVIDENCE_REQUIRES_HUMAN_REVIEW")
    elif ClaimSupportStatus.SUPPORTED in statuses:
        overall = ClaimSupportStatus.SUPPORTED
    elif ClaimSupportStatus.PARTIAL in statuses:
        overall = ClaimSupportStatus.PARTIAL
    elif ClaimSupportStatus.CONTRADICTED in statuses:
        overall = ClaimSupportStatus.CONTRADICTED
    else:
        overall = ClaimSupportStatus.UNKNOWN
    if overall is not ClaimSupportStatus.SUPPORTED:
        risks.append("CLAIM_REQUIRES_SEMANTIC_OR_HUMAN_VERIFICATION")
    return ClaimSupportReport(
        claim=claim,
        evaluator_id=provider.model_id,
        evaluations=evaluations,
        overall_status=overall,
        risk_flags=risks,
    )


class TransformersNLIProvider:
    """Optional Hugging Face NLI provider with an explicit model identity."""

    def __init__(self, model_name: str) -> None:
        try:
            from transformers import pipeline  # type: ignore[import-not-found]
        except ImportError as error:
            raise RuntimeError("transformers is required for NLI evaluation") from error
        self.model_id = model_name
        self._pipeline = pipeline("text-classification", model=model_name)

    def evaluate(self, claim: str, evidence: str) -> tuple[ClaimSupportStatus, float, str]:
        result = self._pipeline(f"{evidence} [SEP] {claim}", truncation=True)[0]
        label = str(result.get("label", "")).casefold()
        score = float(result.get("score", 0.0))
        if "entail" in label or label in {"label_2", "2"}:
            status = ClaimSupportStatus.SUPPORTED
        elif "contrad" in label or label in {"label_0", "0"}:
            status = ClaimSupportStatus.CONTRADICTED
        else:
            status = ClaimSupportStatus.UNKNOWN
        return status, round(score, 4), f"Transformers NLI label: {result.get('label', 'unknown')}"


def configured_evidence_provider() -> EvidenceEntailmentProvider:
    """Build the configured provider; callers must handle explicit degradation."""

    import os

    mode = os.getenv("STEM_SCI_NLI", "off").strip().lower()
    if mode in {"", "off", "lexical"}:
        return LexicalEvidenceEvaluator()
    if mode != "transformers":
        raise RuntimeError(f"unknown STEM_SCI_NLI mode: {mode}")
    model_name = os.getenv("STEM_SCI_NLI_MODEL", "cross-encoder/nli-deberta-v3-base")
    return TransformersNLIProvider(model_name)
