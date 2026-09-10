"""Bounded external scholarly discovery for corpus-gap fallback.

External results are bibliographic candidates. Explicitly public PDF links may
be imported into the project as unverified source documents, but they are never
promoted to formal evidence automatically.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


class ExternalSearchClient:
    """Search OpenAlex or Crossref with a small, deployment-configured budget."""

    def __init__(self, *, timeout_seconds: float | None = None) -> None:
        self.provider = os.getenv("STEM_SCI_EXTERNAL_SEARCH_PROVIDER", "none").strip().lower()
        self.timeout_seconds = timeout_seconds or _timeout_seconds()
        self.email = os.getenv("STEM_SCI_EXTERNAL_SEARCH_EMAIL", "").strip()

    def save_candidates(
        self, *, project_id: str, query: str, results: list[dict[str, Any]], storage_root: Path
    ) -> list[str]:
        """Persist deduplicated discovery records without promoting evidence."""

        database = storage_root / "external-discovery.db"
        database.parent.mkdir(parents=True, exist_ok=True)
        candidate_ids: list[str] = []
        with sqlite3.connect(database) as connection:
            connection.execute(
                """
                create table if not exists external_candidates (
                    candidate_id text primary key, project_id text not null,
                    query text not null, provider text not null, title text not null,
                    doi text, landing_page_url text, full_text_url text,
                    payload text not null, status text not null, created_at text not null,
                    unique(project_id, doi), unique(project_id, landing_page_url)
                )
                """
            )
            for item in results:
                title = str(item.get("title") or "Untitled")
                doi = item.get("doi")
                landing = item.get("landing_page_url")
                existing = connection.execute(
                    "select candidate_id from external_candidates where project_id=? and ((doi is not null and doi=?) or (landing_page_url is not null and landing_page_url=?))",
                    (project_id, doi, landing),
                ).fetchone()
                if existing:
                    candidate_ids.append(str(existing[0]))
                    continue
                candidate_id = f"ext_{hashlib.sha256(f'{project_id}:{doi or landing or title}'.encode()).hexdigest()[:20]}"
                connection.execute(
                    "insert or ignore into external_candidates values (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        candidate_id,
                        project_id,
                        query,
                        str(item.get("source") or self.provider),
                        title,
                        doi,
                        landing,
                        item.get("full_text_url"),
                        json.dumps(item, ensure_ascii=False, sort_keys=True),
                        "DISCOVERED",
                        datetime.now(UTC).isoformat(),
                    ),
                )
                candidate_ids.append(candidate_id)
            connection.commit()
        return candidate_ids

    @property
    def configured(self) -> bool:
        return self.provider in {"openalex", "crossref", "auto"}

    def search(self, query: str, max_results: int = 8) -> dict[str, Any]:
        query = query.strip()
        limit = max(1, min(int(max_results), 10))
        if not query:
            return {"ok": False, "status": "INVALID_QUERY", "message": "query is required"}
        if not self.configured:
            return {
                "ok": False,
                "status": "NOT_CONFIGURED",
                "query": query,
                "message": "External paper search is disabled; only the local corpus was searched.",
                "risk_flags": ["external_search_not_configured"],
            }

        # OpenAlex is the primary source, but a transient outage must not make
        # an explicit external-discovery request unusable. Crossref is a
        # metadata-only fallback; it never promotes results to evidence.
        providers = [self.provider] if self.provider == "crossref" else ["openalex", "crossref"]
        errors: list[str] = []
        for provider in providers:
            for attempt in range(2):
                try:
                    raw_results = self._search_provider(provider, query, limit)
                    year_bounds = _year_bounds(query)
                    if year_bounds:
                        start_year, end_year = year_bounds
                        raw_results = [
                            item for item in raw_results
                            if isinstance(item.get("publication_year"), int)
                            and start_year <= item["publication_year"] <= end_year
                        ]
                    results = self._rank_results(query, raw_results)
                    precision_filtered = bool(raw_results and not results)
                    return {
                        "ok": True,
                        "status": "OK",
                        "provider": provider,
                        "query": query,
                        "results": results,
                        "result_count": len(results),
                        "risk_flags": [
                            "external_metadata_only",
                            "external_results_require_source_verification",
                            *(["external_precision_filter_no_match"] if precision_filtered else []),
                        ],
                        "message": (
                            "External results are discovery candidates only. Download the original paper "
                            "and verify page or character locations before using it as formal evidence."
                        ),
                    }
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
                    errors.append(f"{provider} attempt {attempt + 1}: {error}")
                    if attempt == 0:
                        time.sleep(0.25)
        return {
            "ok": False,
            "status": "UNAVAILABLE",
            "query": query,
            "message": "External scholarly search is temporarily unavailable.",
            "details": errors,
            "risk_flags": ["external_search_unavailable"],
        }

    @staticmethod
    def _rank_results(query: str, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Apply a small, deterministic precision pass after provider ranking.

        OpenAlex searches title, abstract, and indexed full text. That is useful
        for recall but can promote papers matching only one broad word such as
        ``physics``. Keep the provider results as metadata-only candidates, but
        rank them by overlap with the requested research terms and drop obvious
        one-token matches when the query contains several terms.
        """

        tokens = _query_tokens(query)
        if not tokens or not results:
            return results
        scored: list[tuple[float, int, dict[str, Any]]] = []
        minimum_matches = 1 if len(tokens) <= 3 else 2
        broad_terms = {"education", "thinking", "students", "student", "undergraduate"}
        anchor_tokens = [token for token in tokens if token not in broad_terms]
        require_anchor = len(anchor_tokens) >= 2
        title_anchor_tokens = {
            token for token in anchor_tokens
            if token not in {
                "artificial", "intelligence", "impact", "effect", "learning",
                "outcomes", "university", "education", "association", "relationship",
            }
        }
        for index, item in enumerate(results):
            text = _result_search_text(item)
            matched = {token for token in tokens if token in text}
            anchor_matches = matched.intersection(anchor_tokens)
            title_text = str(item.get("title") or "").lower()
            title_matches = sum(1 for token in tokens if token in title_text)
            title_anchor_matches = {
                token for token in title_anchor_tokens if token in title_text
            }
            score = (len(matched) / len(tokens)) + (0.15 * title_matches)
            enriched = dict(item)
            enriched["relevance_score"] = round(min(score, 1.0), 4)
            enriched["matched_query_terms"] = sorted(matched)
            if len(matched) >= minimum_matches and (
                not require_anchor or len(anchor_matches) >= 2
            ) and (not title_anchor_tokens or title_anchor_matches):
                scored.append((score, -index, enriched))
        if not scored:
            # Do not show provider-ranked noise as if it were relevant evidence.
            # An explicit external-search request can be retried with a narrower
            # query, while the caller still reports that the provider responded.
            return [] if len(tokens) >= 4 else [
                dict(item, relevance_score=0.0, matched_query_terms=[]) for item in results
            ]
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in scored]

    def _search_provider(self, provider: str, query: str, limit: int) -> list[dict[str, Any]]:
        headers = {"User-Agent": self._user_agent()}
        with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True, headers=headers) as client:
            if provider == "openalex":
                response = client.get(
                    "https://api.openalex.org/works",
                    params={"search": query, "per-page": limit, "mailto": self.email or None},
                )
                response.raise_for_status()
                payload = response.json()
                return [_openalex_result(item) for item in payload.get("results", [])[:limit]]
            if provider == "crossref":
                response = client.get(
                    "https://api.crossref.org/works",
                    params={"query.bibliographic": query, "rows": limit, "mailto": self.email or None},
                )
                response.raise_for_status()
                payload = response.json()
                return [_crossref_result(item) for item in payload["message"].get("items", [])[:limit]]
        raise ValueError(f"unsupported external search provider: {provider}")

    def _user_agent(self) -> str:
        return f"STEM-SCI/0.2 (mailto:{self.email})" if self.email else "STEM-SCI/0.2"


def _openalex_result(item: Mapping[str, Any]) -> dict[str, Any]:
    doi = _doi(item.get("doi"))
    authors = [
        str(author.get("author", {}).get("display_name"))
        for author in item.get("authorships", [])[:5]
        if isinstance(author, Mapping) and isinstance(author.get("author"), Mapping)
    ]
    return {
        "source": "openalex",
        "work_id": item.get("id"),
        "title": item.get("title") or "Untitled",
        "publication_year": item.get("publication_year"),
        "doi": doi,
        "authors": authors,
        "journal": (item.get("primary_location") or {}).get("source", {}).get("display_name")
        if isinstance(item.get("primary_location"), Mapping)
        and isinstance((item.get("primary_location") or {}).get("source"), Mapping)
        else None,
        "landing_page_url": item.get("doi") or item.get("id"),
        "full_text_url": _openalex_full_text_url(item),
        "cited_by_count": item.get("cited_by_count"),
        "open_access": (item.get("open_access") or {}).get("is_oa")
        if isinstance(item.get("open_access"), Mapping)
        else None,
        "abstract_terms": list((item.get("abstract_inverted_index") or {}).keys())[:300]
        if isinstance(item.get("abstract_inverted_index"), Mapping)
        else [],
        "concepts": [
            str(concept.get("display_name"))
            for concept in item.get("concepts", [])[:12]
            if isinstance(concept, Mapping) and concept.get("display_name")
        ],
    }


def _crossref_result(item: Mapping[str, Any]) -> dict[str, Any]:
    titles = item.get("title")
    authors = item.get("author") or []
    return {
        "source": "crossref",
        "work_id": item.get("URL") or item.get("DOI"),
        "title": titles[0] if isinstance(titles, list) and titles else "Untitled",
        "publication_year": _crossref_year(item),
        "doi": _doi(item.get("DOI")),
        "authors": [
            " ".join(str(value) for value in (author.get("given"), author.get("family")) if value)
            for author in authors[:5]
            if isinstance(author, Mapping)
        ],
        "journal": (item.get("container-title") or [None])[0],
        "landing_page_url": item.get("URL"),
        "full_text_url": None,
        "cited_by_count": item.get("is-referenced-by-count"),
        "open_access": None,
    }


def _crossref_year(item: Mapping[str, Any]) -> int | None:
    for field in ("published-print", "published-online", "issued"):
        date_parts = (item.get(field) or {}).get("date-parts")
        if isinstance(date_parts, list) and date_parts and isinstance(date_parts[0], list) and date_parts[0]:
            year = date_parts[0][0]
            return int(year) if isinstance(year, int) else None
    return None


def _doi(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if normalized.lower().startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    return normalized or None


def _openalex_full_text_url(item: Mapping[str, Any]) -> str | None:
    location = item.get("best_oa_location")
    if not isinstance(location, Mapping):
        return None
    value = location.get("pdf_url")
    return value if isinstance(value, str) and value.startswith(("https://", "http://")) else None


def _timeout_seconds() -> float:
    try:
        return max(1.0, min(float(os.getenv("STEM_SCI_EXTERNAL_SEARCH_TIMEOUT_SECONDS", "5")), 30.0))
    except ValueError:
        return 5.0


def _query_tokens(query: str) -> list[str]:
    """Return meaningful ASCII discovery terms while retaining short acronyms."""

    stopwords = {
        "the", "and", "with", "from", "this", "that", "for", "using", "use",
        "study", "research", "paper", "students", "student",
    }
    tokens = re.findall(r"[a-z][a-z0-9+#/-]{2,}", query.lower())
    return list(dict.fromkeys(token for token in tokens if token not in stopwords))


def _year_bounds(query: str) -> tuple[int, int] | None:
    years = [int(value) for value in re.findall(r"\b(?:19|20)\d{2}\b", query)]
    if len(years) < 2:
        return None
    start, end = min(years), max(years)
    return (start, end) if start < end else None


def _result_search_text(item: Mapping[str, Any]) -> str:
    values: list[str] = []
    for key in ("title", "journal", "abstract", "abstract_terms", "concepts", "topics"):
        value = item.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(str(part) for part in value)
        elif isinstance(value, Mapping):
            values.extend(str(part) for part in value.values())
    return " ".join(values).lower()
