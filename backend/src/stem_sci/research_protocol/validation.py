"""Deterministic checks for causal design and prospective statistical power."""

from __future__ import annotations

import math
from collections import defaultdict, deque
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field
from scipy.stats import norm  # type: ignore[import-untyped]


class ProtocolValidationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DagEdge(ProtocolValidationModel):
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)


class CausalDagSpec(ProtocolValidationModel):
    treatment: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    nodes: list[str] = Field(min_length=2)
    edges: list[DagEdge] = Field(default_factory=list)
    adjustment_set: list[str] = Field(default_factory=list)


class DagFindingSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCK = "BLOCK"


class DagFinding(ProtocolValidationModel):
    code: str = Field(min_length=1)
    severity: DagFindingSeverity
    message: str = Field(min_length=1)
    node_refs: list[str] = Field(default_factory=list)


class CausalDagReport(ProtocolValidationModel):
    validator_version: str = "causal-dag-v1"
    passed: bool
    findings: list[DagFinding] = Field(default_factory=list)
    topological_order: list[str] = Field(default_factory=list)


class PowerAnalysisRequest(ProtocolValidationModel):
    effect_size: float = Field(gt=0.0)
    alpha: float = Field(default=0.05, gt=0.0, lt=1.0)
    target_power: float = Field(default=0.80, gt=0.0, lt=1.0)
    groups: int = Field(default=2, ge=2)
    allocation_ratio: float = Field(default=1.0, gt=0.0)
    expected_total_n: int | None = Field(default=None, ge=2)


class PowerAnalysisReport(ProtocolValidationModel):
    analyzer_version: str = "two-sample-normal-power-v1"
    required_total_n: int
    required_per_group_n: int
    expected_total_n: int | None
    estimated_power: float = Field(ge=0.0, le=1.0)
    target_power: float
    passed: bool
    assumptions: list[str] = Field(default_factory=list)


class CausalDagValidator:
    """Fail-closed structural checks; this is not a causal identification proof."""

    def validate(self, spec: CausalDagSpec) -> CausalDagReport:
        findings: list[DagFinding] = []
        node_set = set(spec.nodes)
        if spec.treatment not in node_set or spec.outcome not in node_set:
            findings.append(DagFinding(code="DAG_ENDPOINT_MISSING", severity=DagFindingSeverity.BLOCK, message="Treatment and outcome must be declared nodes."))
        edge_pairs = {(edge.source, edge.target) for edge in spec.edges}
        for edge in spec.edges:
            if edge.source not in node_set or edge.target not in node_set:
                findings.append(DagFinding(code="DAG_EDGE_NODE_MISSING", severity=DagFindingSeverity.BLOCK, message="Every edge endpoint must be declared as a node.", node_refs=[edge.source, edge.target]))
        if (spec.treatment, spec.treatment) in edge_pairs or (spec.outcome, spec.outcome) in edge_pairs:
            findings.append(DagFinding(code="DAG_SELF_LOOP", severity=DagFindingSeverity.BLOCK, message="A causal graph cannot contain self-loops."))
        order = self._topological_order(spec.nodes, spec.edges)
        if not order:
            findings.append(DagFinding(code="DAG_CYCLE", severity=DagFindingSeverity.BLOCK, message="The causal graph contains a directed cycle."))
        descendants = self._descendants(spec.treatment, spec.edges)
        for node in spec.adjustment_set:
            if node not in node_set:
                findings.append(DagFinding(code="DAG_ADJUSTMENT_NODE_MISSING", severity=DagFindingSeverity.BLOCK, message="Adjustment set contains an undeclared node.", node_refs=[node]))
            elif node in descendants:
                findings.append(DagFinding(code="DAG_POST_TREATMENT_ADJUSTMENT", severity=DagFindingSeverity.BLOCK, message="Adjustment set contains a descendant of treatment.", node_refs=[spec.treatment, node]))
        passed = not any(item.severity is DagFindingSeverity.BLOCK for item in findings)
        return CausalDagReport(passed=passed, findings=findings, topological_order=order)

    @staticmethod
    def _topological_order(nodes: list[str], edges: list[DagEdge]) -> list[str]:
        outgoing: dict[str, list[str]] = defaultdict(list)
        indegree = {node: 0 for node in nodes}
        for edge in edges:
            if edge.source in indegree and edge.target in indegree:
                outgoing[edge.source].append(edge.target)
                indegree[edge.target] += 1
        queue = deque(sorted(node for node, degree in indegree.items() if degree == 0))
        order: list[str] = []
        while queue:
            node = queue.popleft()
            order.append(node)
            for target in sorted(outgoing[node]):
                indegree[target] -= 1
                if indegree[target] == 0:
                    queue.append(target)
        return order if len(order) == len(nodes) else []

    @staticmethod
    def _descendants(source: str, edges: list[DagEdge]) -> set[str]:
        outgoing: dict[str, set[str]] = defaultdict(set)
        for edge in edges:
            outgoing[edge.source].add(edge.target)
        found: set[str] = set()
        queue = deque([source])
        while queue:
            current = queue.popleft()
            for target in outgoing[current]:
                if target not in found:
                    found.add(target)
                    queue.append(target)
        return found


class PowerAnalyzer:
    """Prospective approximation for a two-group standardized mean effect."""

    def analyze(self, request: PowerAnalysisRequest) -> PowerAnalysisReport:
        z_alpha = norm.ppf(1 - request.alpha / 2)
        z_power = norm.ppf(request.target_power)
        base_per_group = math.ceil(2 * ((z_alpha + z_power) / request.effect_size) ** 2)
        required_per_group = max(2, base_per_group)
        required_total = required_per_group * request.groups
        estimated = self._power(request, request.expected_total_n) if request.expected_total_n else 0.0
        passed = request.expected_total_n is not None and estimated >= request.target_power
        return PowerAnalysisReport(
            required_total_n=required_total,
            required_per_group_n=required_per_group,
            expected_total_n=request.expected_total_n,
            estimated_power=round(estimated, 6),
            target_power=request.target_power,
            passed=passed,
            assumptions=["standardized mean difference", "two-sided normal approximation", "independent group allocation"],
        )

    @staticmethod
    def _power(request: PowerAnalysisRequest, total_n: int | None) -> float:
        if not total_n or total_n < request.groups * 2:
            return 0.0
        per_group = total_n / request.groups
        noncentral = request.effect_size * math.sqrt(per_group / 2)
        critical = norm.ppf(1 - request.alpha / 2)
        return float(norm.cdf(-critical - noncentral) + 1 - norm.cdf(critical - noncentral))
