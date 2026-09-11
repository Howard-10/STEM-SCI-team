import autogen
from autogen import UserProxyAgent, AssistantAgent, GroupChat, GroupChatManager, register_function
from typing import Dict, List, Tuple, Any

# 从本地文件导入工具
from graph_tool import get_all_concepts, get_path_between_concepts, check_concepts_in_graph

# 保存最终输出
final_output = ""

def register_tool(func, caller, executor, name: str, description: str):
    register_function(
        func,
        caller=caller,
        executor=executor,
        name=name,
        description=description,
    )

# 获取大模型配置
try:
    config_list = autogen.config_list_from_json(env_or_file="OAI_CONFIG_LIST.json")
except FileNotFoundError:
    print("错误: 找不到 OAI_CONFIG_LIST.json 文件。请确认文件已创建并与脚本在同一目录下。")
    config_list = []
except Exception as e:
    print(f"加载配置时发生错误: {e}")
    config_list = []

if not config_list:
    print("警告: config_list 为空。请检查 OAI_CONFIG_LIST.json 文件内容是否正确。")
    exit("由于无法加载模型配置，程序终止。请修正 OAI_CONFIG_LIST.json 文件。")
else:
    print("-------------------- 配置自查 --------------------")
    print("成功加载配置列表:")
    print(config_list)
    print("--------------------------------------------------")

# 自定义终止条件
def is_termination_msg(x):
    global final_output
    content = x.get("content", "")
    if content:
        final_output = content  # 保存最后一次输出
    if content and content.rstrip().endswith("TERMINATE"):
        return True
    tool_response_output = x.get("tool_response")
    if tool_response_output and isinstance(tool_response_output, str):
        if "错误：以下知识点在图谱中不存在" in tool_response_output:
            print("\n-------------------- 程序强制终止 --------------------")
            print("警告：知识点校验工具调用失败，已通过自定义终止逻辑结束对话。")
            print("------------------------------------------------------\n")
            return True
    return False

# 用户代理
user_proxy = UserProxyAgent(
    name="用户",
    is_termination_msg=is_termination_msg,
    human_input_mode="NEVER",
    llm_config=False,
    system_message="请根据需要，向其他智能体发送信息或使用工具。",
    code_execution_config={"use_docker": False}
)

# 知识点拆分智能体
splitter_agent = AssistantAgent(
    name="知识点拆分智能体",
    llm_config={"config_list": config_list},
    system_message="""你是一个科学教育专家，擅长从用户的问题中提取关键知识点。
    - **任务**：从用户提出的问题中提取所有相关的科学知识点。
    - **约束**：你必须首先调用 `get_all_concepts` 工具来获取知识图谱中所有可用的知识点列表。
      然后，从用户的问题中提取知识点，并调用 `check_concepts_in_graph` 工具来检查这些知识点是否在图谱中。
    - **输出**：将提取出的、且在图谱中存在的知识点以 Python 列表的格式传递给 `路径规划智能体`。
    """
)

# 路径规划智能体
path_planner_agent = AssistantAgent(
    name="路径规划智能体",
    llm_config={"config_list": config_list},
    system_message="""你是一个擅长规划学习路径的智能体。
    - **任务**：接收一个知识点列表。首先，只尝试调用一次 `get_knowledge_path` 工具来查找这些知识点在知识图谱中的先后序关系。
    - **逻辑**：如果工具调用失败或未找到完整路径，不要再次调用，也不要等待其它工具返回。
      你需要直接使用接收到的知识点列表，根据常识和逻辑进行合理排序，形成尽可能完整的学习路径。
    - **输出**：无论工具是否成功，你都必须将当前可用的、有序的知识点列表以 Python 列表格式立即传递给 `题目生成智能体`。
    - **限制**：不要在任何情况下使用 'TERMINATE' 关键字。
    """
)

# 题目生成智能体
question_generator_agent = AssistantAgent(
    name="题目生成智能体",
    llm_config={"config_list": config_list},
    system_message="""你是一个小学科学教育专家，擅长根据知识点生成题目和进行解释。
    - **任务**：接收一个包含知识点的学习路径列表，完成以下三件事：
        1. **知识点顺序**：将接收到的学习路径列表直接作为输出。
        2. **题目解析**：针对每个知识点，提供简短解析，说明它的重要性和与前后知识点的联系。
        3. **题目生成**：为学习路径中的每个知识点生成一道题目，共 6 道。如果路径中少于 6 个知识点，则为部分知识点生成多道题目，直到 6 道。
    - **输出格式**：用标题和列表结构清晰展示三个部分。
    - **终止**：输出完整结果后，最后一行必须是 'TERMINATE'。
    """
)

# 注册工具
register_tool(
    get_all_concepts,
    caller=splitter_agent,
    executor=user_proxy,
    name="get_all_concepts",
    description="返回知识图谱中所有可用的知识点列表。"
)
register_tool(
    check_concepts_in_graph,
    caller=splitter_agent,
    executor=user_proxy,
    name="check_concepts_in_graph",
    description="检查给定的知识点列表是否都存在于知识图谱中。返回一个列表，包含不存在的知识点。"
)
register_tool(
    get_path_between_concepts,
    caller=path_planner_agent,
    executor=user_proxy,
    name="get_knowledge_path",
    description="给定一个知识点列表，从知识图谱中返回一个有先后序关系的路径。"
)

# 创建多智能体对话
groupchat = GroupChat(
    agents=[user_proxy, splitter_agent, path_planner_agent, question_generator_agent],
    messages=[],
    max_round=15,
)

manager = GroupChatManager(
    groupchat=groupchat,
    name="chat_manager",
    llm_config={"config_list": config_list}
)

if __name__ == "__main__":
    user_proxy.initiate_chat(
        manager,
        message="如何测量距离",
    )
    # 从对话记录里取最后一条 content
    for msg in reversed(manager.groupchat.messages):
        if isinstance(msg, dict) and msg.get("content"):
            final_output = msg["content"]
            break

    print("\n==== 最终总结字符串 ====\n")
    print(final_output)

