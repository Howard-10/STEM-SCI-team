"""Provider-neutral reranking for retrieved evidence candidates.

The optional sentence-transformers implementation is deliberately lazy.  A
missing model or dependency is an explicit degradation, never a claim that a
cross-encoder was used.  The lexical implementation is useful for offline
tests and local development only.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Protocol

from .models import RetrievalHit


class Reranker(Protocol):
    """Common interface for a bounded second-stage ranker."""

    model_id: str

    def rerank(self, query: str, hits: Sequence[RetrievalHit], limit: int) -> list[RetrievalHit]:
        ...


def _tokens(value: str) -> set[str]:
    """Return stable word/CJK-character tokens without a heavy tokenizer."""

    lowered = value.casefold()
    words = set(re.findall(r"[a-z0-9_]+", lowered))
    cjk = {char for char in lowered if "\u4e00" <= char <= "\u9fff"}
    return words | cjk


class LexicalReranker:
    """Transparent offline fallback; not a semantic model."""

    model_id = "lexical-overlap-fallback-v1"

    def rerank(self, query: str, hits: Sequence[RetrievalHit], limit: int) -> list[RetrievalHit]:
        query_tokens = _tokens(query)
        scored: list[tuple[float, RetrievalHit]] = []
        for hit in hits:
            hit_tokens = _tokens(hit.text)
            overlap = len(query_tokens & hit_tokens) / max(1, len(query_tokens))
            score = overlap + (hit.rrf_score * 0.01)
            scored.append((score, hit))
        return [
            hit
            for _, hit in sorted(
                scored,
                key=lambda item: (-item[0], item[1].canonical_paper_id, item[1].chunk_index),
            )[:limit]
        ]


class SentenceTransformersCrossEncoder:
    """Optional real cross-encoder adapter.

    Importing sentence-transformers only happens when this class is created,
    so the base backend remains installable without model weights.
    """

    def __init__(self, model_name: str) -> None:
        try:
            from sentence_transformers import CrossEncoder  # type: ignore[import-not-found]
        except ImportError as error:
            raise RuntimeError(
                "sentence-transformers is required for CrossEncoder reranking"
            ) from error
        self.model_id = model_name
        self._model = CrossEncoder(model_name)

    def rerank(self, query: str, hits: Sequence[RetrievalHit], limit: int) -> list[RetrievalHit]:
        if not hits:
            return []
        scores = self._model.predict([(query, hit.text) for hit in hits])
        ranked = sorted(
            zip(scores, hits, strict=True),
            key=lambda item: (-float(item[0]), item[1].canonical_paper_id, item[1].chunk_index),
        )
        return [hit for _, hit in ranked[:limit]]
