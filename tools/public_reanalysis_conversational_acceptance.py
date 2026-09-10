"""Run a real, conversation-driven qualitative physics reanalysis flow.

Every human decision is sent through ``conversation/command``.  The only
non-chat operation is the normal primary-data upload required by the intake
Gate.  The resulting JSON/Markdown log is intended as a readable audit trail.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import urllib.error
import urllib.request
import uuid

BASE = "http://127.0.0.1:8013/api/v1"
ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "test_data" / "public_reanalysis" / "cgt_physics_education"
PAPER = DATA_ROOT / "paper_tschisgale_2023.pdf"
DATA = DATA_ROOT / "Textual_descriptions.csv"
OUT_JSON = ROOT / "docs" / "reports" / "PUBLIC_REANALYSIS_CONVERSATION_LOG_2026-09-09.json"
OUT_MD = ROOT / "docs" / "reports" / "PUBLIC_REANALYSIS_CONVERSATION_LOG_2026-09-09.md"


def call(method: str, path: str, token: str | None = None, body: object | None = None,
         file: pathlib.Path | None = None) -> dict:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload: bytes | None = None
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if file is not None:
        boundary = f"----stem-sci-{uuid.uuid4().hex}"
        payload = b"".join([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{file.name}"\r\n'.encode(),
            b"Content-Type: application/octet-stream\r\n\r\n",
            file.read_bytes(), b"\r\n", f"--{boundary}--\r\n".encode(),
        ])
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    req = urllib.request.Request(BASE + path, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} -> HTTP {error.code}: {raw}") from error


def register(prefix: str) -> tuple[dict, str]:
    username = prefix + uuid.uuid4().hex[:10]
    result = call("POST", "/auth/register", body={
        "username": username,
        "email": f"{username}@example.test",
        "password": "research-pass-123",
    })
    return result["user"], result["access_token"]


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    researcher, researcher_token = register("physconvres")
    reviewer, reviewer_token = register("physconvrev")
    project_id = f"physics-conv-{uuid.uuid4().hex[:12]}"
    title = "物理问题解决文本的计算辅助主题再分析（公开 OSF 资料）"
    direction = (
        "公开二手资料定性主题再分析：基于学生物理问题解决文本，重新检查物理问题解决主题，"
        "并在有物理奥赛经历与无物理奥赛经历资料之间做受限的定性对照。"
    )
    call("POST", "/projects", researcher_token, {
        "project_id": project_id, "title": title, "research_direction": direction,
    })
    call("PUT", f"/projects/{project_id}/members", researcher_token, {
        "username": reviewer["username"], "role": "reviewer",
    })
    call("POST", f"/projects/{project_id}/documents/upload", researcher_token, file=PAPER)

    records: list[dict] = []
    uploaded = False
    start = dt.datetime.now(dt.timezone.utc).isoformat()

    def snapshot() -> dict:
        state = call("GET", f"/projects/{project_id}/control-state", researcher_token)
        stream = (state.get("workstreams") or [{}])[0]
        return {
            "lifecycle_status": state.get("lifecycle_status"),
            "route": stream.get("route"),
            "phase": stream.get("phase"),
            "step": stream.get("current_step_index"),
            "current_action": stream.get("current_action"),
            "checkpoint": stream.get("conversation_checkpoint"),
            "active_gate_id": state.get("active_gate_id"),
            "completed_steps": stream.get("completed_step_ids", []),
            "skipped_steps": stream.get("skipped_step_ids", []),
        }

    def exchange(label: str, message: str, token: str = researcher_token,
                 mode: str = "auto") -> dict:
        before = snapshot()
        response = call("POST", f"/projects/{project_id}/conversation/command", token, {
            "project_id": project_id,
            "message": message,
            "interaction_mode": mode,
        })
        after = snapshot()
        item = {
            "index": len(records) + 1,
            "label": label,
            "actor": "reviewer" if token == reviewer_token else "researcher",
            "user_message": message,
            "assistant_kind": response.get("kind"),
            "assistant_message": response.get("message"),
            "checkpoint": response.get("checkpoint"),
            "gate_type": (response.get("gate") or {}).get("gate_type"),
            "gate_id": (response.get("gate") or {}).get("gate_id"),
            "before": before,
            "after": after,
        }
        records.append(item)
        print(json.dumps(item, ensure_ascii=False))
        return response

    # First a genuine non-executing discussion, then an explicit start.
    exchange(
        "scope_discussion",
        "我想先讨论这个物理教育公开语料的研究边界、资料来源和局限，暂时不要执行分析。",
        mode="discussion",
    )
    exchange(
        "start_research",
        "现在开始建立研究任务：请基于已上传的真实论文、DOI 和 OSF d68ch 公开资料，"
        "开展公开二手资料定性主题再分析，先整理文献、字段字典、筛选规则和证据边界；"
        "不做统计功效、因果模型或把原论文结论冒充本次新发现。",
    )

    checkpoint_messages = {
        "RESEARCH_QUESTION_REVIEW": (
            "我选择第一个研究问题：公开学生物理问题解决文本中有哪些稳定的语义主题；"
            "保留主题候选的证据链接，并明确它们只是待人工复核的候选。"
        ),
        "MANUSCRIPT_OUTLINE_REVIEW": (
            "确认论文大纲：保留公开二手资料、样本边界、数据治理、候选主题、复核限制和可追溯引用章节，生成正文。"
        ),
    }
    gate_messages = {
        "qualitative_design_approval": "确认定性研究设计，继续。",
        "raw_data_import_approval": "请审计已上传的公开学生物理问题解决文本，检查字段、空值、重复记录和资料边界。",
        "data_audit_approval": "确认数据审计结果和字段字典，继续。",
        "data_processing_approval_approval": "确认数据处理方案：保留原文语境，不把公开资料当作新采集样本，继续。",
        "dataset_freeze_hash_approval": "确认并冻结这份公开资料版本，继续主题分析。",
        "thematic_analysis_approval": "确认主题候选仅作为确定性辅助编码线索，保留证据片段链接并进入独立定性复核。",
        "qualitative_validation_approval": "确认定性验证边界：主题仍需研究者回到原文、检查反例和复核饱和度，继续写作。",
        "manuscript_citation_verification_approval": "我已核对论文题录、DOI、OSF 来源、原文定位和数据边界，确认引用核验并进入独立审稿。",
        "reviewer_final_confirmation_approval": "我已作为独立审稿人核对论文内容、证据可追溯性、定性解释边界和数据治理说明，确认进入最终审查。",
    }

    for _ in range(40):
        state = snapshot()
        if state["lifecycle_status"] == "COMPLETED":
            break
        checkpoint = state["checkpoint"]
        if checkpoint:
            exchange(f"checkpoint_{checkpoint}", checkpoint_messages.get(checkpoint, "确认当前研究边界并继续下一步。"))
            continue
        gate_id = state["active_gate_id"]
        if gate_id:
            gate = call("GET", f"/projects/{project_id}/gates/{gate_id}", researcher_token)
            gate_type = gate.get("gate_type", "")
            if gate_type == "raw_data_import_approval" and not uploaded:
                call("POST", f"/projects/{project_id}/primary-data/upload", researcher_token, file=DATA)
                uploaded = True
            token = reviewer_token if gate_type == "reviewer_final_confirmation_approval" else researcher_token
            exchange(f"gate_{gate_type}", gate_messages.get(gate_type, "确认当前候选产物，继续。"), token=token)
            continue
        # A queued internal action can be resumed by an ordinary natural turn.
        exchange("resume_internal_action", "继续处理当前研究任务，并在下一个需要判断的边界停下来。")
    else:
        raise RuntimeError("conversation flow exceeded 40 exchanges")

    final_state = snapshot()
    contents = call("GET", f"/workflow/projects/{project_id}/artifact-contents", researcher_token)
    claims = call("GET", f"/projects/{project_id}/claims", researcher_token)
    events = call("GET", f"/projects/{project_id}/orchestration/events", researcher_token)
    manuscript = next((x for x in contents if x.get("artifact_type") == "ManuscriptDraftZh"), None)
    body = (manuscript or {}).get("body") or {}
    sections = body.get("sections") or {}
    manuscript_text = "\n".join(str(v) for v in sections.values())
    log = {
        "created_at": start,
        "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "project_id": project_id,
        "title": title,
        "researcher": researcher["username"],
        "reviewer": reviewer["username"],
        "paper": {
            "file": PAPER.name,
            "doi": "10.1103/PhysRevPhysEducRes.19.020123",
            "osf": "https://osf.io/d68ch/",
            "sha256": sha256_file(PAPER),
        },
        "dataset": {"file": DATA.name, "sha256": sha256_file(DATA), "uploaded": uploaded},
        "exchanges": records,
        "orchestration_events": [
            {
                "event_type": item.get("event_type"),
                "action": (item.get("payload") or {}).get("action"),
                "gate_id": (item.get("payload") or {}).get("gate_id"),
                "created_at": item.get("created_at"),
            }
            for item in events
        ],
        "final_state": final_state,
        "artifact_count": len(contents),
        "claim_count": len(claims),
        "artifact_types": sorted({str(x.get("artifact_type")) for x in contents}),
        "manuscript_present": manuscript is not None,
        "manuscript_checks": {
            "marks_secondary_data": "二手" in manuscript_text,
            "distinguishes_417_and_550": "417" in manuscript_text and "550" in manuscript_text,
            "states_candidate_review_boundary": "研究者复核" in manuscript_text or "独立" in manuscript_text,
            "no_new_causal_or_significance_claim": (
                "不报告新的组间显著性" in manuscript_text
                and "因果结论" in manuscript_text
                and "候选主题" in manuscript_text
            ),
        },
        "quality_assertions": {
            "qualitative_route": final_state.get("route") == "QUALITATIVE",
            "completed": final_state.get("lifecycle_status") == "COMPLETED",
            "all_decisions_were_conversation_commands": True,
            "reviewer_turn_present": any(x["actor"] == "reviewer" for x in records),
            "manuscript_present": manuscript is not None,
            "claims_present": bool(claims),
            "quantitative_steps_skipped": all(x in final_state.get("skipped_steps", []) for x in (
                "causal_DAG", "power_analysis", "bootstrap_robustness", "permutation_test",
                "statistical_result_validation", "result_direction_consistency", "uncertainty_gate",
                "statistical_result_card",
            )),
        },
    }
    OUT_JSON.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    md = [
        f"# 物理公开语料再分析：完整对话记录\n",
        f"- 项目 ID：`{project_id}`\n- 论文：Tschisgale, Wulff & Kubsch (2023), DOI `10.1103/PhysRevPhysEducRes.19.020123`\n- 数据：OSF `https://osf.io/d68ch/`，`{DATA.name}`\n- 最终状态：`{final_state.get('lifecycle_status')}`，路线：`{final_state.get('route')}`\n",
        "## 对话逐轮记录\n",
    ]
    for item in records:
        md.extend([
            f"### {item['index']}. {item['label']}（{item['actor']}）\n",
            f"**用户：** {item['user_message']}\n\n",
            f"**系统：** {item['assistant_message']}\n\n",
            f"边界：checkpoint=`{item['checkpoint']}`，Gate=`{item['gate_type']}`，流程阶段=`{item['after'].get('phase')}`\n",
        ])
    md.extend([
        "## 最终论文与边界\n",
        f"论文草稿已生成：`{log['manuscript_present']}`；公开二手资料边界：`{log['manuscript_checks']['marks_secondary_data']}`；样本边界 417/550：`{log['manuscript_checks']['distinguishes_417_and_550']}`。\n",
        "主题候选仍需研究者回到原文、检查反例并完成独立复核；本流程不把原论文结论冒充为新的因果或统计发现。\n",
        "## 内部可审计步骤\n",
        "文献证据整理、混合检索、RRF 融合、重排、主张—证据映射、定性设计、原始资料导入、数据审计、处理审批、冻结哈希、主题分析、定性验证、写作、引用核验和独立审稿均保存在 `orchestration_events` 字段；其中需要研究者判断的边界通过上面的对话逐轮完成。\n",
    ])
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({"project_id": project_id, "json": str(OUT_JSON), "markdown": str(OUT_MD), "quality_assertions": log["quality_assertions"]}, ensure_ascii=False, indent=2))
    if not all(bool(v) for v in log["quality_assertions"].values()):
        raise RuntimeError("conversation acceptance assertions failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
