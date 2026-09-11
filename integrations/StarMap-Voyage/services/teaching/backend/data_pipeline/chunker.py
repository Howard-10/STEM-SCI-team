"""
Document chunker: split teaching plans into retrievable chunks.
Strategies: by-section, semantic, and sliding-window.
"""
import json
import os
import re
from pathlib import Path
from typing import Dict, List


def chunk_by_section(doc: Dict) -> List[Dict]:
    """Split document by its natural sections (best for structured教案)."""
    chunks = []
    for sec in doc.get("sections", []):
        title = sec.get("title", "")
        content = sec.get("content", "")
        if not content or len(content) < 10:
            continue

        chunks.append({
            "chunk_id": f"{doc['source_file']}__{_safe_id(title)}",
            "source_file": doc["source_file"],
            "doc_type": doc["type"],
            "doc_title": doc["title"],
            "section_title": title,
            "content": content,
            "content_length": len(content),
            "chunk_type": "section"
        })
    return chunks


def chunk_teacher_manual(doc: Dict) -> List[Dict]:
    """Whole teacher manual as a single Few-shot example chunk."""
    if doc["type"] != "teacher":
        return []

    # Reconstruct full document text
    full_text = f"# {doc['title']}\n\n"
    for sec in doc.get("sections", []):
        full_text += f"## {sec['title']}\n\n{sec['content']}\n\n"

    return [{
        "chunk_id": f"{doc['source_file']}__full",
        "source_file": doc["source_file"],
        "doc_type": doc["type"],
        "doc_title": doc["title"],
        "section_title": "全文",
        "content": full_text,
        "content_length": len(full_text),
        "chunk_type": "full_manual"
    }]


def chunk_for_fewshot(doc: Dict) -> Dict:
    """Create a compact version optimized for Few-shot prompting."""
    if doc["type"] != "teacher":
        return None

    # Extract key structural elements
    overview = ""
    objectives = ""
    activities = ""
    assessment = ""

    for sec in doc.get("sections", []):
        title = sec.get("title", "")
        content = sec.get("content", "")

        if any(kw in title for kw in ["概述", "核心问题", "课程概述"]):
            overview = content[:800]
        elif any(kw in title for kw in ["教学目标", "学习目标"]):
            objectives = content[:600]
        elif any(kw in title for kw in ["活动", "课程内容", "教学流程", "启动课程"]):
            activities = content[:2000]
        elif any(kw in title for kw in ["评价", "总结", "反思"]):
            assessment = content[:600]

    compact = f"""【教案示例：{doc['title']}】

概述：{overview}

教学目标：{objectives}

课程活动设计：{activities}

评价与总结：{assessment}"""
    return compact


def chunk_all(docs: List[Dict]) -> Dict[str, List[Dict]]:
    """Run all chunking strategies."""
    section_chunks = []
    full_manual_chunks = []
    fewshot_chunks = []

    for doc in docs:
        section_chunks.extend(chunk_by_section(doc))
        full_manual_chunks.extend(chunk_teacher_manual(doc))
        fewshot = chunk_for_fewshot(doc)
        if fewshot:
            fewshot_chunks.append(fewshot)

    return {
        "section_chunks": section_chunks,
        "full_manual_chunks": full_manual_chunks,
        "fewshot_chunks": fewshot_chunks
    }


def _safe_id(text: str) -> str:
    return re.sub(r'[^\w一-鿿]', '_', text)[:40]


if __name__ == "__main__":
    import sys
    output_dir = Path(
        os.environ.get(
            "STARMAP_TEACHING_DATA_DIR",
            str(Path(__file__).resolve().parents[2] / "data" / "processed"),
        )
    )
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else output_dir / "extracted_docs.json"

    with open(input_path, "r", encoding="utf-8") as f:
        docs = json.load(f)

    results = chunk_all(docs)
    print(f"Section chunks: {len(results['section_chunks'])}")
    print(f"Full manual chunks: {len(results['full_manual_chunks'])}")
    print(f"Few-shot chunks: {len(results['fewshot_chunks'])}")

    output_dir.mkdir(parents=True, exist_ok=True)
    for name, chunks in results.items():
        path = output_dir / f"{name}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(chunks, f, ensure_ascii=False, indent=2)
        print(f"  Saved {path}")
