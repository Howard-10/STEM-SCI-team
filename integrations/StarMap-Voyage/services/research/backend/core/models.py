"""共享数据模型"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ChunkCategory(str, Enum):
    DATA_PROCESSING = "data_processing"
    DATA_AUGMENTATION = "data_augmentation"
    DATA_LOADER = "data_loader"
    MODEL_DEFINITION = "model_definition"
    FORWARD_PROPAGATION = "forward_propagation"
    BACKWARD_PROPAGATION = "backward_propagation"
    LOSS_FUNCTION = "loss_function"
    OPTIMIZER = "optimizer"
    TRAINING_LOOP = "training_loop"
    VALIDATION_LOOP = "validation_loop"
    EVALUATION = "evaluation"
    CONFIG = "config"
    UTILITY = "utility"


@dataclass
class ModuleInfo:
    name: str
    module_type: str  # nn.Conv2d, nn.Linear, nn.TransformerEncoder, etc.
    input_shape: Optional[list] = None
    output_shape: Optional[list] = None
    parameters_count: int = 0
    source_lines: tuple[int, int] = (0, 0)
    children: list["ModuleInfo"] = field(default_factory=list)


@dataclass
class CodeChunk:
    chunk_id: str
    category: ChunkCategory
    name: str
    file_path: str
    source_code: str
    start_line: int
    end_line: int
    description: str = ""
    modules: list[ModuleInfo] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    input_shapes: list[list[int]] = field(default_factory=list)
    output_shapes: list[list[int]] = field(default_factory=list)


@dataclass
class CodeAnalysisResult:
    project_path: str
    chunks: list[CodeChunk]
    summary: str
    model_architecture: list[ModuleInfo]
    data_flow: dict[str, list[str]]
