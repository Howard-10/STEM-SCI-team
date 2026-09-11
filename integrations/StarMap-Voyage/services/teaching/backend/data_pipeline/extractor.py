"""
Document extractor: extract structured text from docx/pdf teaching plans.
Handles 教师手册 (teacher manual) and 学生手册 (student manual).
"""
import os
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

import docx


def extract_docx(filepath: str) -> Dict:
    """Extract structured content from a .docx teaching plan."""
    doc = docx.Document(filepath)
    filename = os.path.basename(filepath)

    # Determine type
    is_teacher = "教师" in filename or "教学手册" in filename or "教学设计" in filename
    doc_type = "teacher" if is_teacher else "student"

    # Extract title from filename
    title = _extract_title_from_filename(filename)

    # Extract paragraphs with style info
    paragraphs = []
    for p in doc.paragraphs:
        text = p.text.strip()
        if not text:
            continue
        style = p.style.name if p.style else "Normal"
        paragraphs.append({
            "style": style,
            "text": text,
            "is_heading": "Heading" in style or "heading" in style.lower(),
            "heading_level": _get_heading_level(style)
        })

    # Identify sections
    sections = _identify_sections(paragraphs)

    # Extract tables
    tables = []
    for table in doc.tables:
        table_data = []
        for row in table.rows:
            row_data = [cell.text.strip() for cell in row.cells]
            table_data.append(row_data)
        if table_data:
            tables.append(table_data)

    return {
        "source_file": filename,
        "filepath": filepath,
        "type": doc_type,
        "title": title,
        "paragraphs": paragraphs,
        "sections": sections,
        "tables": tables,
        "total_paragraphs": len(paragraphs),
        "total_sections": len(sections)
    }


def _extract_title_from_filename(filename: str) -> str:
    """Extract a clean title from the filename."""
    name = filename.replace(".docx", "").replace(".pdf", "")
    # Remove numbering prefixes like "1.", "2.", "3.", etc
    name = re.sub(r'^\d+[\.\s]+', '', name)
    name = re.sub(r'^第.+组[-]?', '', name)
    name = name.replace("教师手册", "").replace("学生手册", "").replace("教学设计", "")
    name = name.replace("——", "").replace("——", "").replace(".", "").replace(" ", "")
    name = name.strip()
    if not name:
        name = "STEM项目教案"
    return name


def _get_heading_level(style_name: str) -> int:
    """Extract heading level from style name."""
    for i in range(1, 5):
        if str(i) in style_name:
            return i
    return 0


def _identify_sections(paragraphs: List[Dict]) -> List[Dict]:
    """Identify logical sections in the document based on heading patterns."""
    sections = []
    current_section = None
    current_content = []

    # Section boundary keywords (for docs without proper heading styles)
    section_keywords = [
        "概述", "核心问题", "关键词", "教学目标", "学习目标",
        "资源", "课程时长", "课程内容", "启动课程",
        "教学评价", "我的评价", "反思笔记", "课程总结",
        "素养与标准", "设计意图", "情境", "背景介绍",
        "学习清单", "活动", "项目背景", "基本信息",
        "学情分析", "教学流程", "教学过程"
    ]

    for p in paragraphs:
        text = p["text"]
        is_new_section = False

        if p["is_heading"]:
            is_new_section = True
        elif any(text.startswith(kw) for kw in section_keywords) and len(text) < 30:
            is_new_section = True
        elif re.match(r'^[一二三四五六七八九十]、', text):
            is_new_section = True
        elif re.match(r'^活动[一二三四五六]', text):
            is_new_section = True

        if is_new_section:
            if current_section and current_content:
                current_section["content"] = "\n".join(current_content)
                sections.append(current_section)
            current_section = {"title": text, "level": p["heading_level"]}
            current_content = []
        elif current_section is not None:
            current_content.append(text)
        else:
            # Content before first section header
            if current_section is None:
                current_section = {"title": "导言", "level": 0}
                current_content = [text]

    # Don't forget the last section
    if current_section:
        current_section["content"] = "\n".join(current_content)
        sections.append(current_section)

    return sections


def extract_all(data_dir: str) -> List[Dict]:
    """Extract all teaching plan documents from data directory."""
    data_path = Path(data_dir)
    results = []

    for filepath in sorted(data_path.glob("*.docx")):
        try:
            doc = extract_docx(str(filepath))
            results.append(doc)
            print(f"  ✓ {doc['source_file']} ({doc['type']}, {doc['total_paragraphs']} paras, {doc['total_sections']} sections)")
        except Exception as e:
            print(f"  ✗ {filepath.name}: {e}")

    return results


if __name__ == "__main__":
    import sys
    teaching_root = Path(__file__).resolve().parents[2]
    data_dir = sys.argv[1] if len(sys.argv) > 1 else os.environ.get(
        "STARMAP_TEACHING_SOURCE_DIR",
        str(teaching_root / "data" / "source"),
    )
    docs = extract_all(data_dir)

    # Save structured output
    output_path = Path(
        os.environ.get(
            "STARMAP_TEACHING_DATA_DIR",
            str(teaching_root / "data" / "processed"),
        )
    ) / "extracted_docs.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False, indent=2)

    print(f"\nSaved {len(docs)} documents to {output_path}")
    print(f"  Teacher: {sum(1 for d in docs if d['type']=='teacher')}")
    print(f"  Student: {sum(1 for d in docs if d['type']=='student')}")
