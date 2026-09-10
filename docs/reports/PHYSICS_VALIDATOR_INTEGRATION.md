# Physics Validator 接入说明

STEM-SCI 现在支持可选的 Controller-owned 物理校验模式。默认关闭，不影响已有统计分析链；只有 `DataPipelineBeginRequest.physics_validation=true` 时才启用。

## 执行链

```text
CodingProvider
→ PhysicsValidationGate
→ CodeReviewGate
→ Human Gate
→ ResearchCodeSandbox
→ ResultValidationReport
```

Physics Validator 在后端进程中运行，生成代码本身不会获得 SymPy、Pint 或 Z3 的权限。

## 请求字段

调用 `POST /api/v1/workflow/projects/{project_id}/data-pipeline/start` 时，在原请求中增加：

```json
{
  "physics_validation": true,
  "physics_equations": ["F=m*a", "v=v0+a*t"],
  "physics_units": {
    "F": "newton",
    "m": "kilogram",
    "a": "meter / second ** 2"
  },
  "physics_bounds": {
    "m": {"min": 0.000001},
    "t": {"min": 0}
  }
}
```

校验失败会被加入 `CodeReviewGate` 的 finding，随后由现有沙箱流程阻断执行。报告在返回的 `DataPipelineState.physics_validation_report` 中。

## 依赖

后端依赖声明在 `backend/pyproject.toml`：`sympy`、`pint`、`z3-solver`。缺少依赖时系统会返回明确的 `PHYSICS_*_UNAVAILABLE` finding，并失败关闭，不会把结果标为通过。
