---
name: data-processing
description: 数据处理技能 — 数据集自动适配 + 数据增强/攻击
triggers:
  - 数据集
  - 数据处理
  - 数据增强
  - DataLoader
  - augmentation
  - dataset
tools:
  - inspect_dataset
  - generate_dataloader
  - generate_augmentation
  - read_file
  - glob_files
---

# 数据处理

## 适用场景
当用户需要解读数据集、生成DataLoader代码、选择数据增强操作时使用此技能。

## 工作流

### 数据集适配
1. 确认数据集路径（文件或文件夹）
2. 调用 `inspect_dataset` 解读：
   - 数据格式（image_folder/csv/json/npy等）
   - 样本数量、特征维度
   - 标签类型、类别数
3. 如果用户提供了模型代码，先用 `read_file` 读取了解模型输入要求
4. 调用 `generate_dataloader` 生成适配代码，传入模型代码以更好地匹配输入维度
5. 检查生成的代码是否处理了训练/验证/测试集划分
6. 确认数据变换（transforms）与模型输入维度一致

### 数据增强
1. 确认数据形式（image/text/audio等）
2. 如果用户提供了模型代码路径，用 `read_file` 读取关键部分（只看输入预处理，不要遍历全部文件）
3. 优先调用 `generate_augmentation` 工具，传入用户选择的操作和数据形式
4. 对于自定义增强（不在20种预定义内），直接用 LLM 生成完整 Python 代码，不要反复调用 bash_exec
5. 生成代码后直接展示给用户，不要尝试在本地执行验证

### 自定义增强规则
- 用户在"🎨 数据增强 → 自定义"中输入的描述 → 直接生成代码
- 不要用 bash_exec/glob_files 去探索项目——用户需要的是代码片段
- 一次回复中给出完整可用的 Python 代码
- 如果用户提供了模型代码，确保输入维度匹配

## 约束
- 增强操作不能改变数据的语义标签
- 数据攻击仅供安全研究使用
- 生成代码必须可直接运行
- 自定义增强：直接给代码，不调用工具探索项目
