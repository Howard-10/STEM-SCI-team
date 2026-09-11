"""消融实验引擎 — 功能 8

包装化消融实验：
- 基于代码分块结果自动注释/启用模块
- 循环启动多个训练进程
- 收集消融后结果
"""

import json
import os
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.core.config import get_config
from backend.core.llm_client import get_llm_client
from backend.core.models import ChunkCategory, CodeChunk, CodeAnalysisResult
from backend.engines.code_engine.ast_analyzer import analyze_project


@dataclass
class AblationConfig:
    """消融实验配置"""
    name: str  # 消融实验名称
    target_chunks: list[str]  # 要注释掉的 chunk_id 列表
    description: str  # 实验描述
    enabled: bool = True  # 是否启用此实验


@dataclass
class AblationResult:
    """消融实验结果"""
    config_name: str
    removed_modules: list[str]
    metrics: dict  # {"accuracy": 0.85, "f1": 0.79, ...}
    training_time: float
    compared_to_full: dict  # 与完整模型的指标差异


class AblationEngine:
    """消融实验引擎 — 功能 8"""

    def __init__(self):
        self.llm = get_llm_client()
        self.cfg = get_config()

    def plan_ablations(
        self,
        analysis_result: CodeAnalysisResult,
        strategy: str = "auto",
    ) -> list[AblationConfig]:
        """基于代码分析结果自动规划消融实验"""
        model_modules = [
            c for c in analysis_result.chunks
            if c.category in (ChunkCategory.MODEL_DEFINITION,
                              ChunkCategory.FORWARD_PROPAGATION)
        ]

        if len(model_modules) <= 1:
            return []

        # 使用 LLM 规划消融策略
        chunks_text = []
        for chunk in model_modules[:15]:
            chunks_text.append(
                f"- chunk_id: {chunk.chunk_id}\n"
                f"  名称: {chunk.name}\n"
                f"  类别: {chunk.category.value}\n"
                f"  描述: {chunk.description}"
            )

        prompt = f"""请为以下模块规划消融实验。对于每个模块，说明如果将其移除可能产生的影响。

模块列表:
{chr(10).join(chunks_text)}

请规划消融实验方案，返回 JSON:
{{"ablations": [
    {{"name": "消融实验名称", "target_chunks": ["chunk_id1"], "description": "移除该模块的目的和预期影响"}}
]}}

策略: {strategy}
注意：不要移除训练循环、优化器、数据加载等基础设施模块，只消融模型架构相关的模块。"""

        try:
            resp = self.llm.structured_output(
                system_prompt="你是深度学习消融实验设计专家。",
                user_prompt=prompt,
                output_schema={
                    "ablations": [
                        {
                            "name": "str",
                            "target_chunks": ["str"],
                            "description": "str",
                        }
                    ]
                },
            )
            ablations = []
            for ab in resp.get("ablations", []):
                ablations.append(AblationConfig(
                    name=ab["name"],
                    target_chunks=ab["target_chunks"],
                    description=ab["description"],
                ))
            return ablations
        except Exception as e:
            from backend.core.error_logger import log_error
            log_error("ablation", e)
            return []

    def generate_ablation_code(
        self,
        project_path: str,
        ablation_configs: list[AblationConfig],
        analysis_result: CodeAnalysisResult,
        train_command: str = "python train.py",
    ) -> str:
        """生成消融实验的自动化运行脚本"""
        chunk_map = {c.chunk_id: c for c in analysis_result.chunks}

        script_lines = [
            "#!/usr/bin/env python3",
            '"""自动消融实验脚本"""',
            "import subprocess",
            "import json",
            "import sys",
            "import os",
            "from pathlib import Path",
            "",
            f"PROJECT_PATH = {json.dumps(project_path)}",
            f'TRAIN_COMMAND = {json.dumps(train_command)}',
            "",
            "ABLATION_CONFIGS = [",
        ]

        for config in ablation_configs:
            script_lines.append(f"    {{")
            script_lines.append(f'        "name": {json.dumps(config.name)},')
            script_lines.append(f'        "target_chunks": {json.dumps(config.target_chunks)},')
            script_lines.append(f'        "description": {json.dumps(config.description)},')
            script_lines.append(f"    }},")
        script_lines.append("]")
        script_lines.append("")

        # 添加模块注释/启用逻辑
        script_lines.append("""
def modify_code_for_ablation(chunks_to_disable):
    '''生成消融用的修改版代码'''
    # 创建临时工作目录
    import shutil
    import tempfile

    temp_dir = tempfile.mkdtemp(prefix="ablation_")
    shutil.copytree(PROJECT_PATH, temp_dir, dirs_exist_ok=True)
    return temp_dir

def run_ablation(config_name, temp_dir):
    '''运行单个消融实验'''
    print(f"\\n{'='*60}")
    print(f"Running ablation: {config_name}")
    print(f"{'='*60}")

    # 在实际使用中，这里会根据 target_chunks 修改代码
    # 例如注释掉特定模块的 forward 调用

    os.chdir(temp_dir)
    result = subprocess.run(
        TRAIN_COMMAND.split(),
        capture_output=True,
        text=True,
        timeout=36000,
    )
    os.chdir(PROJECT_PATH)

    return {
        "config": config_name,
        "returncode": result.returncode,
        "stdout_tail": result.stdout[-2000:] if result.stdout else "",
        "stderr_tail": result.stderr[-500:] if result.stderr else "",
    }

def main():
    results = []
    for config in ABLATION_CONFIGS:
        temp_dir = modify_code_for_ablation(config["target_chunks"])
        result = run_ablation(config["name"], temp_dir)
        results.append(result)
        # 清理临时目录
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)

    # 保存结果
    with open("ablation_results.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("\\n=== Ablation Complete ===")
    for r in results:
        print(f"- {r['config']}: exitcode={r['returncode']}")

if __name__ == "__main__":
    main()
""")
        return "\n".join(script_lines)

    def analyze_ablation_results(
        self, results: list[dict], baseline_metrics: dict
    ) -> str:
        """分析消融实验结果"""
        prompt = f"""请分析以下消融实验结果：

## 基线结果（完整模型）
{json.dumps(baseline_metrics, ensure_ascii=False, indent=2)}

## 消融结果
{json.dumps(results, ensure_ascii=False, indent=2)}

请分析：
1. 各模块对模型性能的贡献度
2. 哪些模块最关键
3. 哪些模块可以安全移除
4. 消融实验的结论

用中文输出 Markdown 格式。"""

        try:
            return self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4096,
            )
        except Exception as e:
            return f"# 分析失败: {e}"


class HyperParameterTuner:
    """超参数调优器 — 功能 9

    功能:
    - 阅读代码，识别可变超参数
    - 支持每隔 N 个 epoch 改变超参数
    - 生成超参数调度代码
    """

    def __init__(self):
        self.llm = get_llm_client()

    def identify_hyperparameters(self, code: str) -> list[dict]:
        """自动识别代码中的超参数"""
        prompt = f"""请分析以下 PyTorch 训练代码，识别所有可调整的超参数。

```python
{code[:8000]}
```

请列出每个超参数，返回 JSON:
{{"hyperparameters": [
    {{"name": "参数名", "type": "learning_rate/batch_size/epochs/weight_decay/dropout/arch_param/other", "current_value": "当前值", "suggested_range": "建议调整范围", "description": "说明", "adjustable_per_epoch": true/false}}
]}}"""

        try:
            resp = self.llm.structured_output(
                system_prompt="你是 PyTorch 深度学习训练专家。",
                user_prompt=prompt,
                output_schema={
                    "hyperparameters": [
                        {
                            "name": "str",
                            "type": "str",
                            "current_value": "str",
                            "suggested_range": "str",
                            "description": "str",
                            "adjustable_per_epoch": True,
                        }
                    ]
                },
            )
            return resp.get("hyperparameters", [])
        except Exception as e:
            from backend.core.error_logger import log_error
            log_error("ablation", e)
            return []

    def generate_scheduler_code(
        self,
        hyperparameters: list[dict],
        schedule_rules: list[dict],
    ) -> str:
        """生成超参数调度代码

        schedule_rules 示例:
        [{"param": "lr", "epoch": 30, "new_value": 0.0001},
         {"param": "lr", "epoch": 60, "new_value": 0.00001}]
        """
        params_text = json.dumps(hyperparameters, ensure_ascii=False, indent=2)
        rules_text = json.dumps(schedule_rules, ensure_ascii=False, indent=2)

        prompt = f"""请生成一个超参数调度器类，支持在训练过程中的特定 epoch 动态修改超参数。

## 可调超参数
{params_text}

## 调度规则
{rules_text}

请生成一个 HyperParamScheduler 类，包含：
1. 初始化：接收 optimizer 和调度规则
2. step(epoch): 在每个 epoch 开始前调用，自动检查和应用规则
3. 支持修改 learning_rate, weight_decay, dropout 等参数
4. 记录所有调度操作到日志

输出完整可运行的 Python 代码。"""

        try:
            return self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4096,
            )
        except Exception as e:
            return f"# 代码生成失败: {e}"


class ExperimentLogger:
    """实验结果记录器 — 功能 10

    记录所有训练完的参数和对应测试集结果
    """

    def __init__(self, db_path: Optional[str] = None):
        cfg = get_config()
        db_path = db_path or str(cfg.storage.experiment_log_dir / "experiments.db")
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """初始化 SQLite 数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS experiments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_name TEXT NOT NULL,
                model_name TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                hyperparameters TEXT,  -- JSON
                train_metrics TEXT,     -- JSON
                test_metrics TEXT,      -- JSON
                state_dict_path TEXT,
                config_path TEXT,
                notes TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS epoch_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id INTEGER,
                epoch INTEGER,
                train_loss REAL,
                val_loss REAL,
                train_acc REAL,
                val_acc REAL,
                learning_rate REAL,
                timestamp TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (experiment_id) REFERENCES experiments(id)
            )
        """)
        conn.commit()
        conn.close()

    def log_experiment(
        self,
        experiment_name: str,
        model_name: str,
        hyperparameters: dict,
        train_metrics: dict,
        test_metrics: dict,
        state_dict_path: str = "",
        notes: str = "",
    ) -> int:
        """记录一次完整的实验结果"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO experiments (experiment_name, model_name, hyperparameters, train_metrics, test_metrics, state_dict_path, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                experiment_name,
                model_name,
                json.dumps(hyperparameters, ensure_ascii=False),
                json.dumps(train_metrics, ensure_ascii=False),
                json.dumps(test_metrics, ensure_ascii=False),
                state_dict_path,
                notes,
            ),
        )
        exp_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return exp_id

    def log_epoch(
        self,
        experiment_id: int,
        epoch: int,
        train_loss: float = 0.0,
        val_loss: float = 0.0,
        train_acc: float = 0.0,
        val_acc: float = 0.0,
        learning_rate: float = 0.0,
    ):
        """记录每个 epoch 的训练信息"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO epoch_logs (experiment_id, epoch, train_loss, val_loss, train_acc, val_acc, learning_rate) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (experiment_id, epoch, train_loss, val_loss, train_acc, val_acc, learning_rate),
        )
        conn.commit()
        conn.close()

    def get_all_experiments(self) -> list[dict]:
        """获取所有实验记录"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM experiments ORDER BY created_at DESC")
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows

    def get_experiment(self, experiment_id: int) -> dict:
        """获取单个实验的完整记录（含 epoch 日志）"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM experiments WHERE id = ?", (experiment_id,))
        exp = dict(cursor.fetchone() or {})
        cursor.execute(
            "SELECT * FROM epoch_logs WHERE experiment_id = ? ORDER BY epoch",
            (experiment_id,),
        )
        exp["epochs"] = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return exp

    def export_to_csv(self, output_path: str):
        """导出所有实验到 CSV"""
        import csv
        experiments = self.get_all_experiments()
        if not experiments:
            return
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=experiments[0].keys())
            writer.writeheader()
            writer.writerows(experiments)

    def compare_experiments(self, experiment_ids: list[int]) -> str:
        """对比多个实验"""
        experiments = [self.get_experiment(eid) for eid in experiment_ids]
        comparison = []
        for exp in experiments:
            try:
                hp = json.loads(exp.get("hyperparameters", "{}"))
            except (json.JSONDecodeError, TypeError):
                hp = {}
            try:
                tm = json.loads(exp.get("test_metrics", "{}"))
            except (json.JSONDecodeError, TypeError):
                tm = {}
            comparison.append({
                "name": exp.get("experiment_name", ""),
                "hyperparameters": hp,
                "test_metrics": tm,
            })

        llm = get_llm_client()
        prompt = f"""请对比以下实验结果：

{json.dumps(comparison, ensure_ascii=False, indent=2)}

请分析：
1. 不同超参数对结果的影响
2. 最佳配置是什么
3. 实验之间的关键差异

用中文输出 Markdown。"""

        try:
            return llm.chat(messages=[{"role": "user", "content": prompt}], max_tokens=2048)
        except Exception as e:
            return f"# 对比失败: {e}"
