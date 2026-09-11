"""Claude Code Runner — 深度集成 Claude Code CLI 作为执行引擎

架构:
  平台 (Python) → subprocess.Popen("claude ...")
    → Claude Code CLI 读取 CLAUDE.md 理解任务
    → Claude Code 通过 MCP 协议连接我们的 MCP Server
    → Claude Code 调用 14 个科研工具
    → 结果通过 stdout / 文件回传

两种运行模式:
  1. One-shot:  claude -p "任务"        — 执行一次，返回结果
  2. Daemon:    claude --mcp-config ...  — 长期运行，持续交互

参考: DeepScientist 的 runners/claude.py
"""

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.core.config import get_config


# ── Tasks config for CLAUDE.md ────────────────────────────

def build_claude_md(
    task_description: str,
    project_path: str = "",
    tool_hints: str = "",
) -> str:
    """生成 CLAUDE.md 任务文件"""
    return f"""# Research-Copilot-OS Task

## Current Task

{task_description}

## Project Context

Working directory: {project_path or 'N/A'}

## Available MCP Tools

You have access to the following research tools via MCP (server: research-copilot):
- **analyze_paper**: Deep analysis of a single paper PDF
- **review_papers**: Multi-paper review, classification, comparison
- **chunk_code**: AST-based PyTorch code chunking
- **recommend_modules**: Recommend transferable innovative modules
- **migrate_module**: Migrate a module from source to target project
- **inspect_dataset**: Auto-detect dataset format and statistics
- **generate_dataloader**: Generate PyTorch DataLoader code
- **generate_augmentation**: Generate data augmentation/attack code (20 ops)
- **generate_visualization**: Generate full visualization suite (Morandi palette)
- **plan_ablation**: Plan ablation experiments
- **identify_hyperparams**: Identify tunable hyperparameters in code
- **generate_scheduler**: Generate hyperparameter scheduler code
- **list_experiments**: List historical experiment records

{tool_hints}

## Execution Rules

1. Use the MCP tools whenever they can help with the task
2. Read code files with bash_exec or direct file reads before modifying
3. Keep changes minimal and auditable
4. Report results in Chinese if the task is in Chinese
5. Record key findings in a SUMMARY.md file

## Important

- Do NOT fabricate metrics, citations, or results
- Verify tool outputs before presenting conclusions
- If a tool fails, explain why and suggest alternatives
"""


def build_mcp_config(mcp_server_command: str) -> dict:
    """生成 MCP 配置文件内容"""
    return {
        "mcpServers": {
            "research-copilot": {
                "command": mcp_server_command.split()[0] if " " in mcp_server_command else mcp_server_command,
                "args": mcp_server_command.split()[1:] if " " in mcp_server_command else [],
            }
        }
    }


# ── Data Models ───────────────────────────────────────────

@dataclass
class RunnerTask:
    task_id: str
    description: str
    project_path: str = ""
    status: str = "pending"  # pending, running, completed, failed
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    output: str = ""
    error: str = ""
    workspace_path: str = ""


@dataclass
class RunnerSession:
    session_id: str
    tasks: list[RunnerTask] = field(default_factory=list)
    process: Optional[subprocess.Popen] = None
    mcp_config_path: str = ""


# ── ClaudeCodeRunner ──────────────────────────────────────

class ClaudeCodeRunner:
    """Claude Code CLI 包装器

    管理 Claude Code 进程的生命周期，包括:
    - 工作空间准备 (CLAUDE.md + MCP config)
    - 进程启动/监控/终止
    - 输出捕获和解析
    """

    def __init__(self):
        self.cfg = get_config()
        self.sessions: dict[str, RunnerSession] = {}
        self._find_claude_binary()

    def _find_claude_binary(self):
        """查找 claude CLI 可执行文件"""
        self.claude_bin = shutil.which("claude") or shutil.which("claude.exe")
        if not self.claude_bin:
            # 尝试常见路径
            candidates = [
                os.path.expanduser("~/.npm-global/bin/claude"),
                "/usr/local/bin/claude",
                "C:/Users/*/AppData/Roaming/npm/claude.cmd",
            ]
            for c in candidates:
                if os.path.exists(c):
                    self.claude_bin = c
                    break

    @property
    def available(self) -> bool:
        return self.claude_bin is not None

    def create_session(self, session_id: str = None) -> RunnerSession:
        sid = session_id or f"runner_{int(time.time())}"
        session = RunnerSession(session_id=sid)
        self.sessions[sid] = session
        return session

    # ── One-shot 模式 ─────────────────────────────────

    def run_one_shot(
        self,
        task_description: str,
        project_path: str = "",
        timeout: int = 600,
    ) -> dict:
        """一次性执行: claude -p "任务描述"

        适用于独立任务: 分析代码、解读论文等。
        Claude Code 执行完就退出，返回结果。
        """
        if not self.available:
            return {
                "success": False,
                "error": "Claude Code CLI not found. Install with: npm install -g @anthropic-ai/claude-code",
                "install_guide": "https://docs.anthropic.com/en/docs/claude-code",
            }

        # 准备工作空间
        workspace = tempfile.mkdtemp(prefix="rco_claude_")
        task_id = f"task_{int(time.time())}"

        # 写入 CLAUDE.md
        claude_md_path = os.path.join(workspace, "CLAUDE.md")
        claude_md = build_claude_md(task_description, project_path)
        with open(claude_md_path, "w", encoding="utf-8") as f:
            f.write(claude_md)

        # 写入 MCP 配置
        python_exe = sys.executable if hasattr(sys, 'executable') else "python"
        mcp_server_module = "backend.mcp.server"
        mcp_config = build_mcp_config(f"{python_exe} -m {mcp_server_module}")
        mcp_dir = os.path.join(workspace, ".claude")
        os.makedirs(mcp_dir, exist_ok=True)
        mcp_config_path = os.path.join(mcp_dir, "mcp.json")
        with open(mcp_config_path, "w", encoding="utf-8") as f:
            json.dump(mcp_config, f, indent=2)

        # 如果指定了项目路径，复制或使用该路径
        work_dir = project_path if project_path and os.path.isdir(project_path) else workspace

        # 构建命令
        cmd = [
            self.claude_bin,
            "-p", task_description,
            "--mcp-config", mcp_config_path,
            "--output-format", "text",
            "--max-turns", "20",
            "--allowedTools", "mcp__research-copilot__*",
        ]

        task = RunnerTask(
            task_id=task_id,
            description=task_description,
            project_path=project_path,
            status="running",
            workspace_path=workspace,
        )

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=work_dir,
                env={**os.environ, "PYTHONPATH": os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))},
            )

            task.status = "completed" if result.returncode == 0 else "failed"
            task.output = result.stdout[-10000:] if result.stdout else ""
            task.error = result.stderr[-3000:] if result.stderr else ""

            return {
                "success": result.returncode == 0,
                "task_id": task_id,
                "output": task.output,
                "error": task.error,
                "returncode": result.returncode,
                "workspace": workspace,
            }

        except subprocess.TimeoutExpired:
            task.status = "failed"
            task.error = f"Task timed out after {timeout}s"
            return {
                "success": False,
                "task_id": task_id,
                "error": task.error,
                "workspace": workspace,
            }
        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            return {
                "success": False,
                "task_id": task_id,
                "error": str(e),
                "workspace": workspace,
            }
        finally:
            # 清理（可选：保留工作空间用于调试）
            # shutil.rmtree(workspace, ignore_errors=True)
            pass

    # ── Daemon 模式 ──────────────────────────────────

    def start_daemon(
        self,
        session_id: str,
        task_description: str,
        project_path: str = "",
    ) -> dict:
        """启动长期运行的 Claude Code 守护进程

        Claude Code 持续运行，通过 MCP 连接工具，等待后续指令。
        """
        if not self.available:
            return {"success": False, "error": "Claude Code CLI not found"}

        session = self.create_session(session_id)

        workspace = tempfile.mkdtemp(prefix=f"rco_daemon_{session_id}_")
        session.mcp_config_path = os.path.join(workspace, ".claude", "mcp.json")

        # 准备工作空间
        os.makedirs(os.path.dirname(session.mcp_config_path), exist_ok=True)

        claude_md = build_claude_md(task_description, project_path)
        with open(os.path.join(workspace, "CLAUDE.md"), "w", encoding="utf-8") as f:
            f.write(claude_md)

        python_exe = sys.executable if hasattr(sys, 'executable') else "python"
        mcp_config = build_mcp_config(f"{python_exe} -m backend.mcp.server")
        with open(session.mcp_config_path, "w", encoding="utf-8") as f:
            json.dump(mcp_config, f, indent=2)

        work_dir = project_path if project_path and os.path.isdir(project_path) else workspace

        # 启动 Claude Code 进程
        cmd = [
            self.claude_bin,
            "--mcp-config", session.mcp_config_path,
            "--output-format", "text",
        ]

        try:
            session.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=work_dir,
                env={**os.environ, "PYTHONPATH": os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))},
            )

            # 启动输出监控线程
            threading.Thread(
                target=self._monitor_output,
                args=(session,),
                daemon=True,
            ).start()

            return {
                "success": True,
                "session_id": session_id,
                "workspace": workspace,
                "pid": session.process.pid,
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _monitor_output(self, session: RunnerSession):
        """监控 daemon 进程的输出"""
        if not session.process:
            return

        output_file = os.path.join(
            os.path.dirname(session.mcp_config_path), "..", "daemon_output.log"
        )
        with open(output_file, "w", encoding="utf-8") as f:
            for line in session.process.stdout:
                f.write(line)
                f.flush()

    def send_to_daemon(self, session_id: str, message: str) -> dict:
        """向运行中的 daemon 发送消息"""
        session = self.sessions.get(session_id)
        if not session or not session.process:
            return {"success": False, "error": "Session not found or process dead"}

        try:
            session.process.stdin.write(message + "\n")
            session.process.stdin.flush()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def stop_daemon(self, session_id: str) -> dict:
        """停止 daemon 进程"""
        session = self.sessions.get(session_id)
        if not session:
            return {"success": False, "error": "Session not found"}

        if session.process:
            try:
                session.process.stdin.write("/exit\n")
                session.process.stdin.flush()
                session.process.wait(timeout=10)
            except Exception:
                session.process.kill()

        del self.sessions[session_id]
        return {"success": True, "message": "Daemon stopped"}

    def get_status(self) -> dict:
        """获取 Runner 状态"""
        return {
            "available": self.available,
            "claude_binary": self.claude_bin,
            "active_sessions": len(self.sessions),
            "sessions": [
                {
                    "session_id": s.session_id,
                    "tasks_count": len(s.tasks),
                    "running": s.process is not None and s.process.poll() is None,
                }
                for s in self.sessions.values()
            ],
        }


# ── Singleton ─────────────────────────────────────────────

import sys

_runner: Optional[ClaudeCodeRunner] = None


def get_runner() -> ClaudeCodeRunner:
    global _runner
    if _runner is None:
        _runner = ClaudeCodeRunner()
    return _runner
