"""PDF 解析器 — 使用 PyMuPDF 提取论文全文、公式、表格索引"""

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from backend.core.config import get_config


@dataclass
class PDFSection:
    title: str
    level: int
    content: str
    start_page: int
    end_page: int
    figures: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)


@dataclass
class PDFDocument:
    file_path: str
    title: str = ""
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    sections: list[PDFSection] = field(default_factory=list)
    full_text: str = ""
    references: list[str] = field(default_factory=list)
    figures_count: int = 0
    tables_count: int = 0
    page_count: int = 0
    file_hash: str = ""


class PDFParser:
    """论文 PDF 解析器"""

    def __init__(self):
        self.cfg = get_config()

    def parse(self, file_path: str) -> PDFDocument:
        """多策略 PDF 解析 — 自动选择最佳方案"""
        doc = PDFDocument(file_path=file_path)

        with open(file_path, "rb") as f:
            doc.file_hash = hashlib.md5(f.read()).hexdigest()

        # 三路策略管线
        strategies = [
            ("pymupdf_layout", self._try_pymupdf_layout),
            ("pymupdf_dict", self._try_pymupdf_dict),
            ("pdfplumber", self._try_pdfplumber),
        ]

        best_text = ""
        best_quality = 0
        best_strategy = "none"

        for name, strategy_fn in strategies:
            try:
                text, quality, meta = strategy_fn(file_path)
                if quality > best_quality:
                    best_text = text
                    best_quality = quality
                    best_strategy = name
                    # 合并元数据
                    doc.page_count = meta.get("page_count", doc.page_count)
                    doc.figures_count = meta.get("figures_count", doc.figures_count)
                    doc.tables_count = meta.get("tables_count", doc.tables_count)
                # 质量 > 0.7 足够好，不再尝试后续策略
                if best_quality > 0.6:
                    break
            except Exception as e:
                from backend.core.error_logger import log_error
                log_error(f"pdf_parser.{name}", e, f"file={file_path}")
                continue

        doc.full_text = best_text

        # 如果所有策略都失败，给出明确诊断
        if best_quality < 0.1:
            doc.full_text = f"[PDF 解析失败] 所有策略均无法提取有效文本。策略 {best_strategy} 仅提取 {len(best_text)} 字符。可能原因：扫描版PDF、图片型PDF、加密文件。"

        # 提取元数据
        doc.title = self._extract_title(doc.full_text) or Path(file_path).stem
        doc.authors = self._extract_authors(doc.full_text)
        doc.abstract = self._extract_abstract(doc.full_text)
        doc.sections = self._split_sections(doc.full_text)
        doc.references = self._extract_references(doc.full_text)

        # 元数据校准
        self._calibrate_figure_table_counts(doc)

        return doc

    # ═══ 策略 1: PyMuPDF + layout 包 ═══
    def _try_pymupdf_layout(self, file_path: str) -> tuple[str, float, dict]:
        """使用 pymupdf_layout 增强的文本提取"""
        import fitz
        pdf = fitz.open(file_path)
        texts = []
        figs = 0
        tabs = 0

        for page in pdf:
            # 使用 layout 感知的文本提取
            try:
                page_text = page.get_text("text", flags=fitz.TEXT_PRESERVE_LIGATURES | fitz.TEXT_PRESERVE_WHITESPACE)
            except Exception:
                page_text = page.get_text("text")

            texts.append(page_text)

            # 图表检测
            images = page.get_images(full=True)
            for img in images:
                if len(img) > 3 and img[2] > 40 and img[3] > 40:
                    figs += 1
            try:
                found_tabs = page.find_tables()
                if found_tabs:
                    tabs += len(found_tabs.tables)
            except Exception:
                pass

        pdf.close()
        full_text = "\n\n".join(texts)
        quality = self._score_text_quality(full_text)
        return full_text, quality, {"page_count": len(texts), "figures_count": figs, "tables_count": tabs}

    # ═══ 策略 2: PyMuPDF dict 模式（已有） ═══
    def _try_pymupdf_dict(self, file_path: str) -> tuple[str, float, dict]:
        """使用 PyMuPDF dict 模式 + 位置排序"""
        import fitz
        pdf = fitz.open(file_path)
        texts = []
        figs = 0
        tabs = 0

        for page in pdf:
            blocks = page.get_text("dict").get("blocks", [])
            text_blocks = []
            for block in blocks:
                if block["type"] == 0:
                    bbox = block["bbox"]
                    text = ""
                    for line in block.get("lines", []):
                        text += "".join(s["text"] for s in line.get("spans", [])) + "\n"
                    if text.strip():
                        text_blocks.append({"y": bbox[1], "x": bbox[0], "text": text.strip()})
            text_blocks.sort(key=lambda b: (round(b["y"] / 10) * 10, b["x"]))
            texts.append("\n".join(b["text"] for b in text_blocks))

            images = page.get_images(full=True)
            for img in images:
                if len(img) > 3 and img[2] > 40 and img[3] > 40:
                    figs += 1
            try:
                found_tabs = page.find_tables()
                if found_tabs:
                    tabs += len(found_tabs.tables)
            except Exception:
                pass

        pdf.close()
        full_text = "\n\n".join(texts)
        quality = self._score_text_quality(full_text)
        return full_text, quality, {"page_count": len(texts), "figures_count": figs, "tables_count": tabs}

    # ═══ 策略 3: pdfplumber ═══
    def _try_pdfplumber(self, file_path: str) -> tuple[str, float, dict]:
        """使用 pdfplumber — 对复杂排版和表格有更好的支持"""
        import pdfplumber
        texts = []
        tabs = 0
        figs = 0

        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    texts.append(page_text)

                # pdfplumber 原生表格检测
                try:
                    found = page.find_tables()
                    if found:
                        tabs += len(found)
                except Exception:
                    pass

                # 图片检测
                if hasattr(page, 'images') and page.images:
                    figs += len([i for i in page.images if i.get('width', 0) > 40 and i.get('height', 0) > 40])

        full_text = "\n\n".join(texts)
        quality = self._score_text_quality(full_text)
        return full_text, quality, {"page_count": len(texts), "figures_count": figs, "tables_count": tabs}

    def _score_text_quality(self, text: str) -> float:
        """评分文本质量 0.0-1.0"""
        if not text or len(text) < 100:
            return 0.0

        score = 0.0

        # 长度评分
        length = len(text)
        if length > 50000: score += 0.4
        elif length > 20000: score += 0.3
        elif length > 5000: score += 0.2
        elif length > 1000: score += 0.1

        # 可读字符比例
        alpha = sum(1 for c in text if c.isalpha() or c.isspace())
        digit = sum(1 for c in text if c.isdigit())
        punct = sum(1 for c in text if c in '.,;:!?()-=+/*[]{}<>')
        total = max(len(text), 1)
        readable_ratio = (alpha + digit + punct) / total
        score += readable_ratio * 0.3

        # 英文单词密度（正常英文论文的特征）
        words = [w for w in text.split() if len(w) > 2 and w.isalpha()]
        if len(words) > 5000: score += 0.2
        elif len(words) > 1000: score += 0.1

        # 结构特征（有章节标题 vs 纯乱码）
        import re
        has_sections = bool(re.search(r'(?:Introduction|Abstract|Method|Experiment|Conclusion|Related Work|References)', text, re.IGNORECASE))
        if has_sections: score += 0.1

        return min(score, 1.0)

        return doc

    def _extract_title(self, text: str) -> str:
        """从全文首部提取标题"""
        lines = text.strip().split("\n")
        # 取前几行中最长的非空行作为标题
        candidates = []
        for line in lines[:20]:
            line = line.strip()
            if 10 < len(line) < 300 and not line.startswith(("http", "arXiv", "doi")):
                candidates.append(line)
        if candidates:
            return max(candidates, key=len)
        return ""

    def _extract_authors(self, text: str) -> list[str]:
        """提取作者列表"""
        # 常见作者行模式
        author_patterns = [
            r"(?:Authors?|By)\s*[:：]?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+(?:\s*,\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+))*)",
        ]
        for pat in author_patterns:
            match = re.search(pat, text[:2000])
            if match:
                return [a.strip() for a in match.group(1).split(",") if a.strip()]
        return []

    def _extract_abstract(self, text: str) -> str:
        """提取摘要 — 使用固定宽度模式避免 re 报错"""
        import re
        search_text = text[:8000]

        # 方法1: 匹配 "Abstract" 之后到下一个章节标题之前的内容
        m = re.search(r'Abstract\s*[：:\-]\s*\n?\s*(.+?)(?=\n\s*(?:\d+\.?\s+)?[A-Z][a-z]+\b|\n\s*Keywords|\n\s*Index Terms)', search_text, re.IGNORECASE | re.DOTALL)
        if m:
            abstract = m.group(1).strip()
            if 50 < len(abstract) < 4000:
                return abstract

        # 方法2: 匹配 ABSTRACT 大写形式
        m = re.search(r'ABSTRACT\s*\n\s*(.+?)(?=\n\s*(?:\d+\.?\s+)?[A-Z]{3,})', search_text, re.DOTALL)
        if m:
            abstract = m.group(1).strip()
            if 50 < len(abstract) < 4000:
                return abstract

        # 方法3: 宽松匹配 — "abstract" 之后的一段文字
        m = re.search(r'abstract\s*\n(.*?)(?:\n\s*\n)', search_text, re.IGNORECASE | re.DOTALL)
        if m:
            abstract = m.group(1).strip().replace('\n', ' ')
            if 50 < len(abstract) < 4000:
                return abstract

        return ""

    def _split_sections(self, text: str) -> list[PDFSection]:
        """将全文按章节拆分"""
        sections = []
        # 匹配章节标题模式
        section_pat = re.compile(
            r"(?:^|\n)((?:\d+\.?\s*)+[A-Z][^\n]+)|"
            r"(?:^|\n)((?:[IVX]+\.?\s*)+[A-Z][^\n]+)",
            re.MULTILINE,
        )

        matches = list(section_pat.finditer(text))
        if not matches:
            # 没有找到章节标题，返回单一段
            sections.append(PDFSection(
                title="全文", level=0, content=text,
                start_page=0, end_page=0,
            ))
            return sections

        for i, match in enumerate(matches):
            title = (match.group(1) or match.group(2)).strip()
            level = title.count(".") if "." in title else 0
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[start:end].strip()

            sections.append(PDFSection(
                title=title,
                level=level,
                content=content,
                start_page=0,
                end_page=0,
            ))

        return sections

    def _calibrate_figure_table_counts(self, doc: PDFDocument):
        """用文本特征修正图表计数"""
        import re

        # 从文本中检测 Figure/Table 引用
        fig_refs = len(re.findall(r'(?:Fig(?:ure)?\.?\s*\d+|图\s*\d+)', doc.full_text, re.IGNORECASE))
        tab_refs = len(re.findall(r'(?:Table\.?\s*\d+|表\s*\d+)', doc.full_text, re.IGNORECASE))

        # 用引用计数校准: 取文本引用数和图像检测数的中位数
        if fig_refs > 0:
            # 文本中 Figure X 的引用去重
            fig_numbers = set()
            for m in re.finditer(r'(?:Fig(?:ure)?\.?\s*)(\d+)', doc.full_text, re.IGNORECASE):
                fig_numbers.add(int(m.group(1)))
            doc.figures_count = max(len(fig_numbers), 1) if fig_numbers else max(doc.figures_count, 1)

        if tab_refs > 0:
            tab_numbers = set()
            for m in re.finditer(r'(?:Table\.?\s*)(\d+)', doc.full_text, re.IGNORECASE):
                tab_numbers.add(int(m.group(1)))
            doc.tables_count = max(len(tab_numbers), 1) if tab_numbers else max(doc.tables_count, 1)

    def _extract_references(self, text: str) -> list[str]:
        """提取参考文献"""
        ref_pat = re.compile(
            r"(?:^|\n)\s*\[(\d+)\]\s*(.+?)(?=\n\s*\[\d+\]\s*|\n\s*$)",
            re.MULTILINE,
        )
        refs = []
        ref_section = self._find_reference_section(text)
        if ref_section:
            for match in ref_pat.finditer(ref_section):
                refs.append(f"[{match.group(1)}] {match.group(2).strip()}")
        return refs

    def _find_reference_section(self, text: str) -> str:
        """定位参考文献部分"""
        search_text = text[-20000:]
        # 使用非 look-behind 的方式定位
        for marker in [r'References?\s*\n', r'REFERENCES\s*\n', r'Bibliography\s*\n']:
            m = re.search(marker, search_text, re.IGNORECASE)
            if m:
                start = m.end()
                return search_text[start:].strip()
        return ""


def parse_pdf(file_path: str) -> PDFDocument:
    parser = PDFParser()
    return parser.parse(file_path)


def parse_pdfs(file_paths: list[str]) -> list[PDFDocument]:
    parser = PDFParser()
    return [parser.parse(fp) for fp in file_paths]
