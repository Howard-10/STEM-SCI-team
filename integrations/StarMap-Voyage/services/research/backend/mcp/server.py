"""MCP Server — 将 Research-Copilot-OS 的 14 个工具暴露给 Claude Code

遵循 MCP (Model Context Protocol) 规范，通过 stdio JSON-RPC 通信。
当 Claude Code 启动时，它会以子进程方式运行此 server，
然后通过 stdin/stdout 进行工具发现和调用。

协议: JSON-RPC 2.0 over stdio
"""

import json
import sys
import os
import logging
from typing import Any

# 设置日志到文件（因为 stdio 被 MCP 占用）
log_dir = os.path.expanduser("~/.research-copilot-os/logs")
os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(log_dir, "mcp_server.log"),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("mcp_server")

# 确保项目根在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.agent.system_tools import merge_all_tools

AGENT_TOOLS = merge_all_tools()


class MCPServer:
    """轻量级 MCP Server — JSON-RPC 2.0 over stdio"""

    def __init__(self):
        self.server_name = "research-copilot-os"
        self.server_version = "0.1.0"
        self.tools = self._build_tool_definitions()
        logger.info(f"MCP Server initialized with {len(self.tools)} tools")

    def _build_tool_definitions(self) -> list[dict]:
        """从 AGENT_TOOLS 构建 MCP 格式的工具定义"""
        definitions = []
        for tool in AGENT_TOOLS:
            # 构建 JSON Schema for parameters
            properties = {}
            required = []
            for p in tool.parameters:
                prop = {"type": p.type, "description": p.description}
                if p.enum:
                    prop["enum"] = p.enum
                properties[p.name] = prop
                if p.required:
                    required.append(p.name)

            definitions.append({
                "name": tool.name,
                "description": tool.description,
                "inputSchema": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            })
        return definitions

    def run(self):
        """主循环: 读取 stdin 的 JSON-RPC 请求，处理后写回 stdout"""
        logger.info("MCP Server starting main loop")
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                response = self._handle_request(request)
                if response is not None:
                    self._write(response)
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON: {e}")
                self._write({
                    "jsonrpc": "2.0",
                    "error": {"code": -32700, "message": "Parse error"},
                    "id": None,
                })
            except Exception as e:
                logger.exception(f"Unhandled error: {e}")

    def _handle_request(self, request: dict) -> dict | None:
        """处理单个 JSON-RPC 请求"""
        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params", {})

        logger.info(f"Received: {method}")

        # Notification (no id) — no response needed
        if req_id is None:
            self._handle_notification(method, params)
            return None

        # Request — must respond
        try:
            result = self._handle_method(method, params)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": result,
            }
        except Exception as e:
            logger.exception(f"Method error: {method}")
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32603, "message": str(e)},
            }

    def _handle_notification(self, method: str, params: dict):
        """处理通知（无需回复）"""
        if method == "notifications/initialized":
            logger.info("Client initialized")
        elif method == "notifications/cancelled":
            logger.info(f"Request cancelled: {params}")

    def _handle_method(self, method: str, params: dict) -> Any:
        """分派方法"""
        if method == "initialize":
            return {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": self.server_name,
                    "version": self.server_version,
                },
            }
        elif method == "tools/list":
            return {"tools": self.tools}
        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            return self._call_tool(tool_name, arguments)
        else:
            raise ValueError(f"Unknown method: {method}")

    def _call_tool(self, name: str, arguments: dict) -> dict:
        """调用工具并返回 MCP 格式的结果"""
        logger.info(f"Calling tool: {name} with args: {arguments}")

        # 查找工具
        tool = None
        for t in AGENT_TOOLS:
            if t.name == name:
                tool = t
                break

        if not tool:
            return {
                "content": [{"type": "text", "text": f"Error: Unknown tool '{name}'"}],
                "isError": True,
            }

        try:
            result = tool.execute(**arguments)
            result_text = json.dumps(result, ensure_ascii=False, default=str, indent=2)

            # 截断过长结果
            if len(result_text) > 80000:
                result_text = result_text[:80000] + "\n... (truncated)"

            return {
                "content": [{"type": "text", "text": result_text}],
            }
        except Exception as e:
            logger.exception(f"Tool execution failed: {name}")
            return {
                "content": [{"type": "text", "text": f"Tool execution error: {str(e)}"}],
                "isError": True,
            }

    def _write(self, data: dict):
        """写入 JSON-RPC 响应到 stdout"""
        line = json.dumps(data, ensure_ascii=False)
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
        logger.info(f"Sent: {str(data)[:200]}")


def main():
    """MCP Server 入口 — 由 Claude Code 作为子进程启动"""
    server = MCPServer()
    server.run()


if __name__ == "__main__":
    main()
