"""End-to-end acceptance using conversation commands for every workflow decision."""

from __future__ import annotations

import json
import pathlib
import sys
import uuid

from public_reanalysis_acceptance import call, register, require

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAPER = ROOT / "test_data" / "stem_ways_thinking_2025.pdf"
DATA = ROOT / "test_data" / "sphere_fci_quantitative.csv"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    researcher, token = register("natural")
    reviewer, reviewer_token = register("naturalreview")
    project_id = f"natural-{uuid.uuid4().hex[:10]}"
    direction = "Public secondary-data reanalysis: compare FCI conceptual understanding scores between coded groups in the public SPHERE data; report descriptive association only, not causality."
    require(call("POST", "/projects", token=token, body={
        "project_id": project_id,
        "title": "SPHERE 物理概念理解自然语言验收",
        "research_direction": direction,
    }), "create project")
    require(call("PUT", f"/projects/{project_id}/members", token=token, body={
        "username": reviewer, "role": "reviewer",
    }), "add reviewer")
    require(call("POST", f"/projects/{project_id}/documents/upload", token=token, file=PAPER), "upload paper")

    records: list[dict[str, object]] = []

    forbidden_chat_markers = (
        "shared_evd_", "ctx_", "evidence id", "gate_type", "task queued",
    )

    def command(
        label: str,
        message: str,
        actor_token: str = token,
        *,
        expect_discussion: bool = False,
    ) -> dict:
        result = require(call("POST", f"/projects/{project_id}/conversation/command", token=actor_token, body={
            "project_id": project_id, "message": message, "interaction_mode": "auto",
        }), label)
        state = require(call("GET", f"/projects/{project_id}/control-state", token=token), "state")
        stream = (state.get("workstreams") or [{}])[0]
        item = {
            "label": label,
            "kind": result.get("kind"),
            "message": str(result.get("message", "")),
            "gate": (result.get("gate") or {}).get("gate_type"),
            "checkpoint": result.get("checkpoint"),
            "lifecycle": state.get("lifecycle_status"),
            "step": stream.get("current_step_index") if isinstance(stream, dict) else None,
        }
        records.append(item)
        print(json.dumps(item, ensure_ascii=False))
        rendered = str(result.get("message", "")).lower()
        if expect_discussion:
            if result.get("kind") != "qa" or result.get("gate") is not None or result.get("checkpoint") is not None:
                raise RuntimeError(f"{label} was not an ordinary discussion turn: {json.dumps(result, ensure_ascii=False)}")
            if any(marker in rendered for marker in forbidden_chat_markers):
                raise RuntimeError(f"{label} leaked an internal workflow marker: {json.dumps(result, ensure_ascii=False)}")
        return result

    def expect_boundary(
        label: str,
        result: dict,
        *,
        gate: str | None = None,
        checkpoint: str | None = None,
    ) -> None:
        actual_gate = (result.get("gate") or {}).get("gate_type")
        actual_checkpoint = result.get("checkpoint")
        if actual_gate != gate or actual_checkpoint != checkpoint:
            raise RuntimeError(
                f"{label} reached the wrong boundary: expected gate={gate!r}, "
                f"checkpoint={checkpoint!r}, got {json.dumps(result, ensure_ascii=False)}"
            )

    command(
        "ordinary_discussion",
        "我想使用公开 SPHERE 数据研究不同编码组的 FCI 概念理解差异。先只讨论研究边界、变量和局限，不要检索，也不要运行分析。",
        expect_discussion=True,
    )
    started = command(
        "start_research",
        "现在开始建立研究任务：请检索并整理与这个问题相关的文献，基于已上传论文和公开 SPHERE 数据形成证据审阅。研究只做横断面两组描述性比较，不作因果结论。",
    )
    expect_boundary("start_research", started, gate="evidence_sufficiency_review")
    questions = command("evidence_sufficient", "当前证据足够。请提出研究问题候选。")
    expect_boundary("evidence_sufficient", questions, checkpoint="RESEARCH_QUESTION_REVIEW")
    design = command("select_question", "选择第一个研究问题：只比较 group 与 transfer_score 的描述性差异，不作因果解释。")
    expect_boundary("select_question", design, checkpoint="RESEARCH_DESIGN_REVIEW")
    preregistration = command("confirm_design", "确认研究方案：横断面两组比较，只报告描述性差异和不确定性，不作因果解释。")
    expect_boundary("confirm_design", preregistration, gate="preregistration_freeze_approval")
    raw_data = command("freeze_design", "确认并冻结预注册方案。")
    expect_boundary("freeze_design", raw_data, gate="raw_data_import_approval")
    require(call("POST", f"/projects/{project_id}/primary-data/upload", token=token, file=DATA), "upload data")
    frozen_data = command("audit_data", "请审计已上传的原始数据，检查字段、缺失值、重复记录和异常值。")
    expect_boundary("audit_data", frozen_data, gate="dataset_freeze_hash_approval")
    execution = command("confirm_data", "确认数据处理方案，继续。")
    expect_boundary("confirm_data", execution, gate="manual_execution_approval_approval")
    interpretation = command("execute_analysis", "确认执行分析，并在完成后只报告描述性差异和不确定性。")
    expect_boundary("execute_analysis", interpretation, checkpoint="RESULT_INTERPRETATION_REVIEW")
    revision = command("confirm_interpretation", "确认结果解释：只报告 group 与 transfer_score 的描述性差异和不确定性，不作因果结论。")
    expect_boundary("confirm_interpretation", revision, checkpoint="MANUSCRIPT_REVISION_REVIEW")
    citation = command(
        "revise_manuscript",
        "请按全部写作审查意见修改论文，保留已经核验的数字、结果和引用，然后重新进行写作质量检查。",
    )
    expect_boundary("revise_manuscript", citation, gate="manuscript_citation_verification_approval")
    final_review = command(
        "verify_citations",
        "我已核对引用来源、原文定位和结果卡链接，确认引用核验并进入独立审查。",
    )
    expect_boundary("verify_citations", final_review, gate="reviewer_final_confirmation_approval")
    completed = command("reviewer_final", "我已核对论文内容，确认进入最终审查。", reviewer_token)
    expect_boundary("reviewer_final", completed)

    final_state = require(call("GET", f"/projects/{project_id}/control-state", token=token), "final state")
    contents = require(call("GET", f"/workflow/projects/{project_id}/artifact-contents", token=token), "artifacts")
    artifact_types = sorted({item.get("artifact_type") for item in contents})
    manuscripts = [item for item in contents if item.get("artifact_type") == "ManuscriptDraftZh"]
    manuscript = manuscripts[-1].get("body", {}) if manuscripts else {}
    sections = manuscript.get("sections", {}) if isinstance(manuscript, dict) else {}
    section_text = json.dumps(sections, ensure_ascii=False).lower()
    forbidden_manuscript_markers = (
        "shared_evd_", "ctx_", "claim:", "artifact-", "task-",
        "gate_type", "document://", "sha-256：",
    )
    leaked_markers = [marker for marker in forbidden_manuscript_markers if marker in section_text]
    traceability_preserved = bool(
        isinstance(manuscript, dict)
        and manuscript.get("claim_records")
        and manuscript.get("citation_refs")
    )
    result_cards = [item for item in contents if item.get("artifact_type") == "StatisticalResultCardCandidate"]
    result_card_body = result_cards[-1].get("body", {}) if result_cards else {}
    statistical_card = (
        result_card_body.get("statistical_result_card", {})
        if isinstance(result_card_body, dict) else {}
    )
    result_values = statistical_card.get("values", {}) if isinstance(statistical_card, dict) else {}
    result_text = str(sections.get("results", "")) if isinstance(sections, dict) else ""
    missing_result_values = [
        key for key, value in result_values.items()
        if f"{key}={float(value):.4g}" not in result_text
    ] if isinstance(result_values, dict) else ["statistical_result_card"]
    expected_numeric_literals = [f"{float(value):.4g}" for value in result_values.values()]
    numeric_metadata_matches = (
        isinstance(manuscript, dict)
        and manuscript.get("numeric_literals") == expected_numeric_literals
    )
    expected_result_ref = (
        f"result-card://{statistical_card.get('result_id')}"
        if isinstance(statistical_card, dict) and statistical_card.get("result_id") else None
    )
    result_ref_matches = bool(
        expected_result_ref
        and isinstance(manuscript, dict)
        and manuscript.get("result_card_ref") == expected_result_ref
    )
    result = {
        "project_id": project_id,
        "researcher": researcher,
        "reviewer": reviewer,
        "paper": PAPER.name,
        "dataset": DATA.name,
        "final_lifecycle": final_state.get("lifecycle_status"),
        "artifact_count": len(contents),
        "artifact_types": artifact_types,
        "has_manuscript": "ManuscriptDraftZh" in artifact_types,
        "manuscript_sections_hide_internal_ids": not leaked_markers,
        "manuscript_leaked_markers": leaked_markers,
        "audit_traceability_preserved": traceability_preserved,
        "manuscript_result_values_match_card": not missing_result_values,
        "manuscript_missing_result_values": missing_result_values,
        "numeric_metadata_matches_result_card": numeric_metadata_matches,
        "result_card_reference_matches": result_ref_matches,
        "all_turns_natural_language": True,
        "records": records,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if (
        result["final_lifecycle"] != "COMPLETED"
        or not result["has_manuscript"]
        or leaked_markers
        or not traceability_preserved
        or missing_result_values
        or not numeric_metadata_matches
        or not result_ref_matches
    ):
        raise RuntimeError(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
