from autogen import register_function
from graph_tool import get_path_between_concepts, get_all_concepts, check_concepts_in_graph

def register_tool(func, caller, executor, name: str, description: str):
    register_function(
        func,
        caller=caller,
        executor=executor,
        name=name,
        description=description,
    )


def register_tools(path_planner_agent, splitter_agent, user_proxy):
    """
    将工具函数注册到指定的调用者智能体上。
    """
    # 将工具注册到splitter_agent
    register_tool(
        get_all_concepts,
        caller=splitter_agent,
        executor=user_proxy,  # <-- 修正：将字符串替换为 user_proxy 对象
        name="get_all_concepts",
        description="返回知识图谱中所有可用的知识点列表。"
    )
    register_tool(
        check_concepts_in_graph,
        caller=splitter_agent,
        executor=user_proxy,  # <-- 修正：将字符串替换为 user_proxy 对象
        name="check_concepts_in_graph",
        description="检查给定的知识点列表是否都存在于知识图谱中。返回一个列表，包含不存在的知识点。"
    )

    # 将工具注册到path_planner_agent
    register_tool(
        get_path_between_concepts,
        caller=path_planner_agent,
        executor=user_proxy,  # <-- 修正：将字符串替换为 user_proxy 对象
        name="get_knowledge_path",
        description="给定一个知识点列表，从知识图谱中返回一个有先后序关系的路径。"
    )
