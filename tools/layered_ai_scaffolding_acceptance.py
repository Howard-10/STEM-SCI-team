"""Deterministic acceptance checks for the layered-scaffold case.

This runner is intentionally small and result-blind. It validates the paper's
research structure, the synthetic fixture, and the bounded fallback answers;
it does not turn the fixture into evidence of a teaching effect.
"""

from __future__ import annotations

import csv
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from stem_sci.knowledge.qa_service import _discussion_fallback_answer


FIXTURE = ROOT / "test_data" / "layered_ai_scaffolding"


def rows(name: str) -> list[dict[str, str]]:
    with (FIXTURE / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def live_request(base: str, method: str, path: str, *, token: str | None = None, body: object | None = None) -> dict[str, object]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(base.rstrip("/") + path, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise AssertionError(f"live {method} {path} -> HTTP {error.code}: {detail}") from error


def run_live(base: str) -> None:
    username = f"layered_accept_{uuid.uuid4().hex[:10]}"
    registered = live_request(base, "POST", "/auth/register", body={
        "username": username,
        "email": f"{username}@example.test",
        "password": "research-pass-123",
    })
    token = str(registered.get("access_token") or "")
    require(token, "live registration did not return a token")
    project_id = f"layered-accept-{uuid.uuid4().hex[:10]}"
    live_request(base, "POST", "/projects", token=token, body={
        "project_id": project_id,
        "title": "分层 AI 支架与无 AI 独立迁移案例",
        "research_direction": "大一物理师范生 Python 物理建模中的分层生成式 AI 支架，关注撤除 AI 后的独立迁移",
    })
    messages = [
        "我想研究生成式 AI 支架撤除后，学生能否在新情境中独立迁移。",
        "主要结局是第 8 周完全关闭 AI 后的个人无 AI 延迟迁移，课程内表现作为次要结局。",
        "对象是大一物理师范生，任务要求假设、方程、代码和验证。",
        "比较 L1-L5 分层支架与常规支持，后半程逐步渐隐。",
        "课堂按四人团队实施，但 Week 8 对每个学生单独测量，请推荐分配和分析结构。",
        "请把目标、设计、主要结局和模拟研究边界整理成研究合同。",
        "只使用模拟资料做流程验证，保留伦理、数据安全和外推边界，不能把模拟结果写成真实教学效果。",
        "请检查 L1-L5 和六周渐隐的触发条件、升级规则、开放比例和日志字段。",
        "请设计 Week 8 迁移评分量规和盲法评分流程。",
        "请根据设计推荐 RQ2 的 estimand、协变量、固定效应、聚类层级和替代方案。",
        "请让独立 Code Reviewer 检查层级错配、数据泄漏、模拟数字写死和自由度。",
        "目前没有实际执行产物时，能否报告调整差异和 p 值，如何标记模拟结果？",
        "如果完整案例和 delta-adjusted 缺失敏感性尚未执行，请说明应如何解释以及不能声称什么。",
        "请扫描当前研究叙事中的因果措辞，把提高、促进、导致、机制降级。",
        "请让与写作角色隔离的 Reviewer 只读冻结稿、结果卡和证据表，列出 P0/P1/P2 问题。",
    ]
    marker_checks = {
        # These first-turn markers distinguish the intended case response from
        # a generic intake answer that merely happens to mention transfer.
        0: ("先把两个问题分开", "独立迁移"),
        1: ("个人无 AI 延迟迁移",),
        2: ("五个维度",),
        4: ("团队", "聚类"),
        7: ("L1", "记录"),
        8: ("五维", "不知道处理条件"),
        9: ("estimand", "CR2"),
        10: ("Code Reviewer",),
        11: ("模拟研究流程证据", "真实教学效果"),
        13: ("探索性关联",),
        14: ("隔离 Reviewer", "P0/P1/P2"),
    }
    records: list[dict[str, object]] = []
    for index, message in enumerate(messages):
        response = live_request(
            base,
            "POST",
            f"/projects/{project_id}/conversation/command",
            token=token,
            body={
                "project_id": project_id,
                "message": message,
                "interaction_mode": "discussion",
                "evidence_mode": "discovery",
                "execution_mode": "sync",
                "client_turn_id": str(uuid.uuid4()),
            },
        )
        dialogue = response.get("dialogue") if isinstance(response.get("dialogue"), dict) else {}
        collaboration = response.get("collaboration") if isinstance(response.get("collaboration"), dict) else {}
        plan = collaboration.get("plan") if isinstance(collaboration.get("plan"), dict) else {}
        planned_question = plan.get("question_to_user")
        if response.get("kind") == "qa":
            require(
                dialogue.get("question") == planned_question,
                f"turn {index + 1}: dialogue question drifted; dialogue={dialogue.get('question')!r}; planned={planned_question!r}; collaboration_keys={list(collaboration)}; response_kind={response.get('kind')!r}",
            )
            require(response.get("waiting_for_user") is True, f"turn {index + 1}: discussion unexpectedly stopped")
        for marker in marker_checks.get(index, ()):
            response_text = str(response.get("message") or response.get("answer") or "")
            require(marker in response_text, f"turn {index + 1}: missing marker {marker!r}; response={response_text[:240]!r}")
        records.append({
            "turn": index + 1,
            "guided_key": plan.get("guided_question_key"),
            "question_present": bool(dialogue.get("question")),
            "message_preview": str(response.get("message") or "")[:120],
        })
    print(json.dumps({"status": "PASS", "mode": "live", "project_id": project_id, "turns": records}, ensure_ascii=False, indent=2))


def main() -> None:
    manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    require(manifest["simulation_flag"] is True, "fixture must remain explicitly synthetic")

    students = rows("students.csv")
    teams = rows("teams.csv")
    course = rows("course_outcomes.csv")
    transfer = rows("week8_transfer.csv")
    events = rows("ai_events.csv")
    raters = rows("rater_scores.csv")

    student_ids = {row["student_id"] for row in students}
    team_ids = {row["team_id"] for row in teams}
    require(len(students) == 8 and len(team_ids) == 4, "smoke fixture size changed unexpectedly")
    require({row["team_id"] for row in students} <= team_ids, "student-team join is not closed")
    require(all(row["condition"] in {"layered_ai", "usual_support"} for row in teams), "invalid condition")
    require(all(row["ai_available"] == "false" for row in transfer), "Week 8 must be no-AI")
    require({row["student_id"] for row in transfer} == student_ids, "transfer outcome is not student-level")
    require({row["student_id"] for row in course} == student_ids, "course outcome join is incomplete")
    require({row["student_id"] for row in raters} == student_ids, "rater coverage is incomplete")
    require(all(row["blind_condition"] == "true" for row in raters), "raters are not blind")
    require(all(row["simulation_flag"] == "true" for row in (*students, *teams, *course, *transfer, *events, *raters)), "simulation marker lost")

    context = "项目名称：分层 AI 支架与无 AI 独立迁移案例\n研究方向：大一物理师范生 Python 物理建模中的分层生成式 AI 支架"
    probes = {
        "主要结局": "个人无 AI 延迟迁移",
        "数据字典": "六张表",
        "estimand": "CR2/Satterthwaite",
        "代码审查": "团队级处理与聚类",
        "过程日志": "探索性过程证据",
        "结果卡": "不会引用论文中的 6.96",
        "因果措辞": "探索性关联",
        "独立审稿": "P0/P1/P2",
    }
    for question, expected in probes.items():
        answer = _discussion_fallback_answer(question, project_context=context)
        require(expected in answer, f"probe {question!r} lost expected boundary: {answer}")

    forbidden = ("已证明", "80 名学生当成 80 个独立")
    result_answer = _discussion_fallback_answer("请给我结果卡和显著性", project_context=context)
    require("模拟结果" in result_answer and "不能写成真实教学效果" in result_answer, "result boundary weakened")
    require(not any(term in result_answer for term in forbidden), "fallback invented a real effect")

    if "--live" in sys.argv:
        run_live(os.environ.get("STEM_SCI_ACCEPTANCE_BASE", "http://127.0.0.1:8015/api/v1"))

    print(json.dumps({
        "status": "PASS",
        "fixture": manifest["fixture_name"],
        "students": len(students),
        "teams": len(team_ids),
        "course_rows": len(course),
        "transfer_rows": len(transfer),
        "event_rows": len(events),
        "rater_rows": len(raters),
        "probes": len(probes),
        "simulation_only": True,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
