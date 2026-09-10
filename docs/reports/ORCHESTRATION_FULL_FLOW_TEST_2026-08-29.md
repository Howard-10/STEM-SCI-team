# STEM-SCI 科研编排全流程测试记录（历史版本，已过期）

> **不作为当前验收依据。** 本记录写于原始资料 Gate 与文献资料的边界完全收紧之前，因此其中“未上传教师原始资料仍继续主题分析、结果验证和最终完成”的描述已失效。当前工作流会在 `MISSING_PRIMARY_DATA` 停止，绝不将论文或演示 CSV 视为参与者数据。请以 `REAL_FLOW_ACCEPTANCE_2026-08-30.md` 和 `FULL_FLOW_QUALITY_AUDIT_2026-08-30.md` 为准。

测试项目：`report-c67487e-pdf`

测试材料：`for_test(1)(1).pdf`，上传成功，返回文档 ID `doc-24b7f14d8e9f4a208f9a6cafd7f5b1b1`。

测试路线：定性研究。系统判定为 `QUALITATIVE`，并要求用户确认路线后才开始推进。

## 跳过步骤

以下步骤被路线策略标记为不适用，不会生成统计结论：

- `causal_DAG`：研究目标是解释性主题归纳，没有待估计的因果效应。
- `power_analysis`：没有组间效应或因果估计目标。
- `bootstrap_hypothesis_test`：定性主题分析不需要数值稳健性检验。
- `permutation_test`：定性主题分析不需要置换假设检验。
- `statistical_result_validation`：没有统计结果卡需要验证。
- `result_direction_consistency`：没有数值结果方向需要比较。
- `uncertainty_gate`：不对统计估计的不确定性做数值 Gate。
- `statistical_result_card`：定性结果由主题和编码产物表达。

## 逐轮对话与状态

| 轮次 | 用户输入 | 系统输出 | Agent / Artifact | 下一 Gate |
| --- | --- | --- | --- | --- |
| 0 | 上传 PDF | 上传成功 | 文档导入 | 路线判断 |
| 1 | 请基于上传的论文开展定性问卷编码、主题分析并形成可追溯论文 | 判定 `QUALITATIVE`，列出 8 个跳过步骤 | 路线编排器 | `research_route` |
| 2 | 确认 `research_route` | 任务完成，进入证据规范化 | EvidenceReviewAgent / `EvidenceSufficiencyReport` | `evidence_normalization_approval` |
| 3 | 确认证据规范化 | 任务完成，进入混合检索 | EvidenceReviewAgent / `EvidenceMatrixCandidate` | `hybrid_retrieval_approval` |
| 4 | 确认混合检索 | 任务完成，进入 RRF 融合 | EvidenceReviewAgent / `BoundedEvidenceSynthesis` | `rrf_fusion_approval` |
| 5 | 确认 RRF 融合 | 任务完成，进入 Cross-Encoder 重排 | EvidenceReviewAgent / `EvidenceMatrixCandidate` | `cross_encoder_rerank_approval` |
| 6 | 确认重排 | 任务完成，进入主张-证据支持判断 | EvidenceReviewAgent / `ResearchGapReport` | `claim_evidence_support_approval` |
| 7 | 确认证据支持判断 | 任务完成，进入研究问题设计 | MentorPlanningAgent / `ResearchQuestionTree` | `research_question_design_approval` |
| 8 | 确认研究问题设计 | 任务完成，进入定性研究设计 | ResearchDesignAgent / `StudyProtocolCandidate` | `qualitative_design_approval` |
| 9 | 确认定性研究设计 | 任务完成，进入原始资料导入 | 编排器确定性任务 / `RawDataImportCandidate` | `raw_data_import_approval` |
| 10 | 确认资料导入 | 任务完成，进入数据审计 | 编排器确定性任务 / `DataAuditCandidate` | `data_audit_approval` |
| 11 | 确认数据审计 | 任务完成，进入数据处理审批 | 编排器确定性任务 / `DataProcessingApprovalCandidate` | `data_processing_approval_approval` |
| 12 | 确认数据处理审批 | 任务完成，生成冻结哈希 | 编排器确定性任务 / `DatasetFreezeHashCandidate` | `dataset_freeze_hash_approval` |
| 13 | 确认数据冻结 | 任务完成，进入主题分析 | 编排器确定性任务 / `ThematicAnalysisCandidate` | `thematic_analysis_approval` |
| 14 | 确认主题分析 | 任务完成，进入定性结果验证 | 编排器确定性任务 / `QualitativeValidationCandidate` | `qualitative_validation_approval` |
| 15 | 确认定性结果验证 | 任务完成，进入论文写作 | PaperWritingAgent / `ManuscriptDraftZh` | `writing_approval` |
| 16 | 确认论文写作 | 任务完成，进入引用核验 | 编排器确定性任务 / `ManuscriptCitationVerificationCandidate` | `manuscript_citation_verification_approval` |
| 17 | 确认引用核验 | 任务完成，进入审稿复核 | 编排器确定性任务 / `ReviewerFinalConfirmationCandidate` | `reviewer_final_confirmation_approval` |
| 18 | 确认最终审稿复核 | 流程完成，没有下一任务或 Gate | 控制面终态 | 无 |

## 历史状态（已失效）

- 工作线状态：`COMPLETED`
- 最终阶段：`WRITING_PUBLICATION`
- 步骤索引：`18 / 18`
- 状态版本：`35`
- 持久化审计事件：`50`
- 统计分析步骤：按定性路线策略跳过
- 普通问题验证：发送“请解释当前状态”后返回 `kind=qa`，没有错误触发 Agent。

## 历史结论（已失效）

当前仍保留其中“用户只需在对话中提交材料、提出目标并在 Gate 处确认，系统自动选择内部 Agent”的交互结论；但数据审计、主题分析、结果型论文与最终审稿必须以本项目去标识化的原始资料为前提，不能沿用本记录的完成状态。
