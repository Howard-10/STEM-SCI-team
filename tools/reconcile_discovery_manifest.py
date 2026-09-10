"""Rebuild the local discovery full-text manifest from downloaded PDFs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "data" / "catalogs" / "physics_stem" / "discovery_candidates.json"
PDF_ROOT = ROOT / "data" / "local" / "discovery_fulltext"
OUT = ROOT / "data" / "local" / "discovery_fulltext_manifest.json"


def main() -> int:
    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8")).get("candidates", [])
    by_id = {str(item.get("candidate_id")): item for item in candidates}
    records: list[dict[str, object]] = []
    for pdf in sorted(PDF_ROOT.glob("*.pdf")):
        candidate_id = pdf.name.split("_", 1)[0]
        item = by_id.get(candidate_id, {})
        try:
            reader = PdfReader(str(pdf))
            pages = len(reader.pages)
            chars = sum(len(page.extract_text() or "") for page in reader.pages)
            status = "downloaded" if pages and chars >= 500 else "unparseable"
            detail = f"pages={pages};chars={chars}"
        except Exception as error:
            status = "unparseable"
            detail = type(error).__name__
        records.append(
            {
                "candidate_id": candidate_id,
                "title": item.get("title") or pdf.stem,
                "doi": item.get("doi"),
                "year": item.get("year"),
                "landing_page_url": item.get("landing_page_url"),
                "pdf_url": item.get("pdf_url"),
                "open_access_asserted_by": "OpenAlex",
                "status": status,
                "bytes": pdf.stat().st_size,
                "detail": detail,
                "filename": pdf.name,
                "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                "formal_eligible": False,
            }
        )
    payload = {
        "artifact_type": "DiscoveryFullTextManifest",
        "artifact_version": "0.1.1",
        "status": "LOCAL_DISCOVERY_ONLY",
        "policy": "Downloaded files require license review, corpus identity mapping, chunking, and locator validation before formal use.",
        "requested_count": 12,
        "records": records,
        "downloaded_count": sum(record["status"] == "downloaded" for record in records),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"files": len(records), "downloaded": payload["downloaded_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
