---
name: model-fusion
description: 模型融合技能 — 代码分块 + 智能模块迁移 + 对齐风险评估
triggers:
  - 代码分块
  - 模块迁移
  - 代码分析
  - 迁移模块
  - chunk
  - migrate
tools:
  - chunk_code
  - recommend_modules
  - migrate_module
  - glob_files
  - read_file
  - grep_files
---

# 模型融合

## 适用场景
当用户需要分析PyTorch项目代码结构、识别可迁移模块、将模块从一个项目迁移到另一个时使用此技能。

## 工作流

### 代码分块
1. 确认项目路径（本地路径或解压后的目录）
2. 先用 `glob_files` 了解项目结构
3. 用 `grep_files` 搜索关键类定义（class、nn.Module、Dataset等）
4. 用 `read_file` 读取核心模型文件，理解架构
5. 调用 `chunk_code` 进行AST分块
6. 按类别归纳展示：模型定义、前向传播、数据处理、训练循环等
7. 每个块标注文件路径和行号

### 模块迁移
1. 分析源项目和目标项目的代码结构
2. 调用 `recommend_modules` 识别可迁移的亮点模块
3. 对每个候选模块评估：创新性、独立性、迁移难度
4. 用户选择模块后，调用 `migrate_module` 生成对齐代码
5. 展示迁移方案：适配层代码、插入位置、风险评估
6. 如果维度不匹配，自动生成 nn.Linear/nn.Conv2d 适配代码
7. 评估风险：梯度中断、维度匹配、训练稳定性

## 约束
- 只迁移用户确认的模块
- 不修改目标项目的其他文件
- 必须保证代码可运行
- 所有操作需在项目目录内进行
