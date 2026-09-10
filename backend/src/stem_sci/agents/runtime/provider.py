"""Provider contracts for audit-safe structured LLM generation."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from threading import Lock
from time import perf_counter
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny, ValidationError

from stem_sci.utils.hash_utils import sha256_text
from stem_sci.utils.ids import new_id


class GenerationResult(BaseModel):
    """Validated output plus non-content metadata needed for provenance."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    parsed_output: SerializeAsAny[BaseModel]
    model: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    response_hash: str = Field(min_length=64, max_length=64)
    retry_count: int = Field(default=0, ge=0)


class LLMProviderError(RuntimeError):
    """Base class for failures safe to expose to runtime callers."""


class LLMTransportError(LLMProviderError):
    """The configured provider could not be reached."""


class LLMResponseError(LLMProviderError):
    """The provider returned an unusable protocol response."""


class LLMSchemaError(LLMProviderError):
    """The provider response did not satisfy the requested schema."""


class LLMBudgetExceeded(LLMProviderError):
    """The process-level LLM request allowance has been exhausted."""


@dataclass(frozen=True)
class ChatToolCall:
    """A provider-neutral function call emitted by a chat completion."""

    call_id: str
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True)
class ChatCompletionResult:
    """The bounded chat result needed by the tool-routing layer."""

    message: Mapping[str, Any]
    content: str | None
    tool_calls: tuple[ChatToolCall, ...]
    response_hash: str
    request_id: str


class LLMProvider(Protocol):
    """One structured generation call, independent of agent semantics."""

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        model: str,
        prompt_version: str,
    ) -> GenerationResult: ...


class GPTProvider:
    """GPT-compatible chat-completions provider using JSON Schema output."""

    # One backend process creates providers for QA and workflow agents. Keep
    # their remote-call allowance shared so one conversation cannot bypass the
    # configured limit by crossing service boundaries.
    _budget_lock = Lock()
    _budget_limit: int | None = None
    _budget_used = 0

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 60.0,
        default_model: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        if not base_url.strip():
            raise ValueError("LLM base URL must not be empty")
        if not api_key:
            raise ValueError("LLM API key must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("LLM timeout must be greater than zero")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.default_model = default_model
        # A caller-supplied client is commonly an in-process MockTransport in
        # tests and local adapters. Those calls never leave this process, so
        # they should not consume the process-wide remote-call allowance.
        self._counts_toward_budget = client is None
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self.response_format_mode = _response_format_mode(self.base_url)

    @classmethod
    def budget_status(cls) -> tuple[int, int]:
        """Return the configured process budget and calls reserved so far."""

        limit = _configured_max_llm_calls()
        if limit is None:
            return 0, 0
        with cls._budget_lock:
            if cls._budget_limit != limit:
                cls._budget_limit = limit
                cls._budget_used = 0
            return limit, cls._budget_used

    @classmethod
    def _reserve_call(cls) -> None:
        limit = _configured_max_llm_calls()
        # Tests and embedded callers that do not configure a budget retain the
        # provider's historical unlimited behavior. An explicit zero disables
        # remote generation; a positive value is the process-wide cap.
        if limit is None:
            return
        with cls._budget_lock:
            if cls._budget_limit != limit:
                cls._budget_limit = limit
                cls._budget_used = 0
            if cls._budget_used >= limit:
                raise LLMBudgetExceeded("LLM call budget exhausted")
            cls._budget_used += 1

    @classmethod
    def from_env(cls) -> GPTProvider:
        """Build a GPT provider without exposing configuration values in errors."""

        provider_name = os.getenv("STEM_SCI_LLM_PROVIDER", "gpt").strip().lower()
        if provider_name != "gpt":
            raise ValueError("unsupported STEM_SCI_LLM_PROVIDER")
        base_url = _required_environment_value("STEM_SCI_LLM_BASE_URL")
        api_key = _required_environment_value("STEM_SCI_LLM_API_KEY")
        default_model = _required_environment_value("STEM_SCI_LLM_MODEL")
        timeout_raw = os.getenv("STEM_SCI_LLM_TIMEOUT_SECONDS", "60")
        try:
            timeout_seconds = float(timeout_raw)
        except ValueError:
            raise ValueError("STEM_SCI_LLM_TIMEOUT_SECONDS must be numeric") from None
        return cls(
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            default_model=default_model,
        )

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        model: str,
        prompt_version: str,
    ) -> GenerationResult:
        selected_model = model or self.default_model
        if not selected_model:
            raise LLMResponseError("LLM model must not be empty")
        if self._counts_toward_budget:
            self._reserve_call()
        request_body = {
            "model": selected_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": _response_format(
                response_model,
                self.response_format_mode,
            ),
        }
        started = perf_counter()
        try:
            response = self._client.post(
                self._chat_completions_url(),
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=request_body,
                timeout=self.timeout_seconds,
            )
        except httpx.RequestError:
            raise LLMTransportError("LLM provider request failed") from None
        latency_ms = max(0, round((perf_counter() - started) * 1000))
        if not response.is_success:
            raise LLMResponseError(
                f"LLM provider returned HTTP status {response.status_code}"
            ) from None

        response_hash = sha256_text(response.text)
        payload = _response_payload(response)
        parsed_output = _parse_chat_output(payload, response_model)
        usage = payload.get("usage")
        usage_mapping = usage if isinstance(usage, Mapping) else {}
        request_id = _string_or_none(payload.get("id")) or response.headers.get("x-request-id")
        return GenerationResult(
            parsed_output=parsed_output,
            model=selected_model,
            prompt_version=prompt_version,
            request_id=request_id or new_id("llm-request"),
            input_tokens=_nonnegative_int_or_none(usage_mapping.get("prompt_tokens")),
            output_tokens=_nonnegative_int_or_none(usage_mapping.get("completion_tokens")),
            latency_ms=latency_ms,
            response_hash=response_hash,
        )

    def complete(
        self,
        *,
        messages: Sequence[Mapping[str, Any]],
        model: str,
        tools: Sequence[Mapping[str, Any]] = (),
        tool_choice: str | Mapping[str, Any] | None = None,
        response_model: type[BaseModel] | None = None,
    ) -> ChatCompletionResult:
        """Run a chat completion for bounded LLM tool routing.

        This method intentionally returns only the assistant message and parsed
        function calls. The caller owns tool execution and must append tool
        results explicitly before requesting the final answer.
        """

        selected_model = model or self.default_model
        if not selected_model:
            raise LLMResponseError("LLM model must not be empty")
        if self._counts_toward_budget:
            self._reserve_call()
        request_body: dict[str, Any] = {
            "model": selected_model,
            "messages": list(messages),
        }
        if tools:
            request_body["tools"] = list(tools)
            request_body["tool_choice"] = tool_choice or "auto"
        if response_model is not None:
            request_body["response_format"] = _response_format(
                response_model,
                self.response_format_mode,
            )
        try:
            response = self._client.post(
                self._chat_completions_url(),
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=request_body,
                timeout=self.timeout_seconds,
            )
        except httpx.RequestError:
            raise LLMTransportError("LLM provider request failed") from None
        if not response.is_success:
            raise LLMResponseError(
                f"LLM provider returned HTTP status {response.status_code}"
            ) from None
        payload = _response_payload(response)
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
            raise LLMResponseError("LLM provider returned an invalid response shape")
        message = choices[0].get("message")
        if not isinstance(message, Mapping):
            raise LLMResponseError("LLM provider returned an invalid response shape")
        return _chat_completion_result(response, message)

    def _chat_completions_url(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"


def _configured_max_llm_calls() -> int | None:
    raw_limit = os.getenv("STEM_SCI_MAX_LLM_CALLS")
    if raw_limit is None or not raw_limit.strip():
        return None
    try:
        limit = int(raw_limit)
    except ValueError:
        raise ValueError("STEM_SCI_MAX_LLM_CALLS must be a non-negative integer") from None
    if limit < 0:
        raise ValueError("STEM_SCI_MAX_LLM_CALLS must be a non-negative integer")
    return limit


class FakeLLMProvider:
    """Deterministic structured provider for offline tests and CI."""

    def __init__(self, responses: Sequence[Mapping[str, Any] | BaseModel]) -> None:
        self._responses = list(responses)
        self.call_count = 0

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        model: str,
        prompt_version: str,
    ) -> GenerationResult:
        del system_prompt, user_prompt
        response_index = self.call_count
        self.call_count += 1
        if response_index >= len(self._responses):
            raise LLMResponseError("fake LLM response queue exhausted")
        payload = self._responses[response_index]
        raw_payload = payload.model_dump() if isinstance(payload, BaseModel) else dict(payload)
        try:
            parsed_output = response_model.model_validate(raw_payload)
        except ValidationError:
            raise LLMSchemaError("LLM structured response failed schema validation") from None
        json_payload = parsed_output.model_dump(mode="json")
        response_text = json.dumps(
            json_payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        return GenerationResult(
            parsed_output=parsed_output,
            model=model,
            prompt_version=prompt_version,
            request_id=f"fake-llm-request-{self.call_count}",
            response_hash=sha256_text(response_text),
        )


def _required_environment_value(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise ValueError(f"{name} is required")
    return value


def _response_format_mode(base_url: str) -> str:
    """Select a provider-compatible JSON response mode.

    ``auto`` uses JSON mode for DeepSeek-compatible endpoints because some
    deployments do not accept OpenAI's strict json_schema envelope. Set
    ``STEM_SCI_LLM_RESPONSE_FORMAT=json_schema`` or ``json_object`` to
    override this behavior.
    """

    configured = os.getenv("STEM_SCI_LLM_RESPONSE_FORMAT", "auto").strip().lower()
    if configured in {"json_schema", "json_object"}:
        return configured
    # DashScope's OpenAI-compatible endpoint (including regional
    # ``aliyuncs.com`` hosts) supports JSON mode but does not consistently
    # accept OpenAI's strict ``json_schema`` envelope.  Keep this automatic so
    # Qwen deployments work without requiring a second hidden configuration
    # knob; an explicit environment value still wins above.
    lowered_url = base_url.casefold()
    if "deepseek.com" in lowered_url or "aliyuncs.com" in lowered_url or "dashscope" in lowered_url:
        return "json_object"
    return "json_schema"


def _response_format(response_model: type[BaseModel], mode: str) -> Mapping[str, Any]:
    if mode == "json_object":
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": response_model.__name__,
            "strict": True,
            "schema": response_model.model_json_schema(),
        },
    }


def _response_payload(response: httpx.Response) -> Mapping[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        raise LLMResponseError("LLM provider returned invalid JSON") from None
    if not isinstance(payload, Mapping):
        raise LLMResponseError("LLM provider returned an invalid response shape")
    return payload


def _chat_completion_result(
    response: httpx.Response,
    message: Mapping[str, Any],
) -> ChatCompletionResult:
    raw_tool_calls = message.get("tool_calls")
    parsed_tool_calls: list[ChatToolCall] = []
    if raw_tool_calls is not None:
        if not isinstance(raw_tool_calls, list):
            raise LLMResponseError("LLM provider returned invalid tool calls")
        for raw_call in raw_tool_calls:
            if not isinstance(raw_call, Mapping):
                raise LLMResponseError("LLM provider returned invalid tool call")
            function = raw_call.get("function")
            if not isinstance(function, Mapping):
                raise LLMResponseError("LLM provider returned invalid tool call")
            call_id = raw_call.get("id")
            name = function.get("name")
            arguments = function.get("arguments", "{}")
            if not isinstance(call_id, str) or not call_id:
                raise LLMResponseError("LLM provider returned a tool call without an id")
            if not isinstance(name, str) or not name:
                raise LLMResponseError("LLM provider returned a tool call without a name")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    raise LLMResponseError("LLM provider returned invalid tool arguments") from None
            if not isinstance(arguments, Mapping):
                raise LLMResponseError("LLM provider returned invalid tool arguments")
            parsed_tool_calls.append(
                ChatToolCall(
                    call_id=call_id,
                    name=name,
                    arguments=dict(arguments),
                )
            )
    content = message.get("content")
    if content is not None and not isinstance(content, str):
        raise LLMResponseError("LLM provider returned invalid message content")
    return ChatCompletionResult(
        message=dict(message),
        content=content,
        tool_calls=tuple(parsed_tool_calls),
        response_hash=sha256_text(response.text),
        request_id=(
            _string_or_none(response.headers.get("x-request-id"))
            or f"chat-request-{sha256_text(response.text)[:16]}"
        ),
    )


def _parse_chat_output(
    payload: Mapping[str, Any], response_model: type[BaseModel]
) -> BaseModel:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        raise LLMResponseError("LLM provider returned an invalid response shape")
    message = choices[0].get("message")
    if not isinstance(message, Mapping):
        raise LLMResponseError("LLM provider returned an invalid response shape")
    structured_content = message.get("parsed", message.get("content"))
    if isinstance(structured_content, str):
        try:
            structured_content = json.loads(structured_content)
        except json.JSONDecodeError:
            raise LLMResponseError("LLM provider returned invalid structured JSON") from None
    if not isinstance(structured_content, Mapping):
        raise LLMResponseError("LLM provider returned an invalid structured response")
    structured_content = _normalize_json_mode_output(structured_content, response_model)
    try:
        return response_model.model_validate(structured_content)
    except ValidationError:
        raise LLMSchemaError("LLM structured response failed schema validation") from None


def _normalize_json_mode_output(
    content: Mapping[str, Any], response_model: type[BaseModel]
) -> Mapping[str, Any]:
    """Normalize common Qwen JSON-mode omissions before typed validation."""

    name = response_model.__name__
    if name == "ClaimGraphResponse" and "graph" not in content:
        raw_nodes = content.get("atomic_claims", content.get("nodes", []))
        if isinstance(raw_nodes, list):
            nodes: list[dict[str, Any]] = []
            for raw in raw_nodes:
                if not isinstance(raw, Mapping):
                    continue
                raw_type = str(raw.get("claim_type", raw.get("type", "LITERATURE")))
                claim_type = raw_type.upper()
                if claim_type not in {"LITERATURE", "RESULT", "METHOD", "INTERPRETATION", "SPECULATION", "LIMITATION"}:
                    lowered = raw_type.casefold()
                    claim_type = (
                        "RESULT" if any(token in lowered for token in ("statistic", "comparative", "associative"))
                        else "METHOD" if any(token in lowered for token in ("method", "instrument"))
                        else "LITERATURE"
                    )
                refs = raw.get("evidence_refs", [])
                nodes.append({
                    "project_id": str(raw.get("project_id", "llm-generated")),
                    "claim_id": str(raw.get("claim_id", "llm-claim")),
                    "text": str(raw.get("text", "")),
                    "claim_type": claim_type,
                    "evidence_refs": list(refs) if isinstance(refs, list) else [],
                    "section_target": str(raw.get("section_target", raw.get("manuscript_section", "introduction"))),
                    "strength": str(raw.get("strength", "bounded")),
                })
            return {
                "graph": {
                    "project_id": str(content.get("project_id", "llm-generated")),
                    "nodes": nodes,
                    "graph_hash": content.get("graph_hash"),
                }
            }
    if name == "OutlineResponse" and "outline" not in content:
        return {"outline": _normalize_outline_payload(content)}
    if name == "DraftResponse" and "draft" not in content:
        return {"draft": _normalize_draft_payload(content)}
    return content


def _normalize_outline_payload(content: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt common JSON-mode outline shapes to the strict writing contract.

    The LLM may return a rich ``sections`` list because the prompt asks for
    purpose, gaps and transitions.  Those narrative fields are intentionally
    discarded here: only claim assignments cross the trust boundary.
    """
    raw_sections = content.get("sections", [])
    assignments: dict[str, list[str]] = {}
    guidance: dict[str, dict[str, Any]] = {}
    if isinstance(content.get("section_claim_ids"), Mapping):
        for key, value in content["section_claim_ids"].items():
            if isinstance(value, list):
                assignments[str(key)] = [str(item) for item in value if isinstance(item, (str, int))]
    elif isinstance(raw_sections, Mapping):
        raw_sections = [dict(value, section=key) if isinstance(value, Mapping) else {"section": key, "claim_ids": value}
                        for key, value in raw_sections.items()]
    if isinstance(raw_sections, list):
        for index, item in enumerate(raw_sections):
            if not isinstance(item, Mapping):
                continue
            section = item.get("section", item.get("name", item.get("title", f"section_{index + 1}")))
            section_key = str(section)
            claims = item.get("claim_ids", item.get("claims", item.get("claim_ids_to_use", [])))
            if not isinstance(claims, list):
                claims = [claims] if isinstance(claims, (str, int)) else []
            claim_ids: list[str] = []
            for claim in claims:
                if isinstance(claim, Mapping):
                    value = claim.get("claim_id", claim.get("id"))
                    if value is not None:
                        claim_ids.append(str(value))
                elif isinstance(claim, (str, int)):
                    claim_ids.append(str(claim))
            assignments.setdefault(section_key, claim_ids)
            # Keep only explanatory planning fields. Never carry through
            # arbitrary model fields that could look like evidence or results.
            allowed = ("purpose", "argument_order", "unresolved_gaps", "transition", "evidence_to_use")
            hints = {key: item[key] for key in allowed if key in item and isinstance(item[key], (str, list))}
            if hints:
                guidance[section_key] = hints
    return {
        "outline_id": str(content.get("outline_id", content.get("id", "llm-outline"))),
        "project_id": str(content.get("project_id", "llm-generated")),
        "title": str(content.get("title", content.get("working_title", "Manuscript outline"))),
        "section_claim_ids": assignments,
        "section_guidance": guidance,
    }


def _normalize_draft_payload(content: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt rich Qwen draft JSON while retaining only auditable fields."""
    sections_raw = content.get("sections", {})
    sections: dict[str, str] = {}
    if isinstance(sections_raw, Mapping):
        for key, value in sections_raw.items():
            if isinstance(value, Mapping):
                value = value.get("text", value.get("content", ""))
            sections[str(key)] = str(value) if value is not None else ""
    elif isinstance(sections_raw, list):
        for index, item in enumerate(sections_raw):
            if not isinstance(item, Mapping):
                continue
            key = item.get("section", item.get("name", item.get("title", f"section_{index + 1}")))
            value = item.get("text", item.get("content", item.get("body", "")))
            sections[str(key)] = str(value) if value is not None else ""
    claim_values = content.get("claim_ids", content.get("claims", []))
    if not isinstance(claim_values, list):
        claim_values = [claim_values] if isinstance(claim_values, (str, int)) else []
    claim_ids = [str(item.get("claim_id", item.get("id"))) if isinstance(item, Mapping)
                 else str(item) for item in claim_values if isinstance(item, (Mapping, str, int))]
    citations = content.get("citation_refs", content.get("citations", content.get("evidence_refs", [])))
    if not isinstance(citations, list):
        citations = [citations] if isinstance(citations, (str, int)) else []
    language = str(content.get("language", "zh-CN"))
    language = {"zh": "zh-CN", "zh_cn": "zh-CN", "中文": "zh-CN", "en": "en-US", "en_us": "en-US", "英文": "en-US"}.get(language, language)
    return {
        "project_id": str(content.get("project_id", "llm-generated")),
        "language": language,
        "sections": sections,
        "claim_ids": claim_ids,
        "citation_refs": [str(item) for item in citations if isinstance(item, (str, int))],
        "numeric_literals": [str(item) for item in content.get("numeric_literals", []) if isinstance(item, (str, int))],
        "result_directions": content.get("result_directions", {}) if isinstance(content.get("result_directions", {}), Mapping) else {},
        "claim_strengths": content.get("claim_strengths", {}) if isinstance(content.get("claim_strengths", {}), Mapping) else {},
        "limitation_claim_ids": [str(item) for item in content.get("limitation_claim_ids", []) if isinstance(item, (str, int))],
        "status": str(content.get("status", "CANDIDATE_LLM")),
    }


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _nonnegative_int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None
