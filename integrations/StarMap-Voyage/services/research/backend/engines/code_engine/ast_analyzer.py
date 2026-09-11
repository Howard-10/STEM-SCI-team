"""基于 AST 的 PyTorch 代码静态分析器

功能：
1. 识别 Dataset, DataLoader, nn.Module, Loss, Optimizer, Train/Val Loop
2. 在 nn.Module 中自动识别 forward 方法、子模块结构
3. 根据函数名（augment, preprocess 等）识别数据处理块
4. 进行简单的 Tensor Shape 推断
"""

import ast
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional

from backend.core.models import (
    ChunkCategory,
    CodeChunk,
    CodeAnalysisResult,
    ModuleInfo,
)


class PyTorchASTAnalyzer:
    """PyTorch 项目 AST 分析器"""

    # 类别推断关键词映射
    CATEGORY_KEYWORDS = {
        ChunkCategory.DATA_PROCESSING: [
            "preprocess", "process_data", "transform", "normalize",
            "tokenize", "encode", "decode", "clean", "filter_data",
            "prepare_data", "load_data", "read_data",
        ],
        ChunkCategory.DATA_AUGMENTATION: [
            "augment", "augmentation", "random_crop", "random_flip",
            "random_rotate", "mixup", "cutout", "cutmix", "randaugment",
            "noise", "blur", "distortion", "color_jitter",
        ],
        ChunkCategory.DATA_LOADER: [
            "dataloader", "data_loader", "get_loader", "make_loader",
        ],
        ChunkCategory.LOSS_FUNCTION: [
            "loss", "criterion", "cost", "objective",
            "cross_entropy", "mse_loss", "nll_loss", "bce_loss",
        ],
        ChunkCategory.OPTIMIZER: [
            "optimizer", "optim", "lr_scheduler", "scheduler",
            "get_optimizer", "configure_optimizers",
        ],
        ChunkCategory.TRAINING_LOOP: [
            "train_epoch", "train_step", "training_step", "fit",
            "train_loop", "training_loop",
        ],
        ChunkCategory.VALIDATION_LOOP: [
            "val_epoch", "validate", "validation_step", "val_step",
            "eval_epoch", "test_epoch", "evaluate",
        ],
    }

    # PyTorch 模块类型映射
    TORCH_MODULE_ALIASES = {
        "nn.Module", "nn.Linear", "nn.Conv2d", "nn.Conv1d", "nn.Conv3d",
        "nn.BatchNorm1d", "nn.BatchNorm2d", "nn.LayerNorm", "nn.GroupNorm",
        "nn.Dropout", "nn.ReLU", "nn.GELU", "nn.SiLU", "nn.Sigmoid",
        "nn.Tanh", "nn.LSTM", "nn.GRU", "nn.TransformerEncoder",
        "nn.TransformerDecoder", "nn.MultiheadAttention", "nn.Embedding",
        "nn.MaxPool2d", "nn.AvgPool2d", "nn.AdaptiveAvgPool2d",
        "nn.Upsample", "nn.ConvTranspose2d", "nn.Flatten",
        "torch.nn.Linear", "torch.nn.Conv2d", "torch.nn.BatchNorm2d",
    }

    def __init__(self):
        self._source_cache: dict[str, str] = {}
        self._line_counts: dict[str, int] = {}

    def analyze_project(self, project_path: str) -> CodeAnalysisResult:
        """分析整个项目文件夹"""
        chunks = []
        all_modules = []
        data_flow = defaultdict(list)

        py_files = self._collect_python_files(project_path)

        for file_path in py_files:
            try:
                file_chunks, file_modules = self._analyze_file(file_path, project_path)
                chunks.extend(file_chunks)
                all_modules.extend(file_modules)
            except SyntaxError:
                continue
            except Exception as e:
                from backend.core.error_logger import log_error
                log_error("ast_analyzer.analyze_project", e, f"file={file_path}")
                continue

        # 构建数据流图
        data_flow = self._build_data_flow(chunks)

        # 生成总结
        summary = self._generate_summary(chunks)

        return CodeAnalysisResult(
            project_path=project_path,
            chunks=chunks,
            summary=summary,
            model_architecture=all_modules,
            data_flow=data_flow,
        )

    def _collect_python_files(self, project_path: str) -> list[str]:
        """收集项目中的所有 Python 文件"""
        py_files = []
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in
                        ("__pycache__", "node_modules", ".git", "venv", ".venv",
                         "env", "checkpoints", "outputs", "logs", "wandb")]
            for f in files:
                if f.endswith(".py"):
                    py_files.append(os.path.join(root, f))
        return py_files

    def _read_source(self, file_path: str) -> str:
        if file_path not in self._source_cache:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                self._source_cache[file_path] = f.read()
            self._line_counts[file_path] = len(self._source_cache[file_path].splitlines())
        return self._source_cache[file_path]

    def _analyze_file(
        self, file_path: str, project_root: str
    ) -> tuple[list[CodeChunk], list[ModuleInfo]]:
        """分析单个 Python 文件"""
        source = self._read_source(file_path)
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return [], []

        rel_path = os.path.relpath(file_path, project_root)
        chunks = []
        modules = []

        # 遍历顶层节点
        for node in ast.iter_child_nodes(tree):
            # 类定义
            if isinstance(node, ast.ClassDef):
                cls_chunks, cls_modules = self._analyze_class(node, source, rel_path)
                chunks.extend(cls_chunks)
                modules.extend(cls_modules)

            # 函数定义
            elif isinstance(node, ast.FunctionDef):
                chunk = self._analyze_top_function(node, source, rel_path)
                if chunk:
                    chunks.append(chunk)

            # 顶层赋值（可能是配置）
            elif isinstance(node, ast.Assign):
                chunk = self._analyze_top_assign(node, source, rel_path)
                if chunk:
                    chunks.append(chunk)

        return chunks, modules

    def _analyze_class(
        self, node: ast.ClassDef, source: str, rel_path: str
    ) -> tuple[list[CodeChunk], list[ModuleInfo]]:
        """分析类定义"""
        chunks = []
        modules = []

        base_names = self._get_base_names(node)
        is_nn_module = any("Module" in b or "nn.Module" in b for b in base_names)
        is_dataset = any("Dataset" in b for b in base_names)
        is_loss = any("Loss" in b or "_loss" in b.lower() for b in base_names)

        # 提取类完整源代码
        class_source = ast.get_source_segment(source, node) or ""
        class_lines = (node.lineno, node.end_lineno or node.lineno)

        if is_nn_module:
            # 解析 nn.Module 子类
            module_info = self._parse_nn_module(node, source)
            if module_info:
                modules.append(module_info)

            # 分离 forward 方法
            forward_methods = []
            other_methods = []
            sub_classes = []

            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == "forward":
                    forward_methods.append(child)
                elif isinstance(child, ast.FunctionDef):
                    other_methods.append(child)
                elif isinstance(child, ast.ClassDef):
                    sub_classes.append(child)

            # 创建模型定义块（不含 forward）
            if node.body:
                chunks.append(CodeChunk(
                    chunk_id=f"{rel_path}:{node.name}:model_def",
                    category=ChunkCategory.MODEL_DEFINITION,
                    name=f"Model: {node.name}",
                    file_path=rel_path,
                    source_code=class_source,
                    start_line=class_lines[0],
                    end_line=class_lines[1],
                    description=f"nn.Module: {node.name}, 基类: {', '.join(base_names)}",
                    modules=[module_info] if module_info else [],
                ))

            # 创建 forward 传播块
            for fwd in forward_methods:
                fwd_source = ast.get_source_segment(source, fwd) or ""
                fwd_lines = (fwd.lineno, fwd.end_lineno or fwd.lineno)
                chunks.append(CodeChunk(
                    chunk_id=f"{rel_path}:{node.name}:forward",
                    category=ChunkCategory.FORWARD_PROPAGATION,
                    name=f"Forward: {node.name}.forward",
                    file_path=rel_path,
                    source_code=fwd_source,
                    start_line=fwd_lines[0],
                    end_line=fwd_lines[1],
                    description=f"前向传播: {node.name}.forward()",
                ))

            # 其他方法
            for method in other_methods:
                method_source = ast.get_source_segment(source, method) or ""
                method_lines = (method.lineno, method.end_lineno or method.lineno)
                category = self._infer_function_category(method.name)
                chunks.append(CodeChunk(
                    chunk_id=f"{rel_path}:{node.name}:{method.name}",
                    category=category,
                    name=f"{node.name}.{method.name}",
                    file_path=rel_path,
                    source_code=method_source,
                    start_line=method_lines[0],
                    end_line=method_lines[1],
                    description=f"方法: {node.name}.{method.name}()",
                ))

        elif is_dataset:
            chunks.append(CodeChunk(
                chunk_id=f"{rel_path}:{node.name}:dataset",
                category=ChunkCategory.DATA_PROCESSING,
                name=f"Dataset: {node.name}",
                file_path=rel_path,
                source_code=class_source,
                start_line=class_lines[0],
                end_line=class_lines[1],
                description=f"数据集类: {node.name}, 基类: {', '.join(base_names)}",
            ))

        elif is_loss:
            chunks.append(CodeChunk(
                chunk_id=f"{rel_path}:{node.name}:loss",
                category=ChunkCategory.LOSS_FUNCTION,
                name=f"Loss: {node.name}",
                file_path=rel_path,
                source_code=class_source,
                start_line=class_lines[0],
                end_line=class_lines[1],
                description=f"损失函数: {node.name}",
            ))

        else:
            # 通用类
            chunks.append(CodeChunk(
                chunk_id=f"{rel_path}:{node.name}:class",
                category=ChunkCategory.UTILITY,
                name=f"Class: {node.name}",
                file_path=rel_path,
                source_code=class_source,
                start_line=class_lines[0],
                end_line=class_lines[1],
                description=f"类: {node.name}",
            ))

        return chunks, modules

    def _analyze_top_function(
        self, node: ast.FunctionDef, source: str, rel_path: str
    ) -> Optional[CodeChunk]:
        """分析顶层函数"""
        func_source = ast.get_source_segment(source, node) or ""
        func_lines = (node.lineno, node.end_lineno or node.lineno)
        category = self._infer_function_category(node.name)

        return CodeChunk(
            chunk_id=f"{rel_path}:{node.name}",
            category=category,
            name=f"Function: {node.name}",
            file_path=rel_path,
            source_code=func_source,
            start_line=func_lines[0],
            end_line=func_lines[1],
            description=f"函数: {node.name}()",
        )

    def _analyze_top_assign(
        self, node: ast.Assign, source: str, rel_path: str
    ) -> Optional[CodeChunk]:
        """分析顶层赋值（检测配置）"""
        for target in node.targets:
            if isinstance(target, ast.Name):
                name = target.id.lower()
                if any(kw in name for kw in ("config", "cfg", "args", "param",
                                               "hyper", "setting", "constant")):
                    assign_source = ast.get_source_segment(source, node) or ""
                    return CodeChunk(
                        chunk_id=f"{rel_path}:config:{target.id}",
                        category=ChunkCategory.CONFIG,
                        name=f"Config: {target.id}",
                        file_path=rel_path,
                        source_code=assign_source,
                        start_line=node.lineno,
                        end_line=node.end_lineno or node.lineno,
                        description=f"配置变量: {target.id}",
                    )
        return None

    def _get_base_names(self, node: ast.ClassDef) -> list[str]:
        """获取基类名称列表"""
        names = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                names.append(base.id)
            elif isinstance(base, ast.Attribute):
                names.append(ast.unparse(base))
            elif isinstance(base, ast.Call):
                if isinstance(base.func, ast.Name):
                    names.append(base.func.id)
                elif isinstance(base.func, ast.Attribute):
                    names.append(ast.unparse(base.func))
        return names

    def _infer_function_category(self, name: str) -> ChunkCategory:
        """根据函数名推断类别"""
        name_lower = name.lower()
        for category, keywords in self.CATEGORY_KEYWORDS.items():
            for kw in keywords:
                if kw in name_lower:
                    return category
        return ChunkCategory.UTILITY

    def _parse_nn_module(
        self, node: ast.ClassDef, source: str
    ) -> Optional[ModuleInfo]:
        """解析 nn.Module 子类，提取子模块信息"""
        module_info = ModuleInfo(
            name=node.name,
            module_type="nn.Module",
            source_lines=(node.lineno, node.end_lineno or node.lineno),
        )

        # 查找 __init__ 中的子模块赋值
        init_method = None
        for child in node.body:
            if isinstance(child, ast.FunctionDef) and child.name == "__init__":
                init_method = child
                break

        if init_method:
            sub_modules = []
            for stmt in ast.walk(init_method):
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                            value_str = ast.unparse(stmt.value)
                            child_info = self._extract_child_module_info(target.attr, value_str, stmt)
                            if child_info:
                                sub_modules.append(child_info)
            module_info.children = sub_modules

        return module_info

    def _extract_child_module_info(
        self, name: str, value_str: str, node: ast.AST
    ) -> Optional[ModuleInfo]:
        """提取子模块的类型和参数信息"""
        module_type = "unknown"
        in_channels = None
        out_channels = None

        # 识别 nn.xxx 调用
        for alias in self.TORCH_MODULE_ALIASES:
            if alias in value_str:
                module_type = alias.split(".")[-1] if "." in alias else alias
                break

        # 尝试提取 in/out channels
        channel_patterns = [
            r"nn\.Linear\((\d+),\s*(\d+)",
            r"nn\.Conv[12]d\((\d+),\s*(\d+)",
            r"nn\.ConvTranspose[12]d\((\d+),\s*(\d+)",
        ]
        for pat in channel_patterns:
            match = re.search(pat, value_str)
            if match:
                in_channels = int(match.group(1))
                out_channels = int(match.group(2))
                break

        return ModuleInfo(
            name=name,
            module_type=module_type,
            input_shape=[in_channels] if in_channels else None,
            output_shape=[out_channels] if out_channels else None,
        )

    def _build_data_flow(self, chunks: list[CodeChunk]) -> dict[str, list[str]]:
        """构建数据流关系图"""
        flow = defaultdict(list)
        category_order = [
            ChunkCategory.DATA_PROCESSING,
            ChunkCategory.DATA_AUGMENTATION,
            ChunkCategory.DATA_LOADER,
            ChunkCategory.MODEL_DEFINITION,
            ChunkCategory.FORWARD_PROPAGATION,
            ChunkCategory.LOSS_FUNCTION,
            ChunkCategory.OPTIMIZER,
            ChunkCategory.TRAINING_LOOP,
            ChunkCategory.VALIDATION_LOOP,
        ]
        for i, cat in enumerate(category_order):
            cat_chunks = [c for c in chunks if c.category == cat]
            if cat_chunks and i + 1 < len(category_order):
                next_cat = category_order[i + 1]
                next_chunks = [c for c in chunks if c.category == next_cat]
                if next_chunks:
                    flow[cat.value].extend([c.name for c in next_chunks])
        return dict(flow)

    def _generate_summary(self, chunks: list[CodeChunk]) -> str:
        """生成分析摘要"""
        cat_counts = defaultdict(int)
        for c in chunks:
            cat_counts[c.category.value] += 1

        lines = ["=== 代码分析摘要 ===", f"总代码块数: {len(chunks)}", "", "按类别统计:"]
        for cat in ChunkCategory:
            count = cat_counts.get(cat.value, 0)
            if count > 0:
                lines.append(f"  {cat.value}: {count} 块")
        return "\n".join(lines)


def analyze_project(project_path: str) -> CodeAnalysisResult:
    """便捷函数：分析项目"""
    analyzer = PyTorchASTAnalyzer()
    return analyzer.analyze_project(project_path)
