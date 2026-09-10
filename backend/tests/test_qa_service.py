from __future__ import annotations

from pathlib import Path

from stem_sci.knowledge.models import (
    ContextMode,
    GraphCandidate,
    RetrievalMode,
    RetrievalSearchResponse,
    RetrievalTrace,
)
from stem_sci.knowledge.qa_models import QAAnswerRequest, QAReference
from stem_sci.knowledge.qa_service import (
    QuestionAnswerService,
    _clean_researcher_answer,
    _discussion_fallback_answer,
    _external_query,
)
from stem_sci.context.models import (
    EvidenceRef,
    EvidenceSearchResult,
    SourceDocument,
    SourceLocation,
    VerificationStatus,
)
from stem_sci.agents.runtime import FakeLLMProvider


def test_external_query_uses_project_context_and_ignores_instruction_noise() -> None:
    query = _external_query(
        "请进行外部学术检索，找近五年的真实论文，最好使用英文关键词搜索。",
        "外部学术检索 真实论文 英文关键词搜索",
        "项目名称：生成式人工智能与大学物理学习\n研究方向：研究生成式人工智能对大学物理学生计算思维学习成效的影响",
    )

    assert "generative artificial intelligence" in query
    assert "university physics" in query
    assert "computational thinking" in query
    assert "learning outcomes" in query
    assert "English" not in query
    assert "keywords" not in query

    noisy_query = _external_query(
        "请进行外部学术检索。",
        "",
        "项目名称：生成式人工智能与大学物理学习\n研究方向：研究生成式人工智能对大学物理学生计算思维学习成效的影响\n研究协作决策：\n- 当前研究动作：evidence_seek\n- 关键未知归属：system_retrieval",
    )
    assert "retrieval" not in noisy_query
    assert "generative artificial intelligence" in noisy_query


def test_researcher_answer_hides_planner_labels() -> None:
    cleaned = _clean_researcher_answer(
        "在 reflect 模式下，项目约束 causal_claims=forbidden。"
    )

    assert "reflect" not in cleaned
    assert "causal_claims" not in cleaned
    assert "当前讨论" in cleaned
    assert "当前不做因果推断" in cleaned


def test_design_confirmation_does_not_fall_back_to_unrelated_evidence() -> None:
    answer = _discussion_fallback_answer("我确认研究问题和统计计划，继续吧")

    assert "识别到你是在确认当前研究设计" in answer
    assert "本地原文证据" not in answer
    assert "重新询问" not in answer


def test_citation_filter_drops_generic_neighbors_for_specific_method_question() -> None:
    citations = [
        QAReference(
            paper_title="Engineering design in introductory physics laboratory",
            source_filename="engineering.pdf",
            canonical_paper_id="paper-1",
            canonical_chunk_id="chunk-1",
            chunk_index=0,
            excerpt="Students completed a multiweek laboratory design task.",
        ),
        QAReference(
            paper_title="Pretest-posttest design in physics education",
            source_filename="pretest.pdf",
            canonical_paper_id="paper-2",
            canonical_chunk_id="chunk-2",
            chunk_index=0,
            excerpt="A pretest-posttest comparison estimated changes in conceptual understanding.",
        ),
    ]

    filtered = QuestionAnswerService._filter_citations_for_question(
        "What is a pretest-posttest design for physics education?",
        citations,
    )

    assert [item.canonical_paper_id for item in filtered] == ["paper-2"]


class FakeKnowledgeService:
    def __init__(self) -> None:
        self.search_calls: list[str] = []
        self.context_calls: list[str] = []
        self.search_modes: list[ContextMode] = []
        self.context_modes: list[str] = []

    def search(self, request):
        self.search_calls.append(request.query)
        self.search_modes.append(request.mode)
        from stem_sci.knowledge.models import RetrievalHitSummary

        hit = RetrievalHitSummary(
            canonical_chunk_id="chunk-1",
            canonical_paper_id="paper-1",
            source_filename="paper.pdf",
            paper_title="Physics Education Study",
            normalized_doi="10.1000/example",
            chunk_index=0,
            section_hint="Abstract",
            excerpt="The study reports improved conceptual understanding.",
            locator_status="RESOLVED",
            source_locator_method="PAGE_TEXT_EXACT",
            verification_status="source_verified",
            page_start=4,
            page_end=4,
            char_start=20,
            char_end=78,
            pdf_relative_path="papers/paper.pdf",
            pdf_sha256="b" * 64,
            retrieval_modalities=["sparse"],
        )
        trace = RetrievalTrace(
            query_normalized=request.query,
            retrieval_mode=RetrievalMode.SPARSE_ONLY,
            corpus_id="physics_stem_v1",
            manifest_refs=["manifest:physics_stem_v1:test"],
            risk_flags=["dense_retrieval_unavailable"],
            dense_available=False,
            sparse_available=True,
            graph_available=False,
        )
        return RetrievalSearchResponse(
            project_id=request.project_id,
            corpus_id="physics_stem_v1",
            requested_mode=request.mode,
            retrieval_status="DEGRADED",
            degraded_mode=RetrievalMode.SPARSE_ONLY,
            candidate_papers=[],
            chunk_hits=[hit],
            retrieval_trace=trace,
            risk_flags=["dense_retrieval_unavailable"],
            manifest_refs=trace.manifest_refs,
        )

    def build_context(self, **kwargs):
        self.context_calls.append(kwargs["query"])
        self.context_modes.append(kwargs["mode"])
        from stem_sci.context.models import ContextBundle

        return ContextBundle(
            context_id="ctx-test",
            project_id=kwargs["project_id"],
            task_ref=kwargs["task_ref"],
            query=kwargs["query"],
            evidence_refs=[],
            source_refs=[],
            unresolved_questions=[],
            risk_flags=[],
            verification_summary={},
            token_budget=kwargs["token_budget"],
            estimated_tokens=0,
            context_hash="a" * 64,
            generated_at="2026-08-20T00:00:00+00:00",
            context_mode="discovery",
            corpus_refs=["physics_stem_v1"],
            retrieval_strategy="hybrid",
        )


class FakeProjectContextService:
    def search(self, request):
        return [
            EvidenceSearchResult(
                evidence=EvidenceRef(
                    evidence_id="local-evidence-1",
                    project_id=request.project_id,
                    source_id="local-source-1",
                    chunk_id="local-chunk-1",
                    excerpt="The uploaded project paper describes the study sample and coding procedure.",
                    location=SourceLocation(chunk_index=0, char_start=0, char_end=90),
                    verification_status=VerificationStatus.MODEL_GENERATED_UNVERIFIED,
                ),
                score=0.9,
            )
        ]

    def get_source(self, project_id, source_id):
        return SourceDocument(
            source_id=source_id,
            project_id=project_id,
            filename="paper_tschisgale_2023-v1.txt",
            media_type="text/plain",
            sha256="a" * 64,
            storage_path="local.txt",
            imported_at="2026-01-01T00:00:00+00:00",
            verification_status=VerificationStatus.MODEL_GENERATED_UNVERIFIED,
        )


def test_project_material_is_not_replaced_by_shared_hits_for_route_question(tmp_path: Path) -> None:
    knowledge = FakeKnowledgeService()
    knowledge._context_service = FakeProjectContextService()
    service = QuestionAnswerService(
        knowledge_service=knowledge,
        storage_root=tmp_path,
    )

    response = service.answer(
        QAAnswerRequest(
            project_id="project-local",
            question="请比较先补充证据和先按暂定边界形成研究设计这两条路线。",
            allow_llm=False,
        )
    )

    assert response.citations
    assert response.citations[0].source_filename == "paper_tschisgale_2023-v1.txt"


def test_qa_fallback_retrieves_cites_and_persists_memory(tmp_path: Path) -> None:
    knowledge = FakeKnowledgeService()
    service = QuestionAnswerService(
        knowledge_service=knowledge,
        storage_root=tmp_path,
    )

    response = service.answer(
        QAAnswerRequest(
            project_id="demo",
            question="What improves conceptual understanding?",
            conversation_id="conversation-1",
            allow_llm=False,
        )
    )

    assert response.answer_mode == "fallback"
    assert response.citations[0].canonical_chunk_id == "chunk-1"
    assert response.memory_ref is not None
    assert response.turn_id == response.memory_ref
    assert response.mode is ContextMode.DISCOVERY
    assert response.citations[0].citation_index == 1
    assert response.citations[0].verification_status == "source_verified"
    assert response.citations[0].page_start == 4
    assert response.citations[0].source_locator_method == "PAGE_TEXT_EXACT"
    assert response.context_bundle_ref == "ctx-test"
    assert knowledge.search_calls
    assert knowledge.context_calls

    second = service.answer(
        QAAnswerRequest(
            project_id="demo",
            question="What did the previous study report?",
            conversation_id="conversation-1",
            allow_llm=False,
        )
    )
    assert "Physics Education Study" in second.answer
    assert len(knowledge.search_calls) == 2
    assert len(second.rewritten_query) > len(second.question)


def test_plain_conversation_fallback_stays_on_the_users_question(tmp_path: Path) -> None:
    """An unavailable model must not produce an unrelated workflow prompt."""

    service = QuestionAnswerService(
        knowledge_service=FakeKnowledgeService(),
        storage_root=tmp_path,
        provider=FakeLLMProvider([]),
        model="test-model",
        max_retries=0,
    )

    response = service.converse(
        QAAnswerRequest(
            project_id="demo",
            question="下一步需要上传哪些数据和字段？暂时不要执行统计分析。",
        )
    )

    assert response.answer_mode == "fallback"
    assert "CSV" in response.answer
    assert "student_id" not in response.answer
    assert response.citations == []
    assert response.route.route == "direct_answer"


def test_conversation_fallback_acknowledges_short_design_confirmation(tmp_path: Path) -> None:
    """A terse design approval must not trigger the unrelated evidence fallback."""

    service = QuestionAnswerService(
        knowledge_service=FakeKnowledgeService(),
        storage_root=tmp_path,
        provider=FakeLLMProvider([]),
        model="test-model",
        max_retries=0,
    )

    response = service.answer(
        QAAnswerRequest(
            project_id="demo",
            question="我确认这套研究设计，请进入设计审查。",
            allow_llm=False,
        )
    )

    assert "识别到你是在确认当前研究设计" in response.answer
    assert "不会代替项目工作流写入状态" in response.answer
    assert "没有找到与你这三个变量" not in response.answer
    assert response.answer_mode == "fallback"


def test_cgt_project_context_uses_physics_text_fallback(tmp_path: Path) -> None:
    service = QuestionAnswerService(
        knowledge_service=FakeKnowledgeService(),
        storage_root=tmp_path,
        provider=FakeLLMProvider([]),
        model="test-model",
        max_retries=0,
    )

    response = service.converse(
        QAAnswerRequest(
            project_id="cgt-demo",
            project_context="项目名称：学生物理问题解决文本的计算辅助定性研究\n研究方向：物理教育中的问题解决与文本分析",
            question="请判断三阶段的人机协作计算扎根理论路线是否适合，不要预设主题数量和名称。",
            allow_llm=False,
        )
    )

    assert "三阶段" in response.answer
    assert "primary_use" not in response.answer
    assert "secondary_concept" not in response.answer
    assert "这三个变量" not in response.answer


def test_cgt_domain_mismatch_is_corrected_and_audited(tmp_path: Path) -> None:
    provider = FakeLLMProvider(
        responses=[
            {
                "answer": "请使用 primary_use、secondary_concept 和这三个变量完成问卷编码。",
                "citation_indices": [],
                "confidence": 0.9,
                "needs_follow_up": False,
            }
        ]
    )
    service = QuestionAnswerService(
        knowledge_service=FakeKnowledgeService(),
        storage_root=tmp_path,
        provider=provider,
        model="test-model",
        max_retries=0,
    )

    response = service.converse(
        QAAnswerRequest(
            project_id="cgt-demo",
            project_context="项目名称：学生物理问题解决文本的计算辅助定性研究\n研究方向：物理教育中的问题解决与文本分析",
            question="请判断当前路线的边界。",
        )
    )

    assert "primary_use" not in response.answer
    assert response.domain_correction is not None
    audit_path = tmp_path / "memory" / "qa_domain_corrections.jsonl"
    assert audit_path.is_file()
    audit_text = audit_path.read_text(encoding="utf-8")
    assert "original_response" in audit_text
    assert "primary_use" in audit_text
    assert "corrected_response" in audit_text


def test_explanatory_design_confirmation_question_is_not_acknowledged(tmp_path: Path) -> None:
    """Questions about how to confirm remain ordinary evidence-aware turns."""

    service = QuestionAnswerService(
        knowledge_service=FakeKnowledgeService(),
        storage_root=tmp_path,
        provider=FakeLLMProvider([]),
        model="test-model",
        max_retries=0,
    )

    response = service.answer(
        QAAnswerRequest(
            project_id="demo",
            question="如何确认研究设计？",
            allow_llm=False,
        )
    )

    assert "已记录你对当前研究设计的确认" not in response.answer


def test_negated_design_confirmation_is_not_treated_as_approval(tmp_path: Path) -> None:
    service = QuestionAnswerService(
        knowledge_service=FakeKnowledgeService(),
        storage_root=tmp_path,
        provider=FakeLLMProvider([]),
        model="test-model",
        max_retries=0,
    )
    response = service.answer(
        QAAnswerRequest(
            project_id="demo",
            question="我暂不确认研究设计，想先修改变量。",
            allow_llm=False,
        )
    )
    assert "已记录你对当前研究设计的确认" not in response.answer


def test_deferred_design_review_is_not_treated_as_approval(tmp_path: Path) -> None:
    service = QuestionAnswerService(
        knowledge_service=FakeKnowledgeService(),
        storage_root=tmp_path,
        provider=FakeLLMProvider([]),
        model="test-model",
        max_retries=0,
    )
    response = service.answer(
        QAAnswerRequest(
            project_id="demo",
            question="不要进入设计审查，我还想修改方案。",
            allow_llm=False,
        )
    )
    assert "已记录你对当前研究设计的确认" not in response.answer


def test_conversation_fallback_records_correlation_boundary(tmp_path: Path) -> None:
    service = QuestionAnswerService(
        knowledge_service=FakeKnowledgeService(),
        storage_root=tmp_path,
        provider=FakeLLMProvider([]),
        model="test-model",
        max_retries=0,
    )

    response = service.converse(
        QAAnswerRequest(
            project_id="demo",
            question="我更关心相关关系，不做因果推断。",
        )
    )

    assert "不会把相关系数写成因果结论" in response.answer
    assert "下一步" in response.answer


def test_conversation_fallback_challenge_contains_alternative_explanations(tmp_path: Path) -> None:
    service = QuestionAnswerService(
        knowledge_service=FakeKnowledgeService(),
        storage_root=tmp_path,
        provider=FakeLLMProvider([]),
        model="test-model",
        max_retries=0,
    )

    response = service.converse(
        QAAnswerRequest(
            project_id="demo",
            question="请挑战一下生成式人工智能会提高学习成效这个判断。",
            planned_research_acts=["challenge"],
        )
    )

    assert "自我选择" in response.answer
    assert "使用方式不同" in response.answer
    assert "更稳妥的研究问题" in response.answer


def test_conversation_fallback_compare_answers_with_concrete_recommendation(tmp_path: Path) -> None:
    service = QuestionAnswerService(
        knowledge_service=FakeKnowledgeService(),
        storage_root=tmp_path,
        provider=FakeLLMProvider([]),
        model="test-model",
        max_retries=0,
    )

    response = service.converse(
        QAAnswerRequest(
            project_id="demo",
            question="先不检索。请比较刚才列出的三类生成式人工智能使用指标。",
            planned_research_acts=["compare"],
        )
    )

    assert "使用频率/时长" in response.answer
    assert "使用方式" in response.answer
    assert "交互行为深度" in response.answer
    assert "建议把‘使用方式’作为主指标" in response.answer


def test_conversation_fallback_operationalizes_committed_metrics(tmp_path: Path) -> None:
    service = QuestionAnswerService(
        knowledge_service=FakeKnowledgeService(),
        storage_root=tmp_path,
        provider=FakeLLMProvider([]),
        model="test-model",
        max_retries=0,
    )
    response = service.converse(
        QAAnswerRequest(
            project_id="demo",
            question="我接受这个建议。请帮我把这两个指标具体操作化，并指出现在还需要我决定的一个关键问题。",
            planned_research_acts=["commit", "clarify"],
            planned_follow_up_question="你能取得平台交互日志，还是只能通过问卷让学生自报使用方式？",
        )
    )

    assert "主指标‘使用方式’" in response.answer
    assert "补充指标‘频率/时长’" in response.answer
    assert "平台交互日志" in response.answer


def test_conversation_fallback_adapts_to_self_report_constraint(tmp_path: Path) -> None:
    service = QuestionAnswerService(
        knowledge_service=FakeKnowledgeService(),
        storage_root=tmp_path,
        provider=FakeLLMProvider([]),
        model="test-model",
        max_retries=0,
    )
    response = service.converse(
        QAAnswerRequest(
            project_id="demo",
            question="目前拿不到平台交互日志，只能通过问卷让学生自报使用方式。请据此调整操作化方案，并说明如何降低自报偏差。",
        )
    )

    assert "最近一周" in response.answer
    assert "降低自报偏差" in response.answer
    assert "认知访谈" in response.answer


def test_conversation_fallback_designs_requested_scenario_items(tmp_path: Path) -> None:
    service = QuestionAnswerService(
        knowledge_service=FakeKnowledgeService(),
        storage_root=tmp_path,
        provider=FakeLLMProvider([]),
        model="test-model",
        max_retries=0,
    )
    response = service.converse(
        QAAnswerRequest(
            project_id="demo",
            question="每个情境题我倾向只记录最主要的一种使用方式，请继续帮我设计具体题目。",
            planned_research_acts=["reflect"],
        )
    )

    assert "四道情境题草案" in response.answer
    assert "非惯性系中的虚拟力" in response.answer
    assert "代码/建模辅助" in response.answer
    assert "平台交互日志" not in response.answer


def test_conversation_fallback_reviews_and_revises_scenario_structure(tmp_path: Path) -> None:
    service = QuestionAnswerService(
        knowledge_service=FakeKnowledgeService(),
        storage_root=tmp_path,
        provider=FakeLLMProvider([]),
        model="test-model",
        max_retries=0,
    )
    response = service.converse(
        QAAnswerRequest(
            project_id="demo",
            question="这四类基本覆盖，但我担心第3题A更像任务规划而不是概念澄清，而且学生可能在最近一周没有遇到每一种情境。请帮我检查四类是否真正互斥，并优化题目结构。",
            planned_research_acts=["reflect"],
        )
    )

    assert "严格互斥" in response.answer
    assert "过去 7 天" in response.answer
    assert "策略规划" in response.answer
    assert "记录为当前研究边界" not in response.answer


def test_conversation_fallback_advances_to_primary_and_companion_coding(tmp_path: Path) -> None:
    service = QuestionAnswerService(
        knowledge_service=FakeKnowledgeService(),
        storage_root=tmp_path,
        provider=FakeLLMProvider([]),
        model="test-model",
        max_retries=0,
    )
    response = service.converse(
        QAAnswerRequest(
            project_id="demo",
            question="请帮我设计‘主要方式 + 伴随方式’的问卷编码方案，并说明统计分析时如何使用这两个变量。",
            planned_research_acts=["reflect"],
        )
    )

    assert "primary_use" in response.answer
    assert "secondary_concept" in response.answer
    assert "不要把 1—4 当作有序高低分数" in response.answer
    assert "记录为当前研究边界" not in response.answer


def test_conversation_fallback_builds_questionnaire_instead_of_csv_audit(tmp_path: Path) -> None:
    service = QuestionAnswerService(
        knowledge_service=FakeKnowledgeService(),
        storage_root=tmp_path,
        provider=FakeLLMProvider([]),
        model="test-model",
        max_retries=0,
    )
    response = service.converse(
        QAAnswerRequest(
            project_id="demo",
            question="我目前还没有问卷数据。请先把刚才的编码方案整理成可以直接发放的完整问卷和数据字典，不要转到 CSV 数据审查。",
        )
    )

    assert "【筛选题】" in response.answer
    assert "primary_use" in response.answer
    assert "secondary_concept" in response.answer
    assert "CSV 数据审查" not in response.answer
    assert "具体列名" not in response.answer


def test_qa_propagates_formal_mode_to_retrieval_and_context(tmp_path: Path) -> None:
    knowledge = FakeKnowledgeService()
    service = QuestionAnswerService(
        knowledge_service=knowledge,
        storage_root=tmp_path,
    )

    service.answer(
        QAAnswerRequest(
            project_id="demo",
            question="Which evidence supports the study?",
            mode=ContextMode.FORMAL,
            allow_llm=False,
        )
    )

    assert knowledge.search_modes == [ContextMode.FORMAL]
    assert knowledge.context_modes == ["formal"]


def test_qa_uses_one_structured_llm_call_by_default(tmp_path: Path) -> None:
    """Normal chat must not spend a separate model call on tool routing."""

    provider = FakeLLMProvider(responses=[{
        "answer": "The cited source supports a bounded interpretation.",
        "citation_indices": [1],
        "confidence": 0.7,
        "needs_follow_up": False,
    }])
    service = QuestionAnswerService(
        knowledge_service=FakeKnowledgeService(),
        storage_root=tmp_path,
        provider=provider,
        model="test-model",
        max_retries=0,
    )

    response = service.answer(
        QAAnswerRequest(project_id="demo", question="What does the evidence support?")
    )

    assert response.answer_mode == "llm"
    assert provider.call_count == 1
    assert response.tool_calls == []


def test_qa_graph_only_fallback_returns_exploratory_paper_candidates(tmp_path: Path) -> None:
    class GraphOnlyKnowledgeService(FakeKnowledgeService):
        def search(self, request):
            trace = RetrievalTrace(
                query_normalized=request.query,
                retrieval_mode=RetrievalMode.GRAPH_ONLY,
                corpus_id="physics_stem_v1",
                manifest_refs=["manifest:physics_stem_v1:test"],
                graph_candidates=[
                    GraphCandidate(
                        canonical_paper_id="paper-ai",
                        graph_paper_id="Generative AI in Physics Education",
                        navigation_score=1.0,
                        matched_facets=["Physics Education", "Instructional Scaffolding"],
                        supporting_edge_refs=["graph:paper-ai:0"],
                    )
                ],
                dense_available=False,
                sparse_available=False,
                graph_available=True,
            )
            return RetrievalSearchResponse(
                project_id=request.project_id,
                corpus_id="physics_stem_v1",
                requested_mode=ContextMode.DISCOVERY,
                retrieval_status="DEGRADED",
                degraded_mode=RetrievalMode.GRAPH_ONLY,
                candidate_papers=trace.graph_candidates,
                chunk_hits=[],
                retrieval_trace=trace,
                risk_flags=["graph_only_discovery"],
                manifest_refs=trace.manifest_refs,
            )

    service = QuestionAnswerService(
        knowledge_service=GraphOnlyKnowledgeService(),
        storage_root=tmp_path,
    )
    response = service.answer(
        QAAnswerRequest(project_id="demo", question="physics AI research", allow_llm=False)
    )

    assert "探索性论文候选" in response.answer
    assert "Generative AI in Physics Education" in response.answer
    assert "不能作为正式证据" in response.answer
    assert response.citations[0].source_type == "paper"
    assert response.confidence > 0
