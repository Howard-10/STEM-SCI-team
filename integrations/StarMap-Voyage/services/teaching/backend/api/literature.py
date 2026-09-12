"""
Literature reading & management API module.
Ported from ResearchPilot / 科研增效.
"""
import json
import os
import uuid
import re
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import requests
from agents.llm_config import resolve_chat_config

router = APIRouter(prefix="/api/literature", tags=["literature"])

_LLM_CONFIG = resolve_chat_config()
LLM_URL = _LLM_CONFIG["url"]
LLM_MODEL = _LLM_CONFIG["model"]
API_KEY = _LLM_CONFIG["api_key"]
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "literature")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "projects"), exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "papers"), exist_ok=True)


# ---- Schemas ----
class GenerateOverviewInput(BaseModel):
    project_id: Optional[str] = None
    topic: str
    request: str = ""


class AnalyzePaperInput(BaseModel):
    project_id: Optional[str] = None
    title: str
    abstract: str
    keywords: List[str] = []


class ComparePapersInput(BaseModel):
    project_id: Optional[str] = None
    topic: str
    papers: List[Dict] = []


class ResearchIdeaInput(BaseModel):
    project_id: str
    topic: str


# ---- Helpers ----
def _call_llm(system: str, user: str, max_tokens: int = 2048) -> str:
    if not API_KEY:
        return "AI服务未配置，请在助学服务环境中设置模型 API key。"
    try:
        resp = requests.post(LLM_URL, json={
            "model": LLM_MODEL,
            "messages": [{"role":"system","content":system}, {"role":"user","content":user}],
            "max_tokens": max_tokens, "temperature": 0.3,
        }, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=90)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        return f"AI服务不可用 (HTTP {resp.status_code})"
    except Exception as e:
        return f"请求失败: {str(e)}"


def _extract_json(text: str) -> Optional[Dict]:
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try: return json.loads(match.group())
        except: pass
    return None


# ---- Endpoints ----

@router.post("/overview")
async def generate_overview(req: GenerateOverviewInput):
    """Generate a research field overview report."""
    prompt = f"""你是科研导师。学生想了解研究领域"{req.topic}"。
{("具体要求: "+req.request) if req.request else ""}

请生成一份领域入门报告，返回JSON格式：
{{
  "background": "领域背景(200字)",
  "coreConcepts": ["核心概念1", "核心概念2", ...],
  "keyTasks": ["关键任务1", ...],
  "mainstreamMethods": ["主流方法1", ...],
  "commonDatasets": ["常用数据集1", ...],
  "commonMetrics": ["常用指标1", ...],
  "challenges": ["当前挑战1", ...],
  "entryPoints": ["适合新手的切入点1", ...],
  "readingPath": ["推荐阅读路径: 先读X综述→再读Y经典论文→最后Z前沿", ...]
}}
直接返回JSON:"""

    result = _call_llm("你是AI科研导师，擅长帮助研究生快速了解新领域。", prompt)
    data = _extract_json(result)
    if data:
        data["topic"] = req.topic
        data["savedAt"] = datetime.now().isoformat()
    return {"success": True, "report": data or {"topic": req.topic, "raw": result}}


@router.post("/analyze-paper")
async def analyze_paper(req: AnalyzePaperInput):
    """Deep analysis of a single paper."""
    prompt = f"""请深度分析这篇论文：

标题: {req.title}
摘要: {req.abstract}
关键词: {', '.join(req.keywords)}

返回JSON格式：
{{
  "background": "研究背景",
  "motivation": "研究动机",
  "coreProblem": "核心问题",
  "method": "方法概述",
  "innovation": ["创新点1", "创新点2"],
  "experimentDesign": "实验设计",
  "datasets": ["数据集"],
  "metrics": ["指标"],
  "strengths": ["优势"],
  "limitation": "局限性",
  "inspiration": "对你的启发",
  "contribution": "主要贡献",
  "isBaselineCandidate": true/false
}}
直接返回JSON:"""

    result = _call_llm("你是论文分析专家，擅长深度解读科研论文。", prompt)
    data = _extract_json(result)
    paper = {
        "id": f"paper_{uuid.uuid4().hex[:8]}",
        "title": req.title,
        "abstract": req.abstract,
        "keywords": req.keywords,
        "createdAt": datetime.now().isoformat(),
        **(data or {})
    }
    return {"success": True, "paper": paper}


@router.post("/compare")
async def compare_papers(req: ComparePapersInput):
    """Compare multiple papers and identify research gaps."""
    papers_text = "\n\n".join([
        f"论文{i+1}: {p.get('title','')}\n摘要: {p.get('abstract','')[:500]}\n方法: {p.get('method','')[:300]}"
        for i, p in enumerate(req.papers[:10])
    ])

    prompt = f"""请对比以下关于"{req.topic}"的论文：

{papers_text}

返回JSON格式：
{{
  "rows": [
    {{"title": "论文标题", "motivation": "动机", "method": "方法", "innovation": "创新",
      "datasets": "数据集", "metrics": "指标", "strengths": "优势", "limitation": "局限", "inspiration": "启发"}}
  ],
  "gapAnalysis": {{
    "commonProblems": ["共性问题"],
    "unresolvedIssues": ["未解决问题"],
    "datasetGaps": ["数据缺口"],
    "methodGaps": ["方法缺口"],
    "transformableQuestions": ["可转化为研究问题"],
    "ideas": [{{"title": "创新想法", "description": "描述", "noveltyScore": 8, "feasibilityScore": 7, "workloadScore": 5}}]
  }}
}}
直接返回JSON:"""

    result = _call_llm("你是科研方法论专家。", prompt)
    data = _extract_json(result)
    return {"success": True, "compareResult": data or {"raw": result}}


@router.post("/generate-ideas")
async def generate_ideas(req: ResearchIdeaInput):
    """Generate novel research ideas based on topic."""
    prompt = f"""基于研究领域"{req.topic}"，生成3-5个有创新性的研究想法。
返回JSON数组，每个想法包含: title, description, noveltyScore(1-10), feasibilityScore(1-10), workloadScore(1-10)
直接返回JSON数组:"""

    result = _call_llm("你是科研创新顾问。", prompt)
    match = re.search(r'\[.*\]', result, re.DOTALL)
    ideas = []
    if match:
        try: ideas = json.loads(match.group())
        except: pass
    return {"success": True, "ideas": ideas}


@router.get("/explain-concept")
async def explain_concept(concept: str = ""):
    """Explain a research concept simply."""
    if not concept:
        return {"success": False, "error": "请提供要解释的概念"}
    result = _call_llm(
        "用通俗易懂的语言解释科研概念，适合研究生理解。",
        f"请解释科研概念: {concept}\n\n用2-3段话，包含定义、应用场景和一个简单例子。"
    )
    return {"success": True, "concept": concept, "explanation": result}
