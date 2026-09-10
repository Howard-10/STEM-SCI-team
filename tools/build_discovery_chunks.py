"""Extract page-aware chunks from the local discovery-only PDF expansion."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
PDF_ROOT = ROOT / "data" / "local" / "discovery_fulltext"
OUT = PDF_ROOT / "chunks.jsonl"
MANIFEST = ROOT / "data" / "local" / "discovery_fulltext_manifest.json"
CHUNK_SIZE = 1200
OVERLAP = 160


def normalize(text: str) -> str:
    cleaned = (text or "").replace("\ufffd", "")
    cleaned = re.sub(r"\s+-\s+", "-", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def split_text(text: str) -> list[tuple[int, int, str]]:
    text = normalize(text)
    chunks: list[tuple[int, int, str]] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + CHUNK_SIZE)
        if end < len(text):
            boundary = text.rfind(" ", start + CHUNK_SIZE - 120, end)
            if boundary > start:
                end = boundary
        chunks.append((start, end, text[start:end]))
        if end == len(text):
            break
        start = max(end - OVERLAP, start + 1)
    return chunks


def main() -> int:
    rows: list[dict[str, object]] = []
    for pdf in sorted(PDF_ROOT.glob("*.pdf")):
        reader = PdfReader(str(pdf))
        for page_number, page in enumerate(reader.pages, start=1):
            text = normalize(page.extract_text() or "")
            for local_index, (char_start, char_end, excerpt) in enumerate(split_text(text)):
                chunk_id = hashlib.sha256(
                    f"{pdf.name}\0{page_number}\0{char_start}\0{excerpt}".encode("utf-8")
                ).hexdigest()[:24]
                rows.append(
                    {
                        "chunk_id": f"discovery_{chunk_id}",
                        "filename": pdf.name,
                        "page": page_number,
                        "page_chunk_index": local_index,
                        "char_start": char_start,
                        "char_end": char_end,
                        "text": excerpt,
                        "source_status": "metadata_only_fulltext",
                        "formal_eligible": False,
                    }
                )
    OUT.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["chunk_count"] = len(rows)
    payload["chunk_artifact"] = {
        "filename": OUT.name,
        "sha256": hashlib.sha256(OUT.read_bytes()).hexdigest(),
        "formal_eligible": False,
    }
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pdfs": len(list(PDF_ROOT.glob('*.pdf'))), "chunks": len(rows)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
