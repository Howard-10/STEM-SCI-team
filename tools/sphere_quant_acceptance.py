"""Live acceptance run for the SPHERE public quantitative re-analysis fixture."""
from __future__ import annotations

import json
import pathlib
import time
import uuid

from public_reanalysis_acceptance import call, register, require

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAPER = ROOT / "test_data" / "stem_ways_thinking_2025.pdf"
DATA = ROOT / "test_data" / "sphere_fci_quantitative.csv"
OUT = ROOT / "docs" / "reports" / "SPHERE_QUANT_ACCEPTANCE_2026-08-31.json"


def main() -> None:
    researcher, researcher_token = register("spherequant")
    reviewer, reviewer_token = register("spherequantreview")
    project_id = f"sphere-quant-{uuid.uuid4().hex[:10]}"
    direction = "公开二手资料再分析：比较 SPHERE 数据中不同性别编码组的 FCI 物理概念理解得分，进行描述性关联分析。"
    require(call("POST", "/projects", token=researcher_token, body={
        "project_id": project_id,
        "title": "SPHERE FCI 物理概念理解再分析",
        "research_direction": direction,
    }), "create project")
    require(call("PUT", f"/projects/{project_id}/members", token=researcher_token, body={"username": reviewer, "role": "reviewer"}), "add reviewer")
    require(call("POST", f"/projects/{project_id}/documents/upload", token=researcher_token, file=PAPER), "upload paper")
    started = require(call("POST", f"/projects/{project_id}/conversation/command", token=researcher_token, body={
        "project_id": project_id,
        "message": "请把这篇 STEM 物理教育论文作为文献依据，结合已说明来源的 SPHERE 公开 FCI CSV，先完成文献整理和证据规范化，再开展观察性定量再分析。每个阶段都生成候选产物并等待研究者或审稿人确认；仅报告描述性关联，不作因果结论。",
    }), "start workflow")
    records = []
    uploaded = False
    # Long-running deterministic operators may need several resume cycles;
    # leave ample room so the final citation and reviewer gates are exercised.
    for _ in range(96):
        state = require(call("GET", f"/projects/{project_id}/control-state", token=researcher_token), "control state")
        stream = state.get("workstreams", [{}])[0]
        if stream.get("status") == "COMPLETED":
            break
        if not state.get("active_gate_id"):
            require(call("POST", f"/projects/{project_id}/orchestration/continue", token=researcher_token), "continue")
            time.sleep(.25)
            continue
        gate = require(call("GET", f"/projects/{project_id}/gates/{state['active_gate_id']}", token=researcher_token), "gate")
        contents = require(call("GET", f"/workflow/projects/{project_id}/artifact-contents", token=researcher_token), "artifact contents")
        artifact = next((x for x in contents if x.get("artifact_id") in gate.get("artifact_ids", [])), None)
        gate_type = gate.get("gate_type", "")
        if gate_type == "raw_data_import_approval" and not uploaded:
            require(call("POST", f"/projects/{project_id}/primary-data/upload", token=researcher_token, file=DATA), "upload SPHERE CSV")
            uploaded = True
        body = artifact.get("body", {}) if artifact else {}
        records.append({
            "gate_type": gate_type,
            "artifact_type": artifact.get("artifact_type") if artifact else None,
            "artifact_status": body.get("status") if isinstance(body, dict) else None,
            "warnings": gate.get("warnings", []),
            "artifact_present": artifact is not None,
        })
        token = reviewer_token if gate_type.startswith("reviewer_final_confirmation") else researcher_token
        # A failed linkage check is intentionally sent back to writing. The
        # controller creates a new immutable manuscript candidate; approving
        # the failed verification artifact would violate provenance.
        revise_citation = (
            gate_type == "manuscript_citation_verification_approval"
            and isinstance(body, dict)
            and body.get("status") == "FAILED_TRACEABILITY_CHECK"
        )
        decision_body = {"decision": "revise" if revise_citation else "approve"}
        if gate.get("warnings") and not revise_citation:
            decision_body["risk_acceptance"] = ["研究者已确认公开二手数据来源、派生得分和描述性分析边界"]
        if gate_type == "manuscript_citation_verification_approval" and not revise_citation:
            decision_body["risk_acceptance"] = [
                "已人工核对文献作者、年份、页码和主张范围"
            ]
        require(call("POST", f"/projects/{project_id}/gates/{gate['gate_id']}/decision", token=token, body=decision_body), f"approve {gate_type}")
        time.sleep(.25)
    final_state = require(call("GET", f"/projects/{project_id}/control-state", token=researcher_token), "final state")
    contents = require(call("GET", f"/workflow/projects/{project_id}/artifact-contents", token=researcher_token), "final contents")
    claims = require(call("GET", f"/projects/{project_id}/claims", token=researcher_token), "claims")
    report = {
        "project_id": project_id,
        "researcher": researcher,
        "reviewer": reviewer,
        "route": final_state.get("route_decision", {}).get("primary_route"),
        "initial_command_kind": started.get("kind"),
        "paper": PAPER.name,
        "dataset": DATA.name,
        "uploaded_dataset": uploaded,
        "gate_records": records,
        "artifact_count": len(contents),
        "claim_count": len(claims),
        "final_lifecycle": final_state.get("lifecycle_status"),
        "final_step_index": final_state.get("workstreams", [{}])[0].get("current_step_index"),
        "quality_assertions": {
            "observational_route": final_state.get("route_decision", {}).get("primary_route") == "OBSERVATIONAL_QUANTITATIVE",
            "all_gate_artifacts_present": all(x["artifact_present"] for x in records),
            "dataset_uploaded": uploaded,
            "claims_present": bool(claims),
            "manuscript_present": any(x.get("artifact_type") == "ManuscriptDraftZh" for x in contents),
            "result_card_present": any(isinstance(x.get("body"), dict) and x["body"].get("statistical_result_card") for x in contents),
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
