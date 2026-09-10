from __future__ import annotations

from stem_sci.agents.runtime import FakeLLMProvider, StructuredGenerator
from stem_sci.agents.writing_pipeline.models import AtomicClaimGraph, LanguageCode, ManuscriptDraft
from stem_sci.skills.journal_writing import JournalProfileLoader, semantic_rule_keys
from stem_sci.skills.journal_writing.revision import (
    JournalStyleRevisionRequest,
    JournalStyleRevisionService,
)


def test_passed_journal_validation_does_not_report_failure_warning() -> None:
    loader = JournalProfileLoader()
    target_journal = "International Journal of STEM Education"
    article_type = "Research Article"
    constraints = loader.resolve_writing_constraints(target_journal, article_type=article_type)
    sections = {section: f"Content for {section}." for section in constraints.required_sections}
    draft = ManuscriptDraft(
        project_id="journal-regression",
        language=LanguageCode.EN_US,
        sections=sections,
        status="CANDIDATE",
    )
    assessments = [
        {
            "section": section,
            "rule_type": rule_type,
            "rule": rule,
            "status": "PASS",
            "explanation": "Rule satisfied.",
        }
        for section, rule_type, rule in sorted(semantic_rule_keys(constraints), key=str)
    ]
    provider = FakeLLMProvider(
        [
            {
                "sections": [{"name": name, "text": text} for name, text in sections.items()],
                "change_summary": ["Applied target journal structure"],
            },
            {"assessments": assessments},
        ]
    )

    result = JournalStyleRevisionService(
        generator=StructuredGenerator(provider, max_retries=0),
        model="test-model",
        loader=loader,
    ).revise(
        JournalStyleRevisionRequest(
            target_journal=target_journal,
            article_type=article_type,
            draft=draft,
            claim_graph=AtomicClaimGraph(project_id=draft.project_id, nodes=[]),
        )
    )

    assert result.journal_validation is not None
    assert result.journal_validation.status.value == "PASS"
    assert "Journal validation did not pass; review the findings below." not in result.report.layer_warnings
    assert len(result.generation_metadata_refs) == 2


def test_fact_drift_is_rejected_after_bounded_retries() -> None:
    loader = JournalProfileLoader()
    target_journal = "International Journal of STEM Education"
    article_type = "Research Article"
    constraints = loader.resolve_writing_constraints(target_journal, article_type=article_type)
    sections = {section: f"Original content for {section}." for section in constraints.required_sections}
    sections["Abstract"] = "We study STEM education."
    sections["Keywords"] = "STEM, education"
    malicious = dict(sections)
    malicious["Introduction"] = "We studied 42 participants and found that the intervention causes improvement."
    provider = FakeLLMProvider(
        [
            {"sections": [{"name": name, "text": text} for name, text in malicious.items()], "change_summary": ["style"]},
            {"sections": [{"name": name, "text": text} for name, text in malicious.items()], "change_summary": ["style"]},
            {"sections": [{"name": name, "text": text} for name, text in malicious.items()], "change_summary": ["style"]},
        ]
    )
    result = JournalStyleRevisionService(
        generator=StructuredGenerator(provider, max_retries=0),
        model="test-model",
        loader=loader,
    ).revise(
        JournalStyleRevisionRequest(
            target_journal=target_journal,
            article_type=article_type,
            draft=ManuscriptDraft(
                project_id="journal-safety",
                language=LanguageCode.EN_US,
                sections=sections,
                status="CANDIDATE",
            ),
            claim_graph=AtomicClaimGraph(project_id="journal-safety", nodes=[]),
        )
    )

    assert result.report.status.value == "REJECTED"
    assert "NEW_NUMERIC_LITERAL:42" in result.report.safety_findings
    assert "STRONGER_CAUSAL_LANGUAGE:causes" in result.report.safety_findings
    assert result.candidate_draft is not None
    assert result.draft.sections == sections


def test_profile_template_metadata_selects_springer_template() -> None:
    loader = JournalProfileLoader()
    target_journal = "International Journal of STEM Education"
    article_type = "Research Article"
    constraints = loader.resolve_writing_constraints(target_journal, article_type=article_type)
    sections = {section: f"Content for {section}." for section in constraints.required_sections}
    assessments = [
        {
            "section": section,
            "rule_type": rule_type,
            "rule": rule,
            "status": "PASS",
            "explanation": "Rule satisfied.",
        }
        for section, rule_type, rule in sorted(semantic_rule_keys(constraints), key=str)
    ]
    provider = FakeLLMProvider(
        [
            {"sections": [{"name": name, "text": text} for name, text in sections.items()], "change_summary": ["style"]},
            {"assessments": assessments},
        ]
    )
    result = JournalStyleRevisionService(
        generator=StructuredGenerator(provider, max_retries=0),
        model="test-model",
        loader=loader,
    ).revise(
        JournalStyleRevisionRequest(
            target_journal=target_journal,
            article_type=article_type,
            draft=ManuscriptDraft(
                project_id="journal-springer",
                language=LanguageCode.EN_US,
                sections=sections,
                status="CANDIDATE",
            ),
            claim_graph=AtomicClaimGraph(project_id="journal-springer", nodes=[]),
        )
    )

    assert result.latex is not None
    assert result.latex.template.template_id == "springer-nature"
    assert r"\documentclass[pdflatex,sn-mathphys-num]{sn-jnl}" in result.latex.latex


def test_ieee_profile_template_id_is_registered() -> None:
    loader = JournalProfileLoader()
    target_journal = "IEEE Transactions on Education"
    article_type = "Application"
    constraints = loader.resolve_writing_constraints(target_journal, article_type=article_type)
    sections = {section: f"Content for {section}." for section in constraints.required_sections}
    sections["Abstract"] = "Abstract content."
    assessments = [
        {
            "section": section,
            "rule_type": rule_type,
            "rule": rule,
            "status": "PASS",
            "explanation": "Rule satisfied.",
        }
        for section, rule_type, rule in sorted(semantic_rule_keys(constraints), key=str)
    ]
    provider = FakeLLMProvider(
        [
            {"sections": [{"name": name, "text": text} for name, text in sections.items()], "change_summary": ["style"]},
            {"assessments": assessments},
        ]
    )
    result = JournalStyleRevisionService(
        generator=StructuredGenerator(provider, max_retries=0),
        model="test-model",
        loader=loader,
    ).revise(
        JournalStyleRevisionRequest(
            target_journal=target_journal,
            article_type=article_type,
            draft=ManuscriptDraft(
                project_id="journal-ieee",
                language=LanguageCode.EN_US,
                sections=sections,
                status="CANDIDATE",
            ),
            claim_graph=AtomicClaimGraph(project_id="journal-ieee", nodes=[]),
        )
    )

    assert result.latex is not None
    assert result.latex.template.template_id == "ieee-journal"
