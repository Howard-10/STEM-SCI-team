"""
Code Assistant Agent — adapted from Research-Copilot-OS agent architecture.
Provides code explanation, generation, debugging for STEM student projects.
Supports Python + Arduino/C++ code.
"""
import os
import re
import sys
from typing import Dict, List, Optional

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.llm_config import resolve_chat_config

# ---- Config ----
_LLM_CONFIG = resolve_chat_config()
LLM_API_URL = _LLM_CONFIG["url"]
LLM_MODEL = _LLM_CONFIG["model"]
API_KEY = _LLM_CONFIG["api_key"]

# ---- System Prompts ----
EXPLAIN_PROMPT = """你是一位耐心的编程教师，正在帮助一位STEM学生理解代码。

## 你的原则
1. 用通俗的语言解释代码，假设学生是编程初学者
2. 逐行或逐段解释，先说整体目的，再说细节
3. 用生活中类比帮助学生理解抽象概念
4. 如果代码有危险操作（如高温、高压），必须提醒安全
5. 鼓励的语气，让学生感到编程不难

## 输出格式
1. **整体目的**：这段代码要做什么？（1-2句话）
2. **逐段解释**：分段解释每部分的作用
3. **关键概念**：涉及的重要编程概念（变量、循环、函数等）
4. **小提示**：一个实用的建议或常见的坑"""

GENERATE_PROMPT = """你是一位STEM编程专家，帮助学生将想法转化为可运行的代码。

## 你的原则
1. 生成的代码必须完整、可运行
2. 添加清晰的中文注释解释每一步
3. 优先使用简单、易懂的实现方式
4. 代码风格整洁，变量名有意义
5. 如果是Arduino代码，包含完整的setup()和loop()
6. 如果是Python代码，包含必要的import

## 输出格式
直接输出代码块，代码中包含详细注释。在代码前用1-2句话简要说明思路。"""

DEBUG_PROMPT = """你是一位编程调试专家，帮助学生找出代码中的问题。

## 你的原则
1. 先分析错误信息（如果有），解释错误的含义
2. 检查常见问题：语法错误、逻辑错误、接线问题（Arduino）、库缺失
3. 给出具体的修改方案，标注修改的位置
4. 教学生如何自己排查类似问题
5. 如果是硬件问题，同时检查物理连接

## 输出格式
1. **错误原因**：问题出在哪里？
2. **解决方案**：具体该怎么改？
3. **修改后的代码**：完整展示修正后的代码
4. **排查技巧**：下次如何自己发现这类问题"""


class CodeAssistant:
    """STEM code assistant: explain, generate, debug code."""

    def __init__(self):
        self.history: List[Dict] = []

    def explain_code(self, code: str, language: str = "python") -> str:
        """Explain what a piece of code does."""
        lang_hint = "Arduino/C++" if language in ("arduino", "cpp", "ino") else "Python"
        user_msg = f"请解释这段{lang_hint}代码：\n\n```{language}\n{code[:3000]}\n```"

        return self._call_llm(EXPLAIN_PROMPT, user_msg, 1024)

    def generate_code(self, description: str, language: str = "python",
                      context: str = "") -> str:
        """Generate code from natural language description."""
        lang_hint = "Arduino/C++" if language in ("arduino", "cpp", "ino") else "Python"

        user_msg = f"请生成{lang_hint}代码：{description}\n\n要求：代码完整可运行，包含详细中文注释。"

        if context:
            user_msg += f"\n\n项目背景（参考）：\n{context[:1500]}"

        return self._call_llm(GENERATE_PROMPT, user_msg, 2048)

    def debug_code(self, code: str, error_msg: str = "",
                   language: str = "python") -> str:
        """Debug code with an optional error message."""
        lang_hint = "Arduino/C++" if language in ("arduino", "cpp", "ino") else "Python"

        user_msg = f"请帮我调试这段{lang_hint}代码：\n\n```{language}\n{code[:3000]}\n```"
        if error_msg:
            user_msg += f"\n\n错误信息：\n{error_msg[:1000]}"

        return self._call_llm(DEBUG_PROMPT, user_msg, 1536)

    def chat_about_code(self, user_message: str, current_code: str = "",
                        language: str = "python") -> str:
        """General chat about code with context."""
        self.history.append({"role": "user", "content": user_message})

        system = """你是一个STEM编程助教。学生正在编写代码，请帮助他们。

当前可见代码：
""" + (current_code[:2000] if current_code else "(无)")

        messages = [{"role": "system", "content": system}]
        messages.extend(self.history[-8:])

        reply = self._call_llm(system, user_message, 1024, messages[1:])
        self.history.append({"role": "assistant", "content": reply})
        return reply

    def review_code(self, code: str, language: str = "python",
                    requirements: str = "") -> str:
        """Review code quality and suggest improvements."""
        user_msg = f"请审查这段代码，给出改进建议。\n\n```{language}\n{code[:3000]}\n```"
        if requirements:
            user_msg += f"\n\n项目要求：{requirements}"

        prompt = """你是代码审查专家。请从以下角度评价代码：

1. **正确性**：代码能否实现预期功能？
2. **可读性**：变量名、注释、结构是否清晰？
3. **效率**：有没有更高效的写法？
4. **安全性**：有什么潜在风险？
5. **改进建议**：具体怎么优化？

用友好、建设性的语气，适合学生理解。"""

        return self._call_llm(prompt, user_msg, 1024)

    def _call_llm(self, system_prompt: str, user_message: str,
                  max_tokens: int, messages_override: List = None) -> str:
        """Call the configured OpenAI-compatible teaching model."""
        if messages_override:
            messages = [{"role": "system", "content": system_prompt}] + messages_override
        else:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]

        try:
            resp = requests.post(
                LLM_API_URL,
                json={
                    "model": LLM_MODEL,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": 0.3,
                },
                headers={"Authorization": f"Bearer {API_KEY}"},
                timeout=60
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            return f"AI服务暂时不可用 (HTTP {resp.status_code})"
        except Exception as e:
            return f"请求失败: {str(e)}"

    def reset(self):
        self.history = []


# Singleton
_code_assistant: Optional[CodeAssistant] = None


def get_code_assistant() -> CodeAssistant:
    global _code_assistant
    if _code_assistant is None:
        _code_assistant = CodeAssistant()
    return _code_assistant
