import pandas as pd

from stem_sci.knowledge.screening import LexicalActiveScreener, ScreeningRecord
from stem_sci.research_protocol.causal_adapters import (
    CausalLearnDiscoveryAdapter,
    DoWhyIdentificationAdapter,
)
from stem_sci.research_protocol.validation import CausalDagSpec, DagEdge
from stem_sci.statistics.conformal import MAPIEConformalAdapter
from stem_sci.statistics.outliers import PyODOutlierAdapter
from stem_sci.statistics.sensitivity import SensemakrAdapter


def test_active_screening_keeps_human_review_boundary() -> None:
    queue = LexicalActiveScreener().rank(
        queue_id="screen-1",
        query="causal physics experiment",
        records=[
            ScreeningRecord(paper_id="p1", title="Causal physics experiment", abstract=""),
            ScreeningRecord(paper_id="p2", title="Unrelated topic", abstract=""),
        ],
        relevant_paper_ids={"p1"},
    )
    assert queue.decisions[0].paper_id == "p1"
    assert all(item.decision == "REVIEW" for item in queue.decisions)


def test_optional_causal_adapters_fail_closed_without_external_packages() -> None:
    frame = pd.DataFrame({"treatment": [0, 1, 0], "outcome": [1, 2, 1]})
    proposal = CausalLearnDiscoveryAdapter().propose(report_id="causal-1", frame=frame, columns=list(frame))
    identified = DoWhyIdentificationAdapter().identify(
        report_id="causal-2",
        frame=frame,
        spec=CausalDagSpec(
            treatment="treatment",
            outcome="outcome",
            nodes=["treatment", "outcome"],
            edges=[DagEdge(source="treatment", target="outcome")],
        ),
    )
    assert proposal.status in {"UNAVAILABLE", "PROPOSAL_READY"}
    assert identified.status in {"UNAVAILABLE", "IDENTIFIED", "ERROR", "NOT_IDENTIFIED"}


def test_outlier_and_conformal_fallbacks_are_auditable() -> None:
    outliers = PyODOutlierAdapter().run(report_id="outlier-1", values=[1.0, 1.1, 1.0, 20.0])
    interval = MAPIEConformalAdapter().interval(
        prediction=10.0,
        calibration_residuals=[1.0, 2.0, 1.5, 0.5],
    )
    assert outliers.requires_human_review is True
    assert any(item.flagged for item in outliers.findings)
    assert interval.lower < interval.prediction < interval.upper


def test_confounding_sensitivity_report_is_explicitly_qualified() -> None:
    report = SensemakrAdapter().run(
        report_id="sensitivity-1", estimate=0.4, standard_error=0.1, benchmark_partial_r2=0.04
    )
    assert report.provider_id == "sensemakr-compatible-v1"
    assert 0.0 <= report.robustness_value <= 1.0
    assert report.requires_human_review is True
