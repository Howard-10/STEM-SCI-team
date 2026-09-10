"""Controller-facing context providers over local and shared evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from .models import ContextBuildRequest, ContextBundle, VerificationStatus
from .service import ContextService


class ContextProvider(Protocol):
    def build_context(
        self,
        project_id: str,
        task_ref: str,
        query: str,
        token_budget: int,
    ) -> ContextBundle: ...


class LocalContextProvider:
    """Build an initial review context from project material.

    Uploaded material is deliberately still unverified at this point.  It is
    eligible for discovery and researcher review, but not for later formal
    evidence promotion.
    """

    def __init__(self, service: ContextService) -> None:
        self.service = service

    def build_context(
        self,
        project_id: str,
        task_ref: str,
        query: str,
        token_budget: int,
    ) -> ContextBundle:
        return self.service.build(
            ContextBuildRequest(
                project_id=project_id,
                task_ref=task_ref,
                query=query,
                token_budget=token_budget,
                allow_discovery_fallback=True,
                allowed_verification_statuses=[
                    VerificationStatus.SOURCE_VERIFIED,
                    VerificationStatus.HUMAN_VERIFIED,
                    VerificationStatus.DEMO_SEED,
                    VerificationStatus.MODEL_GENERATED_UNVERIFIED,
                ],
            )
        )


class HybridContextProvider:
    """Controller adapter for the read-only shared Physics-STEM corpus.

    Initial literature review uses discovery mode so candidate evidence can be
    screened by the researcher. Formal evidence remains a later promotion step
    after source location and verification are complete.
    """

    def __init__(
        self,
        knowledge_service: "HybridKnowledgeService",
        local_service: ContextService | None = None,
    ) -> None:
        self.knowledge_service = knowledge_service
        self.local_service = local_service

    def build_context(
        self,
        project_id: str,
        task_ref: str,
        query: str,
        token_budget: int,
    ) -> ContextBundle:
        shared = self.knowledge_service.build_context(
            project_id=project_id,
            task_ref=task_ref,
            query=query,
            token_budget=token_budget,
            mode="discovery",
        )
        if self.local_service is None:
            return shared
        local = LocalContextProvider(self.local_service).build_context(
            project_id=project_id,
            task_ref=task_ref,
            query=query,
            token_budget=token_budget,
        )
        return self._merge(project_id, task_ref, query, token_budget, shared, local)

    def _merge(
        self,
        project_id: str,
        task_ref: str,
        query: str,
        token_budget: int,
        shared: ContextBundle,
        local: ContextBundle,
    ) -> ContextBundle:
        """Keep local uploads and the shared corpus in one bounded review set."""

        selected = []
        tokens_used = 0
        seen: set[str] = set()
        for evidence in [*local.evidence_refs, *shared.evidence_refs]:
            if evidence.evidence_id in seen:
                continue
            cost = max(1, len(evidence.excerpt) // 4)
            if tokens_used + cost > token_budget:
                continue
            seen.add(evidence.evidence_id)
            selected.append(evidence)
            tokens_used += cost
        canonical = {
            "project_id": project_id,
            "task_ref": task_ref,
            "query": query,
            "evidence_ids": [item.evidence_id for item in selected],
        }
        bundle = ContextBundle(
            context_id=f"ctx_{uuid4().hex}",
            project_id=project_id,
            task_ref=task_ref,
            query=query,
            evidence_refs=selected,
            source_refs=sorted({item.source_id for item in selected}),
            unresolved_questions=([] if selected else ["No eligible traceable evidence matched the request"]),
            risk_flags=sorted(set([*local.risk_flags, *shared.risk_flags])),
            verification_summary={
                status.value: sum(item.verification_status is status for item in selected)
                for status in VerificationStatus
            },
            token_budget=token_budget,
            estimated_tokens=tokens_used,
            context_hash=hashlib.sha256(
                json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            generated_at=datetime.now(UTC).isoformat(),
            context_mode="discovery",
            corpus_refs=shared.corpus_refs,
            retrieval_strategy="project_local_plus_hybrid",
            retrieval_trace_ref=shared.retrieval_trace_ref,
            retrieval_risk_flags=sorted(set([*local.retrieval_risk_flags, *shared.retrieval_risk_flags])),
            manifest_refs=shared.manifest_refs,
        )
        return self.local_service.persist_bundle(bundle)


from stem_sci.knowledge.service import HybridKnowledgeService  # noqa: E402  # isort: skip
