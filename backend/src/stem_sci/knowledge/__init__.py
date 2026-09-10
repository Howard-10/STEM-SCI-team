"""Read-only shared-corpus retrieval and graph-navigation primitives.

This package deliberately separates retrieval navigation from research evidence.
Graph triples may nominate papers, while only traceable source excerpts may be
used in a ContextBundle.
"""

from .document_parser import GrobidDocumentParser, ParsedDocument, ParsedSection
from .evidence_quality import (
    ClaimSupportEvaluation,
    ClaimSupportReport,
    ClaimSupportStatus,
    LexicalEvidenceEvaluator,
    TransformersNLIProvider,
    build_claim_support_report,
    configured_evidence_provider,
)
from .graph_extraction import (
    GraphExtractionOperator,
    GraphExtractionProvider,
    GraphExtractionUnavailable,
    UnavailableGraphExtractionProvider,
)
from .graph_schema import (
    GraphEntityType,
    GraphExtractionMode,
    GraphExtractionRequest,
    GraphExtractionResult,
    GraphRelationType,
    GraphTriple,
)
from .models import (
    ContextMode,
    CorpusManifest,
    CorpusReadiness,
    HybridContextBuildRequest,
    RetrievalSearchRequest,
    RetrievalSearchResponse,
    RetrievalStrategy,
    SharedCorpusSummary,
)
from .qa_models import (
    ConversationSummary,
    MemoryTurn,
    QAAnswerRequest,
    QAAnswerResponse,
    QARouteDecision,
)
from .qa_service import QuestionAnswerService
from .reranker import LexicalReranker, SentenceTransformersCrossEncoder
from .screening import (
    ASReviewAdapter,
    LexicalActiveScreener,
    ScreeningDecision,
    ScreeningQueue,
    ScreeningRecord,
)
from .service import HybridKnowledgeService

__all__ = [
    "ASReviewAdapter",
    "ClaimSupportEvaluation",
    "ClaimSupportReport",
    "ClaimSupportStatus",
    "ContextMode",
    "ConversationSummary",
    "CorpusManifest",
    "CorpusReadiness",
    "GraphEntityType",
    "GraphExtractionMode",
    "GraphExtractionOperator",
    "GraphExtractionProvider",
    "GraphExtractionRequest",
    "GraphExtractionResult",
    "GraphExtractionUnavailable",
    "GraphRelationType",
    "GraphTriple",
    "GrobidDocumentParser",
    "HybridContextBuildRequest",
    "HybridKnowledgeService",
    "LexicalActiveScreener",
    "LexicalEvidenceEvaluator",
    "LexicalReranker",
    "MemoryTurn",
    "ParsedDocument",
    "ParsedSection",
    "QAAnswerRequest",
    "QAAnswerResponse",
    "QARouteDecision",
    "QuestionAnswerService",
    "RetrievalSearchRequest",
    "RetrievalSearchResponse",
    "RetrievalStrategy",
    "ScreeningDecision",
    "ScreeningQueue",
    "ScreeningRecord",
    "SentenceTransformersCrossEncoder",
    "SharedCorpusSummary",
    "TransformersNLIProvider",
    "UnavailableGraphExtractionProvider",
    "build_claim_support_report",
    "configured_evidence_provider",
]
