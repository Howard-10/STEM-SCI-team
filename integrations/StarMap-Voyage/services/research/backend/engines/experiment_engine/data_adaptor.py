"""数据集自动适配器 — 功能 5 和 6

功能 5: 自动解读数据集形式 → 适配模型代码 → 生成数据处理逻辑
功能 6: 包装化数据增强/攻击操作
"""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from backend.core.config import get_config
from backend.core.llm_client import get_llm_client


@dataclass
class DatasetInfo:
    """数据集信息"""
    data_path: str
    data_format: str  # "image_folder", "csv", "json", "npy", "hdf5", "custom"
    sample_count: int
    feature_shape: list[int]  # 数据维度
    label_type: str  # "classification", "regression", "segmentation", "detection"
    num_classes: int
    train_split: float
    val_split: float
    test_split: float
    description: str


class DatasetAdaptor:
    """数据集自动适配器 — 功能 5"""

    def __init__(self):
        self.llm = get_llm_client()
        self.cfg = get_config()

    def inspect_dataset(self, data_path: str) -> DatasetInfo:
        """自动解读数据集形式"""
        info = DatasetInfo(
            data_path=data_path,
            data_format=self._detect_format(data_path),
            sample_count=0,
            feature_shape=[],
            label_type="classification",
            num_classes=0,
            train_split=0.7,
            val_split=0.15,
            test_split=0.15,
            description="",
        )

        # 采样分析
        samples = self._sample_data(data_path, info.data_format)
        info.sample_count = samples.get("count", 0)
        info.feature_shape = samples.get("feature_shape", [])
        info.label_type = samples.get("label_type", "classification")
        info.num_classes = samples.get("num_classes", 0)

        # LLM 增强描述
        info.description = self._describe_dataset(info, samples)

        return info

    def _detect_format(self, path: str) -> str:
        """检测数据集格式"""
        if os.path.isdir(path):
            files = os.listdir(path)
            # 检测图片文件夹结构（分类任务）
            subdirs = [f for f in files if os.path.isdir(os.path.join(path, f))]
            img_ext = {".jpg", ".png", ".jpeg", ".bmp", ".tiff", ".tif"}
            for subdir in subdirs:
                sub_files = os.listdir(os.path.join(path, subdir))
                if any(f.lower().endswith(tuple(img_ext)) for f in sub_files):
                    return "image_folder"
            # 检测 numpy 文件夹
            npy_files = [f for f in files if f.endswith(".npy")]
            if npy_files:
                return "npy"
            # 检测 CSV 文件夹
            csv_files = [f for f in files if f.endswith(".csv")]
            if csv_files:
                return "csv"
            return "custom"
        elif path.endswith(".csv"):
            return "csv"
        elif path.endswith(".json") or path.endswith(".jsonl"):
            return "json"
        elif path.endswith((".h5", ".hdf5")):
            return "hdf5"
        return "custom"

    def _sample_data(self, path: str, fmt: str) -> dict:
        """采样分析数据"""
        result = {"count": 0, "feature_shape": [], "label_type": "unknown", "num_classes": 0}

        try:
            if fmt == "image_folder":
                import numpy as np
                from PIL import Image

                classes = []
                all_files = []
                for subdir in os.listdir(path):
                    sub_path = os.path.join(path, subdir)
                    if os.path.isdir(sub_path):
                        classes.append(subdir)
                        img_files = [
                            os.path.join(sub_path, f)
                            for f in os.listdir(sub_path)
                            if f.lower().endswith((".jpg", ".png", ".jpeg"))
                        ]
                        all_files.extend(img_files)

                result["count"] = len(all_files)
                result["num_classes"] = len(classes)
                result["label_type"] = "classification"

                if all_files:
                    try:
                        img = Image.open(all_files[0])
                        if img.mode == "RGB":
                            result["feature_shape"] = [3, img.size[1], img.size[0]]
                        else:
                            result["feature_shape"] = [len(img.mode), img.size[1], img.size[0]]
                    except Exception:
                        result["feature_shape"] = [3, 224, 224]

            elif fmt == "csv":
                import pandas as pd
                df = pd.read_csv(path, nrows=100)
                result["count"] = len(df)
                result["feature_shape"] = [df.shape[1] - 1]
                if df.shape[1] > 1:
                    last_col = df.iloc[:, -1]
                    n_unique = last_col.nunique()
                    if n_unique <= 100 and n_unique / len(df) < 0.5:
                        result["label_type"] = "classification"
                        result["num_classes"] = n_unique
                    else:
                        result["label_type"] = "regression"

            elif fmt == "npy":
                import numpy as np
                data = np.load(path, allow_pickle=True)
                result["count"] = len(data)
                result["feature_shape"] = list(data.shape[1:])
                if data.dtype in (np.int32, np.int64) and len(data.shape) == 1:
                    result["label_type"] = "classification"
                    result["num_classes"] = len(np.unique(data))

            elif fmt == "json":
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    result["count"] = len(data)
                elif isinstance(data, dict):
                    result["count"] = len(data)

        except Exception as e:
            from backend.core.error_logger import log_error
            log_error("data_adaptor._sample_data", e, f"path={path}, fmt={fmt}")
            pass

        return result

    def _describe_dataset(self, info: DatasetInfo, samples: dict) -> str:
        """使用 LLM 生成数据集描述"""
        prompt = f"""请简要描述以下数据集：
- 格式: {info.data_format}
- 样本数: {info.sample_count}
- 特征维度: {info.feature_shape}
- 标签类型: {info.label_type}
- 类别数: {info.num_classes}

用 1-2 句话描述这个数据集的特点和建议的处理方式。"""

        try:
            return self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=256,
            )
        except Exception:
            return f"{info.data_format} 格式数据集，{info.sample_count} 样本"

    def generate_data_loader(
        self, dataset_info: DatasetInfo, model_code: str = ""
    ) -> str:
        """生成适配模型的数据加载代码"""
        prompt = f"""请根据数据集信息{'和目标模型代码' if model_code else ''}生成 PyTorch DataLoader 代码。

数据集信息:
- 格式: {dataset_info.data_format}
- 样本数: {dataset_info.sample_count}
- 特征维度: {dataset_info.feature_shape}
- 标签类型: {dataset_info.label_type}
- 类别数: {dataset_info.num_classes}

{'目标模型代码片段:' + model_code[:1500] if model_code else ''}

请生成完整的 Dataset 类和 DataLoader 创建代码，包括：
1. 自定义 Dataset 类（__init__, __len__, __getitem__）
2. 数据变换（transforms）
3. 训练/验证/测试集划分
4. DataLoader 创建

输出完整可运行的 Python 代码。"""

        try:
            return self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4096,
            )
        except Exception as e:
            return f"# 代码生成失败: {e}"


class DataAugmentationEngine:
    """包装化数据增强/攻击引擎 — 功能 6

    支持的增强操作:
    - 几何变换: 裁剪、翻转、旋转、缩放、平移
    - 色彩变换: 亮度、对比度、饱和度、色调
    - 模糊化: 高斯模糊、中值模糊、运动模糊
    - 噪声注入: 高斯噪声、椒盐噪声
    - 高级增强: MixUp, CutMix, CutOut, RandAugment
    - 数据攻击: FGSM, PGD, CW
    """

    AUGMENTATIONS = {
        "random_crop": {"name": "随机裁剪", "category": "几何变换"},
        "random_flip": {"name": "随机翻转", "category": "几何变换"},
        "random_rotation": {"name": "随机旋转", "category": "几何变换"},
        "random_resized_crop": {"name": "随机缩放裁剪", "category": "几何变换"},
        "random_affine": {"name": "随机仿射变换", "category": "几何变换"},
        "color_jitter": {"name": "颜色抖动", "category": "色彩变换"},
        "random_brightness": {"name": "随机亮度", "category": "色彩变换"},
        "random_contrast": {"name": "随机对比度", "category": "色彩变换"},
        "random_saturation": {"name": "随机饱和度", "category": "色彩变换"},
        "gaussian_blur": {"name": "高斯模糊", "category": "模糊化"},
        "median_blur": {"name": "中值模糊", "category": "模糊化"},
        "motion_blur": {"name": "运动模糊", "category": "模糊化"},
        "gaussian_noise": {"name": "高斯噪声", "category": "噪声注入"},
        "salt_pepper_noise": {"name": "椒盐噪声", "category": "噪声注入"},
        "mixup": {"name": "MixUp 混合", "category": "高级增强"},
        "cutmix": {"name": "CutMix 混合", "category": "高级增强"},
        "cutout": {"name": "CutOut 掩码", "category": "高级增强"},
        "randaugment": {"name": "RandAugment", "category": "高级增强"},
        "fgsm": {"name": "FGSM 攻击", "category": "数据攻击"},
        "pgd": {"name": "PGD 攻击", "category": "数据攻击"},
    }

    def __init__(self):
        self.llm = get_llm_client()

    def get_available_operations(self) -> list[dict]:
        """获取所有可用的数据增强/攻击操作"""
        return [
            {"id": op_id, "name": info["name"], "category": info["category"]}
            for op_id, info in self.AUGMENTATIONS.items()
        ]

    def generate_augmentation_code(
        self,
        operations: list[str],
        data_format: str,  # "image", "text", "audio", "video", "tabular"
        model_code: str = "",
    ) -> str:
        """根据选择的操作和数据形式生成适配代码"""
        op_descriptions = []
        for op in operations:
            if op in self.AUGMENTATIONS:
                info = self.AUGMENTATIONS[op]
                op_descriptions.append(f"- {op}: {info['name']} ({info['category']})")
            else:
                op_descriptions.append(f"- {op}: 自定义操作")

        prompt = f"""请为以下数据增强操作生成 PyTorch 代码：

## 数据形式
{data_format}

## 选择的操作
{chr(10).join(op_descriptions)}

## 模型代码（用于适配）
{model_code[:1500] if model_code else '未提供'}

请生成：
1. 适配数据形式的 transforms 代码
2. 如果选择高级增强（MixUp, CutMix等），请实现自定义函数
3. 如果选择数据攻击（FGSM, PGD等），请实现攻击函数
4. 包装成一个统一的 DataAugmentor 类

输出完整可运行的 Python 代码。"""

        try:
            return self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4096,
            )
        except Exception as e:
            return f"# 代码生成失败: {e}"

    def adapt_to_model(self, aug_code: str, model_code: str) -> str:
        """将增强代码适配到具体模型"""
        prompt = f"""请将以下数据增强代码适配到目标模型代码中。

## 数据增强代码
```python
{aug_code}
```

## 目标模型代码
```python
{model_code[:2000]}
```

请将增强代码集成到目标模型的数据加载流程中，确保维度匹配。输出完整的合并代码。"""

        try:
            return self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4096,
            )
        except Exception as e:
            return f"# 适配失败: {e}"
