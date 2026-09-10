"""Deterministic validation for AtomicClaimGraph and writing inputs."""

from __future__ import annotations

from .models import (
    AtomicClaimGraph,
    AtomicClaimNode,
    ManuscriptDraft,
    WritingContextBundle,
    WritingCritiqueFinding,
    WritingCritiqueReport,
)


def validate_claim_node(
    claim: AtomicClaimNode, context: WritingContextBundle
) -> AtomicClaimNode:
    if claim.project_id != context.project_id:
        raise ValueError("claim project does not match writing context project")
    evidence_ids = {item.evidence_id for item in context.evidence_refs}
    formal_evidence_ids = {
        item.evidence_id
        for item in context.evidence_refs
        if item.verification_status.value in {"source_verified", "human_verified"}
    }
    if context.intended_use == "formal" and not set(claim.evidence_refs).issubset(
        formal_evidence_ids
    ):
        raise ValueError("formal claims require source_verified or human_verified evidence")
    if claim.claim_type.value == "LITERATURE":
        if not claim.evidence_refs or not set(claim.evidence_refs).issubset(evidence_ids):
            raise ValueError("literature claim requires context evidence")
    elif claim.claim_type.value == "RESULT":
        if claim.result_card_ref not in context.validated_result_cards:
            raise ValueError("result claim requires a validated result reference")
    elif claim.claim_type.value == "METHOD":
        if claim.method_ref not in context.approved_study_protocol_refs:
            raise ValueError("method claim requires an approved method reference")
    elif claim.claim_type.value == "INTERPRETATION":
        if not claim.evidence_refs:
            raise ValueError("interpretation claim requires bounded theory evidence")
        if claim.interpretation_boundary_ref is None:
            raise ValueError("interpretation claim requires an interpretation boundary")
        if claim.human_approval_ref is None:
            raise ValueError("interpretation claim requires human approval")
    return claim


def validate_claim_graph(
    graph: AtomicClaimGraph, context: WritingContextBundle
) -> AtomicClaimGraph:
    if graph.project_id != context.project_id:
        raise ValueError("claim graph project does not match writing context project")
    claim_ids: set[str] = set()
    nodes_by_id = {node.claim_id: node for node in graph.nodes}
    for claim in graph.nodes:
        if claim.claim_id in claim_ids:
            raise ValueError("claim IDs must be unique")
        claim_ids.add(claim.claim_id)
        validate_claim_node(claim, context)
        for target_id, _ in claim.relations:
            if target_id == claim.claim_id or target_id not in nodes_by_id:
                raise ValueError("claim relation must target another claim in the same graph")
        if claim.claim_type.value == "INTERPRETATION":
            result_relations = [
                target_id
                for target_id, relation in claim.relations
                if relation.value == "INTERPRETS"
                and nodes_by_id[target_id].claim_type.value == "RESULT"
            ]
            if not result_relations:
                raise ValueError("interpretation claim must interpret a RESULT claim")
    return graph


def critique_manuscript(
    draft: ManuscriptDraft,
    graph: AtomicClaimGraph,
    context: WritingContextBundle,
) -> WritingCritiqueReport:
    """Run cheap deterministic checks before a researcher reviews prose.

    This deliberately reports quality risks separately from schema validation:
    a short or incomplete section should be visible to the researcher, but it
    must not be silently rewritten or turn an otherwise traceable draft into a
    fabricated result.
    """

    findings: list[WritingCritiqueFinding] = []
    sections = {str(name).casefold(): text for name, text in draft.sections.items()}
    # Models commonly use ``ethics_limitations`` or ``limitations_and_ethics``
    # for the same required section. Normalize aliases before quality checks.
    if "limitations" not in sections:
        for alias in ("ethics_limitations", "limitations_and_ethics", "study_limitations"):
            if alias in sections:
                sections["limitations"] = sections[alias]
                break
    claim_ids = {node.claim_id for node in graph.nodes}
    literature_claims = [node for node in graph.nodes if node.claim_type.value == "LITERATURE"]
    result_claims = [node for node in graph.nodes if node.claim_type.value == "RESULT"]
    draft_claim_ids = set(draft.claim_ids)

    def add(code: str, severity: str, section: str | None, message: str, action: str, ids: list[str] | None = None) -> None:
        findings.append(
            WritingCritiqueFinding(
                finding_id=f"{draft.project_id}:{draft.language.value}:{code}:{len(findings) + 1}",
                severity=severity,  # type: ignore[arg-type]
                code=code,
                section=section,
                message=message,
                suggested_action=action,
                claim_ids=ids or [],
            )
        )

    minimum_lengths = {
        "introduction": 160,
        "methods": 140,
        "results": 140,
        "discussion": 180,
        "limitations": 100,
    }
    for section in minimum_lengths:
        text = sections.get(section, "")
        if not text.strip():
            add(
                "MISSING_SECTION",
                "WARNING",
                section,
                f"{section} section is missing or empty.",
                "Add only content supported by approved claims and evidence.",
            )
        elif len(text.strip()) < minimum_lengths[section]:
            add(
                "THIN_ARGUMENT",
                "WARNING",
                section,
                f"{section} is too short for its required argument structure.",
                "Expand the section with evidence-linked reasoning and explicit boundaries without adding new facts.",
            )

    if literature_claims and not draft.citation_refs:
        add(
            "LITERATURE_CITATION_GAP",
            "ERROR",
            "introduction",
            "Literature claims exist but the draft contains no citation references.",
            "Attach the relevant verified evidence IDs to the sentences that use those claims.",
            [node.claim_id for node in literature_claims],
        )
    if result_claims and not sections.get("results", "").strip():
        add(
            "RESULT_SECTION_GAP",
            "ERROR",
            "results",
            "Result claims exist but the Results section is empty.",
            "Render the validated result card and keep its scope and direction unchanged.",
            [node.claim_id for node in result_claims],
        )
    synthesis = context.evidence_synthesis
    gap_report = synthesis.get("research_gap_report") if isinstance(synthesis, dict) else None
    gaps = gap_report.get("gaps") if isinstance(gap_report, dict) else None
    introduction = sections.get("introduction", "")
    if isinstance(gaps, list) and gaps and introduction.strip():
        gap_terms = ("研究缺口", "研究空白", "不足", "gap", "unresolved", "limitation")
        if not any(term in introduction.casefold() for term in gap_terms):
            add(
                "RESEARCH_GAP_NOT_ARTICULATED",
                "WARNING",
                "introduction",
                "The evidence package contains research gaps, but the introduction does not articulate one.",
                "Connect the stated gap to the research question using only the supplied gap evidence.",
            )
    if result_claims and sections.get("discussion", "").strip():
        discussion = sections["discussion"].casefold()
        limitation_terms = ("局限", "限制", "不确定", "limitation", "uncertain", "caution")
        if not any(term in discussion for term in limitation_terms):
            add(
                "DISCUSSION_BOUNDARY_GAP",
                "WARNING",
                "discussion",
                "The discussion presents results without an explicit limitation or uncertainty boundary.",
                "Add a bounded limitation statement tied to the design and validated result scope.",
                [node.claim_id for node in result_claims],
            )
    unreferenced_claims = sorted(claim_ids - draft_claim_ids)
    if unreferenced_claims:
        add(
            "CLAIM_COVERAGE_GAP",
            "WARNING",
            None,
            "Some approved claims are not represented in the draft claim map.",
            "Add the missing claims to the appropriate section or explain why they were excluded.",
            unreferenced_claims,
        )
    unknown_claims = set(draft.claim_ids) - claim_ids
    if unknown_claims:
        add(
            "UNKNOWN_CLAIM_REFERENCE",
            "ERROR",
            None,
            "The draft references claims outside the current claim graph.",
            "Remove the references or regenerate from the current claim graph.",
            sorted(unknown_claims),
        )
    unknown_citations = set(draft.citation_refs) - {item.evidence_id for item in context.evidence_refs}
    if unknown_citations:
        add(
            "UNKNOWN_CITATION_REFERENCE",
            "ERROR",
            None,
            "The draft contains citation IDs not present in the approved evidence context.",
            "Replace them with approved evidence IDs; never invent a citation.",
        )

    errors = sum(item.severity == "ERROR" for item in findings)
    warnings = sum(item.severity == "WARNING" for item in findings)
    score = max(0, 100 - errors * 30 - warnings * 8)
    return WritingCritiqueReport(
        report_id=f"writing-critique:{draft.project_id}:{draft.language.value}",
        project_id=context.project_id,
        status="NEEDS_REVISION" if findings else "PASS",
        score=score,
        findings=findings,
    )
