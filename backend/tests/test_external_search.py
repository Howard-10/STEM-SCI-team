from __future__ import annotations

from typing import Any, Self

import httpx

from stem_sci.api import _external_discovery_query
from stem_sci.knowledge.external_search import ExternalSearchClient


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.url = ""

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.url = url
        return _FakeResponse(
            {
                "results": [
                    {
                        "id": "https://openalex.org/W1",
                        "title": "Graph retrieval",
                        "publication_year": 2025,
                        "doi": "https://doi.org/10.1000/test",
                        "authorships": [{"author": {"display_name": "A Researcher"}}],
                        "cited_by_count": 4,
                        "open_access": {"is_oa": True},
                    }
                ]
            }
        )


def test_openalex_search_normalizes_metadata(monkeypatch) -> None:
    monkeypatch.setenv("STEM_SCI_EXTERNAL_SEARCH_PROVIDER", "openalex")
    monkeypatch.setattr(httpx, "Client", _FakeClient)

    result = ExternalSearchClient().search("graph retrieval", max_results=3)

    assert result["ok"] is True
    assert result["provider"] == "openalex"
    assert result["results"][0]["doi"] == "10.1000/test"
    assert result["results"][0]["authors"] == ["A Researcher"]
    assert "external_results_require_source_verification" in result["risk_flags"]


def test_chinese_research_scope_projects_to_a_scholarly_discovery_query() -> None:
    query = _external_discovery_query(
        "我想研究在本科物理课程中引入 Python/VPython 计算建模，是否能够提升学生的计算思维，计划采用前测—后测比较。"
    )

    assert "physics education" in query
    assert "Python VPython" in query
    assert "computational modeling" in query
    assert "computational thinking" in query
    assert "pretest posttest" in query


def test_external_search_precision_pass_prefers_multi_term_matches(monkeypatch) -> None:
    monkeypatch.setenv("STEM_SCI_EXTERNAL_SEARCH_PROVIDER", "openalex")

    class PrecisionClient(_FakeClient):
        def get(self, url: str, **kwargs: Any) -> _FakeResponse:
            del url, kwargs
            return _FakeResponse(
                {
                    "results": [
                        {"id": "https://openalex.org/W1", "title": "An Introduction to Astrophysics"},
                        {
                            "id": "https://openalex.org/W2",
                            "title": "Computational Modeling in Physics Education",
                            "concepts": [{"display_name": "Physics education"}],
                        },
                    ]
                }
            )

    monkeypatch.setattr(httpx, "Client", PrecisionClient)
    result = ExternalSearchClient().search(
        "physics education computational modeling", max_results=5
    )

    assert result["result_count"] == 1
    assert result["results"][0]["title"] == "Computational Modeling in Physics Education"
    assert result["results"][0]["relevance_score"] > 0
    assert "physics" in result["results"][0]["matched_query_terms"]


def test_external_search_precision_pass_excludes_generic_education_match(monkeypatch) -> None:
    monkeypatch.setenv("STEM_SCI_EXTERNAL_SEARCH_PROVIDER", "openalex")

    class PrecisionClient(_FakeClient):
        def get(self, url: str, **kwargs: Any) -> _FakeResponse:
            del url, kwargs
            return _FakeResponse(
                {
                    "results": [
                        {
                            "id": "https://openalex.org/W1",
                            "title": "ChatGPT for Education and Research",
                        },
                        {
                            "id": "https://openalex.org/W2",
                            "title": "Computational Modeling in Physics Education",
                        },
                    ]
                }
            )

    monkeypatch.setattr(httpx, "Client", PrecisionClient)
    result = ExternalSearchClient().search(
        "physics education computational modeling computational thinking",
        max_results=5,
    )

    assert result["result_count"] == 1
    assert result["results"][0]["title"] == "Computational Modeling in Physics Education"


def test_external_search_drops_provider_noise_when_no_anchor_matches(monkeypatch) -> None:
    monkeypatch.setenv("STEM_SCI_EXTERNAL_SEARCH_PROVIDER", "openalex")

    class NoiseClient(_FakeClient):
        def get(self, url: str, **kwargs: Any) -> _FakeResponse:
            del url, kwargs
            return _FakeResponse(
                {"results": [{"id": "https://openalex.org/W1", "title": "Interior design studios"}]}
            )

    monkeypatch.setattr(httpx, "Client", NoiseClient)
    result = ExternalSearchClient().search(
        "generative artificial intelligence computational thinking physics education",
        max_results=5,
    )

    assert result["result_count"] == 0
    assert result["results"] == []
    assert "external_precision_filter_no_match" in result["risk_flags"]
