import { useEffect, useMemo, useRef, useState } from "react";

import {
  researchApi,
  type CausalAdapterReport,
  type ConfoundingSensitivityReport,
  type MetaAnalysisReport,
  type MultipleComparisonReport,
  type OutlierReport,
  type PredictionInterval,
  type DataPipelineState,
  type SchemaValidationReport,
} from "../api/research";

type ResearchAnalysisWorkbenchProps = {
  projectId: string;
  accessToken?: string;
  onClose: () => void;
};

type ParsedCsv = {
  headers: string[];
  rows: Array<Record<string, string | number>>;
  numericColumns: string[];
};

const starterCsv = `treatment,transfer_score,baseline_score
0,70,65
1,82,68
0,72,67
1,86,70
0,69,64
1,84,69`;

function parseSimpleCsv(source: string): ParsedCsv {
  const lines = source.trim().split(/\r?\n/).filter(Boolean);
  if (lines.length < 2) throw new Error("至少需要表头和一行数据");
  const headers = lines[0].split(",").map((item) => item.trim());
  if (headers.some((item) => !item) || new Set(headers).size !== headers.length) {
    throw new Error("CSV 表头不能为空且不能重复");
  }
  const rows = lines.slice(1).map((line, lineIndex) => {
    const values = line.split(",").map((item) => item.trim());
    if (values.length !== headers.length) throw new Error(`第 ${lineIndex + 2} 行列数与表头不一致`);
    return Object.fromEntries(headers.map((header, index) => {
      const raw = values[index];
      const numeric = Number(raw);
      return [header, raw !== "" && Number.isFinite(numeric) ? numeric : raw];
    }));
  });
  const numericColumns = headers.filter((header) => rows.every((row) => typeof row[header] === "number"));
  return { headers, rows, numericColumns };
}

function parseNumberLines(source: string, label: string): number[] {
  const values = source.split(/[\s,]+/).filter(Boolean).map(Number);
  if (!values.length || values.some((value) => !Number.isFinite(value))) throw new Error(`${label}必须是有限数值`);
  return values;
}

function parsePValues(source: string): Record<string, number> {
  const entries = source.trim().split(/\r?\n/).filter(Boolean).map((line) => {
    const [key, raw] = line.split(/[=,]/).map((item) => item.trim());
    const value = Number(raw);
    if (!key || !Number.isFinite(value) || value < 0 || value > 1) throw new Error("每行使用 指标名=0 到 1 之间的 p 值");
    return [key, value] as const;
  });
  if (!entries.length || new Set(entries.map(([key]) => key)).size !== entries.length) throw new Error("至少需要一个不重复的 p 值");
  return Object.fromEntries(entries);
}

function parseStudies(source: string) {
  const studies = source.trim().split(/\r?\n/).filter(Boolean).map((line, index) => {
    const [studyId, rawEffect, rawStandardError] = line.split(",").map((item) => item.trim());
    const effect = Number(rawEffect);
    const standardError = Number(rawStandardError);
    if (!studyId || !Number.isFinite(effect) || !Number.isFinite(standardError) || standardError <= 0) {
      throw new Error(`第 ${index + 1} 行需要：研究标识,效应量,标准误`);
    }
    return { study_id: studyId, effect, standard_error: standardError };
  });
  if (studies.length < 2) throw new Error("元分析至少需要两项独立研究");
  return studies;
}

function numberText(value: number, digits = 3) {
  return Number.isFinite(value) ? value.toFixed(digits) : "-";
}

function ReportHeader({ title, note }: { title: string; note: string }) {
  return <div className="research-report-heading"><h3>{title}</h3><p>{note}</p></div>;
}

export function ResearchAnalysisWorkbench({ projectId, accessToken, onClose }: ResearchAnalysisWorkbenchProps) {
  const [csvText, setCsvText] = useState(starterCsv);
  const parsed = useMemo(() => {
    try { return { value: parseSimpleCsv(csvText), error: "" }; }
    catch (error) { return { value: null, error: error instanceof Error ? error.message : "无法读取 CSV" }; }
  }, [csvText]);
  const defaultNumeric = parsed.value?.numericColumns[0] ?? "";
  const [outlierColumn, setOutlierColumn] = useState("transfer_score");
  const [treatmentColumn, setTreatmentColumn] = useState("treatment");
  const [outcomeColumn, setOutcomeColumn] = useState("transfer_score");
  const [pValuesText, setPValuesText] = useState("primary_outcome=0.018\nsecondary_outcome=0.041\nexploratory_outcome=0.120");
  const [correctionMethod, setCorrectionMethod] = useState("holm");
  const [sensitivity, setSensitivity] = useState({ estimate: "0.42", standardError: "0.15", benchmarkR2: "0.04" });
  const [prediction, setPrediction] = useState("82.4");
  const [residuals, setResiduals] = useState("2.1, 3.4, 1.8, 2.6, 4.0");
  const [metaText, setMetaText] = useState("study_a,0.31,0.12\nstudy_b,0.46,0.15\nstudy_c,0.22,0.11");
  const [busy, setBusy] = useState<string>();
  const [error, setError] = useState("");
  const [schemaReport, setSchemaReport] = useState<SchemaValidationReport>();
  const [outlierReport, setOutlierReport] = useState<OutlierReport>();
  const [multipleReport, setMultipleReport] = useState<MultipleComparisonReport>();
  const [discoveryReport, setDiscoveryReport] = useState<CausalAdapterReport>();
  const [identificationReport, setIdentificationReport] = useState<CausalAdapterReport>();
  const [sensitivityReport, setSensitivityReport] = useState<ConfoundingSensitivityReport>();
  const [intervalReport, setIntervalReport] = useState<PredictionInterval>();
  const [metaReport, setMetaReport] = useState<MetaAnalysisReport>();
  const [pipeline, setPipeline] = useState<DataPipelineState>();
  const [pipelineFile, setPipelineFile] = useState<File>();
  const pipelineFileInput = useRef<HTMLInputElement>(null);
  const [workflowStage, setWorkflowStage] = useState<string>();
  const [workflowLoading, setWorkflowLoading] = useState(false);

  const run = async (name: string, operation: () => Promise<void>) => {
    if (!accessToken) { setError("请先登录，再将研究报告写入项目审计链路。"); return; }
    setBusy(name);
    setError("");
    try { await operation(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "研究分析运行失败"); }
    finally { setBusy(undefined); }
  };

  useEffect(() => {
    if (!accessToken) {
      setWorkflowStage(undefined);
      setPipeline(undefined);
      return;
    }
    let mounted = true;
    setWorkflowLoading(true);
    void researchApi.getWorkflowState(projectId, accessToken)
      .then((state) => {
        if (!mounted) return;
        setWorkflowStage(state.current_stage);
        setPipeline(state.data_pipeline ?? undefined);
      })
      .catch((caught) => {
        if (mounted) setError(caught instanceof Error ? caught.message : "无法读取项目工作流状态");
      })
      .finally(() => {
        if (mounted) setWorkflowLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [accessToken, projectId]);

  const numericColumns = parsed.value?.numericColumns ?? [];
  const actualOutlierColumn = numericColumns.includes(outlierColumn) ? outlierColumn : defaultNumeric;
  const actualOutcomeColumn = numericColumns.includes(outcomeColumn) ? outcomeColumn : defaultNumeric;
  const pipelinePendingLabel = pipeline?.pending_approval?.approval_type === "analysis_preparation"
    ? "确认变量映射"
    : pipeline?.pending_approval?.approval_type === "data_processing"
      ? "确认数据处理"
      : pipeline?.pending_approval?.approval_type === "data_freeze"
        ? "确认数据冻结"
        : pipeline?.pending_approval?.approval_type === "analysis_execution"
          ? "确认代码审查与执行"
          : "等待下一步";
  const canPreparePipeline = workflowStage === "STUDY_PROTOCOL_APPROVED" && !pipeline;
  const workflowStageLabel: Record<string, string> = {
    INTAKE: "研究接入",
    SCOPED: "范围确认",
    EVIDENCE_READY: "证据就绪",
    STUDY_PROTOCOL_APPROVED: "研究方案已批准",
    DATA_READY: "数据分析准备",
    WAITING_HUMAN: "等待人工审批",
    ANALYZED: "分析完成",
    REWORK: "需要返工",
    BLOCKED: "流程阻断",
  };

  const preparePipeline = () => void run("pipeline-prepare", async () => {
    if (!canPreparePipeline) throw new Error("请先完成研究方案审批，或处理当前已有的数据分析管线");
    if (!treatmentColumn || !actualOutcomeColumn) throw new Error("请先选择分组变量和结果变量");
    setPipeline(await researchApi.prepareDataPipeline(projectId, accessToken!, {
      group_variable: treatmentColumn,
      outcome_variable: actualOutcomeColumn,
      multiple_comparison_correction: true,
      multiple_comparison_method: correctionMethod,
    }));
  });

  const uploadPipelineCsv = () => void run("pipeline-upload", async () => {
    if (!pipelineFile) throw new Error("请选择要进入审批流程的 CSV 文件");
    setPipeline(await researchApi.uploadPipelineCsv(projectId, accessToken!, pipelineFile));
  });

  const decidePipeline = (decision: "approved" | "rejected") => void run("pipeline-decision", async () => {
    setPipeline(await researchApi.decideDataPipeline(projectId, accessToken!, decision));
  });

  return (
    <div className="workspace-drawer-backdrop research-analysis-backdrop" role="presentation" onClick={onClose}>
      <section className="workspace-drawer research-analysis-workbench" role="dialog" aria-modal="true" aria-label="科研数据审查工作台" onClick={(event) => event.stopPropagation()}>
        <header className="workspace-drawer-header">
          <div><span className="chat-kicker">科研数据审查</span><h2>从数据检查到结果不确定性</h2><small>所有算法只产生报告与标记，不会自动删数据、宣布因果关系或替代研究者判断。</small></div>
          <button className="header-icon-button" type="button" title="关闭数据审查工作台" onClick={onClose}>×</button>
        </header>

        <div className="research-analysis-body">
          <aside className="research-analysis-inputs">
            <ReportHeader title="审查数据" note="粘贴一份简单 CSV；此处仅用于运行项目内的审查算法。" />
            <textarea value={csvText} onChange={(event) => setCsvText(event.target.value)} rows={12} spellCheck={false} aria-label="CSV 数据" />
            <div className={parsed.error ? "analysis-data-state analysis-data-error" : "analysis-data-state"}>
              {parsed.error || (parsed.value ? `${parsed.value.rows.length} 行 · ${parsed.value.headers.length} 列 · ${numericColumns.length} 个数值变量` : "")}
            </div>
            {!accessToken && <p className="analysis-login-note">登录后才可以运行真实项目审查；当前仅显示输入界面。</p>}
          </aside>

          <main className="research-analysis-reports">
            {error && <div className="analysis-error" role="alert">{error}</div>}
            <section className="analysis-module analysis-pipeline-module">
              <ReportHeader title="正式数据分析流程" note="在已确认的研究方案基础上，依次完成变量映射、数据处理、版本冻结和受控执行。" />
              <div className="analysis-action-row">
                <label className="analysis-inline-field">分组变量<select value={treatmentColumn} onChange={(event) => setTreatmentColumn(event.target.value)}>{parsed.value?.headers.map((column) => <option key={column}>{column}</option>)}</select></label>
                <label className="analysis-inline-field">结果变量<select value={actualOutcomeColumn} onChange={(event) => setOutcomeColumn(event.target.value)}>{numericColumns.map((column) => <option key={column}>{column}</option>)}</select></label>
                <button className="primary-inline-button" type="button" disabled={busy === "pipeline-prepare" || !accessToken || !parsed.value || !canPreparePipeline} onClick={preparePipeline}>{busy === "pipeline-prepare" ? "准备中..." : "创建分析准备"}</button>
              </div>
              <p className="analysis-pipeline-note">项目工作流：{workflowLoading ? "读取中..." : workflowStageLabel[workflowStage ?? ""] ?? workflowStage ?? "未读取"}。仅当项目已通过研究方案审批时可创建分析准备；这里的变量映射会先由研究者确认，系统不会把它当作自动预注册。</p>
              {!pipeline && workflowStage && workflowStage !== "STUDY_PROTOCOL_APPROVED" && <p className="analysis-pipeline-note analysis-data-error">当前阶段不能启动数据管线，请先在研究流程中完成研究方案审批。</p>}
              {pipeline && <div className={pipeline.stage === "ANALYZED" ? "analysis-report report-pass" : pipeline.stage === "REWORK" || pipeline.stage === "BLOCKED" ? "analysis-report report-attention" : "analysis-report"}>
                <strong>{pipeline.stage === "ANALYZED" ? "分析已验证" : `当前阶段：${pipelinePendingLabel}`}</strong>
                <span>{pipeline.rework_reason || pipeline.pending_approval?.reason || `${pipeline.model_specification.formula_or_design}；等待研究者操作。`}</span>
              </div>}
              {pipeline?.stage === "WAITING_RAW_DATA" && <div className="analysis-action-row analysis-file-row"><input ref={pipelineFileInput} type="file" accept=".csv,text/csv" aria-label="正式分析 CSV 文件" onChange={(event) => setPipelineFile(event.target.files?.[0])} /><button className="secondary-inline-button" type="button" disabled={busy === "pipeline-upload" || !pipelineFile} onClick={uploadPipelineCsv}>{busy === "pipeline-upload" ? "上传中..." : "上传并审计 CSV"}</button></div>}
              {pipeline?.pending_approval && <div className="analysis-action-row"><button className="primary-inline-button" type="button" disabled={busy === "pipeline-decision"} onClick={() => decidePipeline("approved")}>{busy === "pipeline-decision" ? "处理中..." : `批准：${pipelinePendingLabel}`}</button><button className="secondary-inline-button" type="button" disabled={busy === "pipeline-decision"} onClick={() => decidePipeline("rejected")}>退回修改</button></div>}
              {pipeline?.data_audit_report && <p className="analysis-pipeline-note">数据审计：{pipeline.data_audit_report.passed ? "通过" : "需修改"}{pipeline.data_audit_report.missing_required_variables.length ? `；缺少 ${pipeline.data_audit_report.missing_required_variables.join("、")}` : ""}{pipeline.data_audit_report.risk_flags.length ? `；${pipeline.data_audit_report.risk_flags.join("、")}` : ""}</p>}
              {pipeline?.statistical_result_card && <div className="analysis-table"><div className="analysis-table-row analysis-table-head"><span>已验证结果</span><span>数值</span><span>状态</span></div>{Object.entries(pipeline.statistical_result_card.values).map(([key, value]) => <div className="analysis-table-row" key={key}><span>{key}</span><span>{numberText(value, 4)}</span><span>{pipeline.statistical_result_card?.execution_status}</span></div>)}</div>}
              {pipeline?.multiple_comparison_report && <p className="analysis-pipeline-note">已按 {pipeline.multiple_comparison_report.method} 校正 {pipeline.multiple_comparison_report.results.length} 个 p 值。</p>}
            </section>
            <section className="analysis-module">
              <ReportHeader title="1. 数据 Schema 审计" note="检查字段缺失、类型与研究者声明是否一致。" />
              <button className="primary-inline-button" type="button" disabled={busy === "schema" || !parsed.value} onClick={() => void run("schema", async () => {
                const data = parsed.value!;
                const schema = { columns: data.headers.map((name) => ({ name, required: true, type: data.numericColumns.includes(name) ? "number" : "string" })) };
                setSchemaReport(await researchApi.validateSchema(projectId, accessToken!, { rows: data.rows, schema }));
              })}>{busy === "schema" ? "审计中..." : "运行 Schema 审计"}</button>
              {schemaReport && <div className={schemaReport.passed ? "analysis-report report-pass" : "analysis-report report-attention"}><strong>{schemaReport.passed ? "Schema 校验通过" : "Schema 需要处理"}</strong><span>{schemaReport.findings.length ? schemaReport.findings.map((item) => `${item.column ? `${item.column}: ` : ""}${item.message}`).join("；") : "所有声明字段均通过"}</span></div>}
            </section>

            <section className="analysis-module">
              <ReportHeader title="2. 异常值筛查" note="只标记潜在异常观测，是否保留必须由研究者记录决定。" />
              <label className="analysis-inline-field">数值变量<select value={actualOutlierColumn} onChange={(event) => setOutlierColumn(event.target.value)}>{numericColumns.map((column) => <option key={column}>{column}</option>)}</select></label>
              <button className="secondary-inline-button" type="button" disabled={busy === "outliers" || !parsed.value || !actualOutlierColumn} onClick={() => void run("outliers", async () => {
                const values = parsed.value!.rows.map((row) => Number(row[actualOutlierColumn]));
                setOutlierReport(await researchApi.screenOutliers(projectId, accessToken!, values));
              })}>{busy === "outliers" ? "筛查中..." : "筛查异常值"}</button>
              {outlierReport && <div className="analysis-report"><strong>{outlierReport.findings.filter((item) => item.flagged).length} 条待人工复核</strong><span>{outlierReport.detector_id} · 标记行：{outlierReport.findings.filter((item) => item.flagged).map((item) => item.row_index + 2).join("、") || "无"}</span></div>}
            </section>

            <section className="analysis-module">
              <ReportHeader title="3. 多重比较校正" note="明确区分原始 p 值与校正后的判断。" />
              <textarea value={pValuesText} onChange={(event) => setPValuesText(event.target.value)} rows={3} aria-label="P 值，每行一个" />
              <div className="analysis-action-row"><label className="analysis-inline-field">方法<select value={correctionMethod} onChange={(event) => setCorrectionMethod(event.target.value)}><option value="holm">Holm</option><option value="bonferroni">Bonferroni</option><option value="fdr_bh">FDR-BH</option></select></label><button className="secondary-inline-button" type="button" disabled={busy === "multiple"} onClick={() => void run("multiple", async () => setMultipleReport(await researchApi.correctMultipleComparisons(projectId, accessToken!, { p_values: parsePValues(pValuesText), method: correctionMethod, alpha: 0.05 })))}>{busy === "multiple" ? "校正中..." : "校正 p 值"}</button></div>
              {multipleReport && <div className="analysis-table"><div className="analysis-table-row analysis-table-head"><span>结果</span><span>原始</span><span>校正后</span></div>{multipleReport.results.map((item) => <div className="analysis-table-row" key={item.result_key}><span>{item.result_key}</span><span>{numberText(item.raw_p_value)}</span><span className={item.rejected ? "analysis-significant" : ""}>{numberText(item.adjusted_p_value)} {item.rejected ? "显著" : ""}</span></div>)}</div>}
            </section>

            <section className="analysis-module">
              <ReportHeader title="4. 因果识别" note="候选图仅供研究者确认；确认 DAG 后才调用 DoWhy 识别估计量。" />
              <div className="analysis-action-row"><label className="analysis-inline-field">处理变量<select value={treatmentColumn} onChange={(event) => setTreatmentColumn(event.target.value)}>{parsed.value?.headers.map((column) => <option key={column}>{column}</option>)}</select></label><label className="analysis-inline-field">结果变量<select value={actualOutcomeColumn} onChange={(event) => setOutcomeColumn(event.target.value)}>{numericColumns.map((column) => <option key={column}>{column}</option>)}</select></label></div>
              <div className="analysis-action-row"><button className="secondary-inline-button" type="button" disabled={busy === "discovery" || !parsed.value || numericColumns.length < 2} onClick={() => void run("discovery", async () => {
                const columns = numericColumns;
                const rows = parsed.value!.rows.map((row) => Object.fromEntries(columns.map((column) => [column, Number(row[column])])));
                setDiscoveryReport(await researchApi.discoverCausalGraph(projectId, accessToken!, { rows, columns }));
              })}>{busy === "discovery" ? "生成中..." : "生成候选 DAG"}</button><button className="primary-inline-button" type="button" disabled={busy === "identify" || !parsed.value || !numericColumns.includes(treatmentColumn) || !actualOutcomeColumn} onClick={() => void run("identify", async () => {
                const columns = numericColumns;
                const rows = parsed.value!.rows.map((row) => Object.fromEntries(columns.map((column) => [column, Number(row[column])])));
                const adjustment = columns.filter((column) => column !== treatmentColumn && column !== actualOutcomeColumn);
                setIdentificationReport(await researchApi.identifyCausalEffect(projectId, accessToken!, { rows, dag: { treatment: treatmentColumn, outcome: actualOutcomeColumn, nodes: columns, edges: [{ source: treatmentColumn, target: actualOutcomeColumn }], adjustment_set: adjustment } }));
              })}>{busy === "identify" ? "识别中..." : "确认 DAG 并识别"}</button></div>
              {(discoveryReport || identificationReport) && <div className="analysis-report"><strong>{identificationReport?.status ?? discoveryReport?.status}</strong><span>{identificationReport?.findings.join("；") || discoveryReport?.findings.join("；") || "仍须由研究者审阅图结构、调整变量和研究设计假设。"}</span></div>}
            </section>

            <section className="analysis-module analysis-module-two-up">
              <div><ReportHeader title="5. 混杂敏感性" note="量化未观测混杂可能削弱结论的程度。" /><div className="analysis-input-grid"><label>效应<input value={sensitivity.estimate} onChange={(event) => setSensitivity((value) => ({ ...value, estimate: event.target.value }))} /></label><label>标准误<input value={sensitivity.standardError} onChange={(event) => setSensitivity((value) => ({ ...value, standardError: event.target.value }))} /></label><label>基准 R²<input value={sensitivity.benchmarkR2} onChange={(event) => setSensitivity((value) => ({ ...value, benchmarkR2: event.target.value }))} /></label></div><button className="secondary-inline-button" type="button" disabled={busy === "sensitivity"} onClick={() => void run("sensitivity", async () => setSensitivityReport(await researchApi.assessConfounding(projectId, accessToken!, { estimate: Number(sensitivity.estimate), standard_error: Number(sensitivity.standardError), benchmark_partial_r2: Number(sensitivity.benchmarkR2) })))}>{busy === "sensitivity" ? "计算中..." : "运行敏感性分析"}</button>{sensitivityReport && <div className="analysis-report"><strong>稳健值 {numberText(sensitivityReport.robustness_value)}</strong><span>{sensitivityReport.conclusion}</span></div>}</div>
              <div><ReportHeader title="6. 预测区间" note="仅用于预测任务，不等同于因果效应置信区间。" /><label className="analysis-inline-field">预测值<input value={prediction} onChange={(event) => setPrediction(event.target.value)} /></label><textarea value={residuals} onChange={(event) => setResiduals(event.target.value)} rows={3} aria-label="校准残差" /><button className="secondary-inline-button" type="button" disabled={busy === "interval"} onClick={() => void run("interval", async () => setIntervalReport(await researchApi.calculatePredictionInterval(projectId, accessToken!, { prediction: Number(prediction), calibration_residuals: parseNumberLines(residuals, "校准残差"), coverage: 0.95 })))}>{busy === "interval" ? "计算中..." : "计算预测区间"}</button>{intervalReport && <div className="analysis-report"><strong>[{numberText(intervalReport.lower)}, {numberText(intervalReport.upper)}]</strong><span>{Math.round(intervalReport.coverage * 100)}% 覆盖率 · {intervalReport.method}</span></div>}</div>
            </section>

            <section className="analysis-module">
              <ReportHeader title="7. 元分析" note="输入经人工抽取、统一口径的独立研究效应量和标准误。" />
              <textarea value={metaText} onChange={(event) => setMetaText(event.target.value)} rows={3} aria-label="元分析研究效应量" />
              <button className="secondary-inline-button" type="button" disabled={busy === "meta"} onClick={() => void run("meta", async () => setMetaReport(await researchApi.runMetaAnalysis(projectId, accessToken!, { studies: parseStudies(metaText), confidence: 0.95 })))}>{busy === "meta" ? "合并中..." : "运行元分析"}</button>
              {metaReport && <div className="analysis-report"><strong>合并效应 {numberText(metaReport.pooled_effect)}</strong><span>95% CI [{numberText(metaReport.ci_lower)}, {numberText(metaReport.ci_upper)}] · I² {numberText(metaReport.heterogeneity_i_squared * 100, 1)}%</span></div>}
            </section>
          </main>
        </div>
      </section>
    </div>
  );
}
