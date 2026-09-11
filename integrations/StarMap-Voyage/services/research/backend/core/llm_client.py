"""DeepSeek LLM 客户端 — Research-Copilot-OS 的核心推理引擎"""

import json
import time
from typing import Optional

from openai import OpenAI

from .config import get_config


class LLMClient:
    """统一 LLM 调用接口，当前适配 DeepSeek API"""

    def __init__(self):
        cfg = get_config()
        self.model = cfg.llm.model
        self.reasoning_model = cfg.llm.reasoning_model
        self.max_tokens = cfg.llm.max_tokens
        self.temperature = cfg.llm.temperature
        self._available = bool(cfg.llm.api_key)
        self._client = None
        self._base_url = cfg.llm.base_url
        self._api_key = cfg.llm.api_key

    def _ensure_client(self):
        if self._client is None:
            if not self._api_key:
                raise RuntimeError(
                    "DeepSeek API Key 未设置。请设置环境变量 DEEPSEEK_API_KEY=sk-xxxx"
                )
            self._client = OpenAI(api_key=self._api_key, base_url=self._base_url)

    @property
    def available(self) -> bool:
        return self._available or bool(self._api_key)

    def chat(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> str:
        """通用对话接口"""
        self._ensure_client()
        kwargs = dict(
            model=model or self.model,
            messages=messages,
            temperature=temperature if temperature is not None else self.temperature,
            max_tokens=max_tokens or self.max_tokens,
        )
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        kwargs["timeout"] = 300
        resp = self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    def reason(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
    ) -> str:
        """使用 reasoning 模型进行深度推理（DeepSeek-R1）"""
        return self.chat(
            messages=[{"role": "user", "content": prompt}],
            model=self.reasoning_model,
            max_tokens=max_tokens or 16384,
            temperature=0.1,
        )

    def structured_output(
        self,
        system_prompt: str,
        user_prompt: str,
        output_schema: dict,
        model: Optional[str] = None,
    ) -> dict:
        """获取结构化 JSON 输出"""
        schema_str = json.dumps(output_schema, ensure_ascii=False, indent=2)
        full_prompt = f"""{system_prompt}

请严格按照以下 JSON schema 输出（只输出 JSON，不要有其他文字）：
{schema_str}

用户输入：
{user_prompt}"""
        for attempt in range(3):
            try:
                text = self.chat(
                    messages=[{"role": "user", "content": full_prompt}],
                    model=model or self.model,
                    temperature=0.0,
                    json_mode=True,
                )
                return json.loads(text.strip())
            except json.JSONDecodeError:
                if attempt == 2:
                    # Last attempt: try to extract JSON from the text
                    text = text.strip()
                    if "```json" in text:
                        text = text.split("```json")[1].split("```")[0].strip()
                    elif "```" in text:
                        text = text.split("```")[1].split("```")[0].strip()
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        raise RuntimeError(f"Failed to parse LLM output as JSON: {text[:500]}")
                time.sleep(0.5)
        return {}

    def batch_process(
        self,
        prompts: list[str],
        system_prompt: str = "",
        max_concurrent: int = 5,
    ) -> list[str]:
        """批量串行处理（避免并发速率限制）"""
        results = []
        for i, prompt in enumerate(prompts):
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            result = self.chat(messages)
            results.append(result)
            if i < len(prompts) - 1:
                time.sleep(0.3)
        return results


_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
