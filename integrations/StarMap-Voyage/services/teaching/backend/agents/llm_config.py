"""Environment-driven chat model configuration for the teaching service."""

import os
from typing import Dict


def resolve_chat_config() -> Dict[str, str]:
    """Return an OpenAI-compatible endpoint and credentials without hardcoding secrets."""
    siliconflow_key = os.environ.get("SILICONFLOW_API_KEY", "").strip()
    if siliconflow_key:
        return {
            "url": os.environ.get(
                "SILICONFLOW_CHAT_URL",
                "https://api.siliconflow.cn/v1/chat/completions",
            ),
            "model": os.environ.get("TEACHING_LLM_MODEL", "deepseek-ai/DeepSeek-V3"),
            "api_key": siliconflow_key,
        }

    dashscope_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if dashscope_key:
        return {
            "url": os.environ.get(
                "DASHSCOPE_CHAT_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            ),
            "model": os.environ.get("DASHSCOPE_CHAT_MODEL", "qwen-plus"),
            "api_key": dashscope_key,
        }

    return {
        "url": os.environ.get(
            "SILICONFLOW_CHAT_URL",
            "https://api.siliconflow.cn/v1/chat/completions",
        ),
        "model": os.environ.get("TEACHING_LLM_MODEL", "deepseek-ai/DeepSeek-V3"),
        "api_key": "",
    }
