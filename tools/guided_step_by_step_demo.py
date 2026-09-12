"""Interactive, one-question-at-a-time demonstration of the research workflow.

This is a human-facing driver, not an automated acceptance test.  It creates a
fresh project, uploads the real paper fixture, and then waits after every
assistant turn.  The researcher answers only the question currently shown by
the system; the script never sends a pre-written sequence of intake answers.

Run from the repository root while the API is available, for example:

    python tools/guided_step_by_step_demo.py

The default fixtures are the real STEM paper and the public SPHERE-derived CSV
under ``test_data/``.  The CSV is uploaded only when the workflow reaches the
raw-data gate.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request
import uuid
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_BASE = os.environ.get("STEM_SCI_ACCEPTANCE_BASE", "http://127.0.0.1:8001/api/v1")
DEFAULT_PAPER = ROOT / "test_data" / "stem_ways_thinking_2025.pdf"
DEFAULT_DATA = ROOT / "test_data" / "sphere_fci_quantitative.csv"
DEFAULT_TOPIC = (
    "我想研究本科物理课程中计算建模对学生学习效果的影响，"
    "但还没决定最终要回答相关关系还是因果效果，请先帮我界定这一点。"
)


class ApiError(RuntimeError):
    """Readable API failure for an interactive session."""


class Client:
    def __init__(self, base: str, token: str | None = None) -> None:
        self.base = base.rstrip("/")
        self.token = token

    def request(
        self,
        method: str,
        path: str,
        *,
        body: object | None = None,
        file: pathlib.Path | None = None,
        timeout: int = 180,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        payload: bytes | None = None
        if file is not None:
            boundary = f"----stem-sci-{uuid.uuid4().hex}"
            payload = b"".join(
                [
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="file"; filename="{file.name}"\r\n'.encode(),
                    b"Content-Type: application/octet-stream\r\n\r\n",
                    file.read_bytes(),
                    b"\r\n",
                    f"--{boundary}--\r\n".encode(),
                ]
            )
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        elif body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base + path, data=payload, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                result = json.loads(raw) if raw else {}
                return result if isinstance(result, dict) else {"value": result}
        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(raw)
            except json.JSONDecodeError:
                detail = raw
            raise ApiError(f"{method} {path} -> HTTP {error.code}: {detail}") from error
        except urllib.error.URLError as error:
            raise ApiError(f"无法连接 {self.base}: {error.reason}") from error

    def command(self, project_id: str, message: str, conversation_id: str | None) -> dict[str, Any]:
        return self.request(
            "POST",
            f"/projects/{project_id}/conversation/command",
            body={
                "project_id": project_id,
                "message": message,
                "interaction_mode": "auto",
                "evidence_mode": "discovery",
                "conversation_id": conversation_id,
                "execution_mode": "sync",
                "client_turn_id": str(uuid.uuid4()),
            },
        )


def register(client: Client) -> tuple[str, str]:
    username = f"guided_{uuid.uuid4().hex[:10]}"
    result = client.request(
        "POST",
        "/auth/register",
        body={
            "username": username,
            "email": f"{username}@example.test",
            "password": "research-pass-123",
        },
    )
    token = result.get("access_token")
    if not isinstance(token, str) or not token:
        raise ApiError(f"注册成功但没有收到 access_token: {result}")
    return username, token


def text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def print_turn(body: dict[str, Any], index: int) -> None:
    dialogue = body.get("dialogue") or {}
    print("\n" + "=" * 72)
    print(f"第 {index} 轮 · 系统当前状态")
    print("-" * 72)
    response_message = text(body.get("message"))
    dialogue_summary = text(dialogue.get("summary"))
    if response_message:
        print(f"系统回复：{response_message}")
    if dialogue_summary and dialogue_summary != response_message:
        print(f"协作状态：{dialogue_summary}")

    # Discussion answers are returned in answer.answer while the envelope's
    # dialogue may be only a generic follow-up shell. Do not hide the actual
    # explanation from the researcher.
    answer = body.get("answer") or {}
    answer_text = text(answer.get("answer")) if isinstance(answer, dict) else ""
    if answer_text and answer_text != response_message:
        print(f"\n本轮详细回答：\n{answer_text}")

    gate = body.get("gate") or {}
    checkpoint = text(body.get("checkpoint"))
    if gate.get("gate_type"):
        print(f"当前边界：{gate['gate_type']}")
    elif checkpoint:
        print(f"当前评审点：{checkpoint}")

    control_state = body.get("control_state") or {}
    streams = control_state.get("workstreams") if isinstance(control_state, dict) else []
    current_action = ""
    if isinstance(streams, list):
        for stream in streams:
            if isinstance(stream, dict) and stream.get("workstream_id") == control_state.get("active_workstream_id"):
                current_action = text(stream.get("current_action"))
                break
    if current_action == "reviewer_final_confirmation":
        print("\n当前需要独立 reviewer 账号确认；研究者账号不能替代最终审稿。")

    evidence = dialogue.get("evidence") or []
    if evidence:
        print("\n本轮依据：")
        for item in evidence[:3]:
            print(f"  · {text(item.get('title'))}: {text(item.get('excerpt'))[:260]}")

    tradeoffs = dialogue.get("tradeoffs") or []
    if tradeoffs:
        print("\n需要注意：")
        for item in tradeoffs[:4]:
            print(f"  · {text(item)}")

    question = text(dialogue.get("question"))
    if question:
        print(f"\n现在只需要回答这一问：\n  {question}")
    else:
        print("\n现在请告诉我你希望如何处理当前材料（可直接用自然语言回答）。")

    suggestions = dialogue.get("suggestions") or []
    branches = dialogue.get("branches") or []
    choices: list[tuple[str, str]] = []
    if suggestions:
        print("\n可选回答：")
        for item in suggestions:
            label = text(item.get("label"))
            message = text(item.get("message"))
            choices.append((label, message))
            print(f"  {len(choices)}. {label}")
    if branches:
        print("\n研究路径（选择后仍可修改）：")
        for item in branches:
            title = text(item.get("title"))
            description = text(item.get("description"))
            choices.append((title, text(item.get("message"))))
            print(f"  {len(choices)}. {title}：{description}")

    next_action = text(dialogue.get("next_action"))
    if next_action:
        print(f"\n下一步：{next_action}")
    if choices:
        print("输入编号选择系统建议；也可以直接输入你对当前问题的回答。")
    else:
        print("直接输入你对当前问题的回答即可。")


def save_transcript(path: pathlib.Path, metadata: dict[str, Any], turns: list[dict[str, Any]]) -> None:
    path.write_text(
        json.dumps({"metadata": metadata, "turns": turns}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="逐轮研究协作交互演示")
    parser.add_argument("--base", default=DEFAULT_BASE, help="后端 API 根地址")
    parser.add_argument("--paper", type=pathlib.Path, default=DEFAULT_PAPER, help="真实论文 PDF")
    parser.add_argument("--data", type=pathlib.Path, default=DEFAULT_DATA, help="公开派生 CSV")
    parser.add_argument("--topic", default=None, help="首轮研究主题；不传则启动时询问")
    parser.add_argument("--transcript", type=pathlib.Path, default=None, help="对话 JSON 输出路径")
    return parser.parse_args()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    if not args.paper.is_file():
        raise SystemExit(f"找不到论文文件：{args.paper}")
    if not args.data.is_file():
        raise SystemExit(f"找不到数据文件：{args.data}")

    topic = args.topic or input(f"只输入第一句话（研究主题，回车使用示例）：\n> ").strip() or DEFAULT_TOPIC
    client = Client(args.base)
    print("正在创建一个全新的演示项目……")
    username, token = register(client)
    client.token = token
    project_id = f"guided-demo-{uuid.uuid4().hex[:10]}"
    client.request(
        "POST",
        "/projects",
        body={"project_id": project_id, "title": "逐步引导演示", "research_direction": topic},
    )
    client.request("POST", f"/projects/{project_id}/documents/upload", file=args.paper)
    print(f"项目已创建：{project_id}")
    print(f"论文已上传：{args.paper.name}")
    print("CSV 不会提前导入；只有系统明确要求原始数据时才上传。")

    conversation_id: str | None = None
    turns: list[dict[str, Any]] = []
    transcript = args.transcript or ROOT / f"guided-conversation-{project_id}.json"
    body = client.command(project_id, topic, conversation_id)
    first_answer = body.get("answer") or {}
    if isinstance(first_answer, dict) and first_answer.get("conversation_id"):
        conversation_id = text(first_answer["conversation_id"])
    turns.append({"role": "user", "message": topic, "response": body})
    save_transcript(
        transcript,
        {"project_id": project_id, "username": username, "paper": str(args.paper), "data": str(args.data)},
        turns,
    )
    print_turn(body, 1)
    turn_index = 1

    while True:
        try:
            answer = input("\n你的回答（/help 查看命令，/quit 结束）：\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已结束本次演示。")
            break
        if not answer:
            continue
        if answer == "/help":
            print("/help 查看命令；/upload 在原始数据 Gate 上传 CSV；/state 查看状态；/quit 结束。")
            continue
        if answer == "/quit":
            break

        if answer == "/state":
            state = client.request("GET", f"/projects/{project_id}/control-state")
            print(json.dumps(state, ensure_ascii=False, indent=2))
            continue

        dialogue = body.get("dialogue") or {}
        suggestions = dialogue.get("suggestions") or []
        branches = dialogue.get("branches") or []
        choices = [*suggestions, *branches]
        message = answer
        selected_upload = False
        selected_id = ""
        if answer.isdigit() and 1 <= int(answer) <= len(choices):
            choice = choices[int(answer) - 1]
            message = text(choice.get("message"))
            selected_id = text(choice.get("id"))
            print(f"已选择：{text(choice.get('label') or choice.get('title'))}")
            selected_upload = (
                selected_id == "upload"
                or "上传" in text(choice.get("label") or choice.get("title"))
            )

            # A suggestion ending in a colon is an interaction affordance,
            # not a complete answer.  Keep the turn paused until the
            # researcher supplies the missing, single decision.
            if selected_id == "answer" or message.endswith(("：", ":")):
                follow_up = input("请只回答当前问题：\n> ").strip()
                if not follow_up:
                    print("没有发送空回答，本轮仍停留在当前问题。")
                    continue
                message = follow_up

        gate_type = text((body.get("gate") or {}).get("gate_type"))
        if answer == "/upload" or selected_upload or (gate_type == "raw_data_import_approval" and answer.lower() in {"上传", "上传数据", "upload"}):
            print(f"正在上传：{args.data.name}")
            client.request("POST", f"/projects/{project_id}/primary-data/upload", file=args.data)
            message = "我已上传数据，请审计这份数据，并告诉我下一处需要决定的边界。"

        turn_index += 1
        body = client.command(project_id, message, conversation_id)
        answer_payload = body.get("answer") or {}
        if isinstance(answer_payload, dict) and answer_payload.get("conversation_id"):
            conversation_id = text(answer_payload["conversation_id"])
        turns.append({"role": "user", "message": message, "response": body})
        save_transcript(
            transcript,
            {"project_id": project_id, "username": username, "paper": str(args.paper), "data": str(args.data)},
            turns,
        )
        print_turn(body, turn_index)

    save_transcript(
        transcript,
        {"project_id": project_id, "username": username, "paper": str(args.paper), "data": str(args.data)},
        turns,
    )
    print(f"\n对话记录已保存：{transcript}")
    print(f"项目 ID：{project_id}")


if __name__ == "__main__":
    main()
