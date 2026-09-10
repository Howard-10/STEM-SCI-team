"""Run a live, project-scoped qualitative acceptance flow against STEM-SCI."""

from __future__ import annotations

import json
import hashlib
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
import uuid


BASE = os.environ.get("STEM_SCI_ACCEPTANCE_BASE", "http://127.0.0.1:8000/api/v1")
ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "test_data" / "public_reanalysis" / "cgt_physics_education"
PAPER = DATA_ROOT / "paper_tschisgale_2023.pdf"
PRIMARY = DATA_ROOT / "Textual_descriptions.csv"
OUT = ROOT / "docs" / "reports" / "PUBLIC_REANALYSIS_ACCEPTANCE_2026-08-30.json"


def call(method: str, path: str, *, token: str | None = None, body: object | None = None,
         fields: dict[str, str] | None = None, file: pathlib.Path | None = None) -> dict:
    url = BASE.rstrip("/") + path
    headers: dict[str, str] = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload: bytes | None = None
    if file is not None:
        boundary = f"----stem-sci-{uuid.uuid4().hex}"
        chunks: list[bytes] = []
        for key, value in (fields or {}).items():
            chunks.extend([
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                value.encode(), b"\r\n",
            ])
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{file.name}"\r\n'.encode(),
            b"Content-Type: application/octet-stream\r\n\r\n",
            file.read_bytes(), b"\r\n", f"--{boundary}--\r\n".encode(),
        ])
        payload = b"".join(chunks)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=payload, headers=headers, method=method)
    try:
        # Evidence indexing, deterministic statistics and manuscript review
        # can legitimately exceed a short browser-style timeout. The API is
        # synchronous for this acceptance harness, so allow one bounded
        # operator cycle to finish before treating it as a failure.
        timeout = float(os.environ.get("STEM_SCI_ACCEPTANCE_TIMEOUT", "180"))
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return {"status": response.status, "body": json.loads(raw) if raw else {}}
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"raw": raw}
        return {"status": error.code, "body": parsed}


def require(response: dict, label: str) -> dict:
    if response["status"] < 200 or response["status"] >= 300:
        raise RuntimeError(f"{label} failed: {response['status']} {response['body']}")
    return response["body"]


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def register(prefix: str) -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:10]
    username = f"{prefix}{suffix}"
    result = require(call("POST", "/auth/register", body={
        "username": username,
        "email": f"{username}@example.test",
        "password": "research-pass-123",
    }), "register")
    return username, result["access_token"]


def main() -> int:
    # Keep the JSON report printable on Windows consoles whose legacy code
    # page cannot represent German umlauts from the public source data.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not PAPER.exists() or not PRIMARY.exists():
        raise RuntimeError("public reanalysis files are missing")
    researcher, researcher_token = register("pubresearch")
    reviewer, reviewer_token = register("pubreview")
    project_id = f"public-cgt-{uuid.uuid4().hex[:12]}"
    direction = (
        "公开二手资料再分析：基于学生物理问题解决文本，重新检查主要主题，"
        "并比较有物理奥赛经历与无物理奥赛经历学生的主题构成。"
    )
    require(call("POST", "/projects", token=researcher_token, body={
        "project_id": project_id,
        "title": "公开二手资料再分析：物理问题解决文本",
        "research_direction": direction,
    }), "create project")
    require(call("PUT", f"/projects/{project_id}/members", token=researcher_token, body={
        "username": reviewer,
        "role": "reviewer",
    }), "add reviewer")
    require(call("POST", f"/projects/{project_id}/documents/upload", token=researcher_token, file=PAPER), "upload paper")
    prompt = (
        "请基于已导入的真实论文 Tschisgale et al. (2023)、OSF d68ch 公开资料和公开学生物理问题解决文本 CSV，"
        "建立一个公开二手资料再分析的定性研究项目。研究问题是重新检查文本主题，并比较有物理奥赛经历与无物理奥赛经历学生的主题构成。"
        "这是定性主题分析/计算扎根理论路线，不是定量实验；不要执行统计功效、因果模型或把原论文结论冒充本次新发现。"
        "先完成文献整理、来源核验、字段字典、筛选规则和证据规范化，再在每个 Gate 说明产物、数据边界和不确定性。"
    )
    started = require(call("POST", f"/projects/{project_id}/conversation/command", token=researcher_token, body={
        "project_id": project_id, "message": prompt, "interaction_mode": "workflow",
    }), "conversation command")

    records: list[dict] = []
    uploaded = False
    uploaded_hash: str | None = None
    reviewer_used = False
    expected_qualitative = {
        "data_audit_approval": "DataAuditCandidate",
        "data_processing_approval_approval": "DataProcessingApprovalCandidate",
        "dataset_freeze_hash_approval": "DatasetFreezeHashCandidate",
        "thematic_analysis_approval": "ThematicAnalysisCandidate",
        "qualitative_validation_approval": "QualitativeValidationCandidate",
        "writing_approval": "ManuscriptDraftZh",
        "manuscript_citation_verification_approval": "ManuscriptCitationVerification",
        "reviewer_final_confirmation_approval": "FinalReviewPacket",
    }
    first = started
    for _ in range(32):
        state = require(call("GET", f"/projects/{project_id}/control-state", token=researcher_token), "control state")
        if not state.get("active_gate_id"):
            if state.get("workstreams", [{}])[0].get("status") == "COMPLETED":
                break
            advanced = require(call("POST", f"/projects/{project_id}/orchestration/continue", token=researcher_token), "continue")
            first = advanced
            time.sleep(0.2)
            continue
        gate = require(call("GET", f"/projects/{project_id}/gates/{state['active_gate_id']}", token=researcher_token), "gate")
        contents = require(call("GET", f"/workflow/projects/{project_id}/artifact-contents", token=researcher_token), "artifact contents")
        artifact_ids = gate.get("artifact_ids", [])
        artifact = next((item for item in contents if item.get("artifact_id") in artifact_ids), None)
        gate_type = gate.get("gate_type", "")
        if gate_type == "raw_data_import_approval" and not uploaded:
            primary_upload = require(
                call("POST", f"/projects/{project_id}/primary-data/upload", token=researcher_token, file=PRIMARY),
                "upload public text",
            )
            uploaded_hash = ((primary_upload.get("artifact") or {}).get("content_sha256"))
            uploaded = True
        expected_type = expected_qualitative.get(gate_type)
        quality: dict[str, object] = {
            "gate_type": gate_type,
            "artifact_type": artifact.get("artifact_type") if artifact else None,
            "artifact_status": (artifact.get("body") or {}).get("status") if artifact else None,
            "expected_artifact_type": expected_type,
            "warnings": gate.get("warnings", []),
            "artifact_present": artifact is not None,
        }
        if gate_type == "thematic_analysis_approval" and artifact:
            quality["themes"] = (artifact.get("body") or {}).get("themes") or []
        if gate_type == "evidence_sufficiency_review" and artifact:
            body = artifact.get("body") or {}
            quality["evidence_count"] = (body.get("coverage") or {}).get("evidence_count")
            quality["source_count"] = (body.get("coverage") or {}).get("source_count")
            quality["matrix_count"] = len(body.get("evidence_matrix") or [])
        if gate_type == "data_audit_approval" and artifact:
            manifest = (artifact.get("body") or {}).get("data_manifest") or {}
            # The upload endpoint stores normalized UTF-8 text (for example,
            # line endings and a UTF-8 BOM may change), so compare with the
            # hash returned for that immutable uploaded artifact rather than
            # the local container's raw file bytes.
            quality["dataset_hash_matches"] = bool(uploaded_hash) and manifest.get("content_sha256") == uploaded_hash
            quality["uploaded_content_sha256"] = uploaded_hash
        records.append(quality)
        actor_token = researcher_token
        if gate_type.startswith("reviewer_final_confirmation"):
            actor_token = reviewer_token
            reviewer_used = True
        decision_body: dict[str, object] = {"decision": "approve"}
        if gate.get("warnings"):
            decision_body["risk_acceptance"] = ["研究者已查看公开二手资料边界和自动化分析限制"]
        decision = call("POST", f"/projects/{project_id}/gates/{gate['gate_id']}/decision", token=actor_token, body=decision_body)
        require(decision, f"approve {gate_type}")
        time.sleep(0.2)
    final_state = require(call("GET", f"/projects/{project_id}/control-state", token=researcher_token), "final state")
    final_contents = require(call("GET", f"/workflow/projects/{project_id}/artifact-contents", token=researcher_token), "final contents")
    claims = require(call("GET", f"/projects/{project_id}/claims", token=researcher_token), "claims")
    stream = final_state["workstreams"][0]
    skipped = set(stream.get("skipped_step_ids", []))
    quantitative_steps = {"causal_DAG", "power_analysis", "bootstrap_robustness", "permutation_test", "statistical_result_validation", "result_direction_consistency", "uncertainty_gate", "statistical_result_card"}
    manuscript = next((item for item in final_contents if item.get("artifact_type") == "ManuscriptDraftZh"), None)
    manuscript_sections = (manuscript or {}).get("body", {}).get("sections", {}) if manuscript else {}
    manuscript_text = "\n".join(str(value) for value in manuscript_sections.values())
    paper_theme_codes = {
        "assumptions_and_idealizations",
        "conceptual_aspects",
        "quantitative_aspects",
        "formulation_of_solution",
        "general_descriptions",
    }
    thematic_record = next(
        (item for item in records if item.get("gate_type") == "thematic_analysis_approval"),
        {},
    )
    candidate_theme_codes = {
        str(theme.get("theme_id", "")).removeprefix("theme:")
        for theme in thematic_record.get("themes", [])
        if isinstance(theme, dict)
    }
    report = {
        "project_id": project_id,
        "source_provenance": {
            "paper_title": "Integrating artificial intelligence-based methods into qualitative research in physics education research: A case for computational grounded theory",
            "paper_doi": "10.1103/PhysRevPhysEducRes.19.020123",
            "paper_url": "https://doi.org/10.1103/PhysRevPhysEducRes.19.020123",
            "data_repository": "OSF",
            "data_project_url": "https://osf.io/d68ch/",
            "paper_file": PAPER.name,
            "paper_sha256": sha256_file(PAPER),
            "text_data_file": PRIMARY.name,
            "text_data_sha256": sha256_file(PRIMARY),
            "secondary_reference_files": {
                "Textual_descriptions.xlsx": sha256_file(DATA_ROOT / "Textual_descriptions.xlsx"),
                "Additional_data.xlsx": sha256_file(DATA_ROOT / "Additional_data.xlsx"),
            },
            "data_use_boundary": "公开 OSF 二手资料；本次输出是候选再分析，不等同于原作者结果或新的参与者样本。",
        },
        "researcher": researcher,
        "reviewer": reviewer,
        "route": final_state.get("route_decision", {}).get("primary_route"),
        "initial_command_kind": started.get("kind"),
        "uploaded_public_data": uploaded,
        "reviewer_used": reviewer_used,
        "gate_records": records,
        "artifact_count": len(final_contents),
        "claim_count": len(claims),
        "final_lifecycle": final_state.get("lifecycle_status"),
        "final_step_index": stream.get("current_step_index"),
        "skipped_quantitative_steps": sorted(quantitative_steps & skipped),
        "quality_assertions": {
            "qualitative_route": final_state.get("route_decision", {}).get("primary_route") == "QUALITATIVE",
            "all_gate_artifacts_present": all(item["artifact_present"] for item in records),
            "expected_types_match": all(item["expected_artifact_type"] in {None, item["artifact_type"]} for item in records),
            "dataset_hash_matches": all(item.get("dataset_hash_matches", True) for item in records),
            "theme_candidates_present": all(
                bool((item.get("themes") or []))
                for item in records
                if item.get("gate_type") == "thematic_analysis_approval"
            ),
            "themes_align_with_paper_framework": paper_theme_codes <= candidate_theme_codes,
            "theme_evidence_links_present": all(
                all(bool(theme.get("evidence_segment_ids")) for theme in (item.get("themes") or []))
                for item in records
                if item.get("gate_type") == "thematic_analysis_approval"
            ),
            "quantitative_steps_skipped": quantitative_steps <= skipped,
            "claims_present": bool(claims),
            "manuscript_present": manuscript is not None,
            "manuscript_marks_secondary_data": (
                "二手" in manuscript_text and "550" in manuscript_text and "417" in manuscript_text
            ),
            "manuscript_does_not_label_students_as_teachers": "教师资料" not in manuscript_text,
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ACCEPTANCE_FAILED: {error}", file=sys.stderr)
        raise
