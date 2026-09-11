"""Agent 工具系统 — 将四大引擎包装为标准化 Tool 接口

工具定义遵循 Claude/OpenAI function calling 格式，
每个工具有 name, description, parameters (JSON Schema), execute 函数。
"""

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from backend.engines.document_engine.rag import get_document_engine
from backend.engines.code_engine.chunker import get_chunker, get_migration_engine
from backend.engines.experiment_engine.data_adaptor import DatasetAdaptor, DataAugmentationEngine
from backend.engines.experiment_engine.ablation import AblationEngine, HyperParameterTuner, ExperimentLogger
from backend.engines.visualization_engine.plotter import VisualizationEngine


@dataclass
class ToolParameter:
    name: str
    type: str  # "string", "integer", "boolean", "array"
    description: str
    required: bool = True
    enum: Optional[list[str]] = None


@dataclass
class Tool:
    name: str
    description: str
    parameters: list[ToolParameter]
    execute: Callable[..., dict]
    category: str = ""  # "literature", "fusion", "data", "experiment"

    def to_openai_schema(self) -> dict:
        """转为 OpenAI function calling 格式"""
        properties = {}
        required = []
        for p in self.parameters:
            prop = {"type": p.type, "description": p.description}
            if p.enum:
                prop["enum"] = p.enum
            properties[p.name] = prop
            if p.required:
                required.append(p.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def to_claude_schema(self) -> dict:
        """转为 Claude tool_use 格式"""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    p.name: {"type": p.type, "description": p.description}
                    for p in self.parameters
                },
                "required": [p.name for p in self.parameters if p.required],
            },
        }


# ═══════════════════════════════════════════════════════════
#  工具执行函数
# ═══════════════════════════════════════════════════════════

def _analyze_paper_tool(file_path: str) -> dict:
    """工具: 单论文解读"""
    engine = get_document_engine()
    return engine.analyze_single_paper(file_path)


def _review_papers_tool(file_paths_json: str) -> dict:
    """工具: 多论文综述"""
    file_paths = json.loads(file_paths_json)
    engine = get_document_engine()
    result = engine.analyze_multiple_papers(file_paths)
    return {
        "clusters": result.clusters,
        "comparative_table": result.comparative_table,
        "narrative_synthesis": result.narrative_synthesis,
        "relationship_graph": result.relationship_graph,
    }


def _chunk_code_tool(project_path: str, strategy: str = "auto") -> dict:
    """工具: 代码分块"""
    chunker = get_chunker()
    result = chunker.chunk_project(project_path, strategy)
    return {
        "summary": result.summary,
        "total_chunks": len(result.chunks),
        "chunks": [
            {
                "chunk_id": c.chunk_id,
                "category": c.category.value,
                "name": c.name,
                "file_path": c.file_path,
                "description": c.description,
            }
            for c in result.chunks
        ],
        "data_flow": result.data_flow,
    }


def _recommend_modules_tool(project_path: str) -> dict:
    """工具: 推荐可迁移模块"""
    chunker = get_chunker()
    result = chunker.chunk_project(project_path)
    engine = get_migration_engine()
    recommendations = engine.recommend_modules(result)
    return {"recommendations": recommendations, "total": len(recommendations)}


def _migrate_module_tool(source_project: str, chunk_id: str, target_project: str) -> dict:
    """工具: 模块迁移"""
    chunker = get_chunker()
    source_result = chunker.chunk_project(source_project)
    source_chunk = None
    for c in source_result.chunks:
        if c.chunk_id == chunk_id:
            source_chunk = c
            break
    if not source_chunk:
        return {"success": False, "error": f"未找到 chunk: {chunk_id}"}

    engine = get_migration_engine()
    return engine.align_and_migrate(source_chunk, target_project, "")


def _inspect_dataset_tool(data_path: str) -> dict:
    """工具: 数据集解读"""
    adaptor = DatasetAdaptor()
    info = adaptor.inspect_dataset(data_path)
    return {
        "format": info.data_format,
        "samples": info.sample_count,
        "feature_shape": info.feature_shape,
        "label_type": info.label_type,
        "num_classes": info.num_classes,
    }


def _generate_dataloader_tool(data_path: str, model_code: str = "") -> dict:
    """工具: 生成 DataLoader"""
    adaptor = DatasetAdaptor()
    info = adaptor.inspect_dataset(data_path)
    code = adaptor.generate_data_loader(info, model_code)
    return {"code": code}


def _generate_augmentation_tool(operations_json: str, data_format: str, model_code: str = "") -> dict:
    """工具: 生成数据增强代码"""
    operations = json.loads(operations_json)
    engine = DataAugmentationEngine()
    code = engine.generate_augmentation_code(operations, data_format, model_code)
    return {"code": code}


def _generate_visualization_tool(model_code: str, paper_context: str = "") -> dict:
    """工具: 生成可视化套件"""
    engine = VisualizationEngine()
    paper_texts = [paper_context] if paper_context.strip() else []
    return engine.generate_full_visualization_suite(model_code, None, paper_texts)


def _plan_ablation_tool(project_path: str, strategy: str = "auto") -> dict:
    """工具: 规划消融实验"""
    chunker = get_chunker()
    result = chunker.chunk_project(project_path)
    engine = AblationEngine()
    ablations = engine.plan_ablations(result, strategy)
    return {
        "ablations": [
            {"name": a.name, "target": a.target_chunks, "description": a.description}
            for a in ablations
        ]
    }


def _identify_hyperparams_tool(code: str) -> dict:
    """工具: 识别超参数"""
    tuner = HyperParameterTuner()
    params = tuner.identify_hyperparameters(code)
    return {"hyperparameters": params}


def _generate_scheduler_tool(hyperparams_json: str, rules_json: str) -> dict:
    """工具: 生成超参数调度器"""
    hyperparams = json.loads(hyperparams_json)
    rules = json.loads(rules_json)
    tuner = HyperParameterTuner()
    code = tuner.generate_scheduler_code(hyperparams, rules)
    return {"code": code}


def _list_experiments_tool() -> dict:
    """工具: 列出实验记录"""
    logger = ExperimentLogger()
    experiments = logger.get_all_experiments()
    return {"experiments": experiments}


# ═══════════════════════════════════════════════════════════
#  工具注册表
# ═══════════════════════════════════════════════════════════

AGENT_TOOLS: list[Tool] = [
    # ── 文献整理与解读 ──
    Tool(
        name="analyze_paper",
        description="深度解读单篇论文 PDF。输入 PDF 文件路径，返回研究领域、方法论、贡献、模型框架、实验总结、优劣势分析。",
        parameters=[
            ToolParameter("file_path", "string", "PDF 文件的绝对路径"),
        ],
        execute=_analyze_paper_tool,
        category="literature",
    ),
    Tool(
        name="review_papers",
        description="多论文综述分析。输入多个 PDF 路径，自动分类聚类、生成对比表格、撰写综述报告、构建关系图谱。",
        parameters=[
            ToolParameter("file_paths_json", "string", '论文路径的 JSON 数组, 如 ["/path/a.pdf","/path/b.pdf"]'),
        ],
        execute=_review_papers_tool,
        category="literature",
    ),

    # ── 模型融合 ──
    Tool(
        name="chunk_code",
        description="对 PyTorch 项目进行 AST 代码分块。按功能识别模型定义、前向传播、数据处理、训练循环等代码块。",
        parameters=[
            ToolParameter("project_path", "string", "项目文件夹的绝对路径"),
            ToolParameter("strategy", "string", "分块策略: auto/function/module", required=False),
        ],
        execute=_chunk_code_tool,
        category="fusion",
    ),
    Tool(
        name="recommend_modules",
        description="分析项目代码，推荐具有创新性的、可迁移到其他模型的亮点模块。",
        parameters=[
            ToolParameter("project_path", "string", "项目文件夹的绝对路径"),
        ],
        execute=_recommend_modules_tool,
        category="fusion",
    ),
    Tool(
        name="migrate_module",
        description="将源项目中的某个模块迁移到目标项目，自动生成适配代码和风险评估。",
        parameters=[
            ToolParameter("source_project", "string", "源项目路径"),
            ToolParameter("chunk_id", "string", "要迁移的代码块 ID（从 chunk_code 结果中获取）"),
            ToolParameter("target_project", "string", "目标项目路径"),
        ],
        execute=_migrate_module_tool,
        category="fusion",
    ),

    # ── 数据处理 ──
    Tool(
        name="inspect_dataset",
        description="自动解读数据集格式、样本数、特征维度、标签类型等关键信息。",
        parameters=[
            ToolParameter("data_path", "string", "数据集路径"),
        ],
        execute=_inspect_dataset_tool,
        category="data",
    ),
    Tool(
        name="generate_dataloader",
        description="根据数据集格式和模型代码，自动生成适配的 PyTorch DataLoader 代码。",
        parameters=[
            ToolParameter("data_path", "string", "数据集路径"),
            ToolParameter("model_code", "string", "模型代码（可选，用于更好的适配）", required=False),
        ],
        execute=_generate_dataloader_tool,
        category="data",
    ),
    Tool(
        name="generate_augmentation",
        description="根据选定的数据增强/攻击操作，生成适配数据形式和模型的增强代码。支持 MixUp, CutMix, FGSM, PGD 等 20 种操作。",
        parameters=[
            ToolParameter("operations_json", "string", '操作 ID 列表的 JSON 数组, 如 ["random_crop","mixup"]'),
            ToolParameter("data_format", "string", "数据形式: image/text/audio/video/tabular"),
            ToolParameter("model_code", "string", "模型代码（可选）", required=False),
        ],
        execute=_generate_augmentation_tool,
        category="data",
    ),

    # ── 实验模块 ──
    Tool(
        name="generate_visualization",
        description="根据模型代码和相关论文，自动规划并生成完整的可视化套件（训练曲线、特征分布、对比图等），使用 Morandi 学术配色。",
        parameters=[
            ToolParameter("model_code", "string", "完整的模型代码"),
            ToolParameter("paper_context", "string", "相关论文摘要（可选，用于学习该领域可视化习惯）", required=False),
        ],
        execute=_generate_visualization_tool,
        category="experiment",
    ),
    Tool(
        name="plan_ablation",
        description="基于代码分块结果自动规划消融实验方案，确定要注释哪些模块。",
        parameters=[
            ToolParameter("project_path", "string", "项目路径"),
            ToolParameter("strategy", "string", "消融策略: auto/module_by_module/grouped", required=False),
        ],
        execute=_plan_ablation_tool,
        category="experiment",
    ),
    Tool(
        name="identify_hyperparams",
        description="自动识别训练代码中的所有可调超参数（学习率、batch_size、dropout 等），标明当前值和调整建议。",
        parameters=[
            ToolParameter("code", "string", "完整的训练代码"),
        ],
        execute=_identify_hyperparams_tool,
        category="experiment",
    ),
    Tool(
        name="generate_scheduler",
        description="生成超参数动态调度器代码，支持在训练过程中每隔 N 个 epoch 改变超参数。",
        parameters=[
            ToolParameter("hyperparams_json", "string", "超参数列表的 JSON（从 identify_hyperparams 获取）"),
            ToolParameter("rules_json", "string", '调度规则的 JSON 数组, 如 [{"param":"lr","epoch":30,"new_value":0.0001}]'),
        ],
        execute=_generate_scheduler_tool,
        category="experiment",
    ),
    Tool(
        name="list_experiments",
        description="列出所有历史实验记录，包括超参数、训练/测试指标、epoch 日志。",
        parameters=[],
        execute=_list_experiments_tool,
        category="experiment",
    ),
]


class ToolRegistry:
    """工具注册表: 按名称查找、按类别筛选、获取 schema"""

    def __init__(self, tools: list[Tool] = None):
        self._tools: dict[str, Tool] = {}
        for t in (tools or AGENT_TOOLS):
            self._tools[t.name] = t

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_all(self) -> list[Tool]:
        return list(self._tools.values())

    def list_by_category(self, category: str) -> list[Tool]:
        return [t for t in self._tools.values() if t.category == category]

    def get_openai_schemas(self, tool_names: list[str] = None) -> list[dict]:
        names = tool_names or list(self._tools.keys())
        return [self._tools[n].to_openai_schema() for n in names if n in self._tools]

    def get_claude_schemas(self, tool_names: list[str] = None) -> list[dict]:
        names = tool_names or list(self._tools.keys())
        return [self._tools[n].to_claude_schema() for n in names if n in self._tools]

    def execute(self, name: str, **kwargs) -> dict:
        tool = self._tools.get(name)
        if not tool:
            return {"error": f"未知工具: {name}"}
        try:
            return tool.execute(**kwargs)
        except Exception as e:
            return {"error": f"工具执行失败: {str(e)}"}


_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
