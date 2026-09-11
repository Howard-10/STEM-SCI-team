"""Claude 式系统工具 — 文件操作 + Bash 执行 + 权限控制

为 DeepSeek Agent 提供 Claude Code 级别的系统交互能力.
工具命名与 Claude Code 保持一致，便于理解和迁移。
"""

import fnmatch
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable

from backend.agent.tools import Tool, ToolParameter


# ═══════════════════════════════════════════════════════════
#  权限控制系统
# ═══════════════════════════════════════════════════════════

class PermissionLevel:
    READ_ONLY = "read_only"       # 自动允许
    WRITE_SAFE = "write_safe"     # 自动允许（仅限项目目录内）
    WRITE_CONFIRM = "write_confirm"  # 需用户确认
    DANGEROUS = "dangerous"       # 需用户确认 + 警告


@dataclass
class PermissionRule:
    tool_name: str
    level: str
    description: str


class PermissionController:
    """权限控制器

    - read_only: 读文件、搜索 → 自动允许
    - write_safe: 项目内写入 → 自动允许
    - write_confirm: 写文件、shell → 需确认
    - dangerous: rm -rf, sudo 等 → 拦截警告
    """

    DANGEROUS_PATTERNS = [
        r"rm\s+-rf", r"sudo\s+", r"chmod\s+777",
        r">\s*/dev/sda", r"mkfs\.", r"dd\s+if=",
        r":(){ :|:& };:", r"curl.*\|.*sh", r"wget.*\|.*sh",
        r"git\s+push\s+--force", r"git\s+reset\s+--hard",
    ]

    def __init__(self, project_root: str = ""):
        self.project_root = os.path.abspath(project_root) if project_root else ""
        self.pending_confirmations: dict[str, dict] = {}
        self.auto_allow: set[str] = set()

    def check(self, tool_name: str, params: dict) -> dict:
        """检查工具调用是否需要确认

        返回: {"allowed": True/False, "require_confirm": True/False, "reason": "..."}
        """
        # 文件系统工具权限
        file_tools = {
            "read_file": PermissionLevel.READ_ONLY,
            "glob_files": PermissionLevel.READ_ONLY,
            "grep_files": PermissionLevel.READ_ONLY,
            "write_file": PermissionLevel.WRITE_CONFIRM,
            "edit_file": PermissionLevel.WRITE_CONFIRM,
        }

        if tool_name in file_tools:
            level = file_tools[tool_name]
            if level == PermissionLevel.READ_ONLY:
                return {"allowed": True, "require_confirm": False, "reason": "只读操作，自动允许"}

            # 检查是否在项目目录内
            file_path = params.get("file_path", "")
            if self.project_root and os.path.abspath(file_path).startswith(self.project_root):
                return {"allowed": True, "require_confirm": False, "reason": "项目目录内操作，自动允许"}
            return {"allowed": True, "require_confirm": True, "reason": "项目目录外写入操作，需要确认"}

        # Bash 执行权限
        if tool_name == "bash_exec":
            command = params.get("command", "")

            for pattern in self.DANGEROUS_PATTERNS:
                if re.search(pattern, command):
                    return {"allowed": False, "require_confirm": False,
                            "reason": f"危险命令被拦截: 匹配模式 '{pattern}'"}

            # 检查是否在项目目录内执行
            cwd = params.get("workdir", "")
            if cwd and self.project_root and os.path.abspath(cwd).startswith(self.project_root):
                return {"allowed": True, "require_confirm": False, "reason": "项目目录内执行，自动允许"}

            return {"allowed": True, "require_confirm": True,
                    "reason": "Shell 执行需要确认。命令: " + command[:80]}

        # 科研引擎工具 — 全部自动允许
        return {"allowed": True, "require_confirm": False, "reason": "科研工具，自动允许"}

    def add_auto_allow(self, tool_name: str):
        """将工具添加到永久自动允许列表"""
        self.auto_allow.add(tool_name)


# ═══════════════════════════════════════════════════════════
#  文件系统工具实现
# ═══════════════════════════════════════════════════════════

def _read_file_tool(file_path: str, offset: int = 0, limit: int = 200) -> dict:
    """读取文件内容"""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        total_lines = len(lines)
        selected = lines[offset:offset + limit]
        content = "".join(selected)

        return {
            "file_path": file_path,
            "total_lines": total_lines,
            "offset": offset,
            "limit": limit,
            "content": content,
            "truncated": (offset + limit) < total_lines,
        }
    except FileNotFoundError:
        return {"error": f"文件不存在: {file_path}"}
    except PermissionError:
        return {"error": f"无权限读取: {file_path}"}
    except Exception as e:
        return {"error": str(e)}


def _write_file_tool(file_path: str, content: str) -> dict:
    """写入文件（创建或覆盖）"""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        size = os.path.getsize(file_path)
        return {"file_path": file_path, "bytes_written": size, "success": True}
    except Exception as e:
        return {"error": str(e), "success": False}


def _edit_file_tool(file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> dict:
    """精确字符串替换编辑（与 Claude Code Edit 工具语义一致）"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        count = content.count(old_string)
        if count == 0:
            return {"error": f"未找到匹配文本: {old_string[:80]}...", "success": False}
        if count > 1 and not replace_all:
            return {
                "error": f"找到 {count} 处匹配，但 replace_all=False。请提供更精确的上下文或设置 replace_all=True。",
                "match_count": count,
                "success": False,
            }

        new_content = content.replace(old_string, new_string) if replace_all else content.replace(old_string, new_string, 1)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        return {
            "file_path": file_path,
            "matches_replaced": count if replace_all else 1,
            "success": True,
        }
    except FileNotFoundError:
        return {"error": f"文件不存在: {file_path}", "success": False}
    except Exception as e:
        return {"error": str(e), "success": False}


def _glob_files_tool(pattern: str, path: str = ".") -> dict:
    """按模式查找文件"""
    try:
        matches = []
        base = Path(path)
        for p in base.rglob(pattern):
            if p.is_file() and not any(part.startswith(".") for part in p.parts if part != "."):
                matches.append(str(p))

        matches.sort()
        return {
            "pattern": pattern,
            "base_path": str(base.absolute()),
            "matches": matches[:100],
            "total_count": len(matches),
            "truncated": len(matches) > 100,
        }
    except Exception as e:
        return {"error": str(e)}


def _grep_files_tool(pattern: str, path: str = ".", glob: str = "*", head_limit: int = 50) -> dict:
    """搜索文件内容（ripgrep 风格）"""
    try:
        import re as re_mod
        results = []
        base = Path(path)

        for file_path in base.rglob(glob):
            if not file_path.is_file():
                continue
            if any(part.startswith(".") for part in file_path.parts):
                continue
            if file_path.suffix not in (".py", ".md", ".txt", ".json", ".yaml", ".yml",
                                         ".toml", ".cfg", ".js", ".ts", ".tsx", ".jsx",
                                         ".html", ".css", ".sh", ".bat", ".c", ".h",
                                         ".cpp", ".hpp", ".java", ".go", ".rs"):
                continue

            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if re_mod.search(pattern, line):
                            results.append({
                                "file": str(file_path.relative_to(base)),
                                "line": i,
                                "content": line.strip()[:200],
                            })
                            if len(results) >= head_limit:
                                break
            except Exception:
                continue

            if len(results) >= head_limit:
                break

        return {
            "pattern": pattern,
            "glob": glob,
            "matches": results,
            "total_shown": min(len(results), head_limit),
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════
#  Bash 执行工具
# ═══════════════════════════════════════════════════════════

def _bash_exec_tool(
    command: str,
    workdir: str = "",
    timeout: int = 120,
    description: str = "",
) -> dict:
    """执行 shell 命令"""
    try:
        cwd = workdir if workdir else os.getcwd()
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )

        stdout = result.stdout[-8000:] if result.stdout else ""
        stderr = result.stderr[-2000:] if result.stderr else ""

        return {
            "command": command,
            "workdir": cwd,
            "exit_code": result.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "truncated_stdout": len(result.stdout) > 8000 if result.stdout else False,
            "success": result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {"error": f"命令超时 ({timeout}s): {command[:100]}", "success": False}
    except Exception as e:
        return {"error": str(e), "success": False}


# ═══════════════════════════════════════════════════════════
#  系统工具注册
# ═══════════════════════════════════════════════════════════

SYSTEM_TOOLS: list[Tool] = [
    Tool(
        name="read_file",
        description="读取文件内容。支持指定起始行(offset)和读取行数(limit)。与 Claude Code 的 Read 工具一致。",
        parameters=[
            ToolParameter("file_path", "string", "文件的绝对路径"),
            ToolParameter("offset", "integer", "起始行号（从0开始）", required=False),
            ToolParameter("limit", "integer", "读取行数，默认200", required=False),
        ],
        execute=_read_file_tool,
        category="system",
    ),
    Tool(
        name="write_file",
        description="创建或覆盖写入文件。会自动创建父目录。与 Claude Code 的 Write 工具一致。",
        parameters=[
            ToolParameter("file_path", "string", "文件的绝对路径"),
            ToolParameter("content", "string", "要写入的完整内容"),
        ],
        execute=_write_file_tool,
        category="system",
    ),
    Tool(
        name="edit_file",
        description="精确字符串替换编辑。找到 old_string 并替换为 new_string。如果找到多处匹配且 replace_all=False 则报错。与 Claude Code 的 Edit 工具一致。",
        parameters=[
            ToolParameter("file_path", "string", "文件的绝对路径"),
            ToolParameter("old_string", "string", "要被替换的原始文本"),
            ToolParameter("new_string", "string", "替换后的新文本"),
            ToolParameter("replace_all", "boolean", "是否替换所有匹配项，默认False", required=False),
        ],
        execute=_edit_file_tool,
        category="system",
    ),
    Tool(
        name="glob_files",
        description="按 glob 模式查找文件。例如 '**/*.py' 查找所有 Python 文件。与 Claude Code 的 Glob 工具一致。",
        parameters=[
            ToolParameter("pattern", "string", "Glob 模式，如 **/*.py, src/**/*.ts"),
            ToolParameter("path", "string", "搜索的根目录，默认当前目录", required=False),
        ],
        execute=_glob_files_tool,
        category="system",
    ),
    Tool(
        name="grep_files",
        description="搜索文件内容（正则表达式）。支持 glob 文件过滤。与 Claude Code 的 Grep 工具一致。",
        parameters=[
            ToolParameter("pattern", "string", "正则表达式搜索模式"),
            ToolParameter("path", "string", "搜索目录，默认当前目录", required=False),
            ToolParameter("glob", "string", "文件过滤 glob，如 *.py，默认*", required=False),
            ToolParameter("head_limit", "integer", "最多返回条数，默认50", required=False),
        ],
        execute=_grep_files_tool,
        category="system",
    ),
    Tool(
        name="bash_exec",
        description="执行 shell 命令并返回结果。支持超时控制和工作目录设置。危险命令（rm -rf, sudo, curl|sh 等）会被自动拦截。与 Claude Code 的 Bash 工具一致。",
        parameters=[
            ToolParameter("command", "string", "要执行的 shell 命令"),
            ToolParameter("workdir", "string", "工作目录，默认当前目录", required=False),
            ToolParameter("timeout", "integer", "超时时间（秒），默认120", required=False),
            ToolParameter("description", "string", "命令用途描述", required=False),
        ],
        execute=_bash_exec_tool,
        category="system",
    ),
]


def merge_all_tools() -> list[Tool]:
    """合并科研引擎工具 + 系统工具"""
    from backend.agent.tools import AGENT_TOOLS
    return list(AGENT_TOOLS) + SYSTEM_TOOLS
