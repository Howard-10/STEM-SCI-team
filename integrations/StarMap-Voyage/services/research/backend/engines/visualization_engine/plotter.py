"""可视化生成引擎 — 功能 7

包装化可视化操作：
- 通过阅读文献学习该研究方向常用的可视化方法
- 根据模型类型和数据形式自动推荐可视化方案
- 自动生成 matplotlib/seaborn 绘图代码
"""

from dataclasses import dataclass, field
from typing import Optional

from backend.core.config import get_config
from backend.core.llm_client import get_llm_client


@dataclass
class VisualizationPlan:
    """可视化方案"""
    plot_type: str  # "line", "bar", "scatter", "heatmap", "confusion_matrix",
                    # "tsne", "radar", "box", "violin", "histogram", etc.
    title: str
    x_label: str
    y_label: str
    description: str
    priority: int  # 1 = 最重要


class VisualizationEngine:
    """可视化生成引擎"""

    VIS_TYPES = {
        "training_curve": {"name": "训练曲线", "types": ["line"], "multi": True},
        "loss_curve": {"name": "损失曲线", "types": ["line"], "multi": True},
        "accuracy_bar": {"name": "精度对比柱状图", "types": ["bar"], "multi": False},
        "confusion_matrix": {"name": "混淆矩阵", "types": ["heatmap"], "multi": False},
        "feature_tsne": {"name": "特征 t-SNE 可视化", "types": ["scatter"], "multi": False},
        "attention_heatmap": {"name": "注意力热力图", "types": ["heatmap"], "multi": False},
        "ablation_radar": {"name": "消融实验雷达图", "types": ["radar"], "multi": False},
        "model_comparison": {"name": "模型对比图", "types": ["bar", "radar"], "multi": True},
        "gradient_flow": {"name": "梯度流可视化", "types": ["line"], "multi": True},
        "weight_distribution": {"name": "权重分布图", "types": ["histogram", "box"], "multi": False},
        "lr_schedule": {"name": "学习率调度曲线", "types": ["line"], "multi": False},
        "data_distribution": {"name": "数据分布图", "types": ["histogram", "violin"], "multi": False},
        "metric_radar": {"name": "多指标雷达图", "types": ["radar"], "multi": False},
        "pareto_frontier": {"name": "帕累托前沿", "types": ["scatter"], "multi": False},
    }

    # Morandi 配色方案
    MORANDI_PALETTES = {
        "mist_stone": ["#F3EEE8", "#D8D1C7", "#8A9199"],
        "sage_clay": ["#E7E1D6", "#B7A99A", "#7F8F84"],
        "dust_rose": ["#F2E9E6", "#D8C3BC", "#B88C8C"],
    }

    def __init__(self):
        self.llm = get_llm_client()
        self.cfg = get_config()

    def learn_from_papers(self, paper_texts: list[str]) -> dict:
        """从文献中学习该研究方向常用的可视化方法"""
        combined = "\n\n---\n\n".join(
            text[:3000] for text in paper_texts[:5]
        )

        prompt = f"""请分析以下论文，总结该研究方向常用的可视化方法。

论文内容:
{combined[:8000]}

请返回 JSON:
{{
    "research_field": "研究方向",
    "common_visualizations": [
        {{"type": "图表类型", "purpose": "使用目的", "frequency": "high/medium/low", "example": "具体例子"}}
    ],
    "recommended_plots": ["推荐的图表1", "推荐的图表2", "推荐的图表3"]
}}"""

        try:
            return self.llm.structured_output(
                system_prompt="你是科研数据可视化专家，熟悉各类深度学习论文的可视化范式。",
                user_prompt=prompt,
                output_schema={
                    "research_field": "str",
                    "common_visualizations": [
                        {"type": "str", "purpose": "str", "frequency": "str", "example": "str"}
                    ],
                    "recommended_plots": ["str"],
                },
            )
        except Exception as e:
            return {"error": str(e)}

    def plan_visualizations(
        self,
        model_code: str,
        experiment_results: dict = None,
        paper_knowledge: dict = None,
    ) -> list[VisualizationPlan]:
        """根据模型代码和实验结果自动规划可视化方案"""
        results_text = ""
        if experiment_results:
            results_text = f"\n实验数据可用字段: {list(experiment_results.keys())}"

        paper_hint = ""
        if paper_knowledge and "recommended_plots" in paper_knowledge:
            paper_hint = f"\n该领域常用图表: {', '.join(paper_knowledge['recommended_plots'])}"

        prompt = f"""请规划可视化方案。

模型代码片段:
```python
{model_code[:2000]}
```

{results_text}
{paper_hint}

请规划一套完整的可视化方案，包括：
1. 训练过程图（损失曲线、精度曲线）
2. 模型分析图（结构图、特征分布）
3. 结果对比图（与其他方法的对比）
4. 消融/分析图

返回 JSON:
{{"plans": [
    {{"plot_type": "line/bar/scatter/heatmap/confusion_matrix/tsne/radar/box/violin/histogram",
     "title": "图表标题",
     "x_label": "X轴标签",
     "y_label": "Y轴标签",
     "description": "图表说明",
     "priority": 1}}
]}}"""

        try:
            resp = self.llm.structured_output(
                system_prompt="你是科研可视化规划专家。请根据模型代码规划最合适的可视化方案。",
                user_prompt=prompt,
                output_schema={
                    "plans": [
                        {
                            "plot_type": "str",
                            "title": "str",
                            "x_label": "str",
                            "y_label": "str",
                            "description": "str",
                            "priority": 0,
                        }
                    ]
                },
            )
            plans = []
            for p in resp.get("plans", []):
                plans.append(VisualizationPlan(
                    plot_type=p["plot_type"],
                    title=p["title"],
                    x_label=p["x_label"],
                    y_label=p["y_label"],
                    description=p["description"],
                    priority=p["priority"],
                ))
            return sorted(plans, key=lambda x: x.priority)
        except Exception:
            return []

    def generate_plot_code(
        self,
        plan: VisualizationPlan,
        data_format_hint: str = "",
        palette: str = "mist_stone",
    ) -> str:
        """根据可视化方案生成具体绘图代码"""
        palette_colors = self.MORANDI_PALETTES.get(
            palette, self.MORANDI_PALETTES["mist_stone"]
        )

        prompt = f"""请生成一个 Python matplotlib 绘图函数。

## 图表需求
- 类型: {plan.plot_type}
- 标题: {plan.title}
- X轴: {plan.x_label}
- Y轴: {plan.y_label}
- 说明: {plan.description}

## 数据格式提示
{data_format_hint or '使用占位数据，方便替换'}

## 配色要求
使用 Morandi 配色: {palette_colors}
plt.rcParams.update 设置全局样式
白色或近白色背景，低饱和度，可读标签

## 代码规范
- 封装为独立函数 `def plot_{plan.plot_type}():`
- 包含 plt.savefig，输出 300dpi 以上的 PNG
- 包含 plt.rcParams.update 设置中文字体
- 支持中文显示
- 注释清晰

输出完整可运行的 Python 代码。"""

        try:
            return self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=3072,
            )
        except Exception as e:
            return f"# 代码生成失败: {e}"

    def generate_full_visualization_suite(
        self,
        model_code: str,
        experiment_results: dict = None,
        paper_texts: list[str] = None,
    ) -> dict:
        """一站式生成完整的可视化套件"""
        # Step 1: 从文献学习
        paper_knowledge = {}
        if paper_texts:
            paper_knowledge = self.learn_from_papers(paper_texts)

        # Step 2: 规划可视化方案
        plans = self.plan_visualizations(model_code, experiment_results, paper_knowledge)

        # Step 3: 逐图生成代码
        plots_code = {}
        for plan in plans:
            code = self.generate_plot_code(plan)
            plots_code[plan.title] = code

        # Step 4: 生成汇总脚本
        full_script = self._assemble_full_script(plots_code, paper_knowledge)

        return {
            "paper_knowledge": paper_knowledge,
            "plans": [
                {"type": p.plot_type, "title": p.title, "priority": p.priority}
                for p in plans
            ],
            "plots_code": plots_code,
            "full_script": full_script,
        }

    def _assemble_full_script(
        self, plots_code: dict[str, str], paper_knowledge: dict
    ) -> str:
        """将所有绘图代码组装成完整脚本"""
        lines = [
            "#!/usr/bin/env python3",
            '"""自动生成的可视化套件"""',
            "",
            "import matplotlib.pyplot as plt",
            "import numpy as np",
            "import os",
            "",
            "# Morandi 配色方案",
            "MORANDI_MIST_STONE = ['#F3EEE8', '#D8D1C7', '#8A9199']",
            "MORANDI_SAGE_CLAY = ['#E7E1D6', '#B7A99A', '#7F8F84']",
            "MORANDI_DUST_ROSE = ['#F2E9E6', '#D8C3BC', '#B88C8C']",
            "",
            "# 全局样式",
            "plt.rcParams.update({",
            "    'font.family': 'DejaVu Sans',",
            "    'font.size': 11,",
            "    'axes.facecolor': '#FAFAFA',",
            "    'figure.facecolor': 'white',",
            "    'axes.edgecolor': '#CCCCCC',",
            "    'axes.grid': True,",
            "    'grid.alpha': 0.3,",
            "    'axes.spines.top': False,",
            "    'axes.spines.right': False,",
            "})",
            "",
            "OUTPUT_DIR = 'output_figures'",
            "os.makedirs(OUTPUT_DIR, exist_ok=True)",
            "",
        ]

        for title, code in plots_code.items():
            # 提取函数定义部分，去掉首行的 #!/usr/bin 和 import
            clean_code = code
            for prefix in ["#!/usr/bin/env python3", '"""', "import matplotlib", "import numpy", "import os", "from matplotlib", "plt.rcParams"]:
                clean_code = "\n".join(
                    line for line in clean_code.split("\n")
                    if not line.strip().startswith(prefix)
                )
            lines.append(clean_code)
            lines.append("")

        lines.append("")
        lines.append("if __name__ == '__main__':")
        for title in plots_code:
            func_name = title.replace(" ", "_").replace("-", "_").lower()
            lines.append(f"    plot_{func_name}()")
        lines.append('    print(f"All figures saved to {{OUTPUT_DIR}}")')

        return "\n".join(lines)

    def get_available_visualizations(self) -> list[dict]:
        """返回可用的可视化类型列表"""
        return [
            {"id": vid, "name": info["name"], "types": info["types"]}
            for vid, info in self.VIS_TYPES.items()
        ]
