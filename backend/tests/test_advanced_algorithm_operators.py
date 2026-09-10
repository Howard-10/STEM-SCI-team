from __future__ import annotations

from stem_sci.core.enums import GateDecision
from stem_sci.knowledge.evidence_quality import (
    ClaimSupportStatus,
    LexicalEvidenceEvaluator,
)
from stem_sci.knowledge.hybrid_retriever import HybridRetriever
from stem_sci.knowledge.models import RetrievalHit
from stem_sci.knowledge.reranker import LexicalReranker
from stem_sci.research_protocol.validation import (
    CausalDagSpec,
    CausalDagValidator,
    DagEdge,
    PowerAnalysisRequest,
    PowerAnalyzer,
)
from stem_sci.statistics.robustness import RobustnessAnalysisOperator, RobustnessStatus
from stem_sci.verification.uncertainty import (
    QualitySignal,
    SignalStatus,
    UncertaintyGate,
)


def _hit(chunk_id: str, text: str, rank: int) -> RetrievalHit:
    return RetrievalHit(
        canonical_chunk_id=chunk_id,
        canonical_paper_id=f"paper-{chunk_id}",
        source_filename=f"{chunk_id}.pdf",
        paper_title=chunk_id,
        chunk_index=0,
        text=text,
        sparse_rank=rank,
        rrf_score=1 / (60 + rank),
    )


def test_hybrid_retriever_records_reranker_trace() -> None:
    retriever = HybridRetriever(
        corpus_id="test",
        manifest_refs=["manifest://test"],
        graph_retriever=None,
        dense_search=None,
        sparse_search=lambda _query, _limit: [
            _hit("low", "unrelated biology text", 1),
            _hit("high", "physics modeling with AI scaffolding", 2),
        ],
        reranker=LexicalReranker(),
    )
    hits, trace = retriever.retrieve("physics modeling", limit=1)
    assert hits[0].canonical_chunk_id == "high"
    assert trace.reranking_enabled is True
    assert trace.reranking_model == "lexical-overlap-fallback-v1"


def test_claim_evidence_screen_is_conservative() -> None:
    report = LexicalEvidenceEvaluator().build_report(
        "AI scaffolding improves transfer performance",
        [("evidence://1", "AI scaffolding improves transfer performance in the study")],
    )
    assert report.overall_status is ClaimSupportStatus.SUPPORTED
    partial = LexicalEvidenceEvaluator().build_report(
        "AI scaffolding improves transfer performance",
        [("evidence://2", "AI scaffolding was used during the intervention")],
    )
    assert partial.overall_status in {ClaimSupportStatus.PARTIAL, ClaimSupportStatus.UNKNOWN}


def test_dag_validator_blocks_post_treatment_adjustment() -> None:
    report = CausalDagValidator().validate(
        CausalDagSpec(
            treatment="ai_scaffold",
            outcome="transfer",
            nodes=["ai_scaffold", "post_score", "transfer"],
            edges=[DagEdge(source="ai_scaffold", target="post_score"), DagEdge(source="post_score", target="transfer")],
            adjustment_set=["post_score"],
        )
    )
    assert report.passed is False
    assert any(item.code == "DAG_POST_TREATMENT_ADJUSTMENT" for item in report.findings)


def test_power_analyzer_reports_underpowered_design() -> None:
    report = PowerAnalyzer().analyze(
        PowerAnalysisRequest(effect_size=0.4, expected_total_n=20)
    )
    assert report.passed is False
    assert report.required_total_n > 20


def test_robustness_operator_passes_stable_effect() -> None:
    report = RobustnessAnalysisOperator().run_two_group(
        control=[1, 2, 2, 3, 2, 1],
        treatment=[5, 6, 6, 7, 5, 6],
        primary_estimate=4.0,
        report_id="robustness://test",
        bootstrap_samples=200,
        permutations=200,
    )
    assert report.status is RobustnessStatus.PASS
    assert report.direction_consistent is True


def test_uncertainty_gate_blocks_on_blocking_signal() -> None:
    assessment = UncertaintyGate().assess(
        assessment_id="assessment://test",
        stage="EVIDENCE_READY",
        signals=[
            QualitySignal(
                signal_id="evidence-1",
                category="evidence",
                score=0.1,
                status=SignalStatus.BLOCK,
                reason="Claim is not source verified.",
            )
        ],
    )
    assert assessment.decision is GateDecision.BLOCKED
    assert assessment.risk_flags == ["EVIDENCE_UNCERTAINTY"]
