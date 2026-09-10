"""Build a citation-oriented demo report over the local discovery expansion."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from query_discovery_chunks import search  # noqa: E402


GOLD = ROOT / "data" / "evaluation" / "physics_stem_v1_retrieval_gold.json"
OUT = ROOT / "docs" / "reports" / "DISCOVERY_FULLTEXT_DEMO_20260909.md"


def main() -> int:
    questions = json.loads(GOLD.read_text(encoding="utf-8")).get("questions", [])[:10]
    lines = [
        "# Discovery full-text demo report",
        "",
        f"> Generated: {date.today().isoformat()}",
        "> Scope: six locally downloaded open-access PDFs and 469 page-aware chunks.",
        "> Evidence boundary: discovery-only; all hits remain `metadata_only_fulltext` and are not formal evidence.",
        "",
        "This report demonstrates that the newly downloaded full texts can be used by a research assistant to find page-addressable source excerpts. It is not a frozen Gold Set and does not report retrieval accuracy.",
        "",
    ]
    for index, question in enumerate(questions, start=1):
        query = question.get("query", "")
        hits = search(query, 3)
        lines.extend([f"## {index}. {query}", ""])
        if not hits:
            lines.append("- No local discovery hit; use the shared corpus or external discovery fallback.")
            lines.append("")
            continue
        for hit in hits:
            excerpt = " ".join(str(hit["text"]).split())[:360]
            lines.extend(
                [
                    f"- **{hit['filename']}**, p. {hit['page']}, score `{hit['score']}`",
                    f"  - chunk: `{hit['chunk_id']}`",
                    f"  - excerpt: {excerpt}",
                    "  - status: `metadata_only_fulltext`; formal eligible: `false`",
                ]
            )
        lines.append("")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"questions": len(questions), "report": str(OUT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
