"""RAG 检索增强生成 — 支持单论文解读和多论文综述"""

import json
import hashlib
import os
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from backend.core.config import get_config
from backend.core.llm_client import get_llm_client
from .pdf_parser import PDFDocument, PDFSection, parse_pdfs


@dataclass
class PaperInsight:
    """单篇论文的深度解读结果 — 多轮 LLM 分析后的结构化报告"""
    title: str
    authors: list[str] = field(default_factory=list)
    venue: str = ""
    year: str = ""

    # 1. 概览
    research_field: str = ""
    sub_field: str = ""
    one_sentence_summary: str = ""

    # 2. 动机与背景
    problem_statement: str = ""
    existing_shortcomings: str = ""
    core_insight: str = ""

    # 3. 方法论
    problem_formulation: str = ""       # 数学问题定义
    model_architecture: str = ""        # 模型架构详解
    algorithm_flow: str = ""            # 算法流程（伪代码描述）
    key_innovations: list[str] = field(default_factory=list)  # 技术创新点
    key_formulas: list[dict] = field(default_factory=list)    # [{"name":"", "formula":"", "meaning":""}]

    # 4. 实验
    datasets_used: list[str] = field(default_factory=list)
    evaluation_metrics: list[str] = field(default_factory=list)
    main_results: str = ""              # 主实验结果解读
    ablation_analysis: str = ""         # 消融实验分析
    baseline_comparison: str = ""       # 与 baseline 对比
    efficiency_analysis: str = ""       # 效率分析

    # 5. 评价
    methodology_strengths: list[str] = field(default_factory=list)
    methodology_weaknesses: list[str] = field(default_factory=list)
    experimental_rigor: str = ""        # 实验说服力评估
    reproducibility_assessment: str = ""  # 可复现性评估
    potential_extensions: list[str] = field(default_factory=list)

    # 6. 定位
    relationship_to_prior_work: str = ""  # 与已有工作的关系
    impact_assessment: str = ""           # 潜在影响力评估
    innovation_level: str = ""
    pdf_text_length: int = 0  # PDF 提取的原始文本长度
    pdf_parse_quality: str = ""  # PDF 解析质量: good/acceptable/poor/empty

    @property
    def quality_score(self) -> float:
        """计算解读完成度评分 (0.0-1.0)"""
        fields = [
            self.research_field, self.sub_field, self.one_sentence_summary,
            self.problem_statement, self.core_insight,
            self.problem_formulation, self.model_architecture, self.algorithm_flow,
            self.main_results, self.ablation_analysis, self.baseline_comparison,
            self.experimental_rigor, self.reproducibility_assessment,
        ]
        scored = 0
        for f in fields:
            if f and len(f) > 20 and f != "未提取" and "未明确" not in f[:10] and "文中未" not in f[:10]:
                scored += 1
        return round(scored / len(fields), 2)

    @property
    def status(self) -> str:
        """解读状态: success / partial / failed"""
        s = self.quality_score
        if s >= 0.5:
            return "success"
        elif s >= 0.2:
            return "partial"
        return "failed"


@dataclass
class ReviewResult:
    """多论文综述结果"""
    papers: list[PaperInsight] = field(default_factory=list)
    clusters: dict[str, list[str]] = field(default_factory=dict)  # 分类 -> 论文标题列表
    comparative_table: str = ""  # Markdown 对比表
    narrative_synthesis: str = ""  # 线索梳理综述
    relationship_graph: dict = field(default_factory=dict)  # 论文关系图谱
    experimental_comparison: str = ""  # 实验数据对比
    paper_status: list[dict] = field(default_factory=list)  # 每篇的状态
    status_summary: str = ""  # 全局状态摘要


class SimpleVectorStore:
    """简易向量存储（基于 TF-IDF + 余弦相似度，无外部依赖）"""

    def __init__(self):
        self.documents: list[dict] = []
        self.vocabulary: dict[str, int] = {}
        self.tfidf_matrix: list[list[float]] = []

    def add_document(self, doc_id: str, text: str, metadata: dict = None):
        self.documents.append({"id": doc_id, "text": text, "metadata": metadata or {}})

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """基于 TF-IDF 的简单检索"""
        from collections import Counter
        import math

        # 分词
        def tokenize(s: str) -> list[str]:
            s = s.lower()
            # 简单中英文分词
            tokens = []
            for word in s.split():
                word = word.strip(",.!?;:()[]{}'\"")
                if len(word) > 1:
                    tokens.append(word)
            return tokens

        # 计算 query TF-IDF
        query_tokens = tokenize(query)
        query_tf = Counter(query_tokens)

        # 对每个文档计算余弦相似度
        scores = []
        for doc in self.documents:
            doc_tokens = tokenize(doc["text"])
            doc_tf = Counter(doc_tokens)

            # 计算余弦相似度
            common = set(query_tf.keys()) & set(doc_tf.keys())
            if not common:
                scores.append((0.0, doc))
                continue

            dot = sum(query_tf[t] * doc_tf[t] for t in common)
            q_norm = math.sqrt(sum(v ** 2 for v in query_tf.values()))
            d_norm = math.sqrt(sum(v ** 2 for v in doc_tf.values()))
            sim = dot / (q_norm * d_norm + 1e-8) if q_norm and d_norm else 0.0
            scores.append((sim, doc))

        scores.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scores[:top_k]]


class DocumentAnalysisEngine:
    """文档理解引擎 — 功能 1 和 2 的核心"""

    def __init__(self):
        self.llm = get_llm_client()
        self.cfg = get_config()
        self.vector_store = SimpleVectorStore()

    # ========== 功能 1：单论文深度解读 ==========

    def analyze_single_paper(self, file_path: str, force: bool = False) -> dict:
        """输入 PDF，输出全面深度解读"""
        docs = parse_pdfs([file_path])
        if not docs:
            return {"error": "PDF 解析失败"}
        doc = docs[0]

        insight = self._deep_read_paper(doc, force=force)

        return {
            "title": insight.title,
            "authors": insight.authors,
            "venue": insight.venue,
            "year": insight.year,

            # 概览
            "research_field": insight.research_field,
            "sub_field": insight.sub_field,
            "one_sentence_summary": insight.one_sentence_summary,

            # 动机与背景
            "problem_statement": insight.problem_statement,
            "existing_shortcomings": insight.existing_shortcomings,
            "core_insight": insight.core_insight,

            # 方法论
            "problem_formulation": insight.problem_formulation,
            "model_architecture": insight.model_architecture,
            "algorithm_flow": insight.algorithm_flow,
            "key_innovations": insight.key_innovations,
            "key_formulas": insight.key_formulas,

            # 实验
            "datasets_used": insight.datasets_used,
            "evaluation_metrics": insight.evaluation_metrics,
            "main_results": insight.main_results,
            "ablation_analysis": insight.ablation_analysis,
            "baseline_comparison": insight.baseline_comparison,
            "efficiency_analysis": insight.efficiency_analysis,

            # 评价
            "methodology_strengths": insight.methodology_strengths,
            "methodology_weaknesses": insight.methodology_weaknesses,
            "experimental_rigor": insight.experimental_rigor,
            "reproducibility_assessment": insight.reproducibility_assessment,
            "potential_extensions": insight.potential_extensions,
            "relationship_to_prior_work": insight.relationship_to_prior_work,
            "impact_assessment": insight.impact_assessment,
            "innovation_level": insight.innovation_level,

            # 元信息
            "abstract": doc.abstract,
            "sections_overview": [
                {"title": s.title, "length": len(s.content)}
                for s in doc.sections[:20]
            ],
            "page_count": doc.page_count,
            "figures_count": doc.figures_count,
            "tables_count": doc.tables_count,
        }

    def _index_document(self, doc: PDFDocument):
        """将文档索引到向量存储"""
        for i, section in enumerate(doc.sections):
            self.vector_store.add_document(
                doc_id=f"{doc.file_hash}:{i}",
                text=section.content[:2000],
                metadata={"section_title": section.title, "level": section.level},
            )

    def _deep_read_paper(self, doc: PDFDocument, force: bool = False) -> PaperInsight:
        """单轮 LLM 深度解读 — 全文一次性发送，避免分段丢失信息"""
        text = doc.full_text
        title = doc.title
        authors_str = ", ".join(doc.authors) if doc.authors else "未知"

        insight = PaperInsight(title=title, authors=doc.authors)
        insight.pdf_text_length = len(text)

        # 文本质量预检
        if len(text) < 100:
            insight.pdf_parse_quality = "empty"
            insight.one_sentence_summary = f"PDF 解析失败：提取到的文本仅 {len(text)} 字符。可能原因：扫描版 PDF（纯图片）、加密文件、或损坏。"
            if not force:
                return insight
        elif len(text) < 500:
            insight.pdf_parse_quality = "poor"
        else:
            alpha_chars = sum(1 for c in text if c.isalpha() or c.isspace() or c in '.,;:!?()-=+/*[]{}<>')
            alpha_ratio = alpha_chars / max(len(text), 1)
            if alpha_ratio < 0.5:
                insight.pdf_parse_quality = "poor"
            elif alpha_ratio < 0.8:
                insight.pdf_parse_quality = "acceptable"
            else:
                insight.pdf_parse_quality = "good"

        # 如果质量差但未强制，跳过 LLM 调用
        if insight.pdf_parse_quality in ("poor", "empty") and not force:
            insight.one_sentence_summary = f"PDF 文本质量差（{len(text)}字，可读率{alpha_chars/max(len(text),1)*100:.0f}%），未发送给 LLM。勾选「强制读取」可忽略质量检查。"
            return insight

        # 取前 15000 字覆盖核心（引言+方法+前半实验），平衡速度与质量
        paper_text = text[:15000]

        # 构建单次综合分析 prompt
        analysis_prompt = """请对以下学术论文进行全面的深度解读。仔细阅读全文，提取所有关键技术细节。

论文标题: {title}
作者: {authors}
摘要: {abstract}

===== 论文全文 =====
{full_text}

===== 分析要求 =====
请返回一个完整的 JSON，包含以下所有部分。每个字段都要具体、有技术细节。如果文中确实没有某项信息，写"文中未明确给出"。公式使用 Unicode 符号，不要 LaTeX 代码。对比数据尽量用 Markdown 表格。

{{
  "overview": {{
    "research_field": "研究大方向（如 NLP/CV/Speech/RL 等）",
    "sub_field": "子方向",
    "one_sentence": "一句话核心思想"
  }},
  "motivation": {{
    "problem": "论文要解决的具体问题（100-200字）",
    "shortcomings": "现有方法有哪些不足（列举3-5个）",
    "insight": "本文核心洞察/突破口（100-200字）"
  }},
  "method": {{
    "formulation": "问题数学化定义：输入、输出、优化目标（100-200字）",
    "architecture": "模型架构详细描述。逐组件：名称、输入输出形状、操作、连接方式。Transformer需写层数/头数/维度。CNN需写卷积核/通道/步长。用表格呈现（300-600字）",
    "algorithm": "核心算法流程。训练/推理分别描述。如论文有伪代码则翻译为中文步骤（150-350字）",
    "innovations": ["创新1及技术细节", "创新2", "创新3"],
    "formulas": [{{"name": "公式名", "formula_text": "公式文字描述(Unicode)", "meaning": "符号含义和作用"}}],
    "components": ["组件1: 功能和设计动机", "组件2: ..."]
  }},
  "experiment": {{
    "datasets": ["数据集名: 用途+规模", ...],
    "metrics": ["指标名: 含义", ...],
    "main_results": "主实验结果解读。用Markdown表格呈现（列=方法，行=数据集），然后文字分析（300-500字）",
    "ablation": "消融实验分析。表格+文字（200-400字）",
    "baseline_comparison": "与baseline对比分析。表格+文字（200-350字）",
    "efficiency": "效率分析。表格列出参数量/FLOPs等（100-250字）"
  }},
  "evaluation": {{
    "strengths": ["方法论优势1及论据", "优势2", "优势3"],
    "weaknesses": ["方法论局限1及论据", "局限2", "局限3"],
    "experimental_rigor": "实验说服力评估（150-250字）",
    "reproducibility": "可复现性评估（100-200字）",
    "extensions": ["后续方向1", "方向2", "方向3"],
    "relation_to_prior": "与已有工作关系（100-200字）",
    "impact": "影响力评估（80-150字）",
    "innovation_level": "high/medium-high/medium/incremental"
  }}
}}

注意: 绝对不要编造数据。所有数字必须来自原文。不确定的写"文中未明确给出"。
所有字段和分析必须使用中文撰写。"""

        prompt = analysis_prompt.format(
            title=title,
            authors=authors_str,
            abstract=doc.abstract or "未提取",
            full_text=paper_text,
        )

        try:
            result = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=8192,
                temperature=0.0,
                json_mode=True,
            )
            # 提取 JSON
            text_out = result.strip()
            if "```json" in text_out:
                text_out = text_out.split("```json")[1].split("```")[0].strip()
            elif "```" in text_out:
                text_out = text_out.split("```")[1].split("```")[0].strip()
            data = json.loads(text_out)
        except Exception as e:
            from backend.core.error_logger import log_error
            log_error("rag._deep_read_paper", e, f"title={doc.title}")
            return insight

        # 填充 insight
        ov = data.get("overview", {}) or {}
        insight.research_field = ov.get("research_field", "")
        insight.sub_field = ov.get("sub_field", "")
        insight.one_sentence_summary = ov.get("one_sentence", "")

        mot = data.get("motivation", {}) or {}
        insight.problem_statement = mot.get("problem", "")
        insight.existing_shortcomings = mot.get("shortcomings", "")
        insight.core_insight = mot.get("insight", "")

        mtd = data.get("method", {}) or {}
        insight.problem_formulation = mtd.get("formulation", "")
        insight.model_architecture = mtd.get("architecture", "")
        insight.algorithm_flow = mtd.get("algorithm", "")
        insight.key_innovations = mtd.get("innovations", [])
        insight.key_formulas = mtd.get("formulas", [])

        exp = data.get("experiment", {}) or {}
        insight.datasets_used = exp.get("datasets", [])
        insight.evaluation_metrics = exp.get("metrics", [])
        insight.main_results = exp.get("main_results", "")
        insight.ablation_analysis = exp.get("ablation", "")
        insight.baseline_comparison = exp.get("baseline_comparison", "")
        insight.efficiency_analysis = exp.get("efficiency", "")

        eva = data.get("evaluation", {}) or {}
        insight.methodology_strengths = eva.get("strengths", [])
        insight.methodology_weaknesses = eva.get("weaknesses", [])
        insight.experimental_rigor = eva.get("experimental_rigor", "")
        insight.reproducibility_assessment = eva.get("reproducibility", "")
        insight.potential_extensions = eva.get("extensions", [])
        insight.relationship_to_prior_work = eva.get("relation_to_prior", "")
        insight.impact_assessment = eva.get("impact", "")
        insight.innovation_level = eva.get("innovation_level", "")

        return insight

    def _llm_pass(
        self, system_prompt: str, user_prompt: str, schema: dict, context: str
    ) -> dict:
        """执行一轮 LLM 分析"""
        try:
            return self.llm.structured_output(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                output_schema=schema,
            )
        except Exception as e:
            from backend.core.error_logger import log_error
            log_error("rag._llm_pass", e, f"system_prompt={system_prompt[:80]}")
            return {}

    def _extract_section(self, text: str, keywords: list[str]) -> str:
        """从全文中提取包含特定关键词的章节"""
        text_lower = text.lower()
        best_start = 0
        best_score = 0
        window_size = min(5000, len(text))
        step = max(100, len(text) // 20)

        for i in range(0, max(1, len(text) - window_size), step):
            window = text_lower[i:i + window_size]
            score = sum(window.count(kw.lower()) for kw in keywords)
            if score > best_score:
                best_score = score
                best_start = i

        if best_score > 0:
            return text[best_start:best_start + window_size]
        # Fallback: return middle portion of text (usually has the method)
        return text[len(text)//4: len(text)*3//4] if len(text) > 2000 else text

    # ========== 功能 2：多论文综述 ==========

    def analyze_multiple_papers(self, file_paths: list[str], force: bool = False) -> ReviewResult:
        """多论文综述：先逐篇单论文解读，再一篇 LLM 模块对模块综述"""
        # Step 1: 并行逐篇解读（提速 N 倍）
        from concurrent.futures import ThreadPoolExecutor, as_completed
        paper_results = []
        paper_status = []

        def _analyze_one(fp):
            try:
                return self.analyze_single_paper(fp, force=force)
            except Exception as e:
                from backend.core.error_logger import log_error
                log_error("rag.review", e, f"file={fp}")
                return {"title": os.path.basename(fp), "error": str(e)}

        with ThreadPoolExecutor(max_workers=min(len(file_paths), 4)) as executor:
            futures = {executor.submit(_analyze_one, fp): i for i, fp in enumerate(file_paths)}
            results_map = {}
            for future in as_completed(futures):
                idx = futures[future]
                results_map[idx] = future.result()

        for i in range(len(file_paths)):
            result = results_map.get(i, {"title": os.path.basename(file_paths[i]), "error": "未知错误"})
            paper_results.append(result)
            if "error" in result:
                paper_status.append({
                    "index": i + 1, "title": result.get("title", os.path.basename(file_paths[i])),
                    "filename": os.path.basename(file_paths[i]),
                    "status": "failed", "quality_score": 0.0,
                    "summary": f"❌ **[failed]** {result.get('title','')} — 异常: {str(result.get('error',''))[:100]}",
                })
            else:
                qs = self._calc_quality_from_dict(result)
                sicon = {"success": "✅", "partial": "⚠️", "failed": "❌"}.get(qs["status"], "❓")
                paper_status.append({
                    "index": i + 1,
                    "title": result.get("title", f"论文{i+1}"),
                    "filename": os.path.basename(file_paths[i]),
                    "status": qs["status"],
                    "quality_score": qs["score"],
                    "summary": f"{sicon} **[{qs['status']}]** {result.get('title', f'论文{i+1}')} — "
                               f"完成度: {qs['score']*100:.0f}% | "
                               f"领域: {result.get('research_field', '未知')} | "
                               f"核心: {result.get('one_sentence_summary', '未提取')[:80]}",
                })

        success_count = sum(1 for p in paper_status if p["status"] == "success")
        partial_count = sum(1 for p in paper_status if p["status"] == "partial")
        failed_count = sum(1 for p in paper_status if p["status"] == "failed")
        status_summary = f"### 论文分析状态\n\n| 状态 | 数量 |\n|------|------|\n| ✅ 完整分析 | {success_count} |\n| ⚠️ 部分完成 | {partial_count} |\n| ❌ 分析失败 | {failed_count} |\n\n"
        for ps in paper_status:
            status_summary += f"- {ps['summary']}\n"

        valid_results = [r for r in paper_results if isinstance(r, dict) and "error" not in r]

        # ═══ 研究方向对比检查（智能相似度） ═══
        direction_comparison = ""
        direction_warning = ""
        if len(valid_results) >= 2:
            fields = []
            for r in valid_results:
                rf = r.get("research_field", "未知")
                sf = r.get("sub_field", "")
                fields.append({"title": r.get("title","")[:50], "field": rf, "sub": sf})

            direction_comparison = "\n### 🔬 研究方向对比\n\n"
            direction_comparison += "| 论文 | 研究领域 | 子方向 |\n|------|---------|--------|\n"
            for f in fields:
                direction_comparison += "| {} | {} | {} |\n".format(f["title"][:30], f["field"], f["sub"][:40])

            # LLM 智能方向相似度判断（处理中英文混合、缩略词等）
            if len(fields) >= 2:
                llm = get_llm_client()
                dir_text = "\n".join("- {} | {} | {}".format(f["title"][:40], f["field"], f["sub"]) for f in fields)
                judge_prompt = """判断以下论文的研究方向是否一致，给出相似度评分(0-100)和判定理由。

论文:
{dirs}

返回 JSON:
{{"similarity": 85, "verdict": "consistent", "reason": "两篇论文都属于计算机视觉中的面部表情识别方向，方法不同但研究问题高度相关"}}

评分标准:
- 90-100: 完全一致（同领域+同子方向+同任务）
- 70-89: 高度相关（同领域+相关子方向，可以深度对比）
- 40-69: 部分相关（同大领域不同子方向）
- 0-39: 基本无关（不同领域）
verdict: "consistent"(>=70) / "partial"(40-69) / "divergent"(<40)""".format(dirs=dir_text)
                try:
                    resp = llm.structured_output(
                        system_prompt="你是科研方向判断专家。",
                        user_prompt=judge_prompt,
                        output_schema={"similarity": 0, "verdict": "str", "reason": "str"},
                    )
                    llm_sim = resp.get("similarity", 0)
                    llm_reason = resp.get("reason", "")
                    verdict = resp.get("verdict", "partial")
                except Exception:
                    llm_sim = 50
                    llm_reason = "LLM判断失败，使用默认评分"
                    verdict = "partial"

                direction_comparison += "\n**方向相似度**: {}% | 判定: {}\n".format(llm_sim, llm_reason[:200])

                if verdict == "consistent":
                    direction_comparison += "\n✅ 论文方向高度一致，适合进行深度模块对模块对比综述。\n"
                elif verdict == "partial":
                    direction_comparison += "\n📝 论文方向有一定关联，可以进行对比分析，但部分模块可能无法直接对齐。\n"
                else:
                    direction_warning = "\n⚠️ **研究方向差异较大**（{}%），建议选择同领域的论文。当前仍会继续分析。\n".format(llm_sim)

        status_summary += direction_comparison + direction_warning

        if len(valid_results) < 2:
            return ReviewResult(
                papers=[], clusters={}, comparative_table="",
                narrative_synthesis=f"仅 {len(valid_results)} 篇分析成功，无法对比综述。",
                relationship_graph={}, experimental_comparison="",
                paper_status=paper_status, status_summary=status_summary,
            )

        synthesis = self._one_shot_review(valid_results)
        return ReviewResult(
            papers=[], clusters=synthesis.get("clusters", {}),
            comparative_table=synthesis.get("comparative_table", ""),
            narrative_synthesis=synthesis.get("narrative", ""),
            relationship_graph=synthesis.get("relationship_graph", {}),
            experimental_comparison=synthesis.get("experimental_comparison", ""),
            paper_status=paper_status, status_summary=status_summary,
        )

    def _calc_quality_from_dict(self, result: dict) -> dict:
        """从单论文解读 dict 计算完成度"""
        key_fields = ["research_field","sub_field","one_sentence_summary","problem_statement","core_insight",
                      "problem_formulation","model_architecture","algorithm_flow","main_results",
                      "ablation_analysis","baseline_comparison","experimental_rigor"]
        scored = sum(1 for k in key_fields if isinstance(result.get(k,""),str) and len(result.get(k,""))>20
                     and "未提取" not in str(result.get(k,""))[:10] and "未明确" not in str(result.get(k,""))[:10])
        score = round(scored/len(key_fields),2)
        status = "success" if score>=0.5 else ("partial" if score>=0.2 else "failed")
        return {"score":score,"status":status}

    def _one_shot_review(self, paper_results: list[dict]) -> dict:
        modules = []
        for i, r in enumerate(paper_results):
            title = r.get("title", "P{}".format(i+1))
            short = (title.split(":")[0].split(".")[0].strip() or title)[:30]
            # 取各字段，增大截断限制以保留更多细节
            s = lambda key, n: (str(r.get(key, "")) or "")[:n]
            j = lambda key, n: json.dumps(r.get(key, []) or [], ensure_ascii=False)[:n]
            modules.append("""
=== 论文 {i}: {title}（简称: {short}）===

【基本信息】领域: {rf} / {sub} | 创新等级: {level} | 核心: {oss}

【研究动机】
- 问题定义: {ps}
- 现有不足: {sc}
- 核心洞察: {ci}

【方法论深度】
- 问题形式化: {pf}
- 模型架构: {ma}
- 算法流程: {af}
- 关键创新点: {ki}
- 核心公式: {kf}

【实验分析】
- 数据集: {ds}
- 评估指标: {em}
- 主实验结果: {mr}
- 消融分析: {aa}
- Baseline对比: {bc}
- 效率分析: {ea}

【评价】
- 方法论优势: {ms}
- 方法论局限: {mw}
- 实验说服力: {er}
- 可复现性: {ra}
- 与已有工作关系: {rp}
- 影响力评估: {ia}
- 后续方向: {ext}
""".format(
                i=i+1, title=title, short=short,
                rf=s("research_field",100), sub=s("sub_field",100), level=s("innovation_level",20), oss=s("one_sentence_summary",150),
                ps=s("problem_statement",400), sc=s("existing_shortcomings",400), ci=s("core_insight",400),
                pf=s("problem_formulation",300), ma=s("model_architecture",800), af=s("algorithm_flow",400),
                ki=j("key_innovations",500), kf=j("key_formulas",400),
                ds=j("datasets_used",300), em=j("evaluation_metrics",200), mr=s("main_results",600),
                aa=s("ablation_analysis",500), bc=s("baseline_comparison",400), ea=s("efficiency_analysis",300),
                ms=j("methodology_strengths",300), mw=j("methodology_weaknesses",300),
                er=s("experimental_rigor",300), ra=s("reproducibility_assessment",200),
                rp=s("relationship_to_prior_work",300), ia=s("impact_assessment",200),
                ext=j("potential_extensions",300),
            ))

        prompt = """你是一位资深学术综述撰写专家，正在为顶级期刊撰写一篇深度综述。以下{n}篇论文已按模块结构化整理，请进行极其详尽、专业的对比分析。

===== 论文详细分析数据 =====
{papers}

===== 撰写要求 =====
请撰写一份深度学术综述。要求：

1. **研究现状概述**（400-600字）
   - 该领域的发展脉络和研究热点
   - 各论文在该领域中的定位
   - 当前研究的主要挑战

2. **方法论深度对比**（1000-1500字，模块对模块）
   - 问题定义的对比：各论文如何定义研究问题？数学形式化有何异同？
   - 模型架构的对比：逐组件分析各模型的架构设计、数据流、关键操作
   - 算法流程的对比：训练/推理流程的异同
   - 创新点的对比：各论文的创新点分别在哪里？哪个最具突破性？
   - 核心公式/机制的对比：各论文的关键数学机制是什么？

3. **实验全面对比**（800-1200字）
   - 数据集与评估协议对比（表格呈现）
   - 性能对比分析：各方法在哪些指标上领先/落后？差值具体是多少？
   - 消融实验对比：各论文消融了什么组件？哪个组件贡献最大？
   - 效率对比：参数量/FLOPs/推理时间的横向比较
   - 实验设计质量评估

4. **深度评价**（600-800字）
   - 各方法的优势与局限
   - 实验说服力评估
   - 可复现性评估
   - 创新性评级及理由

5. **未来研究方向**（300-500字）
   - 基于各论文的局限性，提出有建设性的未来方向
   - 哪些思路可以融合？
   - 还有哪些开放问题？

返回 JSON（各字段务必详尽，不要简短敷衍）:
{{"clusters": {{"分类名": ["简称1","简称2"]}},
  "comparative_table": "详细的 Markdown 对比表。至少包含8行：研究问题/核心方法/模型架构(详述)/关键创新/主要数据集/核心指标(含数字)/方法论优势/主要局限。每列=一篇论文。",
  "narrative": "完整综述正文（中文，3000-5000字）。严格按上述5个部分展开，每部分都要详尽，包含具体技术细节和数据引用。",
  "relationship_graph": {{"nodes":[{{"id":"简称","title":"完整标题"}}],"edges":[{{"source":"A","target":"B","relation":"improves/based_on/compares_with"}}]}},
  "experimental_comparison": "实验数据深度对比（Markdown，600-1200字）。包含：1.数据集/指标对比表 2.性能数字逐项对比 3.消融对比分析 4.效率对比 5.实验设计优劣评述 6.结论可信度评估"
}}
缺信息处如实标注"该论文未提供此信息"，不要编造任何数据。""".format(n=len(paper_results), papers="\n\n".join(modules))

        try:
            result = self.llm.chat(messages=[{"role":"user","content":prompt}], max_tokens=12000, temperature=0.0, json_mode=True)
            text_out = result.strip()
            if "```json" in text_out: text_out = text_out.split("```json")[1].split("```")[0].strip()
            elif "```" in text_out: text_out = text_out.split("```")[1].split("```")[0].strip()
            data = json.loads(text_out)
            return {"clusters":data.get("clusters",{}),"comparative_table":data.get("comparative_table",""),"narrative":data.get("narrative",""),"relationship_graph":data.get("relationship_graph",{}),"experimental_comparison":data.get("experimental_comparison","")}
        except Exception as e:
            from backend.core.error_logger import log_error
            log_error("rag._one_shot_review", e)
            return {"clusters":{},"comparative_table":f"综述失败:{e}","narrative":"","relationship_graph":{},"experimental_comparison":""}

    def _cluster_papers_old(self, insights: list[PaperInsight]) -> dict[str, list[str]]:
        """DEPRECATED — 已被 _one_shot_review 替代"""
        return {}
        papers_text = []
        for i, ins in enumerate(insights):
            papers_text.append(
                f"[论文 {i}] {ins.title}\n"
                f"  领域: {ins.research_field}\n"
                f"  架构: {ins.model_architecture[:200] if ins.model_architecture else ins.one_sentence_summary[:200]}\n"
                f"  创新: {str(ins.key_innovations[:3])[:200] if ins.key_innovations else ins.one_sentence_summary[:200]}"
            )

        prompt = f"""请将以下论文按研究方向进行分类。返回 JSON：
{{
    "clusters": {{
        "类别名1": [0, 2, 5],
        "类别名2": [1, 3]
    }}
}}

论文列表:
{chr(10).join(papers_text)}"""

        try:
            resp = self.llm.structured_output(
                system_prompt="你是科研论文分类专家。请根据论文的研究领域和方法论进行分类。",
                user_prompt=prompt,
                output_schema={"clusters": {"str": [0]}},
            )
            # 将索引映射回论文标题
            result = {}
            for cluster_name, indices in resp.get("clusters", {}).items():
                result[cluster_name] = [
                    insights[i].title if 0 <= i < len(insights) else f"Paper_{i}"
                    for i in indices
                ]
            return result
        except Exception as e:
            from backend.core.error_logger import log_error
            log_error("rag._cluster_papers", e)
            return {"未分类": [ins.title for ins in insights]}

    def _generate_comparative_table(self, insights: list[PaperInsight]) -> str:
        """生成模型思路框架对比表"""
        papers_text = "\n".join(
            f"### {ins.title}\n架构: {ins.model_architecture[:300] if ins.model_architecture else '未提取'}\n"
            f"创新: {str(ins.key_innovations[:3])[:300] if ins.key_innovations else '未提取'}\n"
            f"实验: {ins.main_results[:300] if ins.main_results else '未提取'}"
            for ins in insights
        )
        prompt = f"""请根据以下论文，生成 Markdown 对比表格。横轴为论文（简称），纵轴为：
- 研究方法
- 核心模块
- 数据集
- 主要指标
- 创新点
- 局限性

论文信息:
{papers_text}

输出完整 Markdown 表格，每个论文用简称。"""

        try:
            return self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4096,
            )
        except Exception as e:
            return f"对比表生成失败: {e}"

    def _generate_narrative_synthesis(
        self, insights: list[PaperInsight], clusters: dict[str, list[str]]
    ) -> str:
        """生成线索梳理综述"""
        cluster_text = json.dumps(clusters, ensure_ascii=False, indent=2)
        papers_summary = "\n".join(
            f"- **{ins.title}**: {ins.one_sentence_summary[:200]} | 创新: {str(ins.key_innovations[:2])[:150] if ins.key_innovations else '未提取'}"
            for ins in insights
        )

        prompt = f"""请撰写一份学术综述，梳理以下论文之间的线索和演进关系。

## 论文分类
{cluster_text}

## 各论文贡献总结
{papers_summary}

请撰写一篇完整的综述，包括：
1. **研究现状概述**：该领域的整体情况
2. **分类梳理**：各类方法的演进脉络
3. **对比分析**：各方法的优劣
4. **未来方向**：潜在的研究机会

输出 Markdown 格式，中文撰写。"""

        try:
            return self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=8192,
            )
        except Exception as e:
            return f"综述生成失败: {e}"

    def _build_relationship_graph(
        self, docs: list[PDFDocument], insights: list[PaperInsight]
    ) -> dict:
        """构建论文关系图谱"""
        papers_text = []
        for i, (doc, ins) in enumerate(zip(docs, insights)):
            ref_titles = []
            for ref in doc.references[:10]:
                # 提取参考文献中的论文标题
                ref_clean = ref.strip()
                if len(ref_clean) > 20:
                    ref_titles.append(ref_clean[:200])
            papers_text.append(
                f"[论文 {i}] {doc.title}\n"
                f"  方法: {ins.model_architecture[:200] if ins.model_architecture else '未提取'}\n"
                f"  参考文献: {json.dumps(ref_titles, ensure_ascii=False)}"
            )

        prompt = f"""请分析以下论文之间的引用关系和思路演进（如 A 是 B 的改进，C 借鉴了 A）。
返回 JSON 关系图：
{{
    "nodes": [{{"id": "论文简称", "title": "完整标题"}}],
    "edges": [{{"source": "来源论文", "target": "目标论文", "relation": "improves/based_on/compares_with/cites"}}]
}}

{chr(10).join(papers_text)}"""

        try:
            return self.llm.structured_output(
                system_prompt="你是科研文献分析专家，擅长识别论文间的引用关系和学术演进。",
                user_prompt=prompt,
                output_schema={
                    "nodes": [{"id": "str", "title": "str"}],
                    "edges": [{"source": "str", "target": "str", "relation": "str"}],
                },
            )
        except Exception as e:
            return {"error": str(e), "nodes": [], "edges": []}

    def _compare_experiments(self, insights: list[PaperInsight]) -> str:
        """对比各论文的实验数据"""
        papers_text = "\n".join(
            f"### {ins.title}\n{ins.main_results[:500] if ins.main_results else '未提取'}"
            for ins in insights
        )
        prompt = f"""请对比以下论文的实验设计和结果。

{papers_text}

请用 Markdown 格式输出：
1. 实验数据集对比表
2. 性能指标对比表
3. 实验设计优劣分析
4. 实验结论的可信度评估"""

        try:
            return self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4096,
            )
        except Exception as e:
            return f"实验对比失败: {e}"


_engine: Optional[DocumentAnalysisEngine] = None


def get_document_engine() -> DocumentAnalysisEngine:
    global _engine
    if _engine is None:
        _engine = DocumentAnalysisEngine()
    return _engine
