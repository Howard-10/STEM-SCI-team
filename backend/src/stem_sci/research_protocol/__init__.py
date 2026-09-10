"""Research protocol contracts used by the Phase 1 agent scaffold."""

from .causal_adapters import (
    CausalAdapterReport,
    CausalLearnDiscoveryAdapter,
    DoWhyIdentificationAdapter,
)
from .models import (
    CausalDAGRef,
    Estimand,
    Hypothesis,
    OutcomeOperationalDefinition,
    PreregisteredAnalysisPlan,
    PrimaryContrast,
    PrimaryEstimand,
    ResearchContract,
    ResearchQuestion,
    StatisticalInferenceContract,
    StudyProtocol,
)
from .validation import (
    CausalDagReport,
    CausalDagSpec,
    CausalDagValidator,
    DagEdge,
    PowerAnalysisReport,
    PowerAnalysisRequest,
    PowerAnalyzer,
)

__all__ = [
    "CausalAdapterReport",
    "CausalDAGRef",
    "CausalDagReport",
    "CausalDagSpec",
    "CausalDagValidator",
    "CausalLearnDiscoveryAdapter",
    "DagEdge",
    "DoWhyIdentificationAdapter",
    "Estimand",
    "Hypothesis",
    "OutcomeOperationalDefinition",
    "PowerAnalysisReport",
    "PowerAnalysisRequest",
    "PowerAnalyzer",
    "PreregisteredAnalysisPlan",
    "PrimaryContrast",
    "PrimaryEstimand",
    "ResearchContract",
    "ResearchQuestion",
    "StatisticalInferenceContract",
    "StudyProtocol",
]
