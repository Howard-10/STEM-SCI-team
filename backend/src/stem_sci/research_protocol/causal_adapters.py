"""Optional causal-discovery and causal-identification adapters."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .validation import CausalDagSpec, DagEdge


class CausalAdapterReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    status: str
    passed: bool
    requires_human_review: bool = True
    edges: list[DagEdge] = Field(default_factory=list)
    adjustment_set: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)


class CausalLearnDiscoveryAdapter:
    """Propose a DAG from data; proposals never bypass researcher approval."""

    provider_id = "causal-learn"

    def propose(self, *, report_id: str, frame: Any, columns: list[str]) -> CausalAdapterReport:
        try:
            from causallearn.search.ConstraintBased.PC import pc  # type: ignore[import-not-found]
        except ImportError:
            return CausalAdapterReport(
                report_id=report_id,
                provider_id=self.provider_id,
                status="UNAVAILABLE",
                passed=False,
                findings=["CAUSAL_LEARN_UNAVAILABLE"],
            )
        values = frame[columns].to_numpy()
        graph = pc(values)
        edges: list[DagEdge] = []
        for edge in graph.G.get_graph_edges():
            source_name = edge.get_node1().get_name()
            target_name = edge.get_node2().get_name()
            if source_name in columns and target_name in columns:
                edges.append(DagEdge(source=source_name, target=target_name))
        return CausalAdapterReport(
            report_id=report_id,
            provider_id=self.provider_id,
            status="PROPOSAL_READY",
            passed=True,
            edges=edges,
            findings=["CANDIDATE_DAG_REQUIRES_RESEARCHER_APPROVAL"],
        )


class DoWhyIdentificationAdapter:
    """Identify an estimand from an already researcher-approved DAG."""

    provider_id = "dowhy"

    def identify(
        self,
        *,
        report_id: str,
        frame: Any,
        spec: CausalDagSpec,
    ) -> CausalAdapterReport:
        try:
            from dowhy import CausalModel  # type: ignore[import-not-found]
        except ImportError:
            return CausalAdapterReport(
                report_id=report_id,
                provider_id=self.provider_id,
                status="UNAVAILABLE",
                passed=False,
                requires_human_review=True,
                adjustment_set=spec.adjustment_set,
                findings=["DOWHY_UNAVAILABLE"],
            )
        # DoWhy accepts a NetworkX graph (or a DOT/GML string), not the
        # project-level dictionary representation used in ``CausalDagSpec``.
        try:
            import networkx as nx

            graph = nx.DiGraph()
            graph.add_nodes_from(spec.nodes)
            graph.add_edges_from((edge.source, edge.target) for edge in spec.edges)
            model = CausalModel(
                data=frame,
                treatment=spec.treatment,
                outcome=spec.outcome,
                graph=graph,
            )
            estimand = model.identify_effect()
        except (ImportError, TypeError, ValueError) as error:
            return CausalAdapterReport(
                report_id=report_id,
                provider_id=self.provider_id,
                status="ERROR",
                passed=False,
                requires_human_review=True,
                adjustment_set=spec.adjustment_set,
                findings=[f"DOWHY_IDENTIFICATION_FAILED:{type(error).__name__}"],
            )
        return CausalAdapterReport(
            report_id=report_id,
            provider_id=self.provider_id,
            status="IDENTIFIED" if estimand is not None else "NOT_IDENTIFIED",
            passed=estimand is not None,
            requires_human_review=estimand is None,
            adjustment_set=spec.adjustment_set,
            findings=[] if estimand is not None else ["CAUSAL_ESTIMAND_NOT_IDENTIFIED"],
        )
