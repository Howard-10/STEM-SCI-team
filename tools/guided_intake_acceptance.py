"""Live acceptance for the gradual, researcher-guided project entry flow."""

from __future__ import annotations

import json
import sys
import uuid

from standard_flow_acceptance import DATA, PAPER, call, register, require


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    if not PAPER.is_file() or not DATA.is_file():
        raise RuntimeError("guided acceptance fixtures are missing")

    researcher, researcher_token = register("guided")
    reviewer, reviewer_token = register("guidedreview")
    project_id = f"guided-{uuid.uuid4().hex[:10]}"
    broad_topic = "我想研究本科物理课里使用计算建模对学生学习的影响。"
    require(call("POST", "/projects", token=researcher_token, body={
        "project_id": project_id,
        "title": "引导式研究流程验收",
        "research_direction": broad_topic,
    }), "create guided project")
    require(call("PUT", f"/projects/{project_id}/members", token=researcher_token, body={
        "username": reviewer,
        "role": "reviewer",
    }), "add guided reviewer")
    require(call("POST", f"/projects/{project_id}/documents/upload", token=researcher_token, file=PAPER), "upload paper")

    trace: list[dict[str, object]] = []

    def send(label: str, token: str, message: str) -> dict[str, object]:
        result = call("POST", f"/projects/{project_id}/conversation/command", token=token, body={
            "project_id": project_id,
            "message": message,
        })
        body = require(result, label)
        state = body.get("control_state", {})
        stream = (state.get("workstreams") or [{}])[0]
        record = {
            "label": label,
            "elapsed_ms": result["elapsed_ms"],
            "message": body.get("message"),
            "waiting_for_user": body.get("waiting_for_user", False),
            "gate": (body.get("gate") or {}).get("gate_type"),
            "intake_key": (body.get("intake") or {}).get("current_question_key"),
            "step": stream.get("current_step_index"),
            "action": stream.get("current_action"),
        }
        trace.append(record)
        print(json.dumps(record, ensure_ascii=False))
        return body

    first = send("broad_topic", researcher_token, broad_topic)
    if not first.get("waiting_for_user") or (first.get("intake") or {}).get("current_question_key") != "research_goal":
        raise RuntimeError(f"broad topic did not start clarification: {first}")
    before_answers = require(call("GET", f"/workflow/projects/{project_id}/artifact-contents", token=researcher_token), "artifacts before answers")
    if before_answers:
        raise RuntimeError("broad topic produced research artifacts before the brief was completed")

    answers = [
        ("research_goal", "我想描述公开数据中不同性别编码组的物理概念理解得分差异，不声称因果。"),
        ("research_focus", "公开 SPHERE FCI 数据中的学生，以及 group 和 transfer_score 两个变量。"),
        ("expected_contribution", "提供一份可追溯的公开二手资料描述，帮助后续教学研究提出假设。"),
        ("data_source", "已上传 STEM 物理教育论文，另有公开 SPHERE FCI CSV；数据已去标识化。"),
        ("method_boundary", "倾向观察性两组描述性比较，不进行个体随机，也不作因果解释。"),
        ("constraints", "只使用公开资料，保留来源和不确定性说明，不能把题录或相关性写成因果结论。"),
    ]
    for index, (key, answer) in enumerate(answers):
        body = send(f"answer_{key}", researcher_token, answer)
        if index < len(answers) - 1:
            if not body.get("waiting_for_user"):
                raise RuntimeError(f"intake advanced prematurely at {key}: {body}")
            artifacts = require(call("GET", f"/workflow/projects/{project_id}/artifact-contents", token=researcher_token), f"artifacts after {key}")
            if artifacts:
                raise RuntimeError(f"intake generated artifacts before all answers at {key}")
        elif not body.get("waiting_for_user") or (body.get("intake") or {}).get("status") != "COMPLETE":
            raise RuntimeError(f"completed intake did not return a research brief: {body}")

    intake = require(call("GET", f"/projects/{project_id}/research-intake", token=researcher_token), "read completed intake")
    if intake.get("status") != "COMPLETE" or len(intake.get("answers", {})) != 6:
        raise RuntimeError(f"intake was not durably complete: {intake}")
    confirmed = send("confirm_brief", researcher_token, "确认研究简报，开始检索。")
    if (confirmed.get("gate") or {}).get("gate_type") != "evidence_sufficiency_review":
        raise RuntimeError(f"brief confirmation did not start evidence review: {confirmed}")
    first_package = require(call("GET", f"/projects/{project_id}/evidence-review", token=researcher_token), "first review package")
    first_coverage = first_package["body"]["coverage"]
    if first_coverage.get("source_count", 0) < 1:
        raise RuntimeError(f"uploaded paper missing from guided evidence review: {first_coverage}")
    # External discovery is optional in the offline acceptance instance. A
    # zero count is a visible risk, not a reason to skip the local evidence
    # and analysis workflow.
    if first_coverage.get("external_candidate_count", 0) < 1:
        print(json.dumps({"external_discovery": "unavailable_or_zero", "coverage": first_coverage}, ensure_ascii=False))

    revised = send("incremental_search", researcher_token, "继续搜索")
    second_package = require(call("GET", f"/projects/{project_id}/evidence-review", token=researcher_token), "second review package")
    second_coverage = second_package["body"]["coverage"]
    if (revised.get("gate") or {}).get("gate_type") != "evidence_sufficiency_review":
        raise RuntimeError(f"guided incremental search failed: {revised}, {second_coverage}")
    if "本轮检索完成：新增" not in str(revised.get("message")):
        raise RuntimeError(f"guided incremental search did not report delta counts: {revised}")

    approved = send("evidence_sufficient", researcher_token, "证据足够")
    selected_question = send(
        "select_question",
        researcher_token,
        "选择第 1 个研究问题：只比较公开样本中 group 与 transfer_score 的描述性差异，不作因果解释。",
    )
    design_contents = require(
        call("GET", f"/workflow/projects/{project_id}/artifact-contents", token=researcher_token),
        "design artifacts",
    )
    question = next(item["body"] for item in design_contents if item.get("artifact_type") == "ResearchQuestionTree")
    protocol = next(item["body"] for item in design_contents if item.get("artifact_type") == "StudyProtocolCandidate")
    question_text = question["primary_question"]
    if not all(fragment in question_text for fragment in ("公开 SPHERE FCI", "group", "transfer_score")):
        raise RuntimeError(f"research question ignored intake answers: {question_text}")
    if "高中物理教师" in question_text or protocol.get("primary_outcome", "").startswith("待确认"):
        raise RuntimeError(f"design fell back to a generic template: {protocol}")
    if selected_question.get("checkpoint") != "RESEARCH_DESIGN_REVIEW":
        raise RuntimeError(f"question selection did not open design checkpoint: {selected_question}")
    confirmed_design = send(
        "confirm_design",
        researcher_token,
        "确认研究方案：只报告 group 与 transfer_score 的描述性差异，不作因果解释。",
    )
    if (confirmed_design.get("gate") or {}).get("gate_type") != "preregistration_freeze_approval":
        raise RuntimeError(f"design confirmation did not open preregistration checkpoint: {confirmed_design}")
    preregistered = send("confirm_preregistration", researcher_token, "确认预注册方案并冻结，继续下一步")
    if (preregistered.get("gate") or {}).get("gate_type") != "raw_data_import_approval":
        raise RuntimeError(f"preregistration approval did not open raw-data checkpoint: {preregistered}")
    state = require(call("GET", f"/projects/{project_id}/control-state", token=researcher_token), "raw data gate state")
    gate = require(call("GET", f"/projects/{project_id}/gates/{state['active_gate_id']}", token=researcher_token), "raw data gate")
    if gate.get("gate_type") != "raw_data_import_approval":
        raise RuntimeError(f"expected raw-data checkpoint: {gate}")
    require(call("POST", f"/projects/{project_id}/primary-data/upload", token=researcher_token, file=DATA), "upload guided data")
    audited = send("audit_uploaded_data", researcher_token, "请审计这份原始数据，检查字段、缺失值、重复记录和异常值。")
    if (audited.get("gate") or {}).get("gate_type") != "dataset_freeze_hash_approval":
        raise RuntimeError(f"natural-language data audit did not advance to freeze review: {audited}")
    send("confirm_processing", researcher_token, "确认数据处理方案，继续")
    send("confirm_execution", researcher_token, "请根据冻结的数据和研究方案生成分析代码并检查。确认执行分析。")
    send("confirm_results", researcher_token, "确认结果验证，继续写作")
    send(
        "confirm_outline",
        researcher_token,
        "确认论文大纲，保留结果边界、局限性和数据可追溯性章节，生成正文。",
    )
    send(
        "confirm_citation_verification",
        researcher_token,
        "我已核对论文引用、来源定位和结果卡链接，确认引用核验并进入独立审稿。",
    )
    completed = send("reviewer_confirmation", reviewer_token, "确认论文内容，进入最终审查")
    if completed.get("control_state", {}).get("lifecycle_status") != "COMPLETED":
        raise RuntimeError(f"reviewer did not complete guided workflow: {completed}")

    contents = require(call("GET", f"/workflow/projects/{project_id}/artifact-contents", token=researcher_token), "guided artifacts")
    artifact_types = {item.get("artifact_type") for item in contents}
    required = {"EvidenceReviewPackage", "StudyProtocolCandidate", "DataAuditCandidate", "StatisticalResultCardCandidate", "ManuscriptDraftZh", "FinalReviewPacket"}
    missing = sorted(required - artifact_types)
    if missing:
        raise RuntimeError(f"guided workflow omitted output types: {missing}")
    manuscript = next(item["body"] for item in contents if item.get("artifact_type") == "ManuscriptDraftZh")
    manuscript_text = json.dumps(manuscript, ensure_ascii=False)
    if "group" not in manuscript_text or "transfer_score" not in manuscript_text:
        raise RuntimeError(f"manuscript did not use the uploaded CSV mapping: {manuscript_text}")
    print(json.dumps({
        "project_id": project_id,
        "researcher": researcher,
        "reviewer": reviewer,
        "intake_answers": intake["answers"],
        "first_coverage": first_coverage,
        "second_coverage": second_coverage,
        "artifact_types": sorted(artifact_types),
        "trace": trace,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
