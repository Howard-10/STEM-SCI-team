"""Research-Copilot-OS 全局配置"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class LLMConfig:
    provider: str = "deepseek"
    api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))
    base_url: str = field(default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    model: str = field(default_factory=lambda: os.getenv("DEEPSEEK_MODEL", "deepseek-chat"))
    max_tokens: int = 8192
    temperature: float = 0.1
    reasoning_model: str = "deepseek-reasoner"


@dataclass
class EmbeddingConfig:
    provider: str = "deepseek"
    api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))
    base_url: str = field(default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    model: str = field(default_factory=lambda: os.getenv("DEEPSEEK_MODEL", "deepseek-chat"))


@dataclass
class StorageConfig:
    project_root: Path = field(default_factory=lambda: Path(
        os.getenv("RCO_STORAGE_ROOT", str(Path.home() / ".research-copilot-os"))
    ))
    chunk_cache_dir: Path = field(default_factory=lambda: Path(
        os.getenv("RCO_STORAGE_ROOT", str(Path.home() / ".research-copilot-os"))
    ) / "chunks")
    vector_db_dir: Path = field(default_factory=lambda: Path(
        os.getenv("RCO_STORAGE_ROOT", str(Path.home() / ".research-copilot-os"))
    ) / "vectors")
    experiment_log_dir: Path = field(default_factory=lambda: Path(
        os.getenv("RCO_STORAGE_ROOT", str(Path.home() / ".research-copilot-os"))
    ) / "experiments")


@dataclass
class Config:
    llm: LLMConfig = field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    debug: bool = False

    def __post_init__(self):
        for d in [self.storage.chunk_cache_dir, self.storage.vector_db_dir,
                   self.storage.experiment_log_dir]:
            d.mkdir(parents=True, exist_ok=True)


_config: Optional[Config] = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config


def init_config(**kwargs) -> Config:
    global _config
    _config = Config(**kwargs)
    return _config
