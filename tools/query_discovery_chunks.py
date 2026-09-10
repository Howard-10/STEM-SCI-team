"""Keyword search over the local discovery-only page-aware chunks."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHUNKS = ROOT / "data" / "local" / "discovery_fulltext" / "chunks.jsonl"


def tokens(value: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", value.casefold())


def search(query: str, limit: int) -> list[dict[str, object]]:
    rows = [json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines() if line.strip()]
    query_tokens = tokens(query)
    if not query_tokens:
        return []
    documents = [tokens(str(row["text"])) for row in rows]
    document_frequency = Counter(token for document in documents for token in set(document))
    average_length = sum(len(document) for document in documents) / max(len(documents), 1)
    scored: list[tuple[float, dict[str, object]]] = []
    for row, document in zip(rows, documents):
        counts = Counter(document)
        score = 0.0
        for token in query_tokens:
            if not counts[token]:
                continue
            idf = math.log((len(rows) - document_frequency[token] + 0.5) / (document_frequency[token] + 0.5) + 1)
            tf = counts[token]
            length_norm = 1.2 * (1 - 0.75 + 0.75 * len(document) / max(average_length, 1))
            score += idf * (tf * 2.2) / (tf + length_norm)
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], item[1]["filename"], item[1]["page"], item[1]["char_start"]))
    return [
        {"score": round(score, 4), **row}
        for score, row in scored[:limit]
    ]


def main() -> int:
    # Windows PowerShell may default stdout to GBK; discovery text can contain
    # copyright symbols and other Unicode characters from PDFs.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    for hit in search(args.query, max(1, min(args.limit, 20))):
        print(json.dumps(hit, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
