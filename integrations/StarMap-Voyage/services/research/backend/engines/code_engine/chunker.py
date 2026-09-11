"""代码分块引擎 — 按功能/模块对项目代码进行分块

功能 3: 输入文件夹（论文代码），按功能/模块分块
功能 4: 模块迁移对齐 + 风险评估 + 推荐
"""

import json
import os
from pathlib import Path
from typing import Optional

from backend.core.config import get_config
from backend.core.llm_client import get_llm_client
from backend.core.models import ChunkCategory, CodeChunk, CodeAnalysisResult
from .ast_analyzer import analyze_project


class CodeChunker:
    """代码分块器：AST 自动分块 + LLM 语义增强"""

    def __init__(self):
        self.llm = get_llm_client()
        self.cfg = get_config()

    def chunk_project(
        self,
        project_path: str,
        strategy: str = "auto",  # "function", "module", "auto"
    ) -> CodeAnalysisResult:
        """对项目进行分块分析"""
        result = analyze_project(project_path)

        # 用 LLM 增强分块描述和分类
        if strategy in ("auto", "function", "module"):
            result = self._enhance_with_llm(result, strategy)

        # 缓存结果
        self._cache_result(project_path, result)

        return result

    def _enhance_with_llm(
        self, result: CodeAnalysisResult, strategy: str
    ) -> CodeAnalysisResult:
        """使用 LLM 增强分块质量"""
        # 对每个 chunk 生成更详细的描述
        chunk_summaries = []
        for chunk in result.chunks[:30]:
            chunk_summaries.append(
                f"[{chunk.chunk_id}] ({chunk.category.value})\n"
                f"```python\n{chunk.source_code[:800]}\n```"
            )

        if not chunk_summaries:
            return result

        prompt = f"""以下是 PyTorch 项目的代码块摘要。请分析每个代码块，修正分类错误，并为每个块写一行中文描述。

项目路径: {result.project_path}

代码块列表:
{chr(10).join(chunk_summaries)}

请以 JSON 格式返回修正结果（只返回 JSON）：
{{"corrections": [
    {{"chunk_id": "原ID", "category": "正确类别（从以下选一: data_processing, data_augmentation, data_loader, model_definition, forward_propagation, backward_propagation, loss_function, optimizer, training_loop, validation_loop, evaluation, config, utility）", "description": "一句话中文描述"}}
]}}"""

        try:
            resp = self.llm.structured_output(
                system_prompt="你是 PyTorch 代码分析专家。请精确分析代码块的类别并给出描述。",
                user_prompt=prompt,
                output_schema={
                    "corrections": [
                        {"chunk_id": "str", "category": "str", "description": "str"}
                    ]
                },
            )
            corrections = {c["chunk_id"]: c for c in resp.get("corrections", [])}

            for chunk in result.chunks:
                if chunk.chunk_id in corrections:
                    corr = corrections[chunk.chunk_id]
                    try:
                        chunk.category = ChunkCategory(corr["category"])
                    except ValueError:
                        pass
                    chunk.description = corr.get("description", chunk.description)
        except Exception as e:
            from backend.core.error_logger import log_error
            log_error("chunker._enhance_with_llm", e)

        return result

    def _cache_result(self, project_path: str, result: CodeAnalysisResult):
        """缓存分析结果"""
        cache_dir = self.cfg.storage.chunk_cache_dir
        project_name = Path(project_path).name
        cache_file = cache_dir / f"{project_name}_analysis.json"

        cache_data = {
            "project_path": result.project_path,
            "summary": result.summary,
            "chunks": [
                {
                    "chunk_id": c.chunk_id,
                    "category": c.category.value,
                    "name": c.name,
                    "file_path": c.file_path,
                    "start_line": c.start_line,
                    "end_line": c.end_line,
                    "description": c.description,
                    "source_code": c.source_code,
                }
                for c in result.chunks
            ],
            "data_flow": result.data_flow,
        }
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)

    def get_chunks_by_category(
        self, result: CodeAnalysisResult, category: ChunkCategory
    ) -> list[CodeChunk]:
        """按类别过滤代码块"""
        return [c for c in result.chunks if c.category == category]

    def get_module_chunks(self, result: CodeAnalysisResult) -> list[CodeChunk]:
        """获取所有模型相关的块"""
        return [
            c for c in result.chunks
            if c.category in (
                ChunkCategory.MODEL_DEFINITION,
                ChunkCategory.FORWARD_PROPAGATION,
            )
        ]

    def get_data_chunks(self, result: CodeAnalysisResult) -> list[CodeChunk]:
        """获取所有数据处理相关的块"""
        return [
            c for c in result.chunks
            if c.category in (
                ChunkCategory.DATA_PROCESSING,
                ChunkCategory.DATA_AUGMENTATION,
                ChunkCategory.DATA_LOADER,
            )
        ]


    def classify_chunks(self, result: CodeAnalysisResult) -> dict:
        """将代码块按内容归类到 6 个顶层类别"""
        # 只取模型相关块，跳过纯工具函数
        model_chunks = [
            c for c in result.chunks
            if c.category not in (ChunkCategory.UTILITY,)
        ]
        if not model_chunks:
            model_chunks = result.chunks

        # 构建每个块的摘要
        items = []
        for c in model_chunks[:60]:
            items.append({
                "chunk_id": c.chunk_id,
                "name": c.name,
                "file": c.file_path,
                "category_hint": c.category.value,
                "code_preview": c.source_code[:600],
            })

        classify_prompt = """你是一位深度学习代码架构师。请根据以下代码块的内容，将它们归类到 6 个顶层类别中。

===== 6 个顶层类别 =====
1. 参数与配置 (params_config): 超参数定义、模型维度设置、配置文件、argparse 参数解析、全局常量 (如 LEARNING_RATE, BATCH_SIZE, EPOCHS, HIDDEN_DIM)
2. 模型架构 (model_arch): nn.Module 子类定义、__init__ 中的层定义、forward 方法、attention/transformer/CNN/RNN 等网络结构、自定义模块
3. 数据处理 (data_pipeline): Dataset 类、DataLoader 创建、数据预处理 (preprocess/normalize/tokenize)、数据增强 (augment/crop/flip)、特征提取
4. 训练与优化 (train_optim): 训练循环 (train_epoch/training_step)、优化器定义、损失函数、学习率调度器、反向传播、梯度操作
5. 评估与日志 (eval_logging): 验证/测试循环 (validate/evaluate/test)、指标计算 (accuracy/F1/precision)、TensorBoard/WandB 日志、模型保存/加载
6. 工具与入口 (utils_entry): main 函数、训练启动脚本、辅助工具函数、文件 I/O、可视化绘图、checkpoint 管理

===== 代码块列表 =====
{items_json}

===== 要求 =====
返回 JSON，将每个 chunk_id 映射到上述 6 个类别之一:
{{"classification": {{"chunk_id_1": "model_arch", "chunk_id_2": "data_pipeline", ...}}}}"""

        try:
            resp = self.llm.structured_output(
                system_prompt="你是深度学习代码架构专家。请根据代码内容精确分类。",
                user_prompt=classify_prompt.format(items_json=json.dumps(items, ensure_ascii=False, indent=2)),
                output_schema={"classification": {"chunk_id_example": "model_arch"}},
            )
            classification = resp.get("classification", {})

            # 分组
            groups = {
                "params_config": {"label": "📐 参数与配置", "chunks": []},
                "model_arch": {"label": "🏗️ 模型架构", "chunks": []},
                "data_pipeline": {"label": "📊 数据处理", "chunks": []},
                "train_optim": {"label": "🔄 训练与优化", "chunks": []},
                "eval_logging": {"label": "📈 评估与日志", "chunks": []},
                "utils_entry": {"label": "🔧 工具与入口", "chunks": []},
            }

            for chunk in model_chunks:
                cat = classification.get(chunk.chunk_id, "utils_entry")
                if cat in groups:
                    groups[cat]["chunks"].append({
                        "chunk_id": chunk.chunk_id,
                        "name": chunk.name,
                        "file_path": chunk.file_path,
                        "start_line": chunk.start_line,
                        "end_line": chunk.end_line,
                        "description": chunk.description,
                        "source_code": chunk.source_code,
                        "original_category": chunk.category.value,
                    })
                else:
                    groups["utils_entry"]["chunks"].append({
                        "chunk_id": chunk.chunk_id,
                        "name": chunk.name,
                        "file_path": chunk.file_path,
                        "start_line": chunk.start_line,
                        "end_line": chunk.end_line,
                        "description": chunk.description,
                        "source_code": chunk.source_code,
                        "original_category": chunk.category.value,
                    })

            # 统计
            summary = "### 代码分类结果\n\n"
            for key, info in groups.items():
                count = len(info["chunks"])
                if count > 0:
                    summary += f"- {info['label']}: **{count}** 个代码块\n"

            return {"groups": groups, "summary": summary, "total_chunks": len(model_chunks)}
        except Exception as e:
            from backend.core.error_logger import log_error
            log_error("chunker.classify_chunks", e)
            return {"groups": {}, "summary": f"分类失败: {e}", "total_chunks": 0}


class ModuleMigrationEngine:
    """智能模块迁移引擎 — 功能 4

    支持：
    - 将源模型子模块迁移到目标模型
    - 自动检测 in_channels/out_channels 维度不匹配
    - 自动生成适配层（nn.Linear, nn.Conv2d）
    - 风险评估：梯度中断、计算图连续性检查
    - 推荐：基于性能瓶颈推荐要迁移的模块
    """

    def __init__(self):
        self.llm = get_llm_client()

    def align_and_migrate(
        self,
        source_chunk: CodeChunk,
        target_project_path: str,
        target_model_file: str,
    ) -> dict:
        """将源模块对齐并迁移到目标模型"""
        # 分析目标模型
        target_result = analyze_project(target_project_path)

        # 找到目标模型的定义块
        target_model_chunks = [
            c for c in target_result.chunks
            if c.category == ChunkCategory.MODEL_DEFINITION
        ]

        if not target_model_chunks:
            return {"success": False, "error": "目标项目中未找到模型定义"}

        target_model = target_model_chunks[0]

        # 提取源模块的输入输出形状
        source_shapes = self._extract_shapes(source_chunk)
        target_shapes = self._extract_shapes(target_model)

        # 生成迁移方案
        migration_plan = self._generate_migration_plan(
            source_chunk, target_model, source_shapes, target_shapes
        )

        # 风险评估
        risk_assessment = self._assess_risks(source_chunk, target_model, migration_plan)

        return {
            "success": True,
            "source_module": source_chunk.name,
            "target_model": target_model.name,
            "migration_plan": migration_plan,
            "risk_assessment": risk_assessment,
            "adapter_code": migration_plan.get("adapter_code", ""),
            "merged_code": migration_plan.get("merged_code", ""),
        }

    def _extract_shapes(self, chunk: CodeChunk) -> dict:
        """从代码块中提取张量形状信息"""
        shapes = {"inputs": [], "outputs": []}

        # 从 module_info 提取
        for mod in chunk.modules:
            if mod.input_shape:
                shapes["inputs"].append(mod.input_shape)
            if mod.output_shape:
                shapes["outputs"].append(mod.output_shape)

        # 从源码中搜索常见形状注释
        import re

        shape_patterns = [
            r"#\s*input\s*shape\s*[:=]\s*\(?\[?([\d,\s]+)\]?\)?",
            r"#\s*output\s*shape\s*[:=]\s*\(?\[?([\d,\s]+)\]?\)?",
            r"in_channels\s*[:=]\s*(\d+)",
            r"out_channels\s*[:=]\s*(\d+)",
        ]

        return shapes

    def _generate_migration_plan(
        self,
        source: CodeChunk,
        target: CodeChunk,
        source_shapes: dict,
        target_shapes: dict,
    ) -> dict:
        """使用 LLM 生成详细的迁移方案"""
        prompt = f"""你是深度学习模型架构专家。请分析以下模块迁移方案：

## 源模块（要迁移的）
来自文件: {source.file_path}
类别: {source.category.value}
```python
{source.source_code[:1500]}
```

## 目标模型（迁移到的位置）
来自文件: {target.file_path}
```python
{target.source_code[:1500]}
```

请提供详细的迁移方案，包括：
1. 适配层设计（如果维度不匹配，自动生成 nn.Linear/Conv2d 适配代码）
2. 插入位置（在目标模型的哪个位置插入模块）
3. 完整的合并代码

以 JSON 格式返回：
{{"compatible": true/false, "dimension_mismatch": "描述", "adapter_code": "适配层代码", "insert_position": "插入位置", "merged_code": "完整合并代码", "explanation": "迁移说明"}}"""

        try:
            return self.llm.structured_output(
                system_prompt="你是深度学习模型架构与 PyTorch 实现专家。",
                user_prompt=prompt,
                output_schema={
                    "compatible": True,
                    "dimension_mismatch": "str",
                    "adapter_code": "str",
                    "insert_position": "str",
                    "merged_code": "str",
                    "explanation": "str",
                },
            )
        except Exception as e:
            from backend.core.error_logger import log_error
            log_error("chunker._generate_migration_plan", e)
            return {"compatible": False, "error": str(e)}

    def _assess_risks(
        self, source: CodeChunk, target: CodeChunk, migration_plan: dict
    ) -> dict:
        """评估迁移风险"""
        prompt = f"""你是深度学习模型安全审查专家。请评估以下模块迁移的风险：

## 源模块
```python
{source.source_code[:1000]}
```

## 目标模型
```python
{target.source_code[:1000]}
```

## 迁移方案
{json.dumps(migration_plan, ensure_ascii=False, indent=2)[:1500]}

请检查：
1. 计算图连续性风险（是否会中断梯度传播）
2. 维度匹配风险
3. 训练稳定性风险
4. 性能影响风险

以 JSON 返回：
{{"overall_risk": "low/medium/high", "gradient_risk": "描述", "dimension_risk": "描述", "stability_risk": "描述", "performance_risk": "描述", "recommendations": ["建议1", "建议2"]}}"""

        try:
            return self.llm.structured_output(
                system_prompt="你是深度学习模型安全与性能分析专家。",
                user_prompt=prompt,
                output_schema={
                    "overall_risk": "str",
                    "gradient_risk": "str",
                    "dimension_risk": "str",
                    "stability_risk": "str",
                    "performance_risk": "str",
                    "recommendations": ["str"],
                },
            )
        except Exception as e:
            return {"overall_risk": "unknown", "error": str(e)}

    def recommend_modules(
        self, result: CodeAnalysisResult, target_description: str = ""
    ) -> list[dict]:
        """基于分析结果推荐可迁移的亮点模块"""
        model_chunks = [
            c for c in result.chunks
            if c.category in (ChunkCategory.MODEL_DEFINITION,
                              ChunkCategory.FORWARD_PROPAGATION)
        ]

        if len(model_chunks) < 2:
            return []

        chunks_text = []
        for i, chunk in enumerate(model_chunks[:10]):
            chunks_text.append(
                f"[模块 {i}] {chunk.name}\n```python\n{chunk.source_code[:600]}\n```"
            )

        prompt = f"""以下是论文代码中的模块列表。请分析每个模块的创新性和可迁移性。

{'目标描述: ' + target_description if target_description else ''}

模块列表:
{chr(10).join(chunks_text)}

请为每个模块评分，指出哪些有亮点、可以迁移到其他模型。返回 JSON:
{{"recommendations": [
    {{"module_index": 0, "name": "模块名", "innovation_score": 1-10, "transferability": "high/medium/low", "reason": "推荐理由", "target_scenario": "适用场景"}}
]}}"""

        try:
            resp = self.llm.structured_output(
                system_prompt="你是深度学习模型架构专家，擅长识别模型中的创新模块。",
                user_prompt=prompt,
                output_schema={
                    "recommendations": [
                        {
                            "module_index": 0,
                            "name": "str",
                            "innovation_score": 0,
                            "transferability": "str",
                            "reason": "str",
                            "target_scenario": "str",
                        }
                    ]
                },
            )
            return resp.get("recommendations", [])
        except Exception:
            return []


_chunker: Optional[CodeChunker] = None
_migration_engine: Optional[ModuleMigrationEngine] = None


def get_chunker() -> CodeChunker:
    global _chunker
    if _chunker is None:
        _chunker = CodeChunker()
    return _chunker


def get_migration_engine() -> ModuleMigrationEngine:
    global _migration_engine
    if _migration_engine is None:
        _migration_engine = ModuleMigrationEngine()
    return _migration_engine
