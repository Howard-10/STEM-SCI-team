"""
Experiment & reproduction API module.
Ported from Research-Copilot-OS experiment engines.
"""
import json
import os
import re
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import requests
from agents.llm_config import resolve_chat_config

router = APIRouter(prefix="/api/experiment", tags=["experiment"])

_LLM_CONFIG = resolve_chat_config()
LLM_URL = _LLM_CONFIG["url"]
LLM_MODEL = _LLM_CONFIG["model"]
API_KEY = _LLM_CONFIG["api_key"]
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "experiments")

os.makedirs(DATA_DIR, exist_ok=True)


# ---- Schemas ----
class AnalyzeExperimentInput(BaseModel):
    project_id: Optional[str] = None
    name: str
    raw_result: str
    topic: str = ""


class ReproductionInput(BaseModel):
    project_id: Optional[str] = None
    topic: str
    github_url: str = ""
    error_log: str = ""


class ExperimentRecordInput(BaseModel):
    project_id: str
    name: str
    hyperparams: Dict = {}
    metrics: Dict = {}
    notes: str = ""


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

@router.post("/analyze")
async def analyze_experiment(req: AnalyzeExperimentInput):
    """Analyze experiment results with AI insights."""
    prompt = f"""请分析以下实验结果：

实验名称: {req.name}
研究主题: {req.topic}
原始结果:
{req.raw_result[:3000]}

返回JSON格式：
{{
  "trend": "数据趋势分析",
  "bestMethod": "表现最好的方法/配置",
  "metricChange": "关键指标变化",
  "outlierNote": "异常值说明",
  "possibleReasons": ["可能原因1", "可能原因2"],
  "extraExperiments": ["建议补充的实验1", "建议补充的实验2"],
  "paperConclusion": "可写入论文的结论(50-100字)",
  "chartSuggestion": {{
    "chartType": "bar/line/scatter/heatmap",
    "xAxis": "X轴",
    "yAxis": "Y轴",
    "title": "图表标题",
    "highlight": "关键发现",
    "matplotlibSnippet": "import matplotlib..."
  }}
}}
直接返回JSON:"""

    result = _call_llm("你是实验数据分析专家。", prompt)
    data = _extract_json(result)
    return {"success": True, "insight": data or {"raw": result}}


@router.post("/reproduction-guide")
async def reproduction_guide(req: ReproductionInput):
    """Generate code reproduction guide."""
    prompt = f"""请为以下项目生成代码复现指南：

研究主题: {req.topic}
仓库地址: {req.github_url or "未提供"}
错误日志: {req.error_log or "无"}

返回JSON格式：
{{
  "repoGoal": "仓库目标(一句话)",
  "readmeSummary": ["README要点1", "要点2"],
  "environmentCommands": ["pip install ...", "conda create ..."],
  "debugSuggestions": ["调试建议1", "建议2"],
  "nextSteps": ["下一步1", "下一步2"]
}}
直接返回JSON:"""

    result = _call_llm("你是代码复现专家，擅长搭建环境和调试。", prompt)
    data = _extract_json(result)
    return {"success": True, "guide": data or {"raw": result}}


@router.post("/records")
async def save_experiment(req: ExperimentRecordInput):
    """Save an experiment record."""
    exp_id = f"exp_{uuid.uuid4().hex[:8]}"
    record = {
        "id": exp_id,
        "project_id": req.project_id,
        "name": req.name,
        "hyperparams": req.hyperparams,
        "metrics": req.metrics,
        "notes": req.notes,
        "createdAt": datetime.now().isoformat()
    }

    proj_dir = os.path.join(DATA_DIR, req.project_id)
    os.makedirs(proj_dir, exist_ok=True)
    with open(os.path.join(proj_dir, f"{exp_id}.json"), "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)

    return {"success": True, "record": record}


@router.get("/records/{project_id}")
async def list_experiments(project_id: str):
    """List experiment records for a project."""
    proj_dir = os.path.join(DATA_DIR, project_id)
    if not os.path.exists(proj_dir):
        return {"success": True, "records": []}

    records = []
    for fname in os.listdir(proj_dir):
        if fname.endswith(".json"):
            with open(os.path.join(proj_dir, fname), "r", encoding="utf-8") as f:
                records.append(json.load(f))
    records.sort(key=lambda r: r.get("createdAt", ""), reverse=True)
    return {"success": True, "records": records}


@router.post("/chart-code")
async def generate_chart_code(description: str, chart_type: str = "bar"):
    """Generate matplotlib/seaborn chart code from description."""
    prompt = f"""请根据描述生成Python数据可视化代码。

图表类型: {chart_type}
需求描述: {description}

要求: 使用matplotlib+seaborn，代码完整可运行，包含中文注释，使用学术配色。
直接输出Python代码:"""

    result = _call_llm("你是数据可视化专家。", prompt)
    # Extract code block
    match = re.search(r'```(?:python)?\s*\n(.*?)```', result, re.DOTALL)
    code = match.group(1).strip() if match else result
    return {"success": True, "code": code}
