"""Download a small, license-aware full-text expansion for local discovery.

Only OpenAlex records explicitly marked open access are considered.  The output
is a separate local-only corpus and is not added to the formal manifest or
vector index by this script.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "catalogs" / "physics_stem" / "discovery_candidates.json"
OUT = ROOT / "data" / "local" / "discovery_fulltext"
REPORT = ROOT / "data" / "local" / "discovery_fulltext_manifest.json"
MAX_FILES = 12
MAX_BYTES = 25 * 1024 * 1024
ALLOWED_HOST_MARKERS = (
    "arxiv.org",
    "mdpi.com",
    "frontiersin.org",
    "springeropen.com",
    "bmj.com",
    "hindawi.com",
    "openpraxis.org",
    "academic-publishing.org",
    "aupress.ca",
)


def score(item: dict[str, object]) -> int:
    text = f"{item.get('title', '')} {item.get('abstract', '')}".casefold()
    terms = {
        "physics": 8,
        "stem": 6,
        "computational": 5,
        "modeling": 5,
        "modelling": 5,
        "generative ai": 5,
        "chatgpt": 4,
        "artificial intelligence": 3,
        "teacher education": 4,
        "learning analytics": 3,
        "assessment": 2,
        "research": 1,
    }
    return sum(weight for term, weight in terms.items() if term in text) + int(item.get("cited_by_count", 0) or 0) // 500


def safe_name(title: str, candidate_id: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_")[:90]
    return f"{candidate_id}_{normalized or 'paper'}.pdf"


def download(url: str, target: Path) -> tuple[str, int, str | None]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "STEM-SCI-discovery-ingest/0.1", "Accept": "application/pdf"},
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            content_type = (response.headers.get("Content-Type") or "").casefold()
            data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            return "too_large", 0, f"size>{MAX_BYTES}"
        if not data.startswith(b"%PDF") and "pdf" not in content_type:
            return "not_pdf", len(data), content_type or "unknown_content_type"
        target.write_bytes(data)
        reader = PdfReader(str(target))
        pages = len(reader.pages)
        chars = sum(len(page.extract_text() or "") for page in reader.pages)
        if pages == 0 or chars < 500:
            target.unlink(missing_ok=True)
            return "unparseable", len(data), f"pages={pages};chars={chars}"
        return "downloaded", len(data), f"pages={pages};chars={chars}"
    except Exception as error:  # network and malformed publisher responses are per-item failures
        target.unlink(missing_ok=True)
        return "failed", 0, type(error).__name__


def main() -> int:
    candidates = json.loads(SOURCE.read_text(encoding="utf-8")).get("candidates", [])
    selected = sorted(
        [
            item
            for item in candidates
            if item.get("open_access")
            and item.get("pdf_url")
            and any(marker in str(item.get("pdf_url")) for marker in ALLOWED_HOST_MARKERS)
        ],
        key=lambda item: (-score(item), -(item.get("year") or 0), item.get("candidate_id", "")),
    )[:MAX_FILES]
    OUT.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    for item in selected:
        target = OUT / safe_name(str(item.get("title", "")), str(item.get("candidate_id", "candidate")))
        status, size, detail = download(str(item["pdf_url"]), target)
        record = {
            "candidate_id": item.get("candidate_id"),
            "title": item.get("title"),
            "doi": item.get("doi"),
            "year": item.get("year"),
            "landing_page_url": item.get("landing_page_url"),
            "pdf_url": item.get("pdf_url"),
            "open_access_asserted_by": "OpenAlex",
            "selection_score": score(item),
            "status": status,
            "bytes": size,
            "detail": detail,
            "filename": target.name if status == "downloaded" else None,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest() if status == "downloaded" else None,
            "formal_eligible": False,
        }
        records.append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(
            {
                "artifact_type": "DiscoveryFullTextManifest",
                "artifact_version": "0.1.0",
                "status": "LOCAL_DISCOVERY_ONLY",
                "policy": "Downloaded files require license review, corpus identity mapping, chunking, and locator validation before formal use.",
                "requested_count": MAX_FILES,
                "records": records,
                "downloaded_count": sum(record["status"] == "downloaded" for record in records),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
