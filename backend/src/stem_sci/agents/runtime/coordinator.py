"""Optional STEM-SCI coordinator model with fail-open behavior."""

from __future__ import annotations

import logging
import os

from pydantic import BaseModel, ConfigDict, Field

from .provider import GPTProvider
from .structured_generator import StructuredGenerator

logger = logging.getLogger(__name__)


class CoordinatorResponse(BaseModel):
    """The fixed response shell used by the LoRA coordinator model."""

    model_config = ConfigDict(extra="forbid")

    response_mode: str = Field(min_length=1, max_length=64)
    user_message: str = Field(min_length=1, max_length=4000)
    evidence_items: list[dict[str, object]] = Field(default_factory=list)
    uncertainty: str = Field(min_length=1, max_length=1000)
    open_questions: list[str] = Field(default_factory=list)
    options: list[dict[str, object]] = Field(default_factory=list)
    next_action: str = Field(min_length=1, max_length=128)
    requires_human_decision: bool
    risk_flags: list[str] = Field(default_factory=list)


class OptionalCoordinator:
    """Call a separately deployed LoRA model without becoming a hard dependency."""

    def __init__(self, provider: GPTProvider, model: str, timeout_seconds: float = 10.0) -> None:
        self.provider = provider
        self.model = model
        self.provider.timeout_seconds = timeout_seconds
        self.generator = StructuredGenerator(provider, max_retries=0)

    @classmethod
    def from_env(cls) -> OptionalCoordinator | None:
        enabled = os.getenv("STEM_SCI_LLM_COORDINATOR_ENABLED", "false").strip().lower()
        if enabled not in {"1", "true", "yes", "on"}:
            return None
        base_url = os.getenv(
            "STEM_SCI_LLM_COORDINATOR_BASE_URL",
            "https://maas-api.cn-huabei-1.xf-yun.com/v2",
        ).strip()
        api_key = os.getenv("STEM_SCI_LLM_COORDINATOR_API_KEY", "").strip()
        model = os.getenv("STEM_SCI_LLM_COORDINATOR_MODEL", "xsp593b8e4f").strip()
        if not base_url or not api_key or not model:
            logger.warning("Coordinator model is enabled but its configuration is incomplete")
            return None
        try:
            timeout = float(os.getenv("STEM_SCI_LLM_COORDINATOR_TIMEOUT_SECONDS", "10"))
        except ValueError:
            timeout = 10.0
        return cls(
            GPTProvider(
                base_url=base_url,
                api_key=api_key,
                timeout_seconds=max(1.0, timeout),
                default_model=model,
            ),
            model,
            timeout_seconds=max(1.0, timeout),
        )

    def advise(self, *, user_message: str, context: str, current_answer: str) -> CoordinatorResponse | None:
        """Return advice when the service is available; otherwise return None."""

        try:
            result = self.generator.generate(
                system_prompt=(
                    "你是STEM-SCI人机协同科研协调器。根据用户目标、上下文和已有回答，"
                    "生成下一步可执行回应。不得编造来源、数字或结论；需要人决定时必须交还给人。"
                    "输出必须是JSON，字段固定为response_mode、user_message、evidence_items、"
                    "uncertainty、open_questions、options、next_action、requires_human_decision、risk_flags。"
                ),
                user_prompt=(
                    f"用户消息：{user_message}\n\n当前上下文：{context[:3000]}\n\n"
                    f"已有回答：{current_answer[:3000]}"
                ),
                response_model=CoordinatorResponse,
                model=self.model,
                prompt_version="stem-sci-coordinator-v1",
            )
            return CoordinatorResponse.model_validate(result.parsed_output)
        except Exception as error:  # noqa: BLE001 - service availability is optional
            logger.info("Coordinator service unavailable; skipping optional advice: %s", error)
            return None
