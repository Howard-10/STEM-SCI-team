"""Orchestration for claim-safe bilingual manuscript drafting."""

from __future__ import annotations

import os

from stem_sci.agents.contracts import AgentInput
from stem_sci.agents.runtime import (
    FakeLLMProvider,
    PromptRegistry,
    StructuredGenerationError,
    StructuredGenerator,
)
from stem_sci.skills.journal_writing import JournalProfileLoader, JournalSkillError

from .bilingual import compare_bilingual_drafts
from .models import (
    AtomicClaimGraph,
    BilingualConsistencyStatus,
    WritingContextBundle,
    WritingCritiqueFinding,
    WritingPackage,
    WritingReviewerFinding,
    WritingSufficiencyStatus,
)
from .prompts import register_writing_prompts
from .stages import (
    audit_writing_inputs,
    build_claim_graph,
    build_manuscript_outline,
    normalize_draft,
    render_manuscript,
    review_manuscript_arguments,
    validate_manuscript,
)
from .validators import critique_manuscript, validate_claim_graph, validate_claim_node


class PaperWritingPipeline:
    def __init__(
        self,
        *,
        generator: StructuredGenerator,
        model: str,
        prompt_registry: PromptRegistry | None = None,
        enable_llm_review: bool | None = None,
        journal_loader: JournalProfileLoader | None = None,
    ) -> None:
        self.generator = generator
        self.model = model
        self.prompt_registry = prompt_registry or PromptRegistry()
        self.journal_loader = journal_loader or JournalProfileLoader()
        register_writing_prompts(self.prompt_registry)
        if enable_llm_review is None:
            configured = _as_bool(
                os.getenv("STEM_SCI_WRITING_REVIEWER_ENABLED", "false")
            )
            # Fake providers are deterministic offline fixtures with a fixed
            # response queue. Do not unexpectedly consume a fifth response in
            # legacy tests; callers can still explicitly enable the reviewer.
            self.enable_llm_review = configured and not isinstance(
                generator.provider, FakeLLMProvider
            )
        else:
            self.enable_llm_review = enable_llm_review

    def run(self, context: WritingContextBundle, agent_input: AgentInput) -> WritingPackage:
        del agent_input
        context = self._context_with_empirical_framework(context)
        sufficiency = audit_writing_inputs(context)
        risks: list[str] = []
        metadata_refs: list[str] = []
        if not context.validated_result_cards:
            risks.append("INCOMPLETE_RESULT_INPUT")

        graph_stage = build_claim_graph(
            context, self.generator, self.prompt_registry, self.model
        )
        metadata_refs.append(graph_stage.metadata_ref)
        valid_nodes = []
        for node in graph_stage.value.nodes:
            if node.project_id != context.project_id:
                node = node.model_copy(update={"project_id": context.project_id})
            if not context.validated_result_cards and node.claim_type.value == "RESULT":
                risks.append("INCOMPLETE_RESULT_INPUT")
                continue
            try:
                validate_claim_node(node, context)
            except ValueError:
                risks.append("INVALID_CLAIM_REFERENCE")
                continue
            valid_nodes.append(node)
        graph = AtomicClaimGraph(
            project_id=context.project_id,
            nodes=valid_nodes,
            graph_hash=graph_stage.value.graph_hash,
        )
        try:
            validate_claim_graph(graph, context)
        except ValueError:
            # A malformed claim graph is never rendered as a manuscript.  The
            # Controller may route this candidate back for bounded rework.
            risks.append("INVALID_CLAIM_GRAPH")
            graph = AtomicClaimGraph(project_id=context.project_id, nodes=[])

        outline_stage = build_manuscript_outline(
            context, graph, self.generator, self.prompt_registry, self.model
        )
        metadata_refs.append(outline_stage.metadata_ref)
        graph_ids = {node.claim_id for node in graph.nodes}
        outline = outline_stage.value.model_copy(
            update={
                "project_id": context.project_id,
                "section_claim_ids": {
                    section: [claim_id for claim_id in claim_ids if claim_id in graph_ids]
                    for section, claim_ids in outline_stage.value.section_claim_ids.items()
                },
            }
        )
        chinese_stage = render_manuscript(
            "zh-CN", context, graph, outline, self.generator, self.prompt_registry, self.model
        )
        english_stage = render_manuscript(
            "en-US", context, graph, outline, self.generator, self.prompt_registry, self.model
        )
        metadata_refs.extend([chinese_stage.metadata_ref, english_stage.metadata_ref])
        chinese = normalize_draft(chinese_stage.value, graph)
        english = normalize_draft(english_stage.value, graph)
        chinese_issues = validate_manuscript(chinese, graph, context)
        english_issues = validate_manuscript(english, graph, context)
        chinese_critique = critique_manuscript(chinese, graph, context)
        english_critique = critique_manuscript(english, graph, context)
        risks.extend(chinese_issues + english_issues)
        consistency = compare_bilingual_drafts(chinese, english, graph)
        risks.extend(consistency.risk_flags)
        if consistency.status is BilingualConsistencyStatus.BLOCKED:
            risks.append("BILINGUAL_MISMATCH")
        if risks:
            sufficiency = sufficiency.model_copy(update={"status": WritingSufficiencyStatus.INCOMPLETE})
        critique_findings = [
            *chinese_critique.findings,
            *english_critique.findings,
        ]
        critique = chinese_critique.model_copy(
            update={
                "report_id": f"writing-critique:{context.project_id}",
                "status": "NEEDS_REVISION"
                if critique_findings
                else "PASS",
                "score": min(chinese_critique.score, english_critique.score),
                "findings": critique_findings,
            }
        )
        if self.enable_llm_review:
            try:
                reviewer_stage = review_manuscript_arguments(
                    context,
                    graph,
                    outline,
                    chinese,
                    english,
                    critique,
                    self.generator,
                    self.prompt_registry,
                    self.model,
                )
                metadata_refs.append(reviewer_stage.metadata_ref)
                reviewer_findings = [
                    _to_critique_finding(
                        context.project_id,
                        item,
                        index,
                        {node.claim_id for node in graph.nodes},
                    )
                    for index, item in enumerate(reviewer_stage.value.findings, start=1)
                ]
                if reviewer_findings:
                    risks.append("WRITING_ARGUMENT_REVIEW_NEEDS_REVISION")
                    critique = critique.model_copy(
                        update={
                            "status": "NEEDS_REVISION",
                            "score": max(
                                0,
                                critique.score
                                - sum(
                                    20
                                    if item.severity == "ERROR"
                                    else 6
                                    if item.severity == "WARNING"
                                    else 0
                                    for item in reviewer_findings
                                ),
                            ),
                            "findings": [*critique.findings, *reviewer_findings],
                        }
                    )
            except StructuredGenerationError:
                # Reviewer failure must never discard a valid deterministic
                # report or make manuscript generation unavailable.
                risks.append("LLM_WRITING_REVIEW_FAILED")
        if risks and sufficiency.status is WritingSufficiencyStatus.READY:
            sufficiency = sufficiency.model_copy(update={"status": WritingSufficiencyStatus.INCOMPLETE})
        return WritingPackage(
            project_id=context.project_id,
            claim_graph=graph,
            outline=outline,
            chinese=chinese,
            english=english,
            consistency=consistency,
            sufficiency=sufficiency,
            risk_flags=list(dict.fromkeys(risks)),
            generation_metadata_refs=metadata_refs,
            critique=critique,
        )

    def _context_with_empirical_framework(
        self, context: WritingContextBundle
    ) -> WritingContextBundle:
        constraints = dict(context.journal_constraints)
        style_layers = constraints.get("style_layers")
        has_framework = "empirical_framework" in constraints or (
            isinstance(style_layers, dict) and "empirical_framework" in style_layers
        )
        if has_framework:
            return context
        try:
            framework = self.journal_loader.load_empirical_framework()
        except (JournalSkillError, OSError):
            return context
        constraints["empirical_framework"] = framework
        return context.model_copy(update={"journal_constraints": constraints})


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _to_critique_finding(
    project_id: str,
    item: WritingReviewerFinding,
    index: int,
    allowed_claim_ids: set[str],
) -> WritingCritiqueFinding:
    """Convert model output to a server-identifiable critique finding."""

    return WritingCritiqueFinding(
        finding_id=f"{project_id}:llm-review:{item.code}:{index}",
        severity=item.severity,
        code=item.code,
        section=item.section,
        message=item.message,
        suggested_action=item.suggested_action,
        claim_ids=[claim_id for claim_id in item.claim_ids if claim_id in allowed_claim_ids],
    )
