---
name: experiment-management
description: 实验管理技能 — 可视化生成 + 消融实验 + 超参数调优 + 结果记录
triggers:
  - 可视化
  - 消融
  - 超参数
  - 调参
  - 实验
  - 画图
  - visualization
  - ablation
  - hyperparameter
tools:
  - generate_visualization
  - plan_ablation
  - identify_hyperparams
  - generate_scheduler
  - list_experiments
  - read_file
  - glob_files
  - grep_files
---

# 实验管理

## 适用场景
当用户需要生成论文图表、规划消融实验、调整超参数、查看实验记录时使用此技能。

## 工作流

### 可视化生成
1. 了解用户研究方向和需求
2. 如果用户有已分析的论文，基于论文的方法和指标推荐图表类型
3. 收集用户的实验数据（数值、CSV等）
4. 调用 `generate_visualization` 生成图表代码
5. 迭代优化：生成→执行→评分→修缮，直到评分≥90
6. 评分维度：数据清晰度、标签标题、配色美观、科研规范性、完成度
7. 使用Morandi配色方案（mist-stone/sage-clay/dust-rose）

### 消融实验
1. 先读取项目代码，理解模型架构
2. 识别所有可消融的模块，按两个标准筛选：
   - 拆卸后不影响全局（独立可插拔）
   - 是模型的创新点（验证其重要性）
3. 列出每个模块的所有出现位置
4. 用户选择消融目标后，执行代码修改：
   - 移除所有出现位置
   - 自动对齐上下维度
   - 确保代码可运行
5. 展示修改前后对比，用户确认后保存

### 超参数调优
1. 读取项目所有代码
2. 调用 `identify_hyperparams` 识别所有可调参数
3. 对每个参数说明：当前值、建议范围、调整影响
4. 如果用户描述了训练过程，诊断问题并推荐调整：
   - 过拟合 → 增大weight_decay、添加dropout
   - 欠拟合 → 增大模型容量、降低正则化
   - 震荡 → 降低lr、增加batch_size
   - 收敛慢 → 增大lr、使用warmup
5. 生成调整后的配置代码

### 实验记录
1. 调用 `list_experiments` 查看历史实验
2. 对比不同超参数配置的结果
3. 分析训练曲线变化

## 约束
- 消融代码必须保持可运行性
- 超参数建议要基于训练过程的实际表现
- 可视化需符合学术期刊标准
