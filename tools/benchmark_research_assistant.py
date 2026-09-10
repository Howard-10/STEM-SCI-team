"""Fail-closed benchmark for the STEM-SCI retrieval and manuscript surfaces.

The script intentionally does not invent relevance labels or quality scores. It
can report annotation readiness from the repository Gold Set and can evaluate a
result file once two-person labels are frozen.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLD = ROOT / "data" / "evaluation" / "physics_stem_v1_retrieval_gold.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def readiness(gold: dict[str, Any]) -> dict[str, Any]:
    questions = gold.get("questions") or []
    pending = [q for q in questions if q.get("annotation_status") != "FROZEN"]
    labelled = [
        q for q in questions
        if q.get("relevant_paper_ids")
        and q.get("strongly_relevant_chunk_ids")
        and q.get("acceptable_evidence_quote_ids")
        and q.get("annotation_status") == "FROZEN"
    ]
    policy = gold.get("policy") or {}
    minimum = int(policy.get("minimum_questions", 0) or 0)
    ready = len(questions) >= minimum and not pending and len(labelled) == len(questions)
    return {
        "corpus_id": gold.get("corpus_id"),
        "question_count": len(questions),
        "minimum_questions": minimum,
        "frozen_question_count": len(labelled),
        "pending_question_ids": [q.get("question_id") for q in pending],
        "status": "READY_FOR_SCORING" if ready else "ANNOTATION_REQUIRED",
        "can_report_retrieval_quality": ready,
    }


def reciprocal_rank(relevant: set[str], ranked: list[str]) -> float:
    for index, item in enumerate(ranked, start=1):
        if item in relevant:
            return 1.0 / index
    return 0.0


def score(gold: dict[str, Any], results: dict[str, Any]) -> dict[str, Any]:
    status = readiness(gold)
    if not status["can_report_retrieval_quality"]:
        return {
            **status,
            "error": "Gold Set 尚未完成双人标注和冻结，不能计算或宣传检索质量。",
        }
    result_by_id = {item["question_id"]: item for item in results.get("questions", [])}
    rr = []
    recall = []
    evaluated = 0
    for question in gold["questions"]:
        expected = set(question["strongly_relevant_chunk_ids"])
        actual = result_by_id.get(question["question_id"], {}).get("ranked_chunk_ids", [])
        if not expected:
            continue
        evaluated += 1
        rr.append(reciprocal_rank(expected, actual))
        recall.append(len(expected.intersection(actual[:5])) / len(expected))
    if not evaluated:
        return {**status, "error": "冻结 Gold Set 没有可评分的强相关片段。"}
    return {
        **status,
        "evaluated_questions": evaluated,
        "mrr": sum(rr) / evaluated,
        "recall_at_5": sum(recall) / evaluated,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--results", type=Path)
    args = parser.parse_args()
    gold = load_json(args.gold)
    report = readiness(gold) if args.results is None else score(gold, load_json(args.results))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("status") == "READY_FOR_SCORING" else 2


if __name__ == "__main__":
    raise SystemExit(main())
