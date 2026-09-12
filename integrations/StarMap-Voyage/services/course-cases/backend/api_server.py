from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import json
import os
import random
import asyncio
from fastapi.responses import RedirectResponse

from graph_tool import (
    get_all_concepts,
    check_concepts_in_graph,
    get_path_between_concepts,
    get_prerequisites,
    get_postrequisites,
)

# 导入智能体系统
try:
    import autogen
    from autogen import UserProxyAgent, AssistantAgent, GroupChat, GroupChatManager, register_function
    from config_qwen import get_qwen_config
    AUTOGEN_AVAILABLE = True
except ImportError as e:
    AUTOGEN_AVAILABLE = False
    print(f"警告: AutoGen 导入失败，将使用基础功能: {e}")

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(APP_DIR)
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")
QUESTION_BANK_PATH = os.path.join(APP_DIR, "question_bank.json")

app = FastAPI(title="星图学航--基于深度推理大模型的自适应STEM学习路径规划系统")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static frontend if exists
if os.path.isdir(FRONTEND_DIR):
    app.mount("/app", StaticFiles(directory=FRONTEND_DIR, html=True), name="app")


# ---------- 智能体系统初始化 ----------

def register_tool(func, caller, executor, name: str, description: str):
    """按 AutoGen 0.2 官方方式注册工具。"""
    register_function(
        func,
        caller=caller,
        executor=executor,
        name=name,
        description=description,
    )

def init_agents():
    """初始化智能体系统"""
    if not AUTOGEN_AVAILABLE:
        return None, None, None, None
    
    try:
        config_list = get_qwen_config()
        
        # 用户代理
        user_proxy = UserProxyAgent(
            name="用户",
            human_input_mode="NEVER",
            llm_config=False,
            system_message="请根据需要，向其他智能体发送信息或使用工具。",
            code_execution_config={"use_docker": False}
        )

        # 知识点识别智能体
        concept_agent = AssistantAgent(
            name="知识点识别智能体",
            llm_config={"config_list": config_list},
            system_message="""你是一个科学教育专家，擅长从用户的问题中提取关键知识点。
            - **任务**：从用户提出的问题中提取所有相关的科学知识点。
            - **约束**：你必须首先调用 `get_all_concepts` 工具来获取知识图谱中所有可用的知识点列表。
              然后，从用户的问题中提取知识点，并调用 `check_concepts_in_graph` 工具来检查这些知识点是否在图谱中。
            - **输出**：将提取出的、且在图谱中存在的知识点以 Python 列表的格式输出。
            """
        )

        # 路径推荐智能体
        path_agent = AssistantAgent(
            name="路径推荐智能体",
            llm_config={"config_list": config_list},
            system_message="""你是一个擅长规划学习路径的智能体。
            - **任务**：接收一个知识点列表，调用 `get_knowledge_path` 工具来查找这些知识点在知识图谱中的先后序关系。
            - **输出**：返回有序的学习路径列表。
            """
        )

        # 题目生成智能体
        question_agent = AssistantAgent(
            name="题目生成智能体",
            llm_config={"config_list": config_list},
            system_message="""你是一个小学科学教育专家，擅长根据知识点生成多种类型的题目。
            - **任务**：根据给定的知识点生成不同类型的题目，包括：
                1. 选择题（4个选项）
                2. 填空题（1-2个空）
                3. 简答题（需要简短回答）
                4. 判断题（对错题）
            - **要求**：
                - 题目要符合小学科学课程标准
                - 难度适中，适合小学生理解
                - 每道题都要有详细的解析
                - 题目要生动有趣，贴近生活
            - **输出格式**：返回JSON格式的题目列表，包含题目类型、题干、选项、答案、解析等。
            """
        )

        # 注册工具
        register_tool(
            get_all_concepts,
            caller=concept_agent,
            executor=user_proxy,
            name="get_all_concepts",
            description="返回知识图谱中所有可用的知识点列表。"
        )
        register_tool(
            check_concepts_in_graph,
            caller=concept_agent,
            executor=user_proxy,
            name="check_concepts_in_graph",
            description="检查给定的知识点列表是否都存在于知识图谱中。返回一个列表，包含不存在的知识点。"
        )
        register_tool(
            get_path_between_concepts,
            caller=path_agent,
            executor=user_proxy,
            name="get_knowledge_path",
            description="给定一个知识点列表，从知识图谱中返回一个有先后序关系的路径。"
        )

        return user_proxy, concept_agent, path_agent, question_agent
    
    except Exception as e:
        print(f"智能体初始化失败: {e}")
        return None, None, None, None


# 初始化智能体
user_proxy, concept_agent, path_agent, question_agent = init_agents()


# ---------- Data Loading ----------

def load_question_bank() -> Dict[str, Any]:
    if not os.path.exists(QUESTION_BANK_PATH):
        raise FileNotFoundError("question_bank.json 未找到，请先创建题库文件")
    with open(QUESTION_BANK_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_cases() -> List[Dict[str, str]]:
    bank = load_question_bank()
    cases = bank.get("cases", [])
    return cases


def get_questions_by_case(case_id: str) -> List[Dict[str, Any]]:
    bank = load_question_bank()
    questions_map = bank.get("questions", {})
    if case_id not in questions_map:
        raise HTTPException(status_code=404, detail="未找到该案例的题目")
    return questions_map[case_id]


def get_concept_explanation(concept: str) -> str:
    """获取知识点的详细解释"""
    # 首先尝试从题库中获取预定义的解析
    bank = load_question_bank()
    explanations = bank.get("concept_explanations", {})
    predefined_explanation = explanations.get(concept, "")
    
    # 如果有预定义的解析，直接返回
    if predefined_explanation:
        return predefined_explanation
    
    # 如果没有预定义解析，尝试使用智能体生成
    if AUTOGEN_AVAILABLE and all([user_proxy, concept_agent]):
        try:
            # 创建群聊来生成解析
            groupchat = GroupChat(
                agents=[user_proxy, concept_agent],
                messages=[],
                max_round=5,
            )
            
            manager = GroupChatManager(
                groupchat=groupchat,
                llm_config={"config_list": get_qwen_config()}
            )
            
            # 构建提示词
            prompt = f"""
            请为知识点"{concept}"生成一个详细、准确、易懂的解释。
            
            要求：
            1. 解释要科学准确，符合小学科学课程标准
            2. 语言要通俗易懂，适合小学生理解
            3. 可以包含相关的例子或应用
            4. 长度控制在200-400字之间
            5. 直接返回解释内容，不要包含其他格式
            
            请开始生成解释：
            """
            
            # 启动对话
            user_proxy.initiate_chat(manager, message=prompt)
            
            # 获取结果
            final_output = ""
            for msg in reversed(manager.groupchat.messages):
                if isinstance(msg, dict) and msg.get("content"):
                    final_output = msg["content"]
                    break
            
            # 清理输出，移除可能的格式标记
            import re
            # 移除可能的markdown标记
            cleaned_output = re.sub(r'[*#`]', '', final_output)
            # 移除可能的"解释："等前缀
            cleaned_output = re.sub(r'^解释[：:]\s*', '', cleaned_output)
            cleaned_output = re.sub(r'^知识点[：:]\s*', '', cleaned_output)
            
            if cleaned_output and len(cleaned_output.strip()) > 10:
                return cleaned_output.strip()
            
        except Exception as e:
            print(f"智能体生成知识点解析失败: {e}")
    
    # 如果智能体生成失败，返回一个基础的解析
    return f"'{concept}'是一个重要的科学概念。它涉及科学、技术、工程和数学等多个领域的知识。建议通过具体的学习活动和实践来深入理解这个概念。"


async def generate_smart_questions(concepts: List[str], question_count: int = 3) -> List[Dict[str, Any]]:
    """使用智能体生成智能题目"""
    if not all([user_proxy, concept_agent, question_agent]):
        # 如果智能体不可用，使用基础生成
        return generate_basic_questions(concepts, question_count)
    
    try:
        # 定义终止检测函数
        def is_termination_message(msg):
            """检测消息是否包含终止信号或完整的JSON格式题目列表"""
            if not msg or not isinstance(msg, dict) or 'content' not in msg:
                return False
            content = msg['content'].strip().lower()
            # 检查是否包含完整的JSON数组或终止关键词
            return ('[{' in msg['content'] and '}]' in msg['content']) or 'terminate' in content
        
        # 创建群聊，设置更合理的最大轮数并添加终止检测函数
        groupchat = GroupChat(
            agents=[user_proxy, concept_agent, question_agent],
            messages=[],  # 确保每次都是空的消息历史
            max_round=5,  # 减少最大轮数，避免过多对话
            speaker_selection_method="auto",
            allow_repeat_speaker=False
        )
        
        manager = GroupChatManager(
            groupchat=groupchat,
            llm_config={"config_list": get_qwen_config()},
            is_termination_msg=is_termination_message
        )
        
        # 构建提示词
        prompt = f"""
        请为以下知识点生成{question_count}道不同类型的题目：
        知识点：{', '.join(concepts)}
        
        要求：
        1. 生成选择题、填空题、简答题各1道
        2. 题目要符合小学科学课程标准
        3. 每道题都要有详细解析
        4. 选择题选项必须使用A、B、C、D作为键，不能使用0、1、2、3
        5. 答案必须与选项键对应（如选择A选项，答案就是A）
        6. 解析必须与题目内容相关，不能是通用的解释
        7. 返回JSON格式，包含题目类型、题干、选项、答案、解析等
        
        请直接返回JSON格式的题目列表。
        """
        
        # 清空用户代理的对话历史，避免影响当前生成
        user_proxy.reset()
        
        # 启动对话，设置max_round_talk=2来限制对话轮数
        user_proxy.initiate_chat(
            manager, 
            message=prompt,
            max_round=2  # 限制对话轮数，避免反复生成
        )
        
        # 获取结果
        final_output = ""
        for msg in reversed(manager.groupchat.messages):
            if isinstance(msg, dict) and msg.get("content"):
                final_output = msg["content"]
                # 如果找到包含完整JSON的消息，立即返回
                if '[{' in final_output and '}]' in final_output:
                    break
        
        # 尝试解析JSON结果
        try:
            # 提取JSON部分
            import re
            json_match = re.search(r'\[.*\]', final_output, re.DOTALL)
            if json_match:
                questions_data = json.loads(json_match.group())
                # 确保每个题目都有完整的数据结构
                for i, question in enumerate(questions_data):
                    if not isinstance(question, dict):
                        continue
                    
                    # 确保选项格式正确
                    if question.get('type') == '选择题' and question.get('options'):
                        # 检查选项键是否为ABCD格式
                        options = question['options']
                        if not all(key in ['A', 'B', 'C', 'D'] for key in options.keys()):
                            # 如果不是ABCD格式，重新映射
                            new_options = {}
                            option_values = list(options.values())
                            for j, key in enumerate(['A', 'B', 'C', 'D']):
                                if j < len(option_values):
                                    new_options[key] = option_values[j]
                            question['options'] = new_options
                            
                            # 更新答案
                            if question.get('answer') and str(question['answer']).isdigit():
                                answer_index = int(question['answer'])
                                if 0 <= answer_index < len(option_values):
                                    question['answer'] = ['A', 'B', 'C', 'D'][answer_index]
                    
                    question.setdefault('id', f'gen_smart_{i}')
                    question.setdefault('type', '选择题')
                    question.setdefault('text', question.get('question', '题目内容'))
                    question.setdefault('options', {})
                    question.setdefault('answer', '')
                    question.setdefault('explanation', '暂无解析')
                    question.setdefault('concepts', concepts)
                    question.setdefault('is_generated', True)
                return questions_data
            else:
                # 如果无法解析，使用基础生成
                return generate_basic_questions(concepts, question_count)
        except Exception as parse_error:
            print(f"JSON解析失败: {parse_error}")
            return generate_basic_questions(concepts, question_count)
    
    except Exception as e:
        print(f"智能题目生成失败: {e}")
        return generate_basic_questions(concepts, question_count)


def generate_basic_questions(concepts: List[str], question_count: int = 3) -> List[Dict[str, Any]]:
    """基础题目生成（备用方案）"""
    question_types = ["选择题", "填空题", "简答题"]
    questions = []
    
    for i in range(min(question_count, len(question_types))):
        concept = concepts[i % len(concepts)]
        question_type = question_types[i]
        
        if question_type == "选择题":
            question = {
                "id": f"gen_choice_{random.randint(1000, 9999)}",
                "type": "选择题",
                "text": f"关于{concept}，下列说法正确的是？",
                "options": {
                    "A": f"{concept}是科学中的重要概念，与日常生活密切相关",
                    "B": f"{concept}与日常生活无关，只在实验室中使用",
                    "C": f"{concept}不需要学习，对科学理解没有帮助",
                    "D": f"{concept}只存在于理论中，没有实际应用"
                },
                "answer": "A",
                "explanation": f"{concept}是科学学习中的重要知识点，与我们的日常生活密切相关。通过学习{concept}，我们可以更好地理解自然现象和科学原理，并将其应用到实际生活中。",
                "concepts": [concept],
                "is_generated": True
            }
        elif question_type == "填空题":
            question = {
                "id": f"gen_fill_{random.randint(1000, 9999)}",
                "type": "填空题",
                "text": f"在科学学习中，{concept}主要用来_____。",
                "answer": "解决实际问题",
                "explanation": f"{concept}是科学知识的重要组成部分，主要用于解决实际生活中的问题。通过学习{concept}，我们可以更好地理解自然规律，并将其应用到日常生活中，解决各种实际问题。",
                "concepts": [concept],
                "is_generated": True
            }
        else:  # 简答题
            question = {
                "id": f"gen_short_{random.randint(1000, 9999)}",
                "type": "简答题",
                "text": f"请简要说明{concept}在科学学习中的重要性。",
                "answer": f"{concept}是科学知识体系的重要组成部分，帮助我们更好地理解自然现象和科学原理。",
                "explanation": f"{concept}作为科学概念，在科学学习中起到基础性作用，是理解更复杂科学现象的前提。通过学习{concept}，我们可以建立正确的科学认知，为后续的深入学习打下坚实基础。",
                "concepts": [concept],
                "is_generated": True
            }
        
        questions.append(question)
    
    return questions


async def get_smart_learning_path(concepts: List[str]) -> Dict[str, Any]:
    """使用智能体获取智能学习路径"""
    if not all([user_proxy, concept_agent, path_agent]):
        # 如果智能体不可用，使用基础路径
        return get_basic_learning_path(concepts)
    
    try:
        # 定义终止检测函数
        def is_termination_message(msg):
            """检测消息是否包含终止信号或完整的JSON格式学习路径"""
            if not msg or not isinstance(msg, dict) or 'content' not in msg:
                return False
            # 检查是否包含完整的JSON对象或终止关键词
            return ('{' in msg['content'] and '}' in msg['content']) or 'terminate' in msg['content'].lower()
        
        # 创建群聊，设置更合理的最大轮数并添加终止检测函数
        groupchat = GroupChat(
            agents=[user_proxy, concept_agent, path_agent],
            messages=[],  # 确保每次都是空的消息历史
            max_round=4,  # 减少最大轮数，避免过多对话
            speaker_selection_method="auto",
            allow_repeat_speaker=False
        )
        
        manager = GroupChatManager(
            groupchat=groupchat,
            llm_config={"config_list": get_qwen_config()},
            is_termination_msg=is_termination_message
        )
        
        # 构建提示词
        prompt = f"""
        请为以下知识点规划最优学习路径：
        知识点：{', '.join(concepts)}
        
        要求：
        1. 分析知识点之间的逻辑关系
        2. 规划合理的学习顺序
        3. 考虑学习难度递进
        4. 返回完整的学习路径，包括前驱知识点和后继知识点
        5. 返回JSON格式，包含path（学习路径）、prerequisites（前驱知识点）、postrequisites（后继知识点）
        
        请直接返回JSON格式的学习路径。
        """
        
        # 清空用户代理的对话历史，避免影响当前生成
        user_proxy.reset()
        
        # 启动对话，设置max_round=2来限制对话轮数
        user_proxy.initiate_chat(
            manager, 
            message=prompt,
            max_round=2  # 限制对话轮数，避免反复生成
        )
        
        # 获取结果
        final_output = ""
        for msg in reversed(manager.groupchat.messages):
            if isinstance(msg, dict) and msg.get("content"):
                final_output = msg["content"]
                # 如果找到包含完整JSON的消息，立即返回
                if '{' in final_output and '}' in final_output:
                    break
        
        # 尝试解析结果
        try:
            import re
            json_match = re.search(r'\{.*\}', final_output, re.DOTALL)
            if json_match:
                path_data = json.loads(json_match.group())
                # 确保返回的数据结构完整
                path_data.setdefault('path', concepts)
                path_data.setdefault('prerequisites', [])
                path_data.setdefault('postrequisites', [])
                path_data.setdefault('description', '基于AI智能体的学习路径推荐')
                return path_data
            else:
                return get_basic_learning_path(concepts)
        except Exception as parse_error:
            print(f"路径JSON解析失败: {parse_error}")
            return get_basic_learning_path(concepts)
    
    except Exception as e:
        print(f"智能路径规划失败: {e}")
        return get_basic_learning_path(concepts)


def get_basic_learning_path(concepts: List[str]) -> Dict[str, Any]:
    """基础学习路径（备用方案）"""
    try:
        def flatten_path_nodes(paths: List[Any]) -> List[str]:
            """将 [[a,b],[b,c]] 这类路径结构压平成去重后的知识点序列。"""
            flattened: List[str] = []
            seen = set()
            for item in paths:
                if isinstance(item, list):
                    for node in item:
                        if isinstance(node, str) and node not in seen:
                            seen.add(node)
                            flattened.append(node)
                elif isinstance(item, str) and item not in seen:
                    seen.add(item)
                    flattened.append(item)
            return flattened

        # 获取知识图谱中所有可用的知识点
        all_concepts = get_all_concepts()
        
        # 过滤掉不在知识图谱中的知识点
        valid_concepts = [c for c in concepts if c in all_concepts]
        if not valid_concepts:
            # 如果没有有效知识点，返回空路径
            return {
                "concepts": [],
                "path": [],
                "description": "未找到知识图谱中的相关知识点"
            }
        
        # 定义基础学科（这些应该是平行的，不是一条路径）
        basic_subjects = ['科学', '技术', '工程', '数学']
        
        # 分离基础学科和具体知识点
        basic_concepts = [c for c in valid_concepts if c in basic_subjects]
        specific_concepts = [c for c in valid_concepts if c not in basic_subjects]
        
        # 对于基础学科，它们应该是平行的，不需要排序
        if basic_concepts:
            basic_concepts = list(set(basic_concepts))  # 去重
        
        # 对于具体知识点，尝试使用知识图谱工具获取路径
        if specific_concepts:
            path_result = get_path_between_concepts(specific_concepts)
            if isinstance(path_result, list):
                # 确保路径包含所有相关知识点，且都在知识图谱中
                valid_path = [c for c in path_result if c in all_concepts]
                if not valid_path:
                    valid_path = specific_concepts
            else:
                valid_path = specific_concepts
        else:
            valid_path = []
        
        # 构建最终的学习路径
        # 基础学科放在前面，作为平行的基础
        final_path = basic_concepts + valid_path
        
        # 获取前驱和后继关系
        prerequisites = []
        postrequisites = []
        
        # 为每个具体知识点获取前驱和后继
        for concept in specific_concepts:
            try:
                pre = get_prerequisites(concept)
                post = get_postrequisites(concept)
                
                if isinstance(pre, dict) and not pre.get("error"):
                    prerequisites.extend(flatten_path_nodes(pre.get("prerequisites", [])))
                if isinstance(post, dict) and not post.get("error"):
                    postrequisites.extend(flatten_path_nodes(post.get("postrequisites", [])))
            except Exception as e:
                print(f"获取知识点 {concept} 的前驱后继失败: {e}")
        
        # 去重并过滤
        prerequisites = list(set([c for c in prerequisites if c in all_concepts]))
        postrequisites = list(set([c for c in postrequisites if c in all_concepts]))
        
        # 移除已经在当前概念列表中的知识点
        prerequisites = [c for c in prerequisites if c not in valid_concepts]
        postrequisites = [c for c in postrequisites if c not in valid_concepts]
        
        return {
            "concepts": valid_concepts,
            "path": final_path,
            "prerequisites": prerequisites,
            "postrequisites": postrequisites,
            "description": "基于知识图谱的完整学习路径，基础学科平行排列"
        }
        
    except Exception as e:
        print(f"学习路径生成错误: {e}")
        return {
            "concepts": concepts,
            "path": concepts,
            "prerequisites": [],
            "postrequisites": [],
            "description": "学习路径生成失败，返回原始知识点"
        }


# ---------- Schemas ----------

class EvaluateRequest(BaseModel):
    case_id: str
    answers: Dict[str, str]  # question_id -> selected_option_key

class EvaluateResponseItem(BaseModel):
    question_id: str
    correct: bool
    correct_answer: str
    explanation: str
    concepts: List[str]

class ConceptsRequest(BaseModel):
    question_text: str
    top_k: Optional[int] = 6

class ConceptDetailRequest(BaseModel):
    concept: str

class EvaluateSingleRequest(BaseModel):
    case_id: str
    question_index: int
    selected_answer: str

class GenerateSimilarRequest(BaseModel):
    case_id: str
    question_index: int
    question_count: Optional[int] = 3

class LearningPathRequest(BaseModel):
    concepts: List[str]


# ---------- Helpers ----------

def simple_extract_concepts(question_text: str, top_k: int = 6) -> List[str]:
    """
    基于知识图谱中的概念名做简单的子串/字符重叠匹配，返回最相关的若干个概念。
    支持动态知识图谱，如果知识点不在图谱中会尝试添加。
    """
    concepts = get_all_concepts()
    question = question_text.strip()
    scored: List[tuple[str, int]] = []

    for c in concepts:
        score = 0
        # 简单子串命中
        if c in question:
            score += 10
        # 字符重叠（去重后）
        set_c = set(c)
        set_q = set(question)
        overlap = len(set_c & set_q)
        score += overlap
        if score > 0:
            scored.append((c, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    candidates = [c for c, _ in scored[: max(1, top_k)]]

    # 校验存在性（应全在图谱中）
    missing, existing = check_concepts_in_graph(candidates)
    
    # 尝试添加缺失的知识点到知识图谱
    if missing:
        print(f"发现新知识点: {missing}")
        # 这里可以调用知识图谱工具来添加新节点
        # 暂时跳过无法添加的知识点
        candidates = [c for c in candidates if c not in missing]
    
    return candidates


# ---------- Endpoints ----------

@app.get("/api/cases")
async def api_cases() -> List[Dict[str, str]]:
    return get_cases()


@app.get("/api/questions")
async def api_questions(case_id: str = Query(..., description="案例ID")) -> List[Dict[str, Any]]:
    return get_questions_by_case(case_id)


@app.get("/api/question/{case_id}/{question_index}")
async def api_single_question(case_id: str, question_index: int) -> Dict[str, Any]:
    """获取单个题目"""
    questions = get_questions_by_case(case_id)
    if question_index < 0 or question_index >= len(questions):
        raise HTTPException(status_code=404, detail="题目索引超出范围")
    
    question = questions[question_index]
    return {
        "question": question,
        "index": question_index,
        "total": len(questions)
    }


@app.post("/api/evaluate")
async def api_evaluate(payload: EvaluateRequest) -> List[EvaluateResponseItem]:
    questions = get_questions_by_case(payload.case_id)
    id2q = {q["id"]: q for q in questions}
    results: List[EvaluateResponseItem] = []
    for qid, selected in payload.answers.items():
        q = id2q.get(qid)
        if not q:
            continue
        correct_key = q.get("answer")
        results.append(EvaluateResponseItem(
            question_id=qid,
            correct=(selected == correct_key),
            correct_answer=correct_key or "",
            explanation=q.get("explanation", "暂无解析"),
            concepts=q.get("concepts", [])
        ))
    return results


@app.post("/api/evaluate-single")
async def api_evaluate_single(payload: EvaluateSingleRequest) -> Dict[str, Any]:
    """评估单个题目"""
    questions = get_questions_by_case(payload.case_id)
    if payload.question_index < 0 or payload.question_index >= len(questions):
        raise HTTPException(status_code=404, detail="题目索引超出范围")
    
    question = questions[payload.question_index]
    question_type = question.get("type", "选择题")
    
    # 根据题目类型进行不同的评估
    if question_type == "选择题":
        correct = payload.selected_answer == question["answer"]
    elif question_type == "填空题":
        # 填空题可能有多个答案，用逗号分隔
        correct_answers = [ans.strip() for ans in question["answer"].split(",")]
        user_answer = payload.selected_answer.strip()
        correct = user_answer in correct_answers
    elif question_type == "简答题":
        # 简答题采用关键词匹配的方式
        correct_keywords = question["answer"].lower().split()
        user_answer = payload.selected_answer.lower()
        # 如果用户答案包含超过50%的关键词，认为正确
        matched_keywords = sum(1 for keyword in correct_keywords if keyword in user_answer)
        correct = matched_keywords >= len(correct_keywords) * 0.5
    elif question_type == "判断题":
        correct = payload.selected_answer == question["answer"]
    else:
        # 默认按选择题处理
        correct = payload.selected_answer == question["answer"]
    
    return {
        "correct": correct,
        "correct_answer": question["answer"],
        "explanation": question.get("explanation", "暂无解析"),
        "concepts": question.get("concepts", [])
    }


@app.post("/api/generate-similar")
async def api_generate_similar(payload: GenerateSimilarRequest) -> Dict[str, Any]:
    """生成智能题目"""
    questions = get_questions_by_case(payload.case_id)
    if payload.question_index < 0 or payload.question_index >= len(questions):
        raise HTTPException(status_code=404, detail="题目索引超出范围")
    
    original_question = questions[payload.question_index]
    concepts = original_question.get("concepts", [])
    
    # 使用智能体生成题目
    generated_questions = await generate_smart_questions(concepts, payload.question_count or 3)
    
    return {
        "questions": generated_questions,
        "original_index": payload.question_index,
        "concepts": concepts
    }


@app.post("/api/learning-path")
async def api_learning_path(payload: LearningPathRequest) -> Dict[str, Any]:
    """获取智能学习路径"""
    return await get_smart_learning_path(payload.concepts)


@app.post("/api/concepts")
async def api_concepts(payload: ConceptsRequest) -> Dict[str, Any]:
    concepts = simple_extract_concepts(payload.question_text, payload.top_k or 6)
    return {"concepts": concepts}


@app.get("/api/concept/{concept}")
async def api_concept_detail(concept: str) -> Dict[str, Any]:
    """获取知识点详细解释"""
    explanation = get_concept_explanation(concept)
    return {
        "concept": concept,
        "explanation": explanation
    }


@app.get("/api/path")
async def api_path(concept: str = Query(..., description="知识点名称")) -> Dict[str, Any]:
    pre = get_prerequisites(concept)
    post = get_postrequisites(concept)
    if isinstance(pre, dict) and pre.get("error"):
        raise HTTPException(status_code=404, detail=pre["error"])
    if isinstance(post, dict) and post.get("error"):
        raise HTTPException(status_code=404, detail=post["error"])
    return {"concept": concept, "prerequisites": pre.get("prerequisites", []), "postrequisites": post.get("postrequisites", [])}


@app.get("/")
async def root():
    if os.path.isdir(FRONTEND_DIR):
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="app/")
    return {"message": "API 在线。未发现前端目录。"}


@app.get("/api/health")
async def api_health():
    return {"status": "ok"}
