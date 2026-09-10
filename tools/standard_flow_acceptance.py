"""Step-by-step live acceptance for the researcher-facing standard flow."""

from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = os.environ.get("STEM_SCI_ACCEPTANCE_BASE", "http://127.0.0.1:8000/api/v1")
ROOT = pathlib.Path(__file__).resolve().parents[1]
PAPER = pathlib.Path(r"C:\Users\14139\Documents\WeChat Files\wxid_mi839kohn3k012\FileStorage\File\2026-08\for_test(1)(1).pdf")
# This fixture matches the standard undergraduate two-group instructional
# question below.  The teacher-capacity fixture remains available for the
# separate teacher-practice workflow, but must not be used to validate a
# student-learning manuscript.
DATA = ROOT / "test_data" / "mixed_methods_quantitative.csv"


def call(method: str, path: str, *, token: str | None = None, body: object | None = None, file: pathlib.Path | None = None) -> dict:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = None
    if file is not None:
        boundary = f"----stem-sci-{uuid.uuid4().hex}"
        payload = b"".join([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{file.name}"\r\n'.encode(),
            b"Content-Type: application/octet-stream\r\n\r\n", file.read_bytes(), b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ])
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(BASE.rstrip("/") + path, data=payload, headers=headers, method=method)
    started = time.perf_counter()
    try:
        # Evidence indexing can be CPU-bound on the first local-corpus pass;
        # allow the acceptance harness to distinguish slow completion from a
        # hard timeout while keeping the production API timeout unchanged.
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read().decode("utf-8")
            result = {"status": response.status, "body": json.loads(raw) if raw else {}}
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            result = {"status": error.code, "body": json.loads(raw)}
        except json.JSONDecodeError:
            result = {"status": error.code, "body": {"raw": raw}}
    result["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
    return result


def require(result: dict, label: str) -> dict:
    if not 200 <= result["status"] < 300:
        raise RuntimeError(f"{label}: {result}")
    return result["body"]


def register(prefix: str) -> tuple[str, str]:
    username = f"{prefix}{uuid.uuid4().hex[:10]}"
    body = require(call("POST", "/auth/register", body={
        "username": username,
        "email": f"{username}@example.test",
        "password": "research-pass-123",
    }), "register")
    return username, body["access_token"]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    if not PAPER.is_file() or not DATA.is_file():
        raise RuntimeError(f"missing fixture: paper={PAPER.is_file()} data={DATA.is_file()}")
    researcher, token = register("standard")
    reviewer, reviewer_token = register("reviewer")
    project_id = f"standard-{uuid.uuid4().hex[:10]}"
    direction = "我想研究在本科物理课程中引入 Python/VPython 计算建模，是否能够提升学生的计算思维和物理概念理解，计划采用前测—后测比较。"
    require(call("POST", "/projects", token=token, body={"project_id": project_id, "title": "标准流程测试", "research_direction": direction}), "create project")
    require(call("PUT", f"/projects/{project_id}/members", token=token, body={"username": reviewer, "role": "reviewer"}), "add reviewer")
    require(call("POST", f"/projects/{project_id}/documents/upload", token=token, file=PAPER), "upload paper")
    records: list[dict] = []

    def record(label: str, result: dict) -> dict:
        body = result.get("body", {})
        state = body.get("control_state") if isinstance(body, dict) else None
        if not isinstance(state, dict):
            state = require(call("GET", f"/projects/{project_id}/control-state", token=token), "control state")
        streams = state.get("workstreams") or [{}]
        stream = streams[0] if isinstance(streams[0], dict) else {}
        item = {
            "label": label,
            "status": result.get("status"),
            "elapsed_ms": result.get("elapsed_ms"),
            "message": body.get("message") if isinstance(body, dict) else None,
            "gate_type": (body.get("gate") or {}).get("gate_type") if isinstance(body, dict) and isinstance(body.get("gate"), dict) else None,
            "current_step_index": stream.get("current_step_index"),
            "current_action": stream.get("current_action"),
            "phase": stream.get("phase"),
            "execution_started": body.get("execution_started") if isinstance(body, dict) else None,
        }
        records.append(item)
        print(json.dumps(item, ensure_ascii=False))
        return body

    topic = record("topic", call("POST", f"/projects/{project_id}/conversation/command", token=token, body={"project_id": project_id, "message": direction}))
    # The conversational product now collects a durable six-field research
    # brief before retrieval. Keep this acceptance harness aligned with that
    # contract instead of treating the old direct-search path as standard.
    if topic.get("waiting_for_user") and (topic.get("intake") or {}).get("current_question_key") == "research_goal":
        intake_answers = [
            "比较本科物理课程中计算建模前后学生计算思维测验总分的变化，不把结果写成因果证明。",
            "对象是本科物理课程学生，重点变量是计算思维总分，包含前测、后测和分组信息。",
            "判断这种教学安排下是否出现可重复的学习结果差异，为后续正式实验提供依据。",
            "已上传 STEM 物理教育论文，并准备一份去标识化的公开 CSV 数据。",
            "采用前测—后测的观察性比较；未随机分配时只报告描述性变化和不确定性。",
            "保留数据版本、来源定位和局限说明，不能把相关性写成因果结论。",
        ]
        for index, answer in enumerate(intake_answers):
            record(f"intake_{index + 1}", call("POST", f"/projects/{project_id}/conversation/command", token=token, body={"project_id": project_id, "message": answer}))
        topic = record("confirm_brief", call("POST", f"/projects/{project_id}/conversation/command", token=token, body={"project_id": project_id, "message": "确认研究简报，开始检索。"}))
    first_review = require(call("GET", f"/projects/{project_id}/evidence-review", token=token), "first evidence review")
    first_coverage = first_review["body"]["coverage"]
    if (topic.get("gate") or {}).get("gate_type") != "evidence_sufficiency_review":
        raise RuntimeError(f"topic did not reach evidence review: {topic}")
    if first_coverage.get("source_count", 0) < 1:
        raise RuntimeError(f"evidence review has no sources: {first_coverage}")
    if first_coverage.get("external_candidate_count", 0) < 1:
        raise RuntimeError(f"external scholarly discovery returned no candidates: {first_coverage}")
    repeated = record("continue_search", call("POST", f"/projects/{project_id}/conversation/command", token=token, body={"project_id": project_id, "message": "继续搜索"}))
    second_review = require(call("GET", f"/projects/{project_id}/evidence-review", token=token), "second evidence review")
    second_coverage = second_review["body"]["coverage"]
    if (repeated.get("gate") or {}).get("gate_type") != "evidence_sufficiency_review":
        raise RuntimeError(f"incremental search lost evidence review: {repeated}")
    if "本轮检索完成：新增" not in str(repeated.get("message")):
        raise RuntimeError(f"incremental search did not report delta counts: {repeated}")
    if second_coverage.get("duplicate_source_count", 0) < 1:
        raise RuntimeError(f"incremental search did not report existing sources: {second_coverage}")
    evidence_sufficient = record("evidence_sufficient", call("POST", f"/projects/{project_id}/conversation/command", token=token, body={"project_id": project_id, "message": "证据足够"}))
    design_contents = require(call("GET", f"/workflow/projects/{project_id}/artifact-contents", token=token), "design artifacts")
    design_types = {item.get("artifact_type") for item in design_contents}
    if "ResearchQuestionTree" not in design_types or {"StudyProtocolCandidate", "PowerAnalysisCandidate"} & design_types:
        raise RuntimeError(f"evidence approval did not pause at question review: {sorted(design_types)}")
    if evidence_sufficient.get("checkpoint") != "RESEARCH_QUESTION_REVIEW":
        raise RuntimeError(f"evidence approval did not reach question checkpoint: {evidence_sufficient}")
    design_prompt = record("select_question", call("POST", f"/projects/{project_id}/conversation/command", token=token, body={"project_id": project_id, "message": "选第 1 个研究问题，并把主要结果限定为计算思维测验总分。"}))
    if design_prompt.get("checkpoint") != "RESEARCH_DESIGN_REVIEW":
        raise RuntimeError(f"question selection did not reach design checkpoint: {design_prompt}")
    record("confirm_design", call("POST", f"/projects/{project_id}/conversation/command", token=token, body={"project_id": project_id, "message": "确认研究方案：比较前后测变化，避免未随机分配时的因果表述。"}))
    preregistration = record("freeze_preregistration", call("POST", f"/projects/{project_id}/conversation/command", token=token, body={"project_id": project_id, "message": "确认并冻结预注册方案。"}))
    if (preregistration.get("gate") or {}).get("gate_type") != "raw_data_import_approval":
        raise RuntimeError(f"preregistration freeze did not reach raw data intake: {preregistration}")

    state = require(call("GET", f"/projects/{project_id}/control-state", token=token), "state before data")
    # The raw-data Gate is the point at which the researcher supplies the
    # dataset; upload it before approving that Gate through conversation.
    if state.get("active_gate_id"):
        gate = require(call("GET", f"/projects/{project_id}/gates/{state['active_gate_id']}", token=token), "data gate")
        if gate.get("gate_type") == "raw_data_import_approval":
            require(call("POST", f"/projects/{project_id}/primary-data/upload", token=token, file=DATA), "upload data")
        upload_audit = record("audit_uploaded_data", call("POST", f"/projects/{project_id}/conversation/command", token=token, body={"project_id": project_id, "message": "请审计这份原始数据，检查字段、缺失值、重复记录和异常值。"}))
        if upload_audit.get("checkpoint") != "DATA_DESIGN_REVIEW":
            raise RuntimeError(f"data audit did not catch the pre/post-vs-schema mismatch: {upload_audit}")
        if upload_audit.get("checkpoint") == "DATA_DESIGN_REVIEW":
            upload_audit = record("resolve_design_data_mismatch", call("POST", f"/projects/{project_id}/conversation/command", token=token, body={"project_id": project_id, "message": "按当前两组迁移成绩数据修改为横断面组间差异，不作前测后测分析。"}))
            if upload_audit.get("checkpoint") != "RESEARCH_DESIGN_REVIEW":
                raise RuntimeError(f"design revision did not return to design review: {upload_audit}")
            revised_prereg = record("confirm_revised_design", call("POST", f"/projects/{project_id}/conversation/command", token=token, body={"project_id": project_id, "message": "确认横断面两组比较设计：group 为分组变量，transfer_score 为主要结果，不作因果解释。"}))
            if (revised_prereg.get("gate") or {}).get("gate_type") != "preregistration_freeze_approval":
                raise RuntimeError(f"revised design did not regenerate preregistration: {revised_prereg}")
            refrozen = record("refreeze_preregistration", call("POST", f"/projects/{project_id}/conversation/command", token=token, body={"project_id": project_id, "message": "确认并冻结修订后的预注册方案。"}))
            if (refrozen.get("gate") or {}).get("gate_type") != "raw_data_import_approval":
                raise RuntimeError(f"revised preregistration did not return to raw data intake: {refrozen}")
            upload_audit = record("reaudit_uploaded_data", call("POST", f"/projects/{project_id}/conversation/command", token=token, body={"project_id": project_id, "message": "请审计已上传的原始数据，检查字段、缺失值、重复记录和异常值。"}))
        if (upload_audit.get("gate") or {}).get("gate_type") != "dataset_freeze_hash_approval":
            raise RuntimeError(f"natural-language data audit did not advance to freeze review: {upload_audit}")
    else:
        require(call("POST", f"/projects/{project_id}/primary-data/upload", token=token, file=DATA), "upload data")
    data_audit_prompt = record("data_audit_request", call("POST", f"/projects/{project_id}/conversation/command", token=token, body={"project_id": project_id, "message": "请审计这份原始数据，检查字段、缺失值、重复记录和异常值。"}))
    if "原始数据审计已完成" not in str(data_audit_prompt.get("message")):
        raise RuntimeError(f"data-audit progress was not explained: {data_audit_prompt}")
    record("confirm_processing", call("POST", f"/projects/{project_id}/conversation/command", token=token, body={"project_id": project_id, "message": "确认数据处理方案，继续"}))
    analysis_prompt = record("request_analysis", call("POST", f"/projects/{project_id}/conversation/command", token=token, body={"project_id": project_id, "message": "请根据冻结的数据和研究方案生成分析代码，并进行物理公式、单位和统计逻辑检查。"}))
    if "分析代码" not in str(analysis_prompt.get("message")):
        raise RuntimeError(f"analysis progress was not explained: {analysis_prompt}")
    result_review = record("confirm_execution", call("POST", f"/projects/{project_id}/conversation/command", token=token, body={"project_id": project_id, "message": "确认执行分析"}))
    if result_review.get("checkpoint") != "RESULT_INTERPRETATION_REVIEW":
        raise RuntimeError(f"execution did not pause at interpretation: {result_review}")
    writing_prompt = record("confirm_interpretation", call("POST", f"/projects/{project_id}/conversation/command", token=token, body={"project_id": project_id, "message": "确认仅报告组间差异和不确定性，不作超出研究设计的因果结论。"}))
    if writing_prompt.get("checkpoint") != "MANUSCRIPT_OUTLINE_REVIEW":
        raise RuntimeError(f"interpretation did not pause at manuscript outline: {writing_prompt}")
    final_draft = record("confirm_outline", call("POST", f"/projects/{project_id}/conversation/command", token=token, body={"project_id": project_id, "message": "确认论文大纲，保留局限性与数据可追溯性章节，生成正文。"}))
    if (final_draft.get("gate") or {}).get("gate_type") != "manuscript_citation_verification_approval":
        raise RuntimeError(f"outline confirmation did not reach citation verification: {final_draft}")
    citation_review = record("confirm_citation_verification", call("POST", f"/projects/{project_id}/conversation/command", token=token, body={"project_id": project_id, "message": "我已核对引用来源、原文定位和结果卡链接，确认引用核验并进入独立审稿。"}))
    if (citation_review.get("gate") or {}).get("gate_type") != "reviewer_final_confirmation_approval":
        raise RuntimeError(f"citation verification did not reach final review: {citation_review}")
    reviewer_confirmation = call("POST", f"/projects/{project_id}/conversation/command", token=reviewer_token, body={"project_id": project_id, "message": "确认论文内容，进入最终审查"})
    require(reviewer_confirmation, "reviewer final confirmation")
    record("reviewer_final_confirmation", reviewer_confirmation)
    final_state = require(call("GET", f"/projects/{project_id}/control-state", token=token), "final state")
    contents = require(call("GET", f"/workflow/projects/{project_id}/artifact-contents", token=token), "artifact contents")
    artifact_types = {item.get("artifact_type") for item in contents}
    required_types = {
        "EvidenceReviewPackage", "StudyProtocolCandidate", "DataAuditCandidate", "DatasetFreezeHashCandidate",
        "AnalysisCodePlanCandidate", "PhysicsCodeValidationCandidate", "SandboxExecutionCandidate",
        "StatisticalResultCardCandidate", "BootstrapRobustnessCandidate", "PermutationTestCandidate",
        "ManuscriptDraftZh", "ManuscriptCitationVerification", "FinalReviewPacket",
    }
    missing_types = sorted(required_types - artifact_types)
    if final_state.get("lifecycle_status") != "COMPLETED" or missing_types:
        raise RuntimeError(json.dumps({"final_lifecycle": final_state.get("lifecycle_status"), "missing_types": missing_types}, ensure_ascii=False))
    outline = next((item.get("body", {}) for item in contents if item.get("artifact_type") == "ManuscriptOutline"), {})
    outline_title = outline.get("title", "") if isinstance(outline, dict) else ""
    if not isinstance(outline_title, str) or "RESEARCH_" in outline_title or "研究者在" in outline_title:
        raise RuntimeError(f"manuscript outline title contains workflow feedback: {outline_title!r}")
    manuscript = next((item.get("body", {}) for item in reversed(contents) if item.get("artifact_type") == "ManuscriptDraftZh"), {})
    manuscript_title = manuscript.get("sections", {}).get("title", "") if isinstance(manuscript, dict) else ""
    if not isinstance(manuscript_title, str) or any(term in manuscript_title for term in ("继续搜索", "补充检索", "前测", "后测")):
        raise RuntimeError(f"quantitative manuscript title retained stale workflow/design text: {manuscript_title!r}")
    latest_protocol = next((item.get("body", {}) for item in reversed(contents) if item.get("artifact_type") == "StudyProtocolCandidate"), {})
    if latest_protocol.get("primary_outcome") != "transfer_score（冻结 CSV 字段）":
        raise RuntimeError(f"revised protocol did not adopt the audited outcome: {latest_protocol!r}")
    print(json.dumps({"project_id": project_id, "researcher": researcher, "reviewer": reviewer, "records": records, "first_coverage": first_coverage, "second_coverage": second_coverage, "final_lifecycle": final_state.get("lifecycle_status"), "artifact_count": len(contents), "artifact_types": sorted(artifact_types), "final_state": final_state}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
