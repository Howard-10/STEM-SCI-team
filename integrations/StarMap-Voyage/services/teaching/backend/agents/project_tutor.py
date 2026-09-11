"""
Project AI Tutor Agent.
Per-project conversational AI that answers student questions
based on the project's teaching plan context (RAG on project content).
"""
import os
import sys
import json
from typing import Dict, List, Optional

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---- Config ----
LLM_API_URL = "https://api.siliconflow.cn/v1/chat/completions"
LLM_MODEL = "deepseek-ai/DeepSeek-V3"
API_KEY = os.environ.get("SILICONFLOW_API_KEY", "").strip()


class ProjectTutor:
    """AI tutor that answers questions in the context of a specific project."""

    def __init__(self, project_path: str):
        self.project_path = project_path
        self.conversation_history: List[Dict] = []
        self._load_project_context()

    def _load_project_context(self):
        """Load the teaching plan and project files as context."""
        plan_path = os.path.join(self.project_path, "教案.md")
        self.plan_content = ""
        if os.path.exists(plan_path):
            with open(plan_path, "r", encoding="utf-8") as f:
                self.plan_content = f.read()

        # Also load any code files
        self.code_files = {}
        code_dir = os.path.join(self.project_path, "code")
        if os.path.exists(code_dir):
            for fname in os.listdir(code_dir):
                fpath = os.path.join(code_dir, fname)
                if os.path.isfile(fpath) and fname.endswith(('.py', '.ino', '.cpp', '.js')):
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            self.code_files[fname] = f.read()
                    except Exception:
                        pass

    def chat(self, user_message: str) -> str:
        """Answer a student question within the project context."""
        self.conversation_history.append({"role": "user", "content": user_message})

        system_prompt = self._build_tutor_prompt()
        messages = [{"role": "system", "content": system_prompt}]

        # Keep last 6 messages for context
        recent_history = self.conversation_history[-6:]
        messages.extend(recent_history)

        resp = requests.post(
            LLM_API_URL,
            json={
                "model": LLM_MODEL,
                "messages": messages,
                "max_tokens": 1024,
                "temperature": 0.5,
            },
            headers={"Authorization": f"Bearer {API_KEY}"},
            timeout=60
        )

        if resp.status_code != 200:
            return f"抱歉，AI助手暂时无法响应（{resp.status_code}）。请稍后再试。"

        data = resp.json()
        reply = data["choices"][0]["message"]["content"]
        self.conversation_history.append({"role": "assistant", "content": reply})
        return reply

    def _build_tutor_prompt(self) -> str:
        """Build the system prompt with project context."""
        prompt_parts = [
            "你是一个亲切、耐心的STEM项目AI助教。你正在帮助一位学生完成一个STEM项目。",
            "",
            "## 你的原则",
            "1. 用鼓励的语气，像朋友一样与学生对话",
            "2. 不要直接给答案，而是通过提问和提示引导学生自己思考",
            "3. 如果学生卡住了，先问'你目前做到哪一步了？'再给建议",
            "4. 解释概念时要结合项目中的具体例子",
            "5. 如果涉及安全操作，必须严肃提醒",
            "6. 用emoji让对话更生动，但不要过度",
            "",
        ]

        if self.plan_content:
            # Include truncated plan as context
            plan_summary = self.plan_content[:3000]
            prompt_parts.append("## 当前项目教案")
            prompt_parts.append("以下是学生正在学习的项目内容，请基于此回答：")
            prompt_parts.append(plan_summary)
            prompt_parts.append("")

        if self.code_files:
            prompt_parts.append("## 项目代码")
            for fname, code in list(self.code_files.items())[:3]:
                code_summary = code[:500]
                prompt_parts.append(f"### {fname}")
                prompt_parts.append(f"```\n{code_summary}\n```")
                prompt_parts.append("")

        return "\n".join(prompt_parts)

    def reset(self):
        """Reset conversation history."""
        self.conversation_history = []

    def get_summary(self) -> Dict:
        """Get tutor session summary."""
        return {
            "message_count": len(self.conversation_history),
            "project_path": self.project_path,
            "has_plan": bool(self.plan_content),
            "code_file_count": len(self.code_files)
        }
