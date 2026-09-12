"""Run the complete 39-turn live showcase for the layered-scaffold case."""

from __future__ import annotations

import json
import os
import pathlib
import sys
import uuid
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from layered_ai_scaffolding_acceptance import live_request  # noqa: E402


MESSAGES = [
    "我想研究生成式 AI 在物理建模课里是不是能真正帮助学生学会迁移，而不是只是在 AI 可用时把题做出来。请像一名高水平助研一样引导我，每次只问一个最关键的问题，先不要写论文或编造数据。",
    "是的，我最关心的是 AI 完全关闭后，学生能不能在新的但结构相关的物理任务中独立建模。课程内表现作为次要结局。",
    "对象是大一物理师范生，课程用 Python 做运动、抛体、阻尼振动、电路瞬态、热传导和综合开放建模。每项任务都要求写出假设、方程、代码和验证证据。",
    "我想比较分层生成式 AI 支架和常规支持。AI 不是一开始就给完整答案，而是先要求学生说明目标、变量、假设和验证计划，再按需开放概念、建模、调试和局部示例支持，并在后半程逐步撤除。",
    "课堂里按四人团队实施支持，但我想在撤除 AI 后对每个学生单独测迁移。请你推荐最合适的分配和分析结构，并说明为什么。",
    "请把目前目标、设计、主要结局、次要结局和解释边界整理成一页研究合同，但先不要使用任何结果数字。",
    "请检查 L1–L5 和六周渐隐是否足以让别人复现干预。主动指出仍缺的操作定义，不要只说设计合理。",
    "当前文章使用人工生成数据验证流程，正式研究还没有招募学生。请把模拟研究和未来真实研究的伦理、同意、数据安全和外推边界分开。",
    "请设计 Week 8 的迁移任务原则。它要保持核心物理关系和建模逻辑，但改变表面情境、参数、数据形式和叙事，避免变成训练题记忆，也不能变成完全无关的新题。",
    "请设计迁移评分量规和评分流程，确保评分者不知道实验条件，并能区分会做模型、会写代码和会解释迁移。",
    "请告诉我为了完成这项研究需要哪些数据表和最低字段。现在只做数据需求，不假设文件已经存在。",
    "我现在提供与论文设计一致的模拟数据。请先识别文件，不做清洗、建模或写作。",
    "请审计学生、团队、自然班、周次和事件五个层级的主键、唯一性、连接关系、重复记录和缺失值。尤其检查团队分配是否能连接到学生结局。",
    "请验证每个团队只有一个条件、每班是否同时包含两种条件、每个学生是否只属于一个团队，并核对六周支架开放记录是否符合预设渐隐。",
    "请生成数据审计报告和冻结版本。保留原始数据，只从派生版本分析，并给出样本流转、哈希、缺失清单和版本时间。",
    "请根据设计主动推荐 RQ2 的 estimand、协变量、固定效应、聚类层级和主要模型。比较至少一个合理替代方案，并说明为什么不选它作为主分析。",
    "请把课程末建模、动机、焦虑、认知负荷、代码质量和错误率分成预先列出的次要结局，并说明重复测量和 FDR 如何处理。",
    "请设计 AI 日志的事件字典和探索性分析。高层支架采纳、直接答案、成功修改、验证和独立尝试都不能直接叫作学习机制。",
    "先不要写论文。请把审计、派生、主要分析、稳健性、评分一致性、图表和结果卡拆成可独立运行的模块，说明输入、输出、随机性、失败条件和测试。",
    "请由独立 Code Reviewer 检查分析代码，重点找层级错配、数据泄漏、把模拟数字写死、错误自由度、缺失处理和结果标签越权。只报告问题和修改建议，不直接替我批准执行。",
    "我批准在冻结数据和通过代码审查的模块上执行确定性分析。请先报告环境、软件版本、随机种子和执行计划，再运行。",
    "请生成 RQ2 主要结果卡。聊天中直接展示样本数、调整差值、95% CI、CR2 p、wild cluster bootstrap p、配对随机化 p 和模型诊断，并区分模拟结果与真实效果证据。",
    "请解释 20 个团队对聚类推断意味着什么。除了 p 值，还要报告自由度、残差、影响点、前测平衡和模型设定敏感性。",
    "请执行完整案例和对实验组不利/有利的 δ-adjusted 缺失敏感性分析，并判断结论是否依赖某一种缺失假设。",
    "请生成次要结局结果卡，特别说明哪些结果方向一致，哪些结果不稳定；不要把“所有指标都改善”作为总结。",
    "请解释六周代码质量轨迹。区分组别初始差异、时间趋势和组别乘周次交互，不要把较高起点写成增长更快。",
    "请报告两名评分者的 ICC、平均绝对差和评分流程限制。说明评分一致性高不等于测量已经无偏。",
    "请用研究助理的方式解释主要发现：先告诉我证据支持什么，再告诉我不能说什么，最后给出最合理的下一步。",
    "请解释五个 AI 使用过程指标，不要从正负系数直接推导学习机制。主动指出哪些替代解释最危险。",
    "请扫描当前研究叙事中的因果措辞。把“提高”“促进”“导致”“机制”分别改成证据允许的表述，并说明什么时候才可以使用更强措辞。",
    "请冻结结果卡。把证据分为已执行、候选解释和未执行，不允许写作阶段再修改数字或根据论文补结果。",
    "根据冻结结果卡生成论文大纲。每一节标记需要的证据、不能超过的解释边界和对应图表，不要直接填充漂亮但无来源的结论。",
    "请先写摘要和结果部分。聊天中直接展示最重要的样本结构、主要效应、敏感性和不稳定结果；不要只说“正文已生成”。",
    "请写方法部分，重点让别人能复现团队级配对区组分配、L1–L5 支架、六周渐隐、第 8 周无 AI 测验、盲法评分和聚类稳健推断。",
    "请围绕“即时任务增益不等于独立迁移”组织引言。引用支架理论、迁移理论、计算物理建模和 AI 认知卸载研究，但不要让参考文献替代本研究证据。",
    "请根据冻结结果写讨论。严格区分数据支持、理论一致和仍属推测的解释，并优先指出最可能改变结论的三项限制。",
    "请对完整候选稿做主张—证据核验。逐项检查数字、图表、样本结构、模拟声明、参考文献和因果措辞，并在聊天中直接报告核验摘要。",
    "请让与写作角色隔离的 Reviewer 只读冻结稿、结果卡和证据表，按 P0/P1/P2 列出问题，定位到章节和证据来源，不直接改稿，也不要让我人工冒充 Reviewer。",
    "请根据 Reviewer 报告冻结最终案例交付包。列出论文、结果卡、代码、日志、数据字典、图表、证据表、审稿记录、缺失项、稿件等级、哈希和冻结时间。冻结后不要再根据原论文改数字。",
]


def upload_primary_csv(base: str, project_id: str, token: str, path: pathlib.Path) -> dict[str, object]:
    boundary = f"----codex-{uuid.uuid4().hex}"
    content = path.read_bytes()
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"title\"\r\n\r\n分层 AI 支架模拟主数据\r\n".encode("utf-8"),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\nContent-Type: text/csv\r\n\r\n".encode("utf-8") + content + b"\r\n",
        f"--{boundary}--\r\n".encode("utf-8"),
    ]
    request = urllib.request.Request(
        base.rstrip("/") + f"/projects/{project_id}/primary-data/upload",
        data=b"".join(parts),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    base = os.environ.get("STEM_SCI_ACCEPTANCE_BASE", "http://127.0.0.1:8015/api/v1")
    username = f"layered_full_{uuid.uuid4().hex[:10]}"
    registered = live_request(base, "POST", "/auth/register", body={
        "username": username,
        "email": f"{username}@example.test",
        "password": "research-pass-123",
    })
    token = str(registered.get("access_token") or "")
    if not token:
        raise RuntimeError("registration did not return a token")
    project_id = f"layered-full-{uuid.uuid4().hex[:10]}"
    live_request(base, "POST", "/projects", token=token, body={
        "project_id": project_id,
        "title": "分层 AI 支架与无 AI 独立迁移完整案例",
        "research_direction": "大一物理师范生 Python 物理建模中的分层生成式 AI 支架，关注撤除 AI 后的独立迁移",
    })
    out_path = ROOT / "layered-full-live-run.jsonl"
    with out_path.open("w", encoding="utf-8") as output:
        for index, message in enumerate(MESSAGES, start=1):
            response = live_request(base, "POST", f"/projects/{project_id}/conversation/command", token=token, body={
                "project_id": project_id,
                "message": message,
                "interaction_mode": "discussion",
                "evidence_mode": "discovery",
                "execution_mode": "sync",
                "client_turn_id": str(uuid.uuid4()),
            })
            dialogue = response.get("dialogue") if isinstance(response.get("dialogue"), dict) else {}
            collaboration = response.get("collaboration") if isinstance(response.get("collaboration"), dict) else {}
            plan = collaboration.get("plan") if isinstance(collaboration.get("plan"), dict) else {}
            record = {
                "turn": index,
                "user": message,
                "response": str(response.get("message") or response.get("answer") or ""),
                "kind": response.get("kind"),
                "turn_role": dialogue.get("turn_role"),
                "dialogue_question": dialogue.get("question"),
                "guided_key": plan.get("guided_question_key"),
                "waiting_for_user": response.get("waiting_for_user"),
            }
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
            output.flush()
            preview = record["response"].replace("\n", " ")[:260]
            print(json.dumps({"turn": index, "turn_role": record["turn_role"], "guided_key": record["guided_key"], "preview": preview}, ensure_ascii=False), flush=True)
            if index == 12:
                dataset_path = ROOT / "test_data" / "layered_ai_scaffolding" / "primary_dataset.csv"
                uploaded = upload_primary_csv(base, project_id, token, dataset_path)
                print(json.dumps({"event": "primary_data_uploaded", "document_id": uploaded.get("document_id"), "filename": dataset_path.name}, ensure_ascii=False), flush=True)
    print(json.dumps({"status": "PASS", "project_id": project_id, "turns": len(MESSAGES), "output": str(out_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
