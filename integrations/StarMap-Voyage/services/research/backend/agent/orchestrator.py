"""Agent 编排器 — Claude 式 Think → Act → Observe → Reflect 循环

核心设计:
1. 系统提示词定义 Agent 身份、行为规范、可用工具
2. 多轮对话循环: 用户消息 → DeepSeek 决策(text or tool_calls) → 执行工具 → 喂回结果
3. 记忆管理: 对话历史 + 研究上下文
4. 规划能力: 复杂任务自动拆解为多步工具调用序列
"""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from backend.core.config import get_config
from backend.agent.tools import Tool, ToolRegistry, get_tool_registry
from backend.agent.system_tools import merge_all_tools, PermissionController
from backend.agent.skills import SkillLoader, get_skill_loader


# ── System Prompt ─────────────────────────────────────────

SYSTEM_PROMPT = """你是 Research-Copilot-OS 的 AI 科研助手，一位精通深度学习研究与论文写作的智能体。

## 你的能力
你是一个完整的科研开发助手，同时拥有科研专用工具和通用系统工具:

**🖥️ 系统工具** (文件 + Shell)
- read_file: 读取文件内容
- write_file: 创建或覆盖写入文件
- edit_file: 精确字符串替换编辑文件
- glob_files: 按模式查找文件
- grep_files: 搜索文件内容（正则）
- bash_exec: 执行 shell 命令

**📖 文献整理与解读**
- analyze_paper: 深度解读单篇论文
- review_papers: 多论文分类、对比、综述

**🧩 模型融合**
- chunk_code: AST 代码分块
- recommend_modules: 推荐可迁移的亮点模块
- migrate_module: 将模块从源模型迁移到目标模型

**🔬 数据处理**
- inspect_dataset: 解读数据集格式
- generate_dataloader: 生成适配 DataLoader 代码
- generate_augmentation: 生成数据增强/攻击代码

**⚡ 实验模块**
- generate_visualization: 自动生成可视化套件
- plan_ablation: 规划消融实验
- identify_hyperparams: 识别代码中的超参数
- generate_scheduler: 生成超参数调度器
- list_experiments: 查看历史实验记录

## 行为规范

### 1. 思考先行
在调用工具前，先分析用户需求：
- 需要哪些工具？按什么顺序调用？
- 工具的输入参数是否明确？如果不明确，先向用户确认。
- 是否可以先调用一个轻量工具来获取更多信息？

### 2. 多步规划
对于复杂任务，将其拆解为多个步骤：
- 第一步通常是用一个轻量工具获取信息
- 后续步骤依赖前面的结果
- 每个步骤完成后，评估是否需要调整后续计划

### 3. 结果解读
工具返回数据后，用通俗易懂的中文向用户解读：
- 不要只展示原始 JSON
- 提炼关键发现
- 指出异常或需要注意的地方
- 建议下一步可以做什么

### 4. 何时不调用工具
- 用户只是闲聊或打招呼时
- 用户的问题可以通过已获取的信息直接回答时
- 工具参数不明确且无法合理推断时（应先向用户确认）

### 5. 沟通风格
- 简洁、直接、专业
- 优先给出结论，再解释过程和原因
- 如果操作失败，诚实说明原因并建议替代方案
- 用中文回复"""


# ── Data Models ───────────────────────────────────────────

@dataclass
class AgentMessage:
    role: str  # "user", "assistant", "tool", "system"
    content: str
    tool_calls: Optional[list[dict]] = None
    tool_call_id: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class AgentTurn:
    """一轮对话的完整记录"""
    user_input: str
    thoughts: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    tool_results: list[dict] = field(default_factory=list)
    response: str = ""


@dataclass
class AgentSession:
    """一次 Agent 会话"""
    session_id: str
    history: list[AgentMessage] = field(default_factory=list)
    turns: list[AgentTurn] = field(default_factory=list)
    context: dict = field(default_factory=dict)  # 持久上下文（如当前项目路径）


# ── Orchestrator ──────────────────────────────────────────

class ResearchAgent:
    """科研智能体编排器

    使用 DeepSeek V4 作为推理引擎，Claude Agent SDK 风格的工具调用循环。
    """

    MAX_HISTORY_MESSAGES = 40  # 保留最近 N 条消息
    MAX_TOOL_ITERATIONS = 8    # 单轮最多连续工具调用次数

    def __init__(self):
        # 使用合并工具集（科研引擎 + 系统工具）
        all_tools = merge_all_tools()
        self.registry = ToolRegistry(all_tools)
        self.sessions: dict[str, AgentSession] = {}
        self._client = None
        self.permission = PermissionController()
        self.skill_loader = get_skill_loader()

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI
            cfg = get_config()
            self._client = OpenAI(api_key=cfg.llm.api_key, base_url=cfg.llm.base_url)
        return self._client

    # ── Session Management ────────────────────────────

    def create_session(self, session_id: str = None) -> AgentSession:
        sid = session_id or f"rco_{int(time.time())}"
        session = AgentSession(session_id=sid)
        self.sessions[sid] = session
        return session

    def get_session(self, session_id: str) -> Optional[AgentSession]:
        return self.sessions.get(session_id)

    # ── Core Loop ─────────────────────────────────────

    def run(
        self,
        user_input: str,
        session_id: str = None,
        allowed_tools: list[str] = None,
    ) -> dict:
        """执行一次 Agent 对话轮次

        返回:
        {
            "response": "给用户的文字回复",
            "tool_calls_made": [...],  # 本轮调用的工具及结果
            "session_id": "...",
        }
        """
        # 获取或创建会话
        if session_id and session_id in self.sessions:
            session = self.sessions[session_id]
        else:
            session = self.create_session(session_id)

        # 记录用户输入
        session.history.append(AgentMessage(role="user", content=user_input))

        # 技能匹配：检测用户输入是否触发专项技能
        active_skill = self.skill_loader.match_skill(user_input)
        skill_tools = None
        if active_skill:
            skill_tools = active_skill.tools
            allowed_tools = allowed_tools or skill_tools  # 优先使用技能推荐的工具

        # 构建本轮对话
        turn = AgentTurn(user_input=user_input)
        tool_schemas = self.registry.get_openai_schemas(allowed_tools)

        # 构建消息列表（注入技能上下文）
        messages = self._build_messages(session, tool_schemas, active_skill)

        # 主循环: 思考 → 行动 → 观察 → 反思
        for iteration in range(self.MAX_TOOL_ITERATIONS):
            cfg = get_config()
            response = self.client.chat.completions.create(
                model=cfg.llm.model,
                messages=messages,
                tools=tool_schemas if tool_schemas else None,
                tool_choice="auto" if tool_schemas else None,
                temperature=cfg.llm.temperature,
                max_tokens=cfg.llm.max_tokens,
            )

            choice = response.choices[0]
            msg = choice.message

            # 情况 1: LLM 决定回复文字（无工具调用）
            if not msg.tool_calls:
                assistant_msg = AgentMessage(
                    role="assistant",
                    content=msg.content or "",
                )
                session.history.append(assistant_msg)
                turn.response = msg.content or ""
                break

            # 情况 2: LLM 决定调用工具
            # 记录 assistant 消息（含 tool_calls）
            tc_list = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ]
            session.history.append(AgentMessage(
                role="assistant",
                content=msg.content or "",
                tool_calls=tc_list,
            ))
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": tc_list,
            })

            turn.tool_calls.extend(tc_list)

            # 执行每个工具调用
            for tc in msg.tool_calls:
                tool_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                # 权限检查
                perm_result = self.permission.check(tool_name, args)
                if not perm_result["allowed"]:
                    result = {"error": f"权限被拒绝: {perm_result['reason']}"}
                else:
                    result = self.registry.execute(tool_name, **args)
                    # 附上权限信息
                    result["_permission"] = perm_result

                tool_result = {
                    "tool_call_id": tc.id,
                    "tool_name": tool_name,
                    "arguments": args,
                    "result": result,
                }
                turn.tool_results.append(tool_result)

                # 添加到消息历史
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })
                session.history.append(AgentMessage(
                    role="tool",
                    content=json.dumps(result, ensure_ascii=False, default=str),
                    tool_call_id=tc.id,
                ))

            # 如果 LLM 没有更多工具调用意图，结束循环
            if choice.finish_reason == "stop":
                # 需要再请求一次获取最终回复
                final_response = self.client.chat.completions.create(
                    model=cfg.llm.model,
                    messages=messages,
                    temperature=cfg.llm.temperature,
                    max_tokens=cfg.llm.max_tokens,
                )
                final_content = final_response.choices[0].message.content or ""
                session.history.append(AgentMessage(role="assistant", content=final_content))
                turn.response = final_content
                break

        # 保存 turn
        session.turns.append(turn)

        # 修剪历史长度
        if len(session.history) > self.MAX_HISTORY_MESSAGES:
            session.history = session.history[-self.MAX_HISTORY_MESSAGES:]

        return {
            "response": turn.response,
            "tool_calls_made": [
                {
                    "tool": tr["tool_name"],
                    "arguments": tr["arguments"],
                    "result_summary": (
                        tr["result"].get("summary", "")
                        or tr["result"].get("total_chunks", "")
                        or str(tr["result"])[:200]
                    ),
                }
                for tr in turn.tool_results
            ],
            "session_id": session.session_id,
            "turn_count": len(session.turns),
        }

    def _build_messages(
        self, session: AgentSession, tool_schemas: list[dict],
        active_skill: "Skill" = None,
    ) -> list[dict]:
        """构建发送给 LLM 的消息列表"""
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        # 注入技能 System Prompt
        if active_skill:
            skill_prompt = active_skill.to_system_prompt()
            messages.append({"role": "system", "content": f"### 当前激活技能\n{skill_prompt}"})
        else:
            # 注入所有技能摘要
            messages.append({"role": "system", "content": self.skill_loader.get_all_skills_prompt()})

        # 添加上下文信息
        if session.context:
            ctx_text = "\n当前研究上下文:\n" + json.dumps(session.context, ensure_ascii=False, indent=2)
            messages.append({"role": "system", "content": ctx_text})

        # 添加历史消息（跳过 system）
        for hm in session.history[-self.MAX_HISTORY_MESSAGES:]:
            msg_dict = {"role": hm.role, "content": hm.content}
            if hm.tool_calls:
                msg_dict["tool_calls"] = hm.tool_calls
            if hm.tool_call_id:
                msg_dict["tool_call_id"] = hm.tool_call_id
            messages.append(msg_dict)

        return messages

    # ── Helper Methods ────────────────────────────────

    def set_context(self, session_id: str, key: str, value: any):
        """设置会话持久上下文（如当前项目路径、当前论文等）"""
        session = self.get_session(session_id)
        if session:
            session.context[key] = value

    def get_turn_history(self, session_id: str) -> list[dict]:
        """获取会话的历史轮次摘要"""
        session = self.get_session(session_id)
        if not session:
            return []
        return [
            {
                "user": t.user_input[:100],
                "tools_used": [tc["function"]["name"] for tc in t.tool_calls],
                "response": t.response[:200],
            }
            for t in session.turns
        ]

    def get_tool_descriptions(self) -> list[dict]:
        """获取所有工具的简要描述（用于前端展示）"""
        return [
            {
                "name": t.name,
                "description": t.description,
                "category": t.category,
                "parameters": [{"name": p.name, "type": p.type, "description": p.description, "required": p.required} for p in t.parameters],
            }
            for t in self.registry.list_all()
        ]


# ── Singleton ─────────────────────────────────────────────

_agent: Optional[ResearchAgent] = None


def get_agent() -> ResearchAgent:
    global _agent
    if _agent is None:
        _agent = ResearchAgent()
    return _agent
