"""Public contracts for structured agent generation."""

from .prompt_registry import PromptRegistry, PromptTemplate
from .coordinator import CoordinatorResponse, OptionalCoordinator
from .provider import (
    ChatCompletionResult,
    ChatToolCall,
    FakeLLMProvider,
    GenerationResult,
    GPTProvider,
    LLMBudgetExceeded,
    LLMProvider,
    LLMProviderError,
    LLMResponseError,
    LLMSchemaError,
    LLMTransportError,
)
from .structured_generator import StructuredGenerationError, StructuredGenerator

__all__ = [
    "ChatCompletionResult",
    "ChatToolCall",
    "FakeLLMProvider",
    "GPTProvider",
    "LLMBudgetExceeded",
    "GenerationResult",
    "LLMProvider",
    "LLMProviderError",
    "LLMResponseError",
    "LLMSchemaError",
    "LLMTransportError",
    "PromptRegistry",
    "PromptTemplate",
    "StructuredGenerationError",
    "StructuredGenerator",
    "CoordinatorResponse",
    "OptionalCoordinator",
]
