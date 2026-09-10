"""Public contracts for claim-safe bilingual writing."""

from .bilingual import compare_bilingual_drafts
from .models import (
    AtomicClaimGraph,
    AtomicClaimNode,
    BilingualConsistencyReport,
    BilingualConsistencyStatus,
    ClaimRelation,
    LanguageCode,
    ManuscriptDraft,
    ManuscriptOutline,
    WritingContextBundle,
    WritingCritiqueFinding,
    WritingCritiqueReport,
    WritingReviewerFinding,
    WritingReviewerResponse,
    WritingPackage,
    WritingSufficiencyReport,
    WritingSufficiencyStatus,
)
from .pipeline import PaperWritingPipeline
from .validators import critique_manuscript, validate_claim_graph, validate_claim_node

__all__ = [
    "AtomicClaimGraph",
    "AtomicClaimNode",
    "BilingualConsistencyReport",
    "BilingualConsistencyStatus",
    "ClaimRelation",
    "LanguageCode",
    "ManuscriptDraft",
    "ManuscriptOutline",
    "PaperWritingPipeline",
    "WritingContextBundle",
    "WritingCritiqueFinding",
    "WritingCritiqueReport",
    "WritingReviewerFinding",
    "WritingReviewerResponse",
    "WritingPackage",
    "WritingSufficiencyReport",
    "WritingSufficiencyStatus",
    "compare_bilingual_drafts",
    "critique_manuscript",
    "validate_claim_graph",
    "validate_claim_node",
]
