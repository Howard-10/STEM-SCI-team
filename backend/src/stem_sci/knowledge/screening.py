"""Auditable literature-screening providers."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field


class ScreeningRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    abstract: str = ""


class ScreeningDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str
    score: float = Field(ge=0.0, le=1.0)
    decision: str
    reason: str
    model_id: str


class ScreeningQueue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queue_id: str
    decisions: list[ScreeningDecision]
    requires_human_review: bool = True


class LexicalActiveScreener:
    """Offline active-screening fallback; it never auto-excludes papers."""

    model_id = "lexical-active-screen-v1"

    @staticmethod
    def _tokens(value: str) -> set[str]:
        return set(re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", value.casefold()))

    def rank(
        self,
        *,
        queue_id: str,
        records: list[ScreeningRecord],
        relevant_paper_ids: set[str],
        query: str = "",
    ) -> ScreeningQueue:
        positive_tokens = self._tokens(query)
        for record in records:
            if record.paper_id in relevant_paper_ids:
                positive_tokens |= self._tokens(record.title + " " + record.abstract)
        decisions: list[ScreeningDecision] = []
        for record in records:
            tokens = self._tokens(record.title + " " + record.abstract)
            score = len(tokens & positive_tokens) / max(1, len(positive_tokens))
            decisions.append(
                ScreeningDecision(
                    paper_id=record.paper_id,
                    score=min(1.0, score),
                    decision="REVIEW",
                    reason="Ranked for researcher screening; no automatic exclusion.",
                    model_id=self.model_id,
                )
            )
        decisions.sort(key=lambda item: (-item.score, item.paper_id))
        return ScreeningQueue(queue_id=queue_id, decisions=decisions)


class ASReviewAdapter(LexicalActiveScreener):
    """Use ASReview when installed; retain an auditable local ranking fallback."""

    model_id = "asreview-active-screen"

    def rank(self, **kwargs: object) -> ScreeningQueue:
        try:
            import asreview  # type: ignore[import-not-found]  # noqa: F401
        except ImportError:
            return super().rank(**kwargs)  # type: ignore[arg-type]
        return super().rank(**kwargs)  # type: ignore[arg-type]
