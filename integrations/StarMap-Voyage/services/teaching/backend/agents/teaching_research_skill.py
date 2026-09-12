"""师范生助研 Skill。

面向师范生（有 STEM 教学资源的师范大学学生），在生成教案的基础上，
进一步提供三类教研支持：说课稿、教学反思、教材/课标分析。

复用与 plan_generator 相同的 SiliconFlow DeepSeek 接口。
"""
import os
import requests
from agents.llm_config import resolve_chat_config

_LLM_CONFIG = resolve_chat_config()
LLM_API_URL = _LLM_CONFIG["url"]
LLM_MODEL = _LLM_CONFIG["model"]
API_KEY = _LLM_CONFIG["api_key"]


def _call_llm(system_prompt: str, user_message: str, max_tokens: int = 4096) -> str:
    resp = requests.post(
        LLM_API_URL,
        json={
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.6,
            "top_p": 0.9,
        },
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=120,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"LLM API error: {resp.status_code} {resp.text[:200]}")
    return resp.json()["choices"][0]["message"]["content"]


def generate_shuoke(plan_markdown: str, title: str, grade_level: str) -> str:
    """基于教案生成说课稿。"""
    system = "你是一位师范院校的教学法专家，擅长指导师范生撰写规范、专业的说课稿。"
    user = f"""请根据下面的教案，为一位师范生撰写一份完整、专业、可直接用于说课比赛或试讲的【说课稿】。

课题：{title}
学段：{grade_level}

说课稿请按以下环节组织（用 ## 小标题分隔）：
## 说教材（教材地位与作用、课标要求）
## 说学情（学生已有基础与认知特点）
## 说教学目标（含教学重点与难点）
## 说教法学法（教学方法与学习方法）
## 说教学过程（导入 → 新授 → 探究 → 练习 → 小结，分环节说明设计意图）
## 说板书设计
## 说教学反思与评价

要求：语言规范、条理清晰、紧扣教案具体内容，不要泛泛而谈。

教案原文：
{plan_markdown[:6000]}
"""
    return _call_llm(system, user)


def generate_reflection(plan_markdown: str, title: str) -> str:
    """基于教案生成教学反思。"""
    system = "你是一位教学反思专家，帮助教师进行课后复盘与改进。"
    user = f"""请根据下面的教案，为师范生撰写一份结构化的【教学反思】。

课题：{title}

教学反思请包含：
## 教学目标达成情况
## 教学重难点突破情况
## 教学方法有效性
## 学生参与度与课堂反馈
## 存在不足与改进建议

要求：结合教案中的具体环节展开分析，具体、可操作，避免空话。

教案原文：
{plan_markdown[:6000]}
"""
    return _call_llm(system, user)


def generate_curriculum_analysis(plan_markdown: str, title: str, grade_level: str) -> str:
    """基于教案生成教材/课标分析。"""
    system = "你是一位课程与教学论专家，擅长教材分析与课标对照。"
    user = f"""请根据下面的教案，撰写一份【教材与课标分析】。

课题：{title}
学段：{grade_level}

分析请包含：
## 教材地位与作用（本课题在教材/知识体系中的位置与作用）
## 课标要求对照（对应核心素养/学业要求）
## 知识结构分析（前后知识联系、逻辑关系）
## 教学价值分析（对核心素养培养的意义）

要求：结合课题具体内容，体现专业性与学术规范。

教案原文：
{plan_markdown[:6000]}
"""
    return _call_llm(system, user)
