import { ApiRequestError } from "./auth";

// Use the same relative API base as the authenticated workspace so Vite
// proxies every research request to the active local backend on port 8013.
const base = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export type SchemaValidationReport = {
  report_id: string;
  validator_id: string;
  passed: boolean;
  findings: Array<{ code: string; column?: string | null; message: string }>;
};

export type OutlierReport = {
  report_id: string;
  detector_id: string;
  requires_human_review: boolean;
  findings: Array<{ row_index: number; score: number; flagged: boolean; reason: string }>;
};

export type MultipleComparisonReport = {
  report_id: string;
  method: "holm" | "bonferroni" | "fdr_bh";
  alpha: number;
  significant_count: number;
  results: Array<{ result_key: string; raw_p_value: number; adjusted_p_value: number; rejected: boolean }>;
};

export type CausalAdapterReport = {
  report_id: string;
  provider_id: string;
  status: string;
  passed: boolean;
  requires_human_review: boolean;
  edges: Array<{ source: string; target: string }>;
  adjustment_set: string[];
  findings: string[];
};

export type ConfoundingSensitivityReport = {
  report_id: string;
  provider_id: string;
  estimate: number;
  standard_error: number;
  benchmark_partial_r2: number;
  robustness_value: number;
  adjusted_estimate_at_benchmark: number;
  conclusion: string;
  requires_human_review: boolean;
};

export type PredictionInterval = {
  lower: number;
  prediction: number;
  upper: number;
  coverage: number;
  method: string;
};

export type MetaAnalysisReport = {
  report_id: string;
  method: string;
  study_count: number;
  pooled_effect: number;
  ci_lower: number;
  ci_upper: number;
  tau_squared: number;
  heterogeneity_i_squared: number;
  leave_one_out_effects: Record<string, number>;
};

export type DataPipelineStage =
  | "WAITING_ANALYSIS_PREPARATION_APPROVAL"
  | "WAITING_RAW_DATA"
  | "WAITING_PROCESSING_APPROVAL"
  | "WAITING_FREEZE_APPROVAL"
  | "WAITING_EXECUTION_APPROVAL"
  | "ANALYZED"
  | "REWORK"
  | "BLOCKED";

export type DataPipelineState = {
  project_id: string;
  stage: DataPipelineStage;
  model_specification: {
    model_family: string;
    outcome_variables: string[];
    predictor_variables: string[];
    formula_or_design: string;
  };
  pending_approval?: { approval_type: string; reason: string } | null;
  data_audit_report?: { passed: boolean; missing_required_variables: string[]; risk_flags: string[] } | null;
  rework_reason?: string | null;
  multiple_comparison_report?: MultipleComparisonReport | null;
  statistical_result_card?: {
    result_id: string;
    execution_status: string;
    values: Record<string, number>;
  } | null;
};

export type ProjectWorkflowState = {
  project_id: string;
  current_stage: string;
  data_pipeline?: DataPipelineState | null;
};

async function request<T>(path: string, body: unknown, accessToken: string): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(body),
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = payload as { error?: { code?: string; message?: string } } | null;
    throw new ApiRequestError(error?.error?.message ?? "研究分析请求失败", response.status, error?.error?.code);
  }
  return payload as T;
}

async function workflowRequest<T>(
  path: string,
  accessToken: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${accessToken}`, ...(init.headers ?? {}) },
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = payload as { error?: { message?: string } } | null;
    throw new ApiRequestError(error?.error?.message ?? "数据分析流程请求失败", response.status);
  }
  return payload as T;
}

export const researchApi = {
  validateSchema(projectId: string, accessToken: string, body: unknown) {
    return request<SchemaValidationReport>(`/projects/${encodeURIComponent(projectId)}/data/schema-validate`, body, accessToken);
  },
  screenOutliers(projectId: string, accessToken: string, values: number[]) {
    return request<OutlierReport>(`/projects/${encodeURIComponent(projectId)}/analysis/outliers`, { values }, accessToken);
  },
  correctMultipleComparisons(projectId: string, accessToken: string, body: { p_values: Record<string, number>; method: string; alpha: number }) {
    return request<MultipleComparisonReport>(`/projects/${encodeURIComponent(projectId)}/analysis/multiple-comparisons`, body, accessToken);
  },
  discoverCausalGraph(projectId: string, accessToken: string, body: { rows: Array<Record<string, number>>; columns: string[] }) {
    return request<CausalAdapterReport>(`/projects/${encodeURIComponent(projectId)}/protocol/causal-discovery`, body, accessToken);
  },
  identifyCausalEffect(projectId: string, accessToken: string, body: unknown) {
    return request<CausalAdapterReport>(`/projects/${encodeURIComponent(projectId)}/protocol/causal-identify`, body, accessToken);
  },
  assessConfounding(projectId: string, accessToken: string, body: { estimate: number; standard_error: number; benchmark_partial_r2: number }) {
    return request<ConfoundingSensitivityReport>(`/projects/${encodeURIComponent(projectId)}/analysis/confounding-sensitivity`, body, accessToken);
  },
  calculatePredictionInterval(projectId: string, accessToken: string, body: { prediction: number; calibration_residuals: number[]; coverage: number }) {
    return request<PredictionInterval>(`/projects/${encodeURIComponent(projectId)}/analysis/conformal-interval`, body, accessToken);
  },
  runMetaAnalysis(projectId: string, accessToken: string, body: unknown) {
    return request<MetaAnalysisReport>(`/projects/${encodeURIComponent(projectId)}/analysis/meta-analysis`, body, accessToken);
  },
  prepareDataPipeline(projectId: string, accessToken: string, body: {
    group_variable: string;
    outcome_variable: string;
    multiple_comparison_correction: boolean;
    multiple_comparison_method: string;
  }) {
    return workflowRequest<DataPipelineState>(
      `/projects/${encodeURIComponent(projectId)}/workflow/data-pipeline/prepare`,
      accessToken,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
    );
  },
  getWorkflowState(projectId: string, accessToken: string) {
    return workflowRequest<ProjectWorkflowState>(
      `/projects/${encodeURIComponent(projectId)}/workflow`,
      accessToken,
      { method: "GET" },
    );
  },
  uploadPipelineCsv(projectId: string, accessToken: string, file: File) {
    const body = new FormData();
    body.append("file", file);
    return workflowRequest<DataPipelineState>(
      `/projects/${encodeURIComponent(projectId)}/workflow/data-pipeline/raw`,
      accessToken,
      { method: "POST", body },
    );
  },
  decideDataPipeline(projectId: string, accessToken: string, decision: "approved" | "rejected") {
    return workflowRequest<DataPipelineState>(
      `/projects/${encodeURIComponent(projectId)}/workflow/data-pipeline/decide`,
      accessToken,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision, decided_by: "researcher" }),
      },
    );
  },
};
