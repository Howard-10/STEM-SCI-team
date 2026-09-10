"""Build auditable, non-formal knowledge assets from the shared corpus.

This script deliberately keeps generated cards and OpenAlex candidates separate
from the formal evidence corpus.  Generated fields retain their source chunk
references and remain ``model_generated_unverified`` until a source workflow
verifies them.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IDENTITY = ROOT / "data" / "catalogs" / "physics_stem" / "paper_identity_map.json"
GRAPH = ROOT / "data" / "derived" / "physics_stem" / "sparse_paper_graph_v2.json"
OUT = ROOT / "data" / "structured"
CARDS = OUT / "physics_stem_paper_cards.jsonl"
CANDIDATES = ROOT / "data" / "catalogs" / "physics_stem" / "discovery_candidates.json"
TASK_BANK = OUT / "research_assistant_task_bank.json"
SUMMARY = OUT / "knowledge_asset_summary.json"


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _abstract(inverted: dict[str, list[int]] | None) -> str | None:
    """Reconstruct OpenAlex's public abstract index when it is available."""

    if not inverted:
        return None
    words: dict[int, str] = {}
    for word, positions in inverted.items():
        for position in positions:
            words[position] = word
    return _clean(" ".join(words[index] for index in sorted(words)))[:2500] or None


def build_cards() -> int:
    identity = json.loads(IDENTITY.read_text(encoding="utf-8"))
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    by_id = {paper["paper_id"]: paper for paper in identity["papers"]}
    CARDS.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with CARDS.open("w", encoding="utf-8", newline="\n") as stream:
        for graph_paper in graph["papers"]:
            paper_id = graph_paper["paper_id"]
            base = by_id.get(paper_id, {})
            facets: dict[str, list[str]] = defaultdict(list)
            evidence_refs: list[dict[str, object]] = []
            for triple in graph_paper.get("triples", []):
                relation = str(triple.get("relation", ""))
                tail = _clean(str(triple.get("tail", "")))
                if tail and tail not in facets[relation]:
                    facets[relation].append(tail)
                evidence_refs.append(
                    {
                        "relation": relation,
                        "tail": tail,
                        "evidence": _clean(str(triple.get("evidence", ""))),
                        "confidence": triple.get("confidence"),
                        "source_chunk_ids": triple.get("source_chunk_ids")
                        or ([triple["source_chunk_id"]] if triple.get("source_chunk_id") else []),
                        "source_status": "model_generated_unverified",
                    }
                )
            card = {
                "artifact_type": "PaperCard",
                "artifact_version": "0.1.0-auto",
                "paper_id": paper_id,
                "title": base.get("title") or graph_paper.get("title", ""),
                "authors": [],
                "year": base.get("year") or None,
                "doi": base.get("doi") or None,
                "journal": base.get("journal") or None,
                "source_filename": base.get("source_filename") or graph_paper.get("source_filename"),
                "source_hash": None,
                "research_context": facets.get("STUDIES_DOMAIN", []),
                "sample": facets.get("HAS_SAMPLE", []),
                "study_design": facets.get("USES_METHOD", []),
                "intervention": facets.get("ADOPTS_PEDAGOGY", []) + facets.get("DEPLOYS_TECH", []),
                "comparison": facets.get("COMPARES_WITH", []),
                "outcomes": facets.get("TARGETS_OUTCOME", []),
                "methods": facets.get("USES_METHOD", []),
                "theories": facets.get("APPLIES_THEORY", []),
                "populations": facets.get("INVOLVES_POPULATION", []),
                "claims": facets.get("CLAIMS", []),
                "effect_sizes": facets.get("HAS_EFFECT_SIZE", []),
                "evidence_refs": evidence_refs,
                "source_status": "model_generated_unverified",
                "completeness_flags": {
                    "metadata_missing": [
                        field
                        for field, value in (
                            ("doi", base.get("doi")),
                            ("year", base.get("year")),
                            ("journal", base.get("journal")),
                        )
                        if not value
                    ],
                    "requires_source_review": True,
                },
            }
            stream.write(json.dumps(card, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
    return count


def _openalex_candidates() -> list[dict[str, object]]:
    queries = [
        "physics education artificial intelligence computational modeling",
        "STEM education generative AI scaffolding teacher education",
        "physics education learning analytics assessment",
        "educational research mixed methods measurement validity",
    ]
    seen: set[str] = set()
    results: list[dict[str, object]] = []
    for query in queries:
        params = urllib.parse.urlencode({"search": query, "per-page": 30})
        request = urllib.request.Request(
            f"https://api.openalex.org/works?{params}",
            headers={"User-Agent": "STEM-SCI-knowledge-builder/0.1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, TimeoutError, json.JSONDecodeError):
            continue
        for item in payload.get("results", []):
            doi = (item.get("doi") or "").lower().replace("https://doi.org/", "")
            key = doi or _clean(item.get("title", "")).casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            location = item.get("best_oa_location") or item.get("primary_location") or {}
            source = location.get("source") or {}
            results.append(
                {
                    "candidate_id": item.get("id", "").rsplit("/", 1)[-1],
                    "title": _clean(item.get("title", "")),
                    "doi": doi or None,
                    "year": item.get("publication_year"),
                    "type": item.get("type"),
                    "journal": source.get("display_name"),
                    "landing_page_url": location.get("landing_page_url"),
                    "pdf_url": location.get("pdf_url"),
                    "open_access": bool(item.get("open_access", {}).get("is_oa")),
                    "cited_by_count": item.get("cited_by_count", 0),
                    "topic": (item.get("primary_topic") or {}).get("display_name"),
                    "abstract": _abstract(item.get("abstract_inverted_index")),
                    "abstract_status": (
                        "openalex_public_abstract"
                        if item.get("abstract_inverted_index")
                        else "not_available"
                    ),
                    "discovery_query": query,
                    "source_status": "metadata_only",
                    "eligible_for_formal_evidence": False,
                }
            )
    return results


def build_candidates() -> int:
    candidates = _openalex_candidates()
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "artifact_type": "LiteratureDiscoveryCandidates",
        "artifact_version": "0.1.0",
        "provider": "OpenAlex",
        "status": "METADATA_ONLY",
        "policy": "Candidates require license check, full-text ingestion, source hashing, and locator validation before formal use.",
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    CANDIDATES.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(candidates)


def build_task_bank() -> int:
    """Create deterministic, non-evidence task templates for the research assistant."""

    templates = {
        "literature_screening": [
            "根据纳入标准筛选论文", "去重并解析 DOI", "识别研究对象和学段", "提取研究设计", "记录排除理由"
        ],
        "evidence_synthesis": [
            "生成单篇 PaperCard", "建立研究问题证据矩阵", "区分支持与矛盾证据", "整理研究空白", "检查主张引用覆盖"
        ],
        "study_design": [
            "把研究想法拆成研究问题", "定义干预和对照条件", "选择结果变量和量表", "检查样本与功效计划", "生成预注册检查表"
        ],
        "data_audit": [
            "建立数据字典", "检查缺失和异常值", "生成 Raw-Processed-Frozen 链", "核对变量与分析计划", "生成数据审计报告"
        ],
        "writing_review": [
            "根据证据生成段落提纲", "检查引用与主张绑定", "检查因果措辞", "比较中英文数字", "生成审稿风险清单"
        ],
        "reproducibility": [
            "核对代码与冻结数据", "复核统计结果卡", "生成执行环境摘要", "构建主张追溯链", "生成复现包清单"
        ],
    }
    records: list[dict[str, object]] = []
    for category, names in templates.items():
        for index, name in enumerate(names, start=1):
            records.append(
                {
                    "task_id": f"RA-{category[:3].upper()}-{index:02d}",
                    "category": category,
                    "name": name,
                    "assistant_role": "research_assistant",
                    "input_types": ["project_scope", "context_bundle"],
                    "output_types": ["structured_artifact", "source_refs", "risk_flags"],
                    "required_checks": ["project_scope", "source_status", "provenance"],
                    "formal_claim_allowed": False,
                    "demo_ready": True,
                }
            )
    TASK_BANK.parent.mkdir(parents=True, exist_ok=True)
    TASK_BANK.write_text(
        json.dumps(
            {
                "artifact_type": "ResearchAssistantTaskBank",
                "artifact_version": "0.1.0",
                "status": "TEMPLATE_ASSETS",
                "task_count": len(records),
                "tasks": records,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return len(records)


def build_summary(paper_cards: int, discovery_candidates: int, tasks: int) -> None:
    """Write a bounded summary suitable for a demo/status panel."""

    registry = json.loads(
        (OUT / "research_assistant_knowledge_registry.json").read_text(encoding="utf-8")
    )
    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    local_manifest_path = ROOT / "data" / "local" / "discovery_fulltext_manifest.json"
    local_manifest = (
        json.loads(local_manifest_path.read_text(encoding="utf-8"))
        if local_manifest_path.exists()
        else {}
    )
    cards = [
        json.loads(line)
        for line in CARDS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    SUMMARY.write_text(
        json.dumps(
            {
                "artifact_type": "KnowledgeAssetSummary",
                "artifact_version": "0.1.0",
                "corpus_id": "physics_stem_v1",
                "formal_corpus": {
                    "papers": 122,
                    "vector_chunks": 1788,
                    "graph_triples": 944,
                    "formal_status": "existing_manifest_and_locator_controls_apply",
                },
                "structured_assets": {
                    "paper_cards": paper_cards,
                    "paper_cards_status": "model_generated_unverified",
                    "research_method_and_workflow_records": sum(
                        len(group["records"]) for group in registry["groups"]
                    ),
                    "research_assistant_tasks": tasks,
                    "discovery_candidates": discovery_candidates,
                    "discovery_candidates_with_abstract": sum(
                        bool(item.get("abstract")) for item in candidates["candidates"]
                    ),
                    "discovery_fulltext_pdfs": local_manifest.get("downloaded_count", 0),
                    "discovery_fulltext_chunks": local_manifest.get("chunk_count", 0),
                    "discovery_status": "metadata_only",
                },
                "non_claims": [
                    "Discovery candidates are not formal evidence.",
                    "Generated PaperCards do not establish human verification.",
                    "Retrieval metrics remain blocked until the Gold Set is frozen.",
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    paper_cards = build_cards()
    discovery_candidates = build_candidates()
    research_assistant_tasks = build_task_bank()
    build_summary(paper_cards, discovery_candidates, research_assistant_tasks)
    print(
        json.dumps(
            {
                "paper_cards": paper_cards,
                "discovery_candidates": discovery_candidates,
                "research_assistant_tasks": research_assistant_tasks,
            }
        )
    )
