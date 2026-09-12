"""Run the 39-round CGT blind workflow guide and archive every artifact."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys
import urllib.error
import urllib.request
import uuid
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "test_data" / "public_reanalysis" / "cgt_physics_education"
TEXT_DATA = DATA_ROOT / "Textual_descriptions.csv"
BACKGROUND_DATA = DATA_ROOT / "Additional_data.csv"
SOURCE_PAPER = DATA_ROOT / "paper_tschisgale_2023.pdf"
DEFAULT_BASE = "http://127.0.0.1:8001/api/v1"


def call(base: str, method: str, path: str, token: str | None = None,
         body: object | None = None, file: pathlib.Path | None = None) -> dict[str, Any]:
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
            file.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ])
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    request = urllib.request.Request(base + path, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=240) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} -> HTTP {error.code}: {raw}") from error


def register(base: str, prefix: str) -> tuple[str, str, dict[str, Any]]:
    username = f"{prefix}_{uuid.uuid4().hex[:10]}"
    result = call(base, "POST", "/auth/register", body={
        "username": username,
        "email": f"{username}@example.test",
        "password": "research-pass-123",
    })
    return username, str(result["access_token"]), result


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(base: str, project_id: str, token: str) -> dict[str, Any]:
    state = call(base, "GET", f"/projects/{project_id}/control-state", token)
    streams = state.get("workstreams") or []
    active_id = state.get("active_workstream_id")
    stream = next((item for item in streams if item.get("workstream_id") == active_id), streams[0] if streams else {})
    return {
        "lifecycle_status": state.get("lifecycle_status"),
        "route": (state.get("route_decision") or {}).get("primary_route"),
        "phase": stream.get("phase"),
        "step": stream.get("current_step_index"),
        "current_action": stream.get("current_action"),
        "checkpoint": stream.get("conversation_checkpoint"),
        "active_gate_id": state.get("active_gate_id"),
        "completed_steps": stream.get("completed_step_ids", []),
        "skipped_steps": stream.get("skipped_step_ids", []),
        "stream": stream,
    }


MESSAGES: list[tuple[str, str]] = [
    ("01_blurred_idea", "我手上有一批学生描述自己如何解决一道物理题的文字。我感觉这些回答里可能存在几种稳定的思考方式，但我还不知道应该怎样把它变成一个可靠的研究。请你像研究导师一样一步一步引导我，每次只问一个最关键的问题，现在不要检索、不要分析、不要写完整方案。"),
    ("02_research_goal", "我更想知道学生是怎样组织解题思路的，包括他们先做了什么假设、调用了哪些物理概念、怎样进行定量推导，以及最后怎样表达答案。我暂时不关心得分高低。"),
    ("03_population_task_language", "文本来自中学生或高中阶段学生，内容是他们用完整句子描述怎样解决一道竖直圆环运动问题。题目涉及无摩擦运动、能量关系和圆周运动。原始回答主要是德语，学生编号已经匿名化。"),
    ("04_expected_contribution", "我希望先从文本中归纳出几类可解释的问题解决主题，再检查这些主题是否稳定。最终想写成一篇公开二手资料再分析论文，重点说明计算方法和人工解释怎样配合，而不是声称发现了普遍规律。"),
    ("05_data_source_without_upload", "资料来自一个公开研究项目。我目前有一份 CSV，应该包含匿名学生编号和每名学生的一段德语解题描述。可能还有一份背景变量表，但我想先让你告诉我需要哪些文件和字段，再决定什么时候上传。"),
    ("06_analysis_unit", "我认为一名学生的一段回答可能同时包含多个主题。模式发现可以先以句子为单位，但必须保留 Stu_ID，最后再回到学生层面汇总。公式可能被错误切开，所以请把公式保护和分句敏感性检查写进方案。"),
    ("07_method_boundary", "我想采用三阶段的人机协作流程：第一阶段让计算方法探索性发现模式；第二阶段由研究者阅读代表句、边界句和噪声句，修订并合并主题；第三阶段再用监督模型和交叉验证检查最终主题能否覆盖全语料。现在请先判断这个路线是否适合，不要预设主题数量和名称。"),
    ("08_real_constraints", "代码使用 Python，必须保存随机种子、软件版本、输入文件哈希、中间数据和图表。先做小规模试运行，确认环境可用后再跑完整分析。任何正式结果都必须来自实际执行输出，不能从我的描述或已有论文中推断。"),
    ("09_enter_data_audit", "我确认当前研究目标和三阶段方法边界。现在进入数据导入，但只做文件识别和数据审计，不做主题分析。"),
    ("10_audit_primary_text", "请先报告你实际读取到的文件名、行数、字段、字段类型、缺失值、学生编号唯一性、完全重复记录和文本完全重复情况。所有数字必须从本轮上传文件计算，不要引用其他项目历史，也不要开始清洗。"),
    ("11_missing_text_decision", "排除 Text 为空的 78 条记录，但保留原始文件不变，并生成排除清单。内容完全相同的文本先保留，因为它们来自不同 Stu_ID，可能是真实重复作答；请单独加 duplicate_text 标记，不要静默去重。当前得到的 472 条只能叫“具有非空文本的候选样本”。"),
    ("12_request_background_upload", "我还有一份通过 Stu_ID 连接的公开背景变量表。请告诉我上传后你会怎样检查连接关系、分组编码和缺失值，仍然不要开始主题分析。"),
    ("13_audit_background_join", "请审计背景表并与非空文本记录按 Stu_ID 做一对一连接。先报告连接结果、未连接编号和各字段缺失；不要把 Control_group 的 0/1 自动解释成实验处理。"),
    ("14_explain_background_fields", "字段含义如下：Control_group=0 表示物理奥赛参与者，Control_group=1 表示非参与对照组；Gender=0 表示男性，Gender=1 表示女性。Class 是年级，Still_phy 是对照组是否仍在学习物理的相关信息。分组不是随机分配，而且两组的数据收集形式可能不同，所以只能做描述性或关联性比较，不能写因果结论。"),
    ("15_freeze_analysis_data", "我确认主分析样本采用能够同时连接非空文本和背景变量的 417 名学生。请冻结这一版本，生成 SHA-256、纳入排除流程、字段字典和数据边界说明。原始 550 行文件必须保留，任何后续处理都从冻结版本派生。"),
    ("16_code_specification", "现在只生成分析代码规格，不写论文。请把程序拆成可独立审查的模块：数据审计与冻结、德语分句与清洗、句子嵌入、UMAP 与 HDBSCAN 多随机种子探索、聚类审阅包、人工修订标签导入、监督模型确认、组间比较、稳健性分析和结果汇总。每个模块列出输入、输出、随机性、失败条件和测试。"),
    ("17_preprocess_code", "请先生成第一个可运行代码候选，只完成数据审计和预处理：读取冻结 CSV，保留德语原文，按句子分割，保护常见公式和物理符号，保留 Stu_ID 与 Sentence_ID，默认移除少于 20 个字符的片段，同时输出阈值 10、20、30 的敏感性统计。不要生成任何主题标签。"),
    ("18_review_code", "在执行前审查这段代码。重点检查：是否误把 nan 当文本；是否用行号冒充 Stu_ID；是否会把公式拆成无意义碎片；是否修改原始文件；是否固定随机种子；是否把 417 名学生误写成 417 个句子。请先给审查结论和修改 diff，再请求执行批准。"),
    ("19_approve_preprocess", "批准只执行数据审计和预处理。先运行完整 417 人数据，但不要下载大型模型、不要做嵌入和聚类。执行后报告实际句子数、每名学生句子数分布、被短句阈值排除的片段示例和公式切分错误示例。"),
    ("20_confirm_preprocess", "我确认以句子为主要编码单位，20 字符作为基线阈值，但请保留 10 和 30 字符阈值的敏感性结果。任何包含明确物理关系的短公式片段不得仅因字符数不足而自动删除；请将这些片段放入人工复核清单。冻结预处理版本后再生成模式发现代码。"),
    ("21_pattern_code", "请生成模式发现代码。基线采用适合德语句子的预训练嵌入，将每个句子转成向量；再使用 UMAP 降到 5 维，参数 n_neighbors=15、metric=cosine、min_dist=0；随后使用 HDBSCAN，min_cluster_size=15、metric=euclidean、cluster_selection_method=eom。不要预设簇数。先设计 20 个随机种子的烟雾测试，再设计 100 个种子的试运行和 1000 个种子的正式稳定性运行。"),
    ("22_approve_smoke", "先批准 20 个随机种子的烟雾测试。执行后只报告环境、运行时间、内存、各次簇数、噪声比例和是否出现崩溃；不要根据 20 次试运行宣布最终主题。"),
    ("23_approve_stability", "烟雾测试通过后，先运行 100 个种子检查分布；资源允许时再运行 1000 个种子的正式稳定性分析。请报告簇数分布的众数与范围、噪声比例分布、跨随机种子的簇稳定性，并提出若干候选解供人工审阅，不要自行选择最符合预期结论的解。"),
    ("24_review_packet", "请为每个候选簇生成审阅包：簇大小、10 个高区分度词、15 个最接近簇中心的代表句、5 个边界句、与相邻簇的关系、原始德语和忠实中文翻译。噪声簇也必须抽样。此时只能使用“簇 0、簇 1”等中性名称，不要套入预设理论标签。"),
    ("25_provisional_labels", "我先给出暂定解释，不冻结名称：有的簇主要表达无摩擦、质点、圆形轨道等前提；有的簇围绕能量或受力概念；有的簇描述公式、方程和量的计算；有的簇直接猜测或陈述最低高度；还有一些是一般性的步骤描述。请根据这些暂定解释检查每个簇的正例、边界例和反例，并指出哪些簇应保留、拆分或合并。"),
    ("26_counterexamples", "请把合并建议分成两部分：数据相似性证据和物理问题解决理论证据。嵌入图或树状图不能单独决定合并。对每个拟议主题至少列出定义、纳入标准、排除标准、典型正例、边界例、反例和容易混淆的相邻主题。"),
    ("27_freeze_codebook_plan", "请把当前人工修订方案整理成 Codebook 候选和编码计划：每个主题的定义、纳入/排除规则、代表句、反例、编码者培训、第二编码者复核、Cohen's kappa 或 Krippendorff's alpha 的计算计划。先不要把它标成正式结果。"),
    ("28_supervised_code", "请生成监督确认代码。使用冻结的人工标签，分别设计句子级分层十折交叉验证和按 Stu_ID 分组的交叉验证，报告 accuracy、macro/weighted F1、Cohen's kappa、混淆矩阵和各主题召回率；再增加性别和分组子组检查。若 RVM 环境不可用，请把替代模型与原方法复现分开。"),
    ("29_run_supervised", "批准执行模式确认。任何准确率都必须来自冻结人工标签和实际交叉验证输出。请同时报告类别不平衡、置信区间、按学生分组后的性能变化，以及是否存在明显的性别子组性能差异。没有外部未见数据时，不得声称模型已经具有外部泛化能力。"),
    ("30_group_comparison", "请比较奥赛参与者与非参与者的主题构成。为了与传统分析可比，先给出句子计数的列联表和卡方检验；同时考虑同一学生有多个句子，增加学生层面的主题比例、按学生聚类的 bootstrap 或合适的层级/组成数据稳健性分析。还要检查两组文本长度差异。不要做因果解释。"),
    ("31_freeze_result_cards", "请在写作前生成并冻结结果卡。结果卡必须逐项连接到冻结数据、代码版本、执行日志和输出表。把结果分为：数据审计、主题发现、人工复核、模式确认、组间比较、稳健性分析和未解决问题。未经结果卡支持的数字不能进入论文。"),
    ("32_manuscript_outline", "我确认冻结结果卡。现在只生成论文结构和每节必须回答的问题，不写完整正文。论文定位为公开二手资料的计算扎根理论再分析与部分复现，不冒充原始数据采集研究。"),
    ("33_methods", "请先根据冻结审计表、代码参数和执行记录写“数据与方法”。每一个样本数字都要说明来源；完整写出 550、缺失文本、非空文本、成功连接和最终分析样本的流转。明确句子是编码单位、学生是聚合单位。没有执行证据的参数不要补写。"),
    ("34_results", "请只依据冻结结果卡写“结果”。每个主题给出定义、频数、代表性引文和反例；模型性能同时报告总体和分类别结果；组间比较同时报告描述性结果、效应量和学生层面稳健性。不要在结果部分解释原因，也不要引用原论文的数字。"),
    ("35_introduction", "现在写引言和理论背景。请检索并使用可核验文献支持以下论证：物理问题解决的主要阶段、专家与新手差异、语言数据的价值、人工定性分析的规模和复现挑战、计算扎根理论的人机互补逻辑。不要检索或使用本次最终要对比的那篇原论文内容；如果系统发现同一篇论文，只能把它标记为待最终数据来源引用，不能读取其结果来改写本研究发现。"),
    ("36_discussion", "请根据本研究自己的结果写讨论，不要用原论文结论补齐。区分数据支持的解释、与既有理论一致的解释和仍属推测的解释。重点讨论公式分句、语言模型偏差、一个句子可能含多个主题、人工编码主观性、同一学生多句依赖、非随机分组、不同采集方式和没有外部未见语料验证等限制。"),
    ("37_full_candidate", "请把已确认章节合并为完整候选论文。摘要最后写，且只能包含正文已经报告的内容。正文不要出现内部 segment 编号、Gate 名称或系统状态；这些信息放入审计附录。所有数据性主张必须连接结果卡，所有文献性主张必须连接可核验来源。"),
    ("38_independent_review", "请进入独立审稿，不要直接改稿。按严重程度列出：结果与证据不一致、样本边界错误、方法不可复现、把关联写成因果、主题定义重叠、统计单位错误、缺失引用和过度结论。每个问题必须定位到章节和对应结果卡或证据。"),
    ("39_freeze_candidate", "我确认当前修订稿作为盲测候选稿。请导出论文、表格、图、代码版本、环境文件、结果卡和主张-证据表，并记录候选稿哈希和冻结时间。冻结后不得根据原论文修改这一版本。"),
]


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)[:120]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--output", type=pathlib.Path, default=None)
    args = parser.parse_args()
    for path in (TEXT_DATA, BACKGROUND_DATA, SOURCE_PAPER):
        if not path.is_file():
            raise SystemExit(f"missing test asset: {path}")

    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    output = args.output or ROOT / "acceptance_runs" / f"cgt_blind_{run_id}"
    output.mkdir(parents=True, exist_ok=True)
    (output / "artifacts").mkdir(exist_ok=True)
    (output / "documents").mkdir(exist_ok=True)

    researcher, researcher_token, researcher_record = register(args.base, "cgt_researcher")
    reviewer, reviewer_token, reviewer_record = register(args.base, "cgt_reviewer")
    project_id = f"cgt-blind-{uuid.uuid4().hex[:12]}"
    call(args.base, "POST", "/projects", researcher_token, {
        "project_id": project_id,
        "title": "学生物理问题解决文本的计算辅助定性研究",
        "research_direction": "物理教育中的问题解决与文本分析",
    })
    call(args.base, "PUT", f"/projects/{project_id}/members", researcher_token, {
        "username": reviewer,
        "role": "reviewer",
    })

    records: list[dict[str, Any]] = []
    uploads: list[dict[str, Any]] = []
    conversation_id: str | None = None

    def persist_partial() -> None:
        """Keep a usable transcript even when a later round fails."""

        (output / "dialogue.partial.json").write_text(
            json.dumps({"project_id": project_id, "records": records, "uploads": uploads}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def exchange(
        index: int,
        label: str,
        message: str,
        mode: str = "auto",
        actor_token: str | None = None,
    ) -> dict[str, Any]:
        nonlocal conversation_id
        # The final Gate is deliberately reviewer-only. All research design,
        # data, and writing turns use the researcher account; the last turn
        # must exercise the assigned independent reviewer's permission path.
        token = actor_token or researcher_token
        before = snapshot(args.base, project_id, researcher_token)
        response = call(args.base, "POST", f"/projects/{project_id}/conversation/command", token, {
            "project_id": project_id,
            "message": message,
            "interaction_mode": mode,
            "conversation_id": conversation_id,
            "client_turn_id": f"{run_id}-{index}",
        })
        answer = response.get("answer") or {}
        if isinstance(answer, dict) and answer.get("conversation_id"):
            conversation_id = str(answer["conversation_id"])
        after = snapshot(args.base, project_id, researcher_token)
        gate = response.get("gate") or {}
        record = {
            "index": index,
            "label": label,
            "user_message": message,
            "assistant_kind": response.get("kind"),
            "assistant_message": response.get("message"),
            "assistant_answer": answer.get("answer") if isinstance(answer, dict) else None,
            "checkpoint": response.get("checkpoint"),
            "gate_type": gate.get("gate_type"),
            "gate_id": gate.get("gate_id"),
            "waiting_for_user": response.get("waiting_for_user"),
            "before": before,
            "after": after,
            "response": response,
        }
        records.append(record)
        persist_partial()
        # JSON escaping keeps this progress stream safe on Windows consoles
        # whose active code page may not represent Chinese output.
        print(json.dumps({k: record[k] for k in ("index", "label", "assistant_kind", "assistant_message", "checkpoint", "gate_type", "after")}, ensure_ascii=True))
        return response

    for index, (label, message) in enumerate(MESSAGES, start=1):
        mode = "discussion" if index <= 8 else "auto"
        exchange(
            index,
            label,
            message,
            mode,
            actor_token=reviewer_token if index == 39 else researcher_token,
        )
        if index == 9:
            uploaded = call(args.base, "POST", f"/projects/{project_id}/primary-data/upload", researcher_token, file=TEXT_DATA)
            uploads.append({"round": index, "role": "primary_text", "file": TEXT_DATA.name, "sha256": sha256_file(TEXT_DATA), "response": uploaded})
            persist_partial()
        elif index == 12:
            # The current API has one private primary-data slot.  Keep the
            # background table as a project reference so the blind run can
            # expose whether the join is actually implemented rather than
            # silently replacing the main text dataset.
            uploaded = call(args.base, "POST", f"/projects/{project_id}/documents/upload", researcher_token, file=BACKGROUND_DATA)
            uploads.append({"round": index, "role": "background_reference", "file": BACKGROUND_DATA.name, "sha256": sha256_file(BACKGROUND_DATA), "response": uploaded})
            persist_partial()

    final_state = snapshot(args.base, project_id, researcher_token)
    contents = call(args.base, "GET", f"/workflow/projects/{project_id}/artifact-contents", researcher_token)
    claims = call(args.base, "GET", f"/projects/{project_id}/claims", researcher_token)
    events = call(args.base, "GET", f"/projects/{project_id}/orchestration/events", researcher_token)
    documents = call(args.base, "GET", f"/projects/{project_id}/documents", researcher_token)
    for item in contents if isinstance(contents, list) else []:
        artifact_type = safe_name(str(item.get("artifact_type", "artifact")))
        artifact_id = safe_name(str(item.get("artifact_id", uuid.uuid4().hex)))
        (output / "artifacts" / f"{artifact_type}--{artifact_id}.json").write_text(
            json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    for item in documents if isinstance(documents, list) else []:
        document_id = str(item.get("document_id", "document"))
        detail = call(args.base, "GET", f"/projects/{project_id}/documents/{document_id}", researcher_token)
        (output / "documents" / f"{safe_name(document_id)}.json").write_text(
            json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    summary = {
        "run_id": run_id,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "project_id": project_id,
        "researcher": researcher_record.get("user", {}),
        "reviewer": reviewer_record.get("user", {}),
        "text_data": {"file": TEXT_DATA.name, "sha256": sha256_file(TEXT_DATA), "bytes": TEXT_DATA.stat().st_size},
        "background_data": {"file": BACKGROUND_DATA.name, "sha256": sha256_file(BACKGROUND_DATA), "bytes": BACKGROUND_DATA.stat().st_size},
        "source_paper_reserved_for_external_comparison": {"file": SOURCE_PAPER.name, "sha256": sha256_file(SOURCE_PAPER), "uploaded_to_project": False},
        "uploads": uploads,
        "turn_count": len(records),
        "turns": records,
        "final_state": final_state,
        "artifact_count": len(contents) if isinstance(contents, list) else None,
        "claim_count": len(claims) if isinstance(claims, list) else None,
        "document_count": len(documents) if isinstance(documents, list) else None,
        "artifacts": contents,
        "claims": claims,
        "events": events,
        "documents": documents,
        "quality_assertions": {
            "all_39_rounds_recorded": len(records) == 39,
            "source_paper_not_uploaded": True,
            "reviewer_assigned": True,
            "completed": final_state.get("lifecycle_status") == "COMPLETED",
            "claims_present": bool(claims),
            "candidate_manuscript_present": any(item.get("artifact_type") == "ManuscriptDraftZh" for item in contents) if isinstance(contents, list) else False,
        },
    }
    (output / "run.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    md: list[str] = [
        "# CGT 盲测全流程验收记录",
        f"- 项目 ID：`{project_id}`",
        f"- 运行 ID：`{run_id}`",
        f"- 最终状态：`{final_state.get('lifecycle_status')}`",
        f"- 最终路线：`{final_state.get('route')}`",
        f"- 原论文是否上传项目：`否`",
        "",
        "## 逐轮记录",
    ]
    for record in records:
        md.extend([
            f"### {record['index']}. {record['label']}",
            f"**用户：** {record['user_message']}",
            f"**系统：** {record.get('assistant_message') or record.get('assistant_answer') or '(无文本回答)'}",
            f"**边界：** checkpoint=`{record.get('checkpoint')}`，Gate=`{record.get('gate_type')}`，阶段=`{record['after'].get('phase')}`，步骤=`{record['after'].get('step')}`",
            "",
        ])
    md.extend([
        "## 上传记录",
        *[f"- 第 {item['round']} 轮：{item['role']} / `{item['file']}` / SHA-256 `{item['sha256']}`" for item in uploads],
        "",
        "## 质量断言",
        *[f"- `{key}`: `{value}`" for key, value in summary["quality_assertions"].items()],
    ])
    (output / "dialogue.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "project_id": project_id, "final_state": final_state, "quality_assertions": summary["quality_assertions"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
