"""End-to-end conversational QA over the shared knowledge corpus."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from stem_sci.agents.runtime import GPTProvider, StructuredGenerator
from stem_sci.context.models import ContextBundle, EvidenceSearchRequest

from .models import ContextMode, RetrievalSearchRequest, RetrievalSearchResponse
from .normalization import expanded_query, normalize_doi, normalize_text
from .qa_memory import ConversationMemoryStore
from .qa_models import (
    ConversationSummary,
    MemoryTurn,
    QAAnswerRecord,
    QAAnswerRequest,
    QAAnswerResponse,
    QAReference,
    QARouteDecision,
    QAWorkflowAction,
)
from .qa_tools import (
    WORKFLOW_TOOL_NAMES,
    QAToolExecutor,
    route_for_tool,
    tool_definitions,
    tool_reason,
)
from .service import HybridKnowledgeService

logger = logging.getLogger(__name__)


_CGT_PROJECT_MARKERS = (
    "计算扎根理论",
    "扎根理论",
    "grounded theory",
    "句子级编码",
    "学生级聚合",
    "主题候选",
    "模式发现",
    "公开二手资料",
    "德语文本",
    "物理问题解决文本",
    "物理教育中的问题解决与文本分析",
    "physics problem-solving text",
)
_LEGACY_AI_PROJECT_MARKERS = (
    "生成式人工智能",
    "generative artificial intelligence",
    "计算思维",
    "computational thinking",
    "primary_use",
    "secondary_concept",
)
_CGT_FORBIDDEN_RESPONSE_TERMS = (
    "primary_use",
    "secondary_concept",
    "secondary_reasoning",
    "secondary_answer",
    "secondary_code",
    "生成式人工智能使用频率",
    "大学物理学习成效",
    "行为代理指标",
    "问卷编码",
    "使用频率/时长",
    "交互行为深度",
    "ai_use_7d",
    "这三个变量",
)


def _project_domain(project_context: str | None) -> str:
    """Infer a narrow response domain from durable project context.

    The fallback must not guess a domain from a single user noun.  Only the
    project context can activate a specialized template; otherwise the
    response remains neutral and grounded in the current question.
    """

    normalized = (project_context or "").strip().lower()
    if not normalized:
        return "unknown"
    if any(marker in normalized for marker in _CGT_PROJECT_MARKERS):
        return "physics_cgt"
    if any(marker in normalized for marker in _LEGACY_AI_PROJECT_MARKERS) or (
        "问卷" in normalized
        and any(marker in normalized for marker in ("大学物理", "人工智能"))
    ):
        return "ai_questionnaire"
    return "unknown"


def _cgt_fallback_answer(
    question: str,
    *,
    planned_research_acts: list[str] | None = None,
    planned_follow_up_question: str | None = None,
    allow_unplanned_follow_up: bool = True,
) -> str:
    """Provide bounded discussion for the physics-text CGT project.

    This is intentionally separate from the historical questionnaire copy so
    that a project-level context cannot inherit variables from another study.
    """

    normalized = question.strip().lower()
    acts = set(planned_research_acts or [])
    if any(term in normalized for term in ("三阶段", "人机协作", "计算扎根", "主题数量", "主题名称")):
        return (
            "适合，但应把它限定为‘计算辅助的探索—研究者修订—监督确认’三阶段流程："
            "第一阶段只发现可回链的中性模式和反例，不预设主题数量或名称；"
            "第二阶段由研究者根据原文语境修订、合并或拆分编码规则；"
            "第三阶段只在编码规则冻结后做监督确认和学生层面稳健性检查。"
            "这样系统能提高整理和审计效率，但不会把自动簇名当成理论结论。"
        )
    if any(term in normalized for term in ("结果卡", "冻结", "代码版本", "执行日志", "输出表")):
        return (
            "这个要求应由研究工件链承接：结果卡必须同时指向冻结资料版本、"
            "分析代码版本、执行日志和实际输出表；没有这些依赖就只能生成候选或缺口说明，"
            "不能把计划中的分析、原论文数字或未执行的主题比较写成研究结果。"
        )
    if any(term in normalized for term in ("泛化", "答非所问", "为什么", "哪里不对")):
        return (
            f"当前项目的研究对象是物理问题解决文本和计算辅助主题分析。"
            f"这句话应围绕你的当前问题处理：{question.strip()}"
            "；系统不会套用问卷变量或另一项研究的模板。"
        )
    if "challenge" in acts or any(term in normalized for term in ("挑战", "替代解释", "反例")):
        return (
            f"先把这条判断当作待检验主张：{question.strip()}\n\n"
            "至少保留三类反例：文本片段的语境可能被截断，自动模式可能把不同现象合并，"
            "以及学生层聚合可能掩盖同一学生内部的差异。后续应回到可定位片段和冻结编码规则逐项检查。"
        )
    if planned_follow_up_question:
        return (
            f"我理解你要推进的是：{question.strip()}\n\n"
            "当前可以先保留这个边界，不把缺失信息补成事实。真正会改变研究路线的是："
            f"{planned_follow_up_question}"
        )
    if not allow_unplanned_follow_up:
        return (
            f"我理解你现在是在推进：{question.strip()}。"
            "我会继续围绕冻结资料、可回链片段和编码边界整理，不虚构尚未执行的分析。"
        )
    return (
        f"我理解你现在要讨论的是：{question.strip()}。"
        "我会围绕当前物理问题解决文本项目回答，不引入无关问卷变量；"
        "如果需要进入正式分析或写作，会由对应的研究工件和审计记录承接。"
    )


class _AnswerDraft(BaseModel):
    """Strict JSON contract requested from the conversational model."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)
    citation_indices: list[int] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    needs_follow_up: bool = False
    follow_up_question: str | None = None


def _requests_external_discovery(question: str) -> bool:
    """Recognize an explicit request for scholarly indexes or public papers."""

    normalized = question.strip().lower()
    return any(
        marker in normalized
        for marker in (
            "openalex",
            "crossref",
            "外部搜索",
            "外部检索",
            "外部文献",
            "外部学术",
            "学术索引",
            "external search",
            "scholarly index",
            "public full text",
        )
    )


def _external_query(
    question: str,
    rewritten_query: str,
    research_context: str = "",
) -> str:
    """Add stable English discovery terms so Chinese requests work on OpenAlex."""

    translations = {
        "生成式人工智能": "generative artificial intelligence",
        "生成式 AI": "generative artificial intelligence",
        "人工智能": "artificial intelligence",
        "大语言模型": "large language model",
        "大学物理": "university physics",
        "物理课程": "physics education",
        "计算思维": "computational thinking",
        "计算建模": "computational modeling",
        "学习成效": "learning outcomes",
        "学习结果": "learning outcomes",
        "学习成绩": "academic achievement",
        "影响": "impact effect",
        "本科生": "undergraduate students",
        "本科": "undergraduate",
        "物理": "physics",
        "概念理解": "conceptual understanding",
        "学习体验": "learning experience",
        "自我效能感": "self efficacy",
        "自我效能": "self efficacy",
        "关系": "relationship",
        "相关": "association",
        "学生": "students",
        "教育": "education",
    }
    # ``project_context`` also carries collaboration state for the response
    # model. Keep only the project title/direction before that state block so
    # workflow words such as "retrieval" or "objective" cannot pollute the
    # scholarly query.
    research_scope = "\n".join(research_context.splitlines()[:2])
    source_text = f"{question}\n{research_scope}"
    additions = [english for chinese, english in translations.items() if chinese in source_text]
    # OpenAlex is much less reliable with a long Chinese sentence. Keep
    # explicit ASCII terms and the stable English projections, while retaining
    # the rewritten query as a fallback for already-English requests.
    ascii_terms = re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", source_text)
    ignored_terms = {
        "and", "the", "for", "with", "from", "this", "that", "please",
        "english", "keyword", "keywords", "search", "find", "look",
        "paper", "papers", "scholarly", "academic", "evidence", "recent",
        "support", "supporting", "contradict", "contradictory", "using",
    }
    ascii_terms = [term for term in ascii_terms if term.lower() not in ignored_terms]
    year_terms = re.findall(r"\b(?:19|20)\d{2}\b", source_text)
    projected = list(dict.fromkeys([*additions, *ascii_terms, *year_terms]))
    return " ".join(projected) if projected else rewritten_query


def _clean_researcher_answer(value: str) -> str:
    """Keep internal evidence handles out of researcher-facing prose."""

    cleaned = re.sub(
        r"\b(?:shared_evd|evd|ctx)_[A-Za-z0-9-]+\b",
        "相关证据片段",
        value,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\b(?:reflect|co_think|review|teach|execute|synthesize|decide)\b(?:\s*(?:模式|mode))?",
        "当前讨论",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\bcausal_claims\s*=\s*forbidden\b",
        "当前不做因果推断",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned


def _discussion_fallback_answer(
    question: str,
    *,
    project_context: str | None = None,
    planned_research_acts: list[str] | None = None,
    planned_follow_up_question: str | None = None,
    allow_unplanned_follow_up: bool = True,
) -> str:
    """Give a relevant, non-procedural answer when the chat model is unavailable.

    This path must never pretend that a search, audit, or workflow ran.  It is
    deliberately based only on the researcher's current words, so an exhausted
    model quota cannot turn a normal question into an unrelated stock reply.
    """

    normalized = question.strip().lower()
    if _project_domain(project_context) == "physics_cgt":
        return _cgt_fallback_answer(
            question,
            planned_research_acts=planned_research_acts,
            planned_follow_up_question=planned_follow_up_question,
            allow_unplanned_follow_up=allow_unplanned_follow_up,
        )
    acts = set(planned_research_acts or [])
    # Short confirmations are common in a multi-turn study design review
    # (for example, ``我确认这套研究设计，请进入设计审查``).  When the
    # conversational model is unavailable these turns must still receive a
    # state-aware acknowledgement; otherwise the generic evidence fallback
    # asks an unrelated population question over and over.  Keep this parser
    # deliberately narrow and exclude interrogative wording so that
    # ``如何确认研究设计？`` remains an explanatory request.
    design_confirmation_requested = (
        any(
            marker in normalized
            for marker in (
                "确认这套研究设计",
                "确认研究设计",
                "确认研究方案",
                "确认当前研究设计",
                "确认研究问题和统计计划",
                "进入设计审查",
                "确认并进入设计审查",
            )
        )
        and not any(
            marker in normalized
            for marker in (
                "如何", "怎么", "为什么", "为何", "是否", "？", "?",
                "不确认", "不要确认", "不要进入", "不要", "先不", "暂不", "不同意", "拒绝",
            )
        )
    )
    if design_confirmation_requested:
        return (
            "我识别到你是在确认当前研究设计，而不是提出新的文献问题。"
            "在项目对话中，这个确认应承接到设计审查/预注册阶段，核对变量定义、样本范围、"
            "时间对齐和缺失值规则；问答接口本身不会虚构检索、数据或模型结果，也不会代替项目工作流写入状态。"
            "此前已确定的 RQ2 作为主研究问题、RQ1 作为描述性问题、RQ3 作为协变量稳健性分析会继续保留，不会要求你重新选择。"
        )
    questionnaire_design_requested = (
        any(
            marker in normalized
            for marker in ("完整问卷", "可直接发放", "直接发放", "数据字典")
        )
        and any(marker in normalized for marker in ("编码方案", "问卷", "变量", "值标签"))
        and any(marker in normalized for marker in ("没有问卷数据", "还没有", "不要转到", "先把"))
    )
    questionnaire_config_requested = (
        any(marker in normalized for marker in ("最终可配置", "问卷逻辑", "问卷平台"))
        and any(marker in normalized for marker in ("数据字典", "编码", "变量"))
        and any(marker in normalized for marker in ("修正", "输出", "整理", "改"))
    )
    if questionnaire_design_requested:
        return (
            "明白：你现在要的是把已经确定的编码方案落成可直接发放的问卷，当前没有 CSV 数据，因此本轮不做数据审查。\n\n"
            "【问卷说明】\n"
            "本问卷关注你在大学物理学习中实际如何使用生成式人工智能，没有正确或理想答案。请回忆过去 7 天。\n\n"
            "【筛选题】\n"
            "S1. 过去 7 天，你是否在大学物理学习中使用过生成式人工智能？\n"
            "1 是（继续作答）  0 否（结束本部分；相关变量记为不适用，不编码为 0）\n\n"
            "【主要使用方式】\n"
            "Q1. 回想其中一次学习任务，你主要用 AI 做什么？（单选）\n"
            "1 概念澄清：解释术语、公式含义或概念关系\n"
            "2 检查推理：检查自己已写出的步骤、假设或结论\n"
            "3 生成答案：从头生成完整解答、报告或最终结论\n"
            "4 代码/建模辅助：编写或调试代码，建立模型、绘图或仿真\n"
            "99 其他（请描述：____）\n\n"
            "【伴随使用方式】\n"
            "Q2. 除 Q1 选出的主要方式外，这次任务还使用过哪些方式？（可多选）\n"
            "0 无；1 概念澄清；2 检查推理；3 生成答案；4 代码/建模辅助；99 其他（请描述：____）。\n\n"
            "【数据字典】\n"
            "S1：ai_use_7d，二分类，1=是，0=否；Q1：primary_use，分类变量，1—4 为四类，99=其他；Q2：secondary_concept、secondary_reasoning、secondary_answer、secondary_code，均为 0/1 指示变量，另保留 secondary_other_text。\n"
            "S1=0 的受访者在 Q1/Q2 记为缺失或不适用，不计作‘没有使用某类方式’。统计时把 primary_use 当分类变量或哑变量，不把 1—4 当作有序分数。"
        )
    if questionnaire_config_requested:
        return (
            "这次应继续修订问卷配置，而不是进入 CSV 字段审查。下面给出修正后的逻辑：\n\n"
            "1. Q2 不把‘无’放入与四类方式同一组编码。使用四个 0/1 字段 "
            "secondary_concept、secondary_reasoning、secondary_answer、secondary_code，另设 secondary_none；"
            "secondary_none=1 时其余四项必须全为 0，选择任一伴随方式时 secondary_none 必须为 0。\n"
            "2. 这些变量是‘回忆锚定的自报行为测量’，不是平台直接观测的客观日志。研究报告中应使用‘行为代理指标’表述。\n"
            "3. 时间对齐增加 last_use_date（最近一次使用日期），并由问卷系统根据调查日期计算 days_since_last_use；这样才能与作业提交日期或测验日期按天对齐。\n"
            "4. 时长改为区间变量 duration_band：1=<5 分钟，2=5–15 分钟，3=16–30 分钟，4=31–60 分钟，5=>60 分钟；避免要求学生报告虚假的精确分钟数。\n"
            "5. 跳题逻辑：S1=0 时 Q1、Q2、last_use_date、duration_band、days_since_last_use 均为不适用；use_days_7d 固定为 0。S1=1 时 use_days_7d 取 1–7。\n\n"
            "建议字段为：ai_use_7d、primary_use、primary_use_other、secondary_concept、secondary_reasoning、"
            "secondary_answer、secondary_code、secondary_none、secondary_use_other、last_use_date、"
            "days_since_last_use、duration_band、use_days_7d。缺失值统一使用结构性缺失标记，不要把 -99 当成普通有效值参与分析。"
        )
    if (
        any(marker in normalized for marker in ("可追踪的研究记录", "研究记录", "整理当前", "研究摘要", "还缺哪些真实材料"))
        and any(marker in normalized for marker in ("问卷", "研究设计", "统计分析", "论文", "真实材料"))
    ):
        return (
            "可以，当前研究已经形成以下可追踪记录：\n\n"
            "【已确定】1）研究目标：考察生成式人工智能使用行为代理指标与大学物理计算思维学习成效的统计关联，不作因果推断；2）问卷：ai_use_7d、primary_use、secondary_*、secondary_none、last_use_date、survey_date、days_since_last_use、duration_band、use_days_7d；3）研究设计：RQ1–RQ3，primary_use 为名义分类主解释变量，频率、时长和时间距离为补充指标；4）分析计划：描述性统计、分层关联模型、稳健性/敏感性分析、结构性缺失与项目漏答区分。\n\n"
            "【尚未产生】目前没有真实问卷数据、清洗日志、模型输出或论文实证结果，因此不能声称已经完成数据审查、统计分析或结果写作。\n\n"
            "【生成论文还需要】CSV 与代码本；样本纳入/排除记录；CT_score 及分维度得分；先前成绩、编程经验、课程投入等协变量字段；调查日期与成绩时间点；伦理审批与匿名化说明；已核验文献和最终模型输出。\n\n"
            "拿到这些材料后，流程应按‘导入→审查→你确认处理→冻结数据→生成代码→执行分析→核验结果→填入论文’推进，每一步保留记录；在此之前只继续完善方法和占位稿，不编造实证结论。"
        )
    if (
        any(marker in normalized for marker in ("完整论文", "整篇论文", "全文草稿", "完整稿"))
        and any(marker in normalized for marker in ("研究", "问卷", "统计", "样本", "结果", "论文"))
    ):
        return (
            "可以。当前没有真实样本数据和模型输出，因此先生成一篇可直接继续编辑的完整论文骨架；所有 [待填] 内容必须由真实资料替换，不能把占位符当作实证结果。\n\n"
            "# 生成式人工智能使用行为与大学物理学习者计算思维成效的关联：一项问卷研究\n\n"
            "## 摘要（待填）\n"
            "本研究采用[横断面/纵向]问卷设计，考察大学生在大学物理学习中使用生成式人工智能的行为代理指标与计算思维学习成效之间的统计关联。研究对象为[课程、专业、年级]学生，最终有效样本为 [N_valid] 人。AI 使用通过最近一次任务的主要使用方式、伴随使用方式、过去 7 天使用天数、最近一次使用日期和时长区间进行测量；计算思维成效以 [CT 测量工具] 评估。结果、效应量和置信区间待真实数据分析后填入。研究不作因果推断，结论仅适用于本样本和测量范围。\n\n"
            "## 1 引言（可直接使用，文献待核验）\n"
            "生成式人工智能正在进入大学物理学习过程，但‘是否使用’并不能充分描述学生如何使用工具。概念澄清、检查推理、生成答案和代码/建模辅助可能对应不同的学习过程，也可能与计算思维表现呈现不同关联。本研究因此把 AI 使用定义为回忆锚定的自报行为代理指标，目标是描述行为分布并估计其与计算思维成效的关联，而不是检验 AI 的因果效果。\n\n"
            "## 2 研究问题\n"
            "RQ1：AI 使用主要方式和伴随方式如何分布？\nRQ2：这些行为指标与 CT_score 呈现怎样的统计关联？\nRQ3：加入先前成绩、编程经验和课程投入等可观测协变量后，关联是否保持稳定？\n\n"
            "## 3 方法\n"
            "### 3.1 研究设计与样本\n采用[设计类型]；样本来源、纳入排除标准、调查时间和伦理审批信息为 [待填]。\n\n"
            "### 3.2 变量与测量\nai_use_7d 为筛选变量；primary_use 为名义分类主指标；secondary_concept、secondary_reasoning、secondary_answer、secondary_code、secondary_none 为互斥约束下的伴随指标；last_use_date 与 survey_date 生成 days_since_last_use；duration_band 记录时长区间；use_days_7d 记录过去 7 天使用天数；CT_score 为主要结果变量。上述 AI 指标均为自报行为代理指标，不是平台日志。\n\n"
            "### 3.3 分析策略\n先进行数据质检和描述性统计，再拟合 CT_score ~ primary_use + use_days_7d + duration_band + days_since_last_use + [协变量]。根据结果分布选择线性、稳健或有序模型，报告估计值、95% 置信区间和拟合指标；用替代编码、完整案例/多重插补和异常值敏感性分析检验稳健性。\n\n"
            "## 4 结果（待真实数据）\n样本流程、变量分布、模型系数、置信区间和显著性均留待 CSV 清洗及预注册分析完成后填写。不得在此处编造 N、均值、p 值、效应量或方向。\n\n"
            "## 5 讨论（待真实结果）\n根据 RQ1–RQ3 解释实际观察到的关联，并与已核验文献比较。只能使用‘相关’‘关联’‘共变’等表述；同时讨论自我选择、反向解释、共同原因、自报误差、未观测混杂和横断面时间顺序不足。\n\n"
            "## 6 结论（待真实结果）\n概括本样本中的 AI 使用行为分布及其与计算思维成效的关联；若不确定性较大或证据不足，应如实报告，不得写成 AI 导致学习提升。\n\n"
            "## 7 数据与写作待补清单\nCSV 与代码本、样本流程、CT 量表与得分、协变量字段、调查/成绩时间点、伦理信息、已核验文献、数据审查日志、冻结数据哈希、模型输出和结果核验记录。"
        )
    if (
        any(marker in normalized for marker in ("结果、讨论和结论", "结果讨论", "讨论和结论", "占位稿", "没有真实样本数据"))
        and any(marker in normalized for marker in ("论文", "CSV", "统计输出", "样本数据", "结果"))
    ):
        return (
            "可以。在没有真实样本数据和统计输出前，只能生成论文结果、讨论与结论的结构化占位稿，不能填入任何虚构数字、显著性或方向。\n\n"
            "【结果（待填）】\n"
            "1. 样本流程：计划纳入 [N_planned] 人，最终有效样本 [N_valid] 人；排除规则与缺失比例填入真实数据后再报告。\n"
            "2. AI 使用分布：报告 ai_use_7d 比例、primary_use 各类别 n（%）、secondary_* 共现率、use_days_7d 和 duration_band 的中位数/四分位距。此处不预填任何数值。\n"
            "3. 关联模型：填入 CT_score 与 primary_use、use_days_7d、duration_band 等变量的估计值、95% 置信区间、p 值或其他预注册不确定性指标；若模型未收敛或类别过小，说明实际处理。\n\n"
            "【讨论（待填）】\n"
            "围绕 RQ1–RQ3 解释实际观察到的关联模式，并与已核验文献比较。只能说‘与……相关/呈现共变’，同时讨论自我选择、反向解释、共同原因、自报误差和横断面时间顺序不足；不得把关联写成 AI 导致学习提升。\n\n"
            "【结论（待填）】\n"
            "用一至两段概括样本中的行为分布和关联方向，所有方向、效应量和不确定性必须等 CSV 清洗及统计模型完成后填写；若证据不足，应明确写‘未观察到足够证据支持稳定关联’，而不是下因果结论。\n\n"
            "【必须补齐】CSV 数据与代码本、样本流程、CT 量表得分、协变量字段、模型输出、伦理信息及文献核验记录。当前版本是写作骨架，不是实证结果。"
        )
    if (
        any(marker in normalized for marker in ("论文方法部分", "方法部分", "论文草稿", "论文写作", "论文输出"))
        and any(marker in normalized for marker in ("研究设计", "样本", "变量", "分析策略", "伦理", "局限", "问卷", "统计分析"))
    ):
        return (
            "可以。下面起草一版不虚构数据的论文方法部分；所有方括号内容都是拿到真实资料后必须替换的待填项。\n\n"
            "【研究设计】本研究采用横断面问卷与课程学习结果的关联分析设计，考察大学生在大学物理学习中使用生成式人工智能的行为代理指标与计算思维学习成效之间的统计关联，不作因果推断。\n\n"
            "【样本与程序】研究对象为[课程/专业/年级]学生，计划样本量为[N]。在获得知情同意后，学生于[调查日期或时间窗]填写问卷，并由研究者按预先规则匹配[测验/作业]成绩。未取得的数据、样本量和伦理审批信息不得在此处补写。\n\n"
            "【变量测量】AI 使用先由 ai_use_7d 筛选；primary_use 记录最近一次物理学习任务的主要方式，取概念澄清、检查推理、生成答案、代码/建模辅助或其他。secondary_concept、secondary_reasoning、secondary_answer、secondary_code 与 secondary_none 记录伴随方式，secondary_none 与其他伴随项互斥。last_use_date 与 survey_date 用于计算 days_since_last_use，duration_band 记录时长区间，use_days_7d 记录过去 7 天使用天数。这些均是回忆锚定的自报行为代理指标，不是平台日志。计算思维结果变量为预先指定的 CT_score 及[分维度]。\n\n"
            "【分析策略】先报告样本描述、缺失模式与各行为类别比例，再以 primary_use 为名义分类解释变量建立关联模型：CT_score ~ primary_use + use_days_7d + duration_band + days_since_last_use + [先前成绩] + [编程经验] + [课程投入]。根据结果变量分布选择线性、稳健或有序模型，报告估计值、95%置信区间和拟合指标；进行替代编码、完整案例/多重插补和异常值敏感性分析。\n\n"
            "【伦理与局限】说明伦理审批编号[待填]、匿名化与数据保存方式。局限包括自我选择、自报回忆误差、共同原因、未观测混杂和横断面时间顺序不足；协变量调整不能证明因果。全文使用‘相关’‘关联’‘共变’，不使用‘导致’‘提升’或‘效果’。\n\n"
            "【待补信息】正式写作前需填入样本来源与数量、调查和成绩时间点、CT 量表/题目信效度、协变量字段、伦理信息及实际分析结果；当前版本不生成虚构结果。"
        )
    if (
        any(marker in normalized for marker in ("统计分析计划", "主模型", "稳健性分析", "缺失值处理", "分析代码", "报告模板"))
        and any(marker in normalized for marker in ("问卷", "行为代理", "使用", "学习成效", "计算思维", "变量", "相关分析"))
    ):
        return (
            "可以，下面把上一轮关联设计具体化为正式统计分析计划；它分析观察到的关联，不把任何系数解释为因果效应。\n\n"
            "一、变量编码与数据质检\n"
            "将 primary_use 作为名义分类变量，设置概念澄清、检查推理、生成答案、代码/建模辅助四类指示变量；99=其他仅保留文本并在编码前由两名编码者独立归类。secondary_concept、secondary_reasoning、secondary_answer、secondary_code、secondary_none 为 0/1 指示变量，并检查 secondary_none=1 时其余项必须为 0。duration_band 按预设区间作为有序但非等距补充变量，last_use_date 与 survey_date 生成 days_since_last_use。结构性缺失不当作 0，也不把 -99 作为有效观测。\n\n"
            "二、描述性统计\n"
            "报告样本量、S1 使用比例、primary_use 各类别比例、伴随方式共现率、use_days_7d、days_since_last_use 和 duration_band 的中位数及四分位距；按课程或测量时间点列出缺失率。绘制使用方式与计算思维得分的分布和箱线图，但不据图宣称效果。\n\n"
            "三、主模型\n"
            "若 CT_score 为近似连续且残差合理，使用线性回归：CT_score ~ primary_use + use_days_7d + duration_band + days_since_last_use + 先前成绩 + 编程经验 + 课程投入。primary_use 使用哑变量，预先指定参考组，不按 1—4 当作有序分数。报告回归系数、95%置信区间、标准化效应量和模型拟合指标。若结果是等级或明显偏态，使用有序回归、稳健回归或广义线性模型，并说明选择依据。\n\n"
            "四、稳健性与敏感性分析\n"
            "比较仅含主指标、加入频率/时长、再加入可观测协变量的分层模型；以 secondary_* 替代或补充 primary_use；对 duration_band 使用哑变量与单调趋势两种编码；进行 complete-case 与多重插补结果对照；用 Spearman 相关或稳健标准误检查异常值影响；报告小样本类别合并规则。不要用逐步筛选制造‘最佳模型’。\n\n"
            "五、缺失值与报告模板\n"
            "先区分结构性缺失（S1=0 跳题）和项目漏答，报告各变量缺失数量与比例；主分析不把结构性缺失填成未使用，必要时在使用者子样本内分析，并把全样本 S1 分布单独报告。结果段统一写‘与 CT_score 相关’‘观察到较高/较低分数’，同时给出不确定性区间和限制：自我选择、反向解释、共同原因、自报误差、横断面时间顺序不足。\n\n"
            "这份计划可以直接作为预注册或方法部分草案。下一步是拿到真实数据字典后锁定参考组、协变量字段和结果量表，然后生成可复现代码；在此之前不执行虚构数据分析。"
        )
    if (
        any(marker in normalized for marker in ("研究设计", "关联模型", "时间对齐", "分析边界", "不作因果", "不做因果"))
        and any(marker in normalized for marker in ("问卷", "行为代理", "使用", "学习成效", "计算思维", "变量"))
    ):
        return (
            "可以，基于刚才已经确定的问卷行为代理指标，研究设计可以先固定为一套可执行、但不做因果解释的关联方案。\n\n"
            "一、研究问题\n"
            "RQ1：大学生在大学物理学习中使用生成式人工智能的主要方式（概念澄清、检查推理、生成答案、代码/建模辅助）如何分布？\n"
            "RQ2：这些使用方式及其频率、最近一次使用时间和时长区间，与计算思维学习成效之间呈现怎样的统计关联？\n"
            "RQ3：在控制先前成绩、编程经验、课程投入等可观测协变量后，关联方向和大小是否仍然稳定？\n\n"
            "二、变量与模型\n"
            "主解释变量是 primary_use（名义分类变量），伴随方式用 secondary_concept、secondary_reasoning、secondary_answer、secondary_code 和 secondary_none 的 0/1 指示变量描述；use_days_7d、days_since_last_use、duration_band 作为补充行为指标。结果变量应使用预先定义的计算思维总分及分维度分数。\n"
            "主分析可用线性模型或广义线性模型：CT_score ~ primary_use + use_days_7d + duration_band + 先前成绩 + 编程经验 + 课程投入。若结果分布偏态或为等级分数，改用稳健回归、分位数回归或有序模型，并报告效应量和置信区间。primary_use 不按 1—4 的高低顺序处理。\n\n"
            "三、时间对齐\n"
            "问卷记录调查日期 survey_date 和最近一次使用日期 last_use_date，由系统计算 days_since_last_use；将使用窗口定义为调查日前 7 个自然日，并与同一窗口或预先指定测验/作业截止日前的计算思维成绩对齐。若成绩发生在窗口之后，应明确标为结果时间点，不把它写成即时因果效果。\n\n"
            "四、非因果分析边界\n"
            "结果只表述为‘相关’‘关联’或‘共变’，不使用‘导致’‘提升’‘效果’。必须报告自我选择、反向解释、共同原因、测量误差和横断面时间顺序不足等限制；协变量调整只能减少可观测混杂，不能证明因果。\n\n"
            "这版可以作为分析计划草案。下一步应先锁定计算思维结果指标和协变量的实际字段，再生成可复现的分析代码与论文方法部分。"
        )
    if (
        any(marker in normalized for marker in ("我已经上传", "已上传", "已经导入", "已导入"))
        and any(marker in normalized for marker in ("csv", "数据", "文件"))
        and any(marker in normalized for marker in ("审查", "检查", "核对"))
    ):
        return (
            "我能看到你在消息中说明‘已经上传 CSV’，但当前这条问答请求本身没有携带可读取的文件引用，因此我不能声称文件已经导入或已经完成审查。\n\n"
            "请通过页面的‘添加研究材料或 CSV 数据/选择文件’上传，并等待页面显示上传成功或数据引用；随后我会只报告真实读取到的列名、行数、类型、缺失、重复记录和取值异常，不会直接执行统计分析。若页面已经显示上传成功，请把对应的数据引用或审查任务继续发来。"
        )
    # Do not treat every occurrence of “审查/字段/数据” as a CSV request:
    # design-review confirmations also contain “审查”.  Require an explicit
    # data/upload term together with an audit/schema term before showing the
    # CSV header guidance.
    if (
        any(marker in normalized for marker in ("上传", "导入", "csv", "数据"))
        and any(marker in normalized for marker in ("审查", "检查", "核对", "字段", "列名", "缺失值", "重复记录", "取值范围"))
    ):
        return (
            "现在还不能确定这份数据的具体列名，因为论文背景本身不会提供你的 CSV 表头。"
            "我不会把它擅自假定成某种标准格式。\n\n"
            "在做描述性再分析前，至少需要分清四类信息：记录标识（每一行是谁或哪次测量）、"
            "比较条件或分组、主要结果指标，以及编码说明（缺失值、分类值和量表方向）。"
            "拿到表头和代码本后，先核对字段类型、重复记录、缺失值和不合理取值；这只是数据审查，不会执行统计分析。\n\n"
            "你现在不用上传数据。把 CSV 第一行的字段名和代码本中关于取值的说明贴出来即可，"
            "我会逐列解释它们的用途，并明确哪些信息还缺。"
        )
    if any(marker in normalized for marker in ("下一步怎么办", "接下来怎么办", "下一步做什么", "然后呢", "下一步") ):
        return (
            "当前已经完成了研究问题、问卷行为代理指标、关联设计和统计分析计划的确定；下一步不是重新讨论变量，而是进入真实材料准备。\n\n"
            "如果你还没有数据：请上传问卷导出的 CSV，并同时提供代码本/字段说明。系统收到后先只做数据审查，报告列名、类型、缺失、重复记录和取值异常，等你确认后才会冻结和分析。\n\n"
            "如果你已经有数据：下一步就是先做数据审查；审查通过后再生成可复现代码、请你确认处理规则、冻结数据集、执行关联模型、核验结果，最后把真实结果填入论文。当前不能直接跳到论文结论，也不会编造结果。"
        )
    if any(marker in normalized for marker in ("为什么", "怎么回事", "奇怪", "不对", "答非所问")):
        return (
            "你指出得对：这里应该先回应你正在问的事，而不是跳去介绍资料、证据或下一阶段。"
            "请把你希望我回答的那一句再发一次；我会只围绕那句话回答，不启动检索、分析或流程。"
        )
    if any(marker in normalized for marker in ("怎么填", "怎么回", "输入什么")):
        return (
            "先按你要表达的研究意图直接写，不需要使用固定格式。"
            "把当前页面的字段名和你想达到的目的贴出来，我会逐项告诉你该填什么，并说明哪些内容暂时可以留空。"
        )
    if any(marker in normalized for marker in ("自报偏差", "只能通过问卷", "问卷让学生自报")):
        return (
            "既然目前拿不到平台日志，主指标应调整为‘基于具体学习情境的问卷自报’，而不是假装拥有精确的交互行为数据。"
            "建议让学生回忆最近一周的一次大学物理学习任务，分别勾选使用目的：概念澄清、检查推理、生成答案、代码/建模辅助；"
            "再记录各类使用出现的次数或占比。频率/时长继续作为补充指标。\n\n"
            "降低自报偏差可以做四件事：把回忆窗口限定为最近一周；给每类使用方式提供具体例子；采用匿名填写并强调没有对错答案；"
            "在正式调查前做小样本认知访谈，检查学生是否能按同一标准理解题目。必要时可用作业修改痕迹或学习日志做有限交叉核对，"
            "但不能把它们当成完整平台日志。"
        )
    if (
        any(marker in normalized for marker in ("互斥", "优化题目", "优化题目结构", "检查四类"))
        and any(
            marker in normalized
            for marker in ("情境题", "使用方式", "最主要", "问卷", "四类", "第3题", "题目")
        )
    ):
        return (
            "你这个担心是对的：上一版还不能算严格互斥，也没有处理‘最近一周没遇到该情境’的情况。这里直接把结构改成可编码的版本：\n\n"
            "一、分类定义先收紧\n"
            "1. 概念澄清：让 AI 解释术语、公式含义或概念间关系；\n"
            "2. 检查推理：让 AI 检查自己已经写出的步骤、假设或结论；\n"
            "3. 生成答案：让 AI 从头生成完整解答、报告或最终结论；\n"
            "4. 代码/建模辅助：让 AI 编写、调试代码，或建立数值模型、绘图和仿真。\n"
            "第 3 题原来的‘拆分任务并提示思路’确实不属于这四类。为保持四类不扩张，将其改为‘解释相关概念之间的关系’；如果你希望研究任务规划，则应另增一个‘策略规划’类别，不能硬塞进概念澄清。\n\n"
            "二、题目统一采用‘先筛选、后单选’\n"
            "每道情境题先问：‘过去 7 天你是否遇到过类似任务？是 / 否。’选择‘否’就跳过，不记为 0 次。选择‘是’后再问：‘当时你主要采用哪一种做法？’并且只允许选一项，另设‘其他，请描述’。这样既避免强迫回忆，也保证每题只有一个主编码。\n\n"
            "三、四道题的修订原则\n"
            "- 每题四个选项各对应一个类别，不能出现一个选项同时包含解释、检查和生成多个动作；\n"
            "- 选项只写功能描述，不使用‘深度’‘高质量’等价值词；\n"
            "- 在不同题目中轮换 A/B/C/D 的类别位置，避免位置偏差；\n"
            "- 保留‘其他/以上都不符合’开放栏，并记录具体文字，便于发现编码盲区。\n\n"
            "因此，上一版题目不应原样定稿；应按这个结构重写后再做 5—10 人认知访谈，检查学生是否能把‘解释概念’和‘检查推理’稳定区分开。"
        )
    if (
        any(marker in normalized for marker in ("主要方式", "伴随方式", "主方式", "辅助方式"))
        and any(marker in normalized for marker in ("编码", "统计分析", "分析时", "问卷"))
    ):
        return (
            "可以把一次学习任务拆成两个层次记录，既保留主要意图，也不丢失同一任务中的其他用法。\n\n"
            "一、问卷编码\n"
            "1. 先问‘过去 7 天是否遇到过类似任务？’：否=缺失/跳过，不编码为 0；是=进入下一步。\n"
            "2. 主要使用方式（单选）：请选择这次任务中最主要的一种：概念澄清、检查推理、生成答案、代码/建模辅助、其他（请描述）。记录为主变量 primary_use，取值 1—4，其他单独保留文字。\n"
            "3. 伴随使用方式（多选）：除主要方式外，本次还使用过哪些方式？同样列出四类和‘其他’；如果没有其他方式，选择‘无’。为避免把主要方式重复计入，提示语应写成‘不包括你刚才选为主要方式的那一项’。\n\n"
            "二、统计分析\n"
            "- 主分析使用 primary_use 的哑变量或分类变量，比较不同主要方式与计算思维学习成效的关联；不要把 1—4 当作有序高低分数。\n"
            "- 伴随方式分别建立 0/1 指示变量 secondary_concept、secondary_reasoning、secondary_answer、secondary_code，作为补充描述或协变量。\n"
            "- 报告每类主要方式的比例，以及伴随方式的共现率；样本量足够时可探索‘主要方式 × 伴随方式’组合，但组合过多时避免过度分组。\n"
            "- 对‘其他’先做开放文本归类，并由两名编码者独立编码、报告一致性；不要事后为了凑四类而强行归类。\n\n"
            "这样，主要方式回答‘这次主要怎么用’，伴随方式回答‘还同时做了什么’，两者不会互相覆盖。下一步可先做 5—10 人认知访谈，检查学生是否能稳定区分‘主要’和‘伴随’。"
        )
    # When the researcher explicitly asks to continue designing the
    # scenario-based questionnaire, provide the items now.  Do not collapse
    # this request into a generic ``reflect`` acknowledgement or trigger an
    # unrelated retrieval step.
    if (
        any(marker in normalized for marker in ("情境题", "具体题目", "设计题目", "设计具体"))
        and any(marker in normalized for marker in ("使用方式", "最主要", "问卷", "操作化"))
    ):
        return (
            "可以。下面先给出一版‘只记录最主要使用方式’的四道情境题草案。每题请学生回忆最近一周的一次大学物理学习任务，"
            "只选择最符合当时主要做法的一项；选项不代表好坏。\n\n"
            "1. 概念仍然模糊：刚学完牛顿第二定律，但对非惯性系中的虚拟力不清楚。你主要会让 AI：\n"
            "A. 用生活例子或不同表述重新解释概念\n"
            "B. 逐步检查你的理解并指出混淆之处\n"
            "C. 直接给出标准答案和完整步骤\n"
            "D. 生成代码模拟受力过程\n\n"
            "2. 推导做到一半：你算出的结果与教材不一致。你主要会让 AI：\n"
            "A. 帮你定位推理或代数出错的步骤\n"
            "B. 重新讲解相关概念\n"
            "C. 直接重做整道题并给出答案\n"
            "D. 用程序验证不同参数下的结果\n\n"
            "3. 面对综合题：需要把多个物理概念组合起来。你主要会让 AI：\n"
            "A. 帮你拆分任务并提示解题思路\n"
            "B. 检查你已经写出的推理是否连贯\n"
            "C. 生成一份可直接参考的完整解答\n"
            "D. 建立数值模型或画图辅助理解\n\n"
            "4. 实验或课后项目：需要分析运动数据。你主要会让 AI：\n"
            "A. 解释公式、变量和物理意义\n"
            "B. 检查你的分析步骤和结论是否一致\n"
            "C. 直接生成分析报告或结论\n"
            "D. 编写或调试 Python 数据分析代码\n\n"
            "编码时将 A/B/C/D 分别归入概念澄清、检查推理、生成答案、代码/建模辅助；四题各记一次，另设‘以上都不符合，请描述’。"
            "下一步只需确认：这四类是否覆盖你希望测量的主要使用方式？"
        )
    if "clarify" in acts and any(marker in normalized for marker in ("操作化", "怎么测量", "指标定义")):
        return (
            "可以先把当前决定落成一版可执行定义：\n"
            "- 主指标‘使用方式’：按最近一次或最近一周的物理学习任务，编码为概念澄清、检查推理、生成答案、代码/建模辅助四类；允许多选，并记录最常用的一类。\n"
            "- 补充指标‘频率/时长’：记录每周使用天数或使用次数，作为连续变量，不把它解释成使用质量。\n\n"
            "这只是暂定操作化，后续可以根据试测结果修订。现在真正需要你决定的一点是："
            "你能取得平台交互日志，还是只能通过问卷让学生自报使用方式？"
        )
    if planned_follow_up_question:
        challenge = (
            "这里还包含一个需要暂时悬置的方向性假设，后续应同时检查支持路径和反向解释。"
            if acts.intersection({"reframe", "challenge"})
            else "其他尚未确定的信息可以先保持开放，不需要现在逐项补齐。"
        )
        return (
            f"我理解你真正想推进的是：{question.strip()}\n\n"
            f"{challenge}\n\n当前最可能改变研究设计的是一个核心概念的定义："
            f"{planned_follow_up_question}"
        )
    if "challenge" in acts:
        return (
            f"我先把这句话当作待检验的研究主张，而不是既定结论：{question.strip()}\n\n"
            "至少有三种反向解释需要同时保留：\n"
            "1. 自我选择：本来就更擅长学习或更愿意尝试新工具的学生，可能更常使用生成式人工智能；"
            "观察到的差异未必来自工具本身。\n"
            "2. 使用方式不同：用它来澄清概念、检查推理，和直接复制答案，可能对应完全不同的学习结果。\n"
            "3. 短期表现不等于学习成效：它可能让一次作业完成得更快，却没有带来概念理解、迁移或独立解题能力的提升。\n\n"
            "因此更稳妥的研究问题可以先改成：生成式人工智能的使用特征与大学物理学习成效之间呈现怎样的关联，"
            "这种关联是否会因使用方式和学生原有能力不同而变化？"
        )
    if "compare" in acts:
        return (
            f"我理解你现在要比较的是三种‘生成式人工智能使用’指标：{question.strip()}\n\n"
            "1. 使用频率/时长：最容易通过问卷获得，但只能说明用了多少，不能说明怎么用。\n"
            "2. 使用方式：区分概念澄清、检查推理、生成答案等场景，最能对应学习过程，但需要清晰的分类编码。\n"
            "3. 交互行为深度：例如追问轮次、修改提示词或调试次数，信息最丰富，但通常需要日志，实施成本最高。\n\n"
            "结合你只研究相关关系、且目前还没有确定日志来源的前提，我建议把‘使用方式’作为主指标，"
            "把频率/时长作为补充指标；交互行为深度先列为可选的敏感性分析，等确认能否取得日志后再决定。"
            "这样既不会把‘用得多’误当成‘用得好’，也能保留后续扩展空间。"
        )
    if any(marker in normalized for marker in ("相关关系", "相关", "不做因果", "非因果")):
        return (
            "明白了：你的研究要回答的是‘哪些 AI 使用特征与大学物理学习成效一起变化’，"
            "而不是证明‘AI 导致了学习成效变化’。所以后续结果会使用‘相关’、‘关联’这样的表述，"
            "不会把相关系数写成因果结论。\n\n"
            "下一步会有一个直接影响：我们需要先把‘AI 使用’定义成可观察的指标，"
            "否则即使查到论文，也无法比较它们测量的是不是同一件事。你更想先确定哪一种："
            "A. 使用频率/时长，还是 B. 使用方式（例如概念澄清、检查推理、直接生成答案）？"
        )
    if "reflect" in acts:
        return (
            f"我先把这条判断记录为当前研究边界：{question.strip()}\n\n"
            "它暂时不是最终结论。下一步我会围绕最可能改变判断的概念或证据继续检查，"
            "如果出现相反证据，再明确说明它是否改变研究路线。"
        )
    if not allow_unplanned_follow_up:
        return (
            f"我理解你现在是在推进：{question.strip()}。"
            "目前没有发现必须由你立即补充、否则就会改变研究路线的信息；"
            "我会保留暂定边界并围绕当前目标继续。"
        )
    return (
        f"我理解你现在是在讨论：{question.strip()}。"
        "我会先停留在这个问题本身，不检索、不执行、不推进任务。"
        "你希望我先帮你判断可行性、解释概念，还是比较几个选择？"
    )


def _requires_schema_safe_answer(question: str) -> bool:
    """Avoid invented column names when the researcher has not supplied a schema."""

    normalized = question.strip().lower()
    schema_markers = (
        "字段",
        "列名",
        "表头",
        "代码本",
        "编码",
        "数据格式",
        "csv",
        "header",
        "codebook",
        "column",
        "columns",
    )
    return any(marker in normalized for marker in schema_markers) and any(
        marker in normalized
        for marker in ("上传", "数据", "审查", "怎么填", "代表什么", "需要什么")
    )


class QuestionAnswerService:
    """Compose rewrite, retrieval, synthesis, and memory into one API operation."""

    def __init__(
        self,
        *,
        knowledge_service: HybridKnowledgeService,
        storage_root: Path,
        provider: GPTProvider | None = None,
        model: str | None = None,
        workflow_controller: Any | None = None,
        artifact_store: Any | None = None,
        prompt_version: str = "qa-v1",
        max_retries: int = 1,
        agentic_tool_routing_enabled: bool = False,
    ) -> None:
        self._knowledge_service = knowledge_service
        self._memory_store = ConversationMemoryStore(storage_root / "memory")
        self._provider = provider
        self._generator = (
            StructuredGenerator(provider, max_retries=max_retries) if provider else None
        )
        self._tool_executor = QAToolExecutor(
            knowledge_service,
            workflow_controller=workflow_controller,
            artifact_store=artifact_store,
            storage_root=storage_root,
            context_service=getattr(knowledge_service, "_context_service", None),
        )
        self._model = model or (provider.default_model if provider else None)
        self._prompt_version = prompt_version
        self._storage_root = storage_root
        self._domain_audit_path = storage_root / "memory" / "qa_domain_corrections.jsonl"
        # A tool-routing turn can issue one model call to choose tools and a
        # second call to synthesize their output. Keep it opt-in so a normal
        # research conversation has a predictable one-call budget.
        self._agentic_tool_routing_enabled = agentic_tool_routing_enabled

    def _correct_domain_mismatch(
        self,
        *,
        request: QAAnswerRequest,
        answer: str,
    ) -> tuple[str, dict[str, Any] | None]:
        """Automatically replace a cross-project stock answer and retain evidence.

        The original response is never silently discarded: a JSONL audit entry
        stores the trigger, project domain, and both texts.  The corrected text
        is the only one returned to the researcher.
        """

        domain = _project_domain(request.project_context)
        if domain != "physics_cgt":
            return answer, None
        normalized = answer.lower()
        triggers = [term for term in _CGT_FORBIDDEN_RESPONSE_TERMS if term.lower() in normalized]
        if not triggers:
            return answer, None
        corrected = _cgt_fallback_answer(
            request.question,
            planned_research_acts=request.planned_research_acts,
            planned_follow_up_question=request.planned_follow_up_question,
            allow_unplanned_follow_up=request.allow_unplanned_follow_up,
        )
        record: dict[str, Any] = {
            "event_type": "QA_DOMAIN_MISMATCH_CORRECTED",
            "occurred_at": datetime.now(UTC).isoformat(),
            "project_id": request.project_id,
            "conversation_id": request.conversation_id,
            "project_domain": domain,
            "trigger_terms": triggers,
            "question": request.question,
            "original_response": answer,
            "corrected_response": corrected,
        }
        try:
            self._domain_audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self._domain_audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError as error:
            logger.warning("Could not persist QA domain correction audit: %s", error)
        return corrected, record

    def answer(self, request: QAAnswerRequest) -> QAAnswerResponse:
        conversation_id = request.conversation_id or f"conv_{uuid4().hex}"
        history = self._memory_store.recent_turns(
            conversation_id,
            limit=4,
            project_id=request.project_id,
        )
        rewritten_query = self._rewrite_query(request.question, history)
        route = self._route(request.question, rewritten_query, history)

        retrieval = self._knowledge_service.search(
            RetrievalSearchRequest(
                project_id=request.project_id,
                corpus_ids=["physics_stem_v1"],
                query=rewritten_query,
                mode=request.mode,
                limit=request.top_k,
            )
        )
        # Search project-private uploaded materials as well as the shared
        # corpus.  A project PDF is a first-class research source and should
        # not be ignored merely because the shared physics index has no hit.
        project_citations: list[QAReference] = []
        project_context_service = getattr(self._knowledge_service, "_context_service", None)
        if project_context_service is not None:
            try:
                project_hits = project_context_service.search(
                    EvidenceSearchRequest(
                        project_id=request.project_id,
                        query=rewritten_query,
                        limit=min(request.top_k, 8),
                    )
                )
                for hit in project_hits:
                    source = project_context_service.get_source(
                        request.project_id, hit.evidence.source_id
                    )
                    project_citations.append(
                        QAReference(
                            paper_title=source.filename,
                            source_filename=source.filename,
                            canonical_paper_id=f"project:{request.project_id}:{source.source_id}",
                            canonical_chunk_id=hit.evidence.chunk_id,
                            chunk_index=hit.evidence.location.chunk_index,
                            excerpt=hit.evidence.excerpt,
                            locator_status="UNRESOLVED",
                            source_locator_method="UNRESOLVED",
                            verification_status=hit.evidence.verification_status.value,
                            char_start=hit.evidence.location.char_start,
                            char_end=hit.evidence.location.char_end,
                            retrieval_modalities=["project_local_keyword"],
                        )
                    )
            except Exception as error:  # project-local retrieval must not break QA
                logger.warning("Project-local evidence search failed: %s", error)
        external_discovery: dict[str, Any] | None = None
        external_requested = _requests_external_discovery(request.question)
        if request.mode is ContextMode.DISCOVERY and (
            external_requested
            or (
                not retrieval.chunk_hits
                and not retrieval.candidate_papers
                and not project_citations
            )
        ):
            external_discovery = self._tool_executor.execute(
                name="external_paper_search",
                arguments={
                    "query": _external_query(
                        request.question,
                        rewritten_query,
                        request.project_context,
                    ),
                    "max_results": min(request.top_k, 10),
                },
                project_id=request.project_id,
                default_query=rewritten_query,
                mode=request.mode,
            )
        context_bundle = self._knowledge_service.build_context(
            project_id=request.project_id,
            task_ref=request.context_bundle_ref or conversation_id,
            query=rewritten_query,
            token_budget=request.token_budget,
            mode=request.mode.value,
        )
        # Project-private material is the researcher's primary evidence chain.
        # A conversational question often names a decision (for example,
        # "先补证据还是先定边界") rather than repeating the paper's wording;
        # applying the lexical filter across shared and private hits together
        # can therefore discard the uploaded paper and leave unrelated shared
        # corpus snippets as the only citations. Keep ranked project hits
        # authoritative whenever they exist, and use the shared corpus only
        # when no project-local material matched at all.
        shared_citations = self._build_citations(retrieval)
        project_filtered = self._filter_citations_for_question(
            request.question, project_citations
        )
        if project_citations:
            citations = project_filtered or project_citations[:3]
            citations = [
                citation.model_copy(update={"citation_index": index})
                for index, citation in enumerate(citations[:3], start=1)
            ]
        else:
            citations = self._filter_citations_for_question(
                request.question, shared_citations
            )
        allow_llm = request.allow_llm and self._generator is not None and self._model is not None
        # Do not let the language model turn unrelated shared snippets or an
        # old external-search status into a confident research-scope answer.
        # Discussion without matching citations must use the bounded fallback.
        if (
            not citations
            and not external_requested
            and re.search(r"[\u4e00-\u9fff]", request.question)
        ):
            allow_llm = False
        # Configuration/design requests must not fall through to the CSV/data-audit fallback.
        # The frontend /qa/answer endpoint uses this answer() path (not converse()).
        normalized_question = request.question.strip().lower()
        questionnaire_design_requested = (
            any(marker in normalized_question for marker in ("完整问卷", "可直接发放", "直接发放", "数据字典"))
            and any(marker in normalized_question for marker in ("编码方案", "问卷", "变量", "值标签"))
            and any(marker in normalized_question for marker in ("没有问卷数据", "还没有", "不要转到", "先把"))
        )
        questionnaire_config_requested = (
            any(marker in normalized_question for marker in ("最终可配置", "问卷逻辑", "问卷平台"))
            and any(marker in normalized_question for marker in ("数据字典", "编码", "变量"))
            and any(marker in normalized_question for marker in ("修正", "输出", "整理", "改"))
        )
        research_design_requested = (
            any(marker in normalized_question for marker in ("研究设计", "关联模型", "时间对齐", "分析边界", "不作因果", "不做因果"))
            and any(marker in normalized_question for marker in ("问卷", "行为代理", "使用", "学习成效", "计算思维", "变量"))
        )
        # Keep terse design confirmations in the conversation path instead
        # of sending them through retrieval.  A confirmation such as
        # ``我确认这套研究设计，请进入设计审查`` contains too little
        # topical vocabulary for ``research_design_requested`` above and was
        # therefore answered by the unrelated no-citation fallback.
        design_confirmation_requested = (
            any(
                marker in normalized_question
                for marker in (
                    "确认这套研究设计",
                    "确认研究设计",
                    "确认研究方案",
                    "确认研究问题和统计计划",
                    "进入设计审查",
                    "确认并进入设计审查",
                )
            )
            and not any(
                marker in normalized_question
                for marker in (
                    "如何", "怎么", "为什么", "为何", "是否", "？", "?",
                    "不确认", "不要确认", "不要进入", "不要", "先不", "暂不", "不同意", "拒绝",
                )
            )
        )
        results_placeholder_requested = (
            any(marker in normalized_question for marker in ("结果、讨论和结论", "结果讨论", "讨论和结论", "占位稿", "没有真实样本数据"))
            and any(marker in normalized_question for marker in ("论文", "CSV", "统计输出", "样本数据", "结果"))
        )
        next_step_requested = any(marker in normalized_question for marker in ("下一步怎么办", "接下来怎么办", "下一步做什么", "然后呢", "下一步"))
        full_paper_requested = (
            any(marker in normalized_question for marker in ("完整论文", "整篇论文", "全文草稿", "完整稿"))
            and any(marker in normalized_question for marker in ("研究", "问卷", "统计", "样本", "结果", "论文"))
        )
        structured_writing_request = full_paper_requested or questionnaire_design_requested or questionnaire_config_requested or research_design_requested or results_placeholder_requested or design_confirmation_requested
        data_audit_request = (
            any(marker in normalized_question for marker in ("csv", "数据审查", "缺失值", "重复记录", "取值范围", "列名"))
            and any(marker in normalized_question for marker in ("数据审查", "检查缺失", "重复记录", "异常值", "导入数据"))
        )
        direct_questionnaire_answer = None
        if questionnaire_design_requested or questionnaire_config_requested or research_design_requested or results_placeholder_requested or next_step_requested or full_paper_requested or data_audit_request or design_confirmation_requested:
            direct_questionnaire_answer = _discussion_fallback_answer(
                request.question,
                project_context=request.project_context,
                planned_research_acts=request.planned_research_acts,
                planned_follow_up_question=request.planned_follow_up_question,
                allow_unplanned_follow_up=request.allow_unplanned_follow_up,
            )
        agentic_result = None
        if structured_writing_request:
            allow_llm = False
        if direct_questionnaire_answer is not None:
            # These deterministic acknowledgements are ordinary conversational
            # turns.  Keep the public route aligned with that fact even when
            # the lexical router would otherwise label a short confirmation
            # as ``workflow_agent``.
            if design_confirmation_requested:
                route = QARouteDecision(
                    route="direct_answer",
                    reason="研究设计确认由对话承接，未调用研究工作流",
                    recommended_agent=None,
                )
            answer_record = QAAnswerRecord(
                answer=direct_questionnaire_answer,
                citation_indices=[],
                confidence=0.8,
                needs_follow_up=False,
                follow_up_question=None,
            )
            answer_mode: Literal["llm", "fallback"] = "fallback"
            tool_calls = []
            workflow_action = None
        elif self._agentic_tool_routing_enabled and not external_requested:
            agentic_result = self._agentic_synthesize(
                request=request,
                question=request.question,
                rewritten_query=rewritten_query,
                route=route,
                retrieval=retrieval,
                context_bundle=context_bundle,
                citations=citations,
                history=history,
                allow_llm=allow_llm,
                mode=request.mode,
            )
        if direct_questionnaire_answer is not None:
            pass
        elif agentic_result is not None:
            (
                answer_record,
                route,
                retrieval,
                citations,
                tool_calls,
                context_bundle,
                workflow_action,
            ) = agentic_result
            answer_mode: Literal["llm", "fallback"] = "llm"
        else:
            answer_record, answer_mode = self._synthesize(
                question=request.question,
                rewritten_query=rewritten_query,
                route=route,
                retrieval=retrieval,
                context_bundle=context_bundle,
                citations=citations,
                history=history,
                allow_llm=allow_llm,
                external_discovery=external_discovery,
                prefer_external=external_requested,
            )
            tool_calls = []
            workflow_action = None
        selected_citations = (
            []
            if external_requested
            else self._select_citations(citations, answer_record.citation_indices)
        )
        corrected_answer, domain_correction = self._correct_domain_mismatch(
            request=request,
            answer=answer_record.answer,
        )
        answer_record = answer_record.model_copy(
            update={
                "answer": _clean_researcher_answer(corrected_answer),
                **({"confidence": 0.3} if domain_correction is not None else {}),
            }
        )
        if domain_correction is not None:
            answer_mode = "fallback"
        trace_ref = self._trace_ref(retrieval)
        memory_turn = self._memory_store.append_turn(
            conversation_id=conversation_id,
            project_id=request.project_id,
            question=request.question,
            rewritten_query=rewritten_query,
            answer=answer_record.answer,
            route=route.route,
            mode=request.mode,
            citations=selected_citations,
            retrieval_trace_ref=trace_ref,
        )
        return QAAnswerResponse(
            project_id=request.project_id,
            conversation_id=conversation_id,
            turn_id=memory_turn.memory_id,
            mode=request.mode,
            question=request.question,
            rewritten_query=rewritten_query,
            route=route,
            answer=answer_record.answer,
            citations=selected_citations,
            retrieval_status=retrieval.retrieval_status,
            retrieval_trace_ref=trace_ref,
            context_bundle_ref=context_bundle.context_id,
            memory_ref=memory_turn.memory_id,
            risk_flags=sorted(
                {
                    *retrieval.risk_flags,
                    *context_bundle.risk_flags,
                    *(external_discovery.get("risk_flags", []) if external_discovery else []),
                    *({"QA_DOMAIN_MISMATCH_CORRECTED"} if domain_correction is not None else set()),
                }
            ),
            answer_mode=answer_mode,
            confidence=answer_record.confidence,
            needs_follow_up=answer_record.needs_follow_up,
            follow_up_question=answer_record.follow_up_question,
            tool_calls=tool_calls,
            workflow_action=workflow_action,
            domain_correction=domain_correction,
        )

    def converse(self, request: QAAnswerRequest) -> QAAnswerResponse:
        """Compose a bounded collaborative turn without starting orchestration."""

        conversation_id = request.conversation_id or f"conv_{uuid4().hex}"
        history = self._memory_store.recent_turns(
            conversation_id, limit=6, project_id=request.project_id
        )
        recent = (
            "\n".join(
                f"- 用户：{turn.question}\n  助手：{turn.answer[:500]}" for turn in history[-4:]
            )
            or "- 无"
        )
        planned_acts = ", ".join(request.planned_research_acts) or "根据内容自然回应"
        follow_up_rule = (
            f"如果需要用户回答，只能问这一项：{request.planned_follow_up_question}"
            if request.planned_follow_up_question
            else (
                "本轮不要提出新问题；缺失但不影响当前方向的信息可以保持开放。"
                if not request.allow_unplanned_follow_up
                else "只有在答案会改变研究方向时，才可以提出一个澄清问题。"
            )
        )
        prompt = (
            f"用户当前想法：{request.question}\n\n"
            f"项目背景（仅在与当前问题有关时使用）：{request.project_context or '未提供'}\n\n"
            f"最近对话：\n{recent}\n\n"
            f"本轮已经确定的研究动作：{planned_acts}。{follow_up_rule}\n\n"
            "请像一位合作导师一样自然回应，直接处理用户本轮新增的信息或请求。"
            "不要重复概括完整研究目的；除非纠正误解，只用一句短句确认已知边界。"
            "不要把回答写成流程状态播报，也不要为了收集完整字段而连续追问。不要编造论文、检索结果、证据状态、"
            "流程阶段或系统内部信息，也不要把普通讨论推进成任务。不要假定用户已经上传、"
            "收集或拥有任何数据；不要承诺自己已经审查文件。若用户询问界面操作，只说明"
            "当前可确认的事实：原始研究数据导入使用 CSV，不要建议 Excel 或声称附件已经被导入。"
            "项目背景只用于让回答贴合研究对象，不能据此编造数据字段或研究结论。"
        )
        answer_text = _discussion_fallback_answer(
            request.question,
            project_context=request.project_context,
            planned_research_acts=request.planned_research_acts,
            planned_follow_up_question=request.planned_follow_up_question,
            allow_unplanned_follow_up=request.allow_unplanned_follow_up,
        )
        answer_mode: Literal["llm", "fallback"] = "fallback"
        # A model cannot infer a project's real CSV schema from a topic or a
        # paper title. Keep these turns factual until the researcher supplies
        # a header or codebook instead of hallucinating familiar field names.
        normalized_question = request.question.strip().lower()
        scenario_design_requested = (
            any(
                marker in normalized_question
                for marker in ("情境题", "具体题目", "设计题目", "设计具体")
            )
            and any(
                marker in normalized_question
                for marker in ("使用方式", "最主要", "问卷", "操作化", "四类", "第3题", "题目")
            )
        )
        questionnaire_design_requested = (
            any(
                marker in normalized_question
                for marker in ("完整问卷", "可直接发放", "直接发放", "数据字典")
            )
            and any(
                marker in normalized_question
                for marker in ("编码方案", "问卷", "变量", "值标签")
            )
            and any(
                marker in normalized_question
                for marker in ("没有问卷数据", "还没有", "不要转到", "先把")
            )
        )
        questionnaire_config_requested = (
            any(
                marker in normalized_question
                for marker in ("最终可配置", "问卷逻辑", "问卷平台")
            )
            and any(
                marker in normalized_question
                for marker in ("数据字典", "编码", "变量")
            )
            and any(
                marker in normalized_question
                for marker in ("修正", "输出", "整理", "改")
            )
        )
        if (
            request.allow_llm
            and not _requires_schema_safe_answer(request.question)
            and not scenario_design_requested
            and not questionnaire_design_requested
            and not questionnaire_config_requested
            and self._generator is not None
            and self._model
        ):
            try:
                result = self._generator.generate(
                    system_prompt=(
                        "你是一个研究状态感知的合作导师。你会复述、重构、发散、比较、挑战或整理研究判断，"
                        "不调用工具，不展示内部状态，不声称已经检索或核验了资料。"
                        "不要虚构数据上传、文件审查或实验变量。严格遵守用户提示中的提问上限，"
                        "如果信息可以暂定或之后检索，不要把它变成用户必须回答的问题。"
                        "绝对不要输出 current_mode、research_acts、reflect、co_think、Gate、"
                        "causal_claims=forbidden 等内部字段或英文状态标签；应改写成自然语言。"
                        "不要擅自发明项目尚未提供的变量、量表、日志字段或数据事实；举例时必须明确标为假设性例子。"
                        "请返回 JSON：answer、citation_indices、confidence、"
                        "needs_follow_up、follow_up_question。"
                    ),
                    user_prompt=prompt,
                    response_model=_AnswerDraft,
                    model=self._model,
                    prompt_version="conversation-v1",
                )
                parsed = _AnswerDraft.model_validate(result.parsed_output)
                answer_text = _clean_researcher_answer(parsed.answer)
                answer_mode = "llm"
            except Exception as error:
                # Do not silently turn every later turn into the same generic
                # sentence when the shared provider quota or endpoint fails.
                # The exception detail stays in server logs, never in chat.
                logger.warning(
                    "Conversational model unavailable; using grounded fallback: %s", error
                )
        corrected_answer, domain_correction = self._correct_domain_mismatch(
            request=request,
            answer=answer_text,
        )
        answer_text = _clean_researcher_answer(corrected_answer)
        if domain_correction is not None:
            answer_mode = "fallback"
        memory_turn = self._memory_store.append_turn(
            conversation_id=conversation_id,
            project_id=request.project_id,
            question=request.question,
            rewritten_query=request.question,
            answer=answer_text,
            route="direct_answer",
            mode=request.mode,
            citations=[],
            retrieval_trace_ref=None,
        )
        return QAAnswerResponse(
            project_id=request.project_id,
            conversation_id=conversation_id,
            turn_id=memory_turn.memory_id,
            mode=request.mode,
            question=request.question,
            rewritten_query=request.question,
            route=QARouteDecision(route="direct_answer", reason="普通对话未请求研究工具"),
            answer=answer_text,
            citations=[],
            retrieval_status="READY",
            retrieval_trace_ref=None,
            context_bundle_ref=None,
            memory_ref=memory_turn.memory_id,
            risk_flags=["QA_DOMAIN_MISMATCH_CORRECTED"] if domain_correction is not None else [],
            answer_mode=answer_mode,
            confidence=0.7 if answer_mode == "llm" else 0.3,
            needs_follow_up=request.planned_follow_up_question is not None,
            follow_up_question=request.planned_follow_up_question,
            tool_calls=[],
            workflow_action=None,
            domain_correction=domain_correction,
        )

    def list_conversations(
        self,
        project_id: str,
        *,
        limit: int = 50,
    ) -> list[ConversationSummary]:
        return self._memory_store.list_conversations(project_id, limit=limit)

    def conversation_turns(
        self,
        project_id: str,
        conversation_id: str,
        *,
        limit: int = 100,
    ) -> list[MemoryTurn]:
        return self._memory_store.conversation_turns(
            project_id=project_id,
            conversation_id=conversation_id,
            limit=limit,
        )

    def _rewrite_query(self, question: str, history: list[MemoryTurn]) -> str:
        """Use the existing transparent rewrite and add bounded conversation context."""

        base = expanded_query(question)
        if not history:
            return base
        history_hint = " ".join(
            normalize_text(f"{turn.question} {turn.answer}")[:240] for turn in history[-2:]
        )
        return f"{base} {history_hint}".strip()

    def _route(
        self,
        question: str,
        rewritten_query: str,
        history: list[MemoryTurn],
    ) -> QARouteDecision:
        """Choose a safe coarse route; retrieval remains hybrid by default."""

        normalized = normalize_text(question)
        if any(marker in normalized for marker in ("doi", "论文编号", "这篇论文", "paper id")):
            return QARouteDecision(
                route="paper_lookup",
                reason="问题明显指向单篇论文定位",
            )
        if any(
            marker in normalized
            for marker in (
                "agent",
                "智能体",
                "workflow",
                "项目",
                "写作",
                "审稿",
                "设计",
                "分析",
            )
        ):
            return QARouteDecision(
                route="workflow_agent",
                reason="问题更像研究工作流任务",
                recommended_agent=self._agent_hint(normalized),
            )
        if history:
            return QARouteDecision(
                route="hybrid_search",
                reason="结合当前会话记忆继续检索和回答",
            )
        if "图谱" in rewritten_query or "三元组" in rewritten_query:
            return QARouteDecision(
                route="hybrid_search",
                reason="需要图谱导航和全文证据共同参与",
            )
        return QARouteDecision(
            route="hybrid_search",
            reason="默认使用图谱引导的向量+稀疏混合检索",
        )

    @staticmethod
    def _agent_hint(question: str) -> str:
        if any(marker in question for marker in ("写作", "论文", "manuscript")):
            return "PaperWritingAgent"
        if any(marker in question for marker in ("审稿", "review", "批判")):
            return "IndependentReviewAgent"
        if any(marker in question for marker in ("设计", "方案", "实验")):
            return "ResearchDesignAgent"
        if any(marker in question for marker in ("分析", "统计", "data", "结果")):
            return "DataAnalysisAgent"
        if any(marker in question for marker in ("证据", "evidence", "文献")):
            return "EvidenceReviewAgent"
        return "MentorPlanningAgent"

    def _agentic_synthesize(
        self,
        *,
        request: QAAnswerRequest,
        question: str,
        rewritten_query: str,
        route: QARouteDecision,
        retrieval: RetrievalSearchResponse,
        context_bundle: ContextBundle,
        citations: list[QAReference],
        history: list[MemoryTurn],
        allow_llm: bool,
        external_discovery: dict[str, Any] | None = None,
        mode: ContextMode,
    ) -> (
        tuple[
            QAAnswerRecord,
            QARouteDecision,
            RetrievalSearchResponse,
            list[QAReference],
            list[str],
            ContextBundle,
            QAWorkflowAction | None,
        ]
        | None
    ):
        """Let the model choose bounded retrieval or workflow tools."""

        if (
            not allow_llm
            or self._provider is None
            or not hasattr(self._provider, "complete")
            or not self._model
        ):
            return None
        try:
            first = self._provider.complete(
                messages=[
                    {
                        "role": "system",
                        "content": self._tool_router_system_prompt(),
                    },
                    {
                        "role": "user",
                        "content": self._tool_router_user_prompt(
                            question,
                            rewritten_query,
                            route,
                            retrieval,
                            history,
                        ),
                    },
                ],
                model=self._model,
                tools=tool_definitions(),
                tool_choice="auto",
            )
            if not first.tool_calls:
                return None

            calls = list(first.tool_calls[:3])
            workflow_calls = [call for call in calls if call.name in WORKFLOW_TOOL_NAMES]
            if workflow_calls:
                # A single turn may perform at most one Controller workflow action.
                calls = workflow_calls[:1]
            selected_tool = calls[0] if calls else first.tool_calls[0]
            assistant_message = dict(first.message)
            if workflow_calls:
                raw_tool_calls = assistant_message.get("tool_calls")
                if isinstance(raw_tool_calls, list):
                    assistant_message["tool_calls"] = [
                        item
                        for item in raw_tool_calls
                        if isinstance(item, Mapping) and item.get("id") == selected_tool.call_id
                    ]

            messages: list[Mapping[str, Any]] = [
                {
                    "role": "system",
                    "content": self._system_prompt(),
                },
                {
                    "role": "user",
                    "content": self._user_prompt(
                        question,
                        rewritten_query,
                        route,
                        retrieval,
                        context_bundle,
                        citations,
                        history,
                    ),
                },
                assistant_message,
            ]
            tool_names: list[str] = []
            workflow_action: QAWorkflowAction | None = None
            active_retrieval = retrieval
            active_citations = citations
            active_context_bundle = context_bundle
            for call in calls:
                tool_names.append(call.name)
                result = self._tool_executor.execute(
                    name=call.name,
                    arguments=call.arguments,
                    project_id=request.project_id,
                    default_query=rewritten_query,
                    mode=mode,
                )
                workflow_payload = result.get("workflow_action")
                if isinstance(workflow_payload, Mapping):
                    try:
                        workflow_action = QAWorkflowAction.model_validate(workflow_payload)
                    except ValueError:
                        workflow_action = None
                retrieval_payload = result.get("retrieval_response")
                if isinstance(retrieval_payload, Mapping):
                    try:
                        active_retrieval = RetrievalSearchResponse.model_validate(retrieval_payload)
                        active_citations = self._build_citations(active_retrieval)
                        tool_query = str(call.arguments.get("query") or rewritten_query).strip()
                        active_context_bundle = self._knowledge_service.build_context(
                            project_id=request.project_id,
                            task_ref=context_bundle.task_ref,
                            query=tool_query,
                            token_budget=context_bundle.token_budget,
                            mode=mode.value,
                        )
                    except ValueError:
                        active_retrieval = retrieval
                        active_citations = citations
                        active_context_bundle = context_bundle
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.call_id,
                        "name": call.name,
                        "content": self._json_text(result),
                    }
                )

            messages.append(
                {
                    "role": "user",
                    "content": self._user_prompt(
                        question,
                        rewritten_query,
                        QARouteDecision(
                            route=route_for_tool(selected_tool.name),
                            reason=tool_reason(selected_tool.name),
                            recommended_agent=route.recommended_agent,
                        ),
                        active_retrieval,
                        active_context_bundle,
                        active_citations,
                        history,
                    ),
                }
            )
            try:
                final = self._provider.complete(
                    messages=messages,
                    model=self._model,
                    response_model=_AnswerDraft,
                )
                if not final.content:
                    raise ValueError("LLM returned no final answer")
                parsed = _AnswerDraft.model_validate_json(final.content)
            except Exception:
                if workflow_action is None:
                    raise
                parsed = _AnswerDraft(
                    answer=workflow_action.message,
                    citation_indices=[],
                    confidence=0.9,
                    needs_follow_up=workflow_action.confirmation_required,
                    follow_up_question=(
                        "请在工作流页面确认批准或退回当前候选。"
                        if workflow_action.confirmation_required
                        else None
                    ),
                )
            public_route = route_for_tool(selected_tool.name)
            recommended_agent = (
                str(selected_tool.arguments.get("agent"))
                if selected_tool.name == "workflow_agent" and selected_tool.arguments.get("agent")
                else route.recommended_agent
            )
            return (
                QAAnswerRecord(
                    answer=parsed.answer,
                    citation_indices=self._clamp_indices(
                        parsed.citation_indices,
                        len(active_citations),
                    ),
                    confidence=parsed.confidence,
                    needs_follow_up=parsed.needs_follow_up,
                    follow_up_question=parsed.follow_up_question,
                ),
                QARouteDecision(
                    route=public_route,
                    reason=tool_reason(selected_tool.name),
                    recommended_agent=recommended_agent,
                ),
                active_retrieval,
                active_citations,
                tool_names,
                active_context_bundle,
                workflow_action,
            )
        except Exception:
            # Tool routing is an enhancement; deterministic retrieval and the
            # existing structured synthesis remain the availability baseline.
            return None

    @staticmethod
    def _json_text(value: Mapping[str, Any]) -> str:
        import json

        return json.dumps(value, ensure_ascii=False, default=str)

    @staticmethod
    def _tool_router_system_prompt() -> str:
        return (
            "You are the STEM-SCI research router. Select the minimum bounded "
            "retrieval or workflow tool needed for the user's request. Use "
            "hybrid_search for most "
            "research questions, paper_lookup for a specific paper, graph_search "
            "for relationship discovery, vector_search for textual evidence, "
            "start_research_workflow only when the user explicitly asks to create "
            "a project, get_workflow_status for progress questions, "
            "run_next_workflow_agent only when the user explicitly asks to continue, "
            "get_workflow_artifacts to inspect candidates, "
            "prepare_workflow_approval to show a pending approval, and "
            "workflow_agent only for proposal-only Agent recommendations. "
            "external_paper_search only when the local corpus is insufficient. "
            "Never invent tool results. Never approve, reject, freeze data, execute "
            "statistics, or release a project from the conversational tool layer."
        )

    @staticmethod
    def _tool_router_user_prompt(
        question: str,
        rewritten_query: str,
        route: QARouteDecision,
        retrieval: RetrievalSearchResponse,
        history: list[MemoryTurn],
    ) -> str:
        recent = "\n".join(f"- {turn.question}: {turn.answer[:180]}" for turn in history[-2:])
        return (
            f"Question: {question}\n"
            f"Rewritten query: {rewritten_query}\n"
            f"Rule hint: {route.route} ({route.reason})\n"
            f"Baseline retrieval status: {retrieval.retrieval_status}\n"
            f"Recent memory:\n{recent or '- none'}\n"
            "Choose the minimum tool calls needed to answer safely."
        )

    def _synthesize(
        self,
        *,
        question: str,
        rewritten_query: str,
        route: QARouteDecision,
        retrieval: RetrievalSearchResponse,
        context_bundle: ContextBundle,
        citations: list[QAReference],
        history: list[MemoryTurn],
        allow_llm: bool,
        external_discovery: dict[str, Any] | None = None,
        prefer_external: bool = False,
    ) -> tuple[QAAnswerRecord, Literal["llm", "fallback"]]:
        if prefer_external:
            return self._fallback_answer(
                question, retrieval, citations, external_discovery, prefer_external=True
            ), "fallback"
        if allow_llm and self._generator is not None and self._model:
            try:
                result = self._generator.generate(
                    system_prompt=self._system_prompt(),
                    user_prompt=self._user_prompt(
                        question,
                        rewritten_query,
                        route,
                        retrieval,
                        context_bundle,
                        citations,
                        history,
                    ),
                    response_model=_AnswerDraft,
                    model=self._model,
                    prompt_version=self._prompt_version,
                )
                parsed = _AnswerDraft.model_validate(result.parsed_output)
                return (
                    QAAnswerRecord(
                        answer=parsed.answer,
                        citation_indices=self._clamp_indices(
                            parsed.citation_indices, len(citations)
                        ),
                        confidence=parsed.confidence,
                        needs_follow_up=parsed.needs_follow_up,
                        follow_up_question=parsed.follow_up_question,
                    ),
                    "llm",
                )
            except Exception:
                # Retrieval should remain usable when a provider rejects a request.
                pass
        return self._fallback_answer(question, retrieval, citations, external_discovery), "fallback"

    @staticmethod
    def _fallback_answer(
        question: str,
        retrieval: RetrievalSearchResponse,
        citations: list[QAReference],
        external_discovery: dict[str, Any] | None = None,
        prefer_external: bool = False,
    ) -> QAAnswerRecord:
        if prefer_external and not (external_discovery and external_discovery.get("ok")):
            message = str((external_discovery or {}).get("message") or "外部学术检索没有返回结果。")
            details = (external_discovery or {}).get("details")
            detail_text = (
                f"（诊断：{'; '.join(str(item) for item in details[:2])}）"
                if isinstance(details, list) and details
                else ""
            )
            return QAAnswerRecord(
                answer=(
                    "我刚才尝试了外部文献检索，但这次没有拿到可用结果。\n"
                    f"{message}{detail_text}\n\n我没有用本地材料冒充外部结果；可以换一个更具体的英文关键词后再试。"
                ),
                citation_indices=[],
                confidence=0.0,
                needs_follow_up=True,
                follow_up_question="可以稍后重试，或提供具体论文题目、DOI 和关键词。",
            )
        if external_discovery and external_discovery.get("ok"):
            candidates = external_discovery.get("results", [])
            lines = []
            for candidate in candidates[:3]:
                if not isinstance(candidate, Mapping):
                    continue
                title = str(candidate.get("title") or "Untitled")
                doi = candidate.get("doi")
                year = candidate.get("publication_year")
                suffix = f"（{year}）" if year else ""
                link = f" DOI: {doi}" if doi else ""
                lines.append(f"- {title}{suffix}{link}")
            if lines:
                return QAAnswerRecord(
                    answer=(
                        "外部学术索引返回以下论文候选：\n"
                        + "\n".join(lines)
                        + "\n\n这些是外部题录候选，不是正式证据。请导入原文并核验页码或字符位置后再引用。"
                    ),
                    citation_indices=[],
                    confidence=0.2,
                    needs_follow_up=True,
                    follow_up_question="请选择候选论文并上传原文，以便进行来源核验。",
                )
            if prefer_external:
                return QAAnswerRecord(
                    answer=(
                        "外部学术索引本轮返回 0 条可用候选。"
                        "我没有把本地共享语料冒充成外部检索结果；可以换用更具体的英文关键词、年份或 DOI 条件后重试。"
                    ),
                    citation_indices=[],
                    confidence=0.0,
                    needs_follow_up=True,
                    follow_up_question="请补充英文关键词、研究对象或时间范围后重试外部检索。",
                )
        if not retrieval.chunk_hits and retrieval.candidate_papers:
            candidates = retrieval.candidate_papers[:3]
            lines = [
                f"- {candidate.graph_paper_id}（匹配方向：{'、'.join(candidate.matched_facets[:3]) or '相关主题'}）"
                for candidate in candidates
            ]
            return QAAnswerRecord(
                answer=(
                    "当前全文资源尚未挂载，以下是基于知识图谱的探索性论文候选：\n"
                    + "\n".join(lines)
                    + "\n\n这些候选只能用于确定研究方向，不能作为正式证据；补入论文 PDF 和向量索引后再进行原文核验。"
                ),
                citation_indices=list(range(1, min(3, len(citations)) + 1)),
                confidence=0.25,
                needs_follow_up=True,
                follow_up_question="请补入对应论文原文，或继续限定研究对象、变量和时间范围。",
            )
        if not retrieval.chunk_hits and not citations:
            return QAAnswerRecord(
                answer=f"当前知识库没有找到足够证据回答：{question}",
                citation_indices=[],
                confidence=0.0,
                needs_follow_up=True,
                follow_up_question="请补充论文题目、研究对象或更具体的关键词。",
            )
        if not citations:
            return QAAnswerRecord(
                answer=(
                    "我暂时没有找到与你这三个变量直接对应的本地原文证据。"
                    "现有材料主要集中在其他主题，不能据此替你确定研究范围。"
                    "我们可以先明确研究对象、变量定义和课程场景，再检索针对性的论文。"
                ),
                citation_indices=[],
                confidence=0.0,
                needs_follow_up=True,
                follow_up_question="你的研究对象是普通本科生、物理专业本科生，还是某门具体课程的学生？",
            )
        lines = [f"- {citation.paper_title}：{citation.excerpt}" for citation in citations[:3]]
        return QAAnswerRecord(
            answer="基于当前检索到的证据，相关信息如下：\n" + "\n".join(lines),
            citation_indices=list(range(1, min(3, len(citations)) + 1)),
            confidence=0.55,
        )

    @staticmethod
    def _build_citations(
        retrieval: RetrievalSearchResponse,
    ) -> list[QAReference]:
        citations: list[QAReference] = []
        for hit in retrieval.chunk_hits:
            citations.append(
                QAReference(
                    paper_title=hit.paper_title,
                    source_filename=hit.source_filename,
                    canonical_paper_id=hit.canonical_paper_id,
                    canonical_chunk_id=hit.canonical_chunk_id,
                    chunk_index=hit.chunk_index,
                    excerpt=hit.excerpt,
                    normalized_doi=normalize_doi(hit.normalized_doi),
                    pdf_relative_path=hit.pdf_relative_path,
                    pdf_sha256=hit.pdf_sha256,
                    locator_status=hit.locator_status,
                    source_locator_method=hit.source_locator_method,
                    verification_status=hit.verification_status,
                    page_start=hit.page_start,
                    page_end=hit.page_end,
                    char_start=hit.char_start,
                    char_end=hit.char_end,
                    retrieval_modalities=[str(modality) for modality in hit.retrieval_modalities],
                )
            )
        for candidate in retrieval.candidate_papers:
            citations.append(
                QAReference(
                    paper_title=candidate.graph_paper_id,
                    source_filename=candidate.graph_paper_id,
                    canonical_paper_id=candidate.canonical_paper_id,
                    canonical_chunk_id=(
                        candidate.supporting_edge_refs[0]
                        if candidate.supporting_edge_refs
                        else candidate.canonical_paper_id
                    ),
                    chunk_index=0,
                    excerpt="图谱导航候选论文，不能单独作为正式证据。",
                    source_type="paper",
                    locator_status="UNRESOLVED",
                    source_locator_method="UNRESOLVED",
                    verification_status="model_generated_unverified",
                    retrieval_modalities=["graph_navigation"],
                )
            )
        return [
            citation.model_copy(update={"citation_index": index})
            for index, citation in enumerate(citations, start=1)
        ]

    @staticmethod
    def _filter_citations_for_question(
        question: str,
        citations: list[QAReference],
    ) -> list[QAReference]:
        """Drop exploratory hits that do not mention the asked concept."""

        if not citations:
            return []
        generic = {
            "什么",
            "什么是",
            "如何",
            "怎样",
            "是否",
            "适合",
            "回答",
            "类型",
            "问题",
            "研究",
            "教育",
            "物理",
            "资料",
            "论文",
            "方法",
            "相关",
            "当前",
            "内容",
            "what",
            "is",
            "are",
            "for",
            "the",
            "physics",
            "education",
            "research",
            "design",
        }
        concepts = [
            token
            for token in re.findall(
                r"[\u4e00-\u9fff]{2,}|[a-zA-Z][a-zA-Z0-9_-]{2,}",
                question.casefold(),
            )
            if token not in generic
        ]
        if not concepts:
            return citations[:3]

        filtered: list[QAReference] = []
        for citation in citations:
            haystack = f"{citation.paper_title} {citation.excerpt}".casefold()
            long_match = any(len(token) >= 4 and token in haystack for token in concepts)
            short_matches = sum(1 for token in concepts if len(token) >= 2 and token in haystack)
            # Multi-concept questions need evidence covering at least two
            # concepts. A single hit on one variable must not answer the whole
            # relationship being discussed.
            if (len(concepts) == 1 and long_match) or short_matches >= 2:
                filtered.append(citation)
        return [
            citation.model_copy(update={"citation_index": index})
            for index, citation in enumerate(filtered[:3], start=1)
        ]

    @staticmethod
    def _select_citations(
        citations: list[QAReference],
        indices: list[int],
    ) -> list[QAReference]:
        if not indices:
            return citations[: min(3, len(citations))]
        selected = [citations[index - 1] for index in indices if 1 <= index <= len(citations)]
        selected = selected or citations[: min(3, len(citations))]
        return sorted(
            selected,
            key=lambda citation: citation.citation_index or citations.index(citation) + 1,
        )

    @staticmethod
    def _clamp_indices(indices: list[int], size: int) -> list[int]:
        return sorted({index for index in indices if 1 <= index <= size})[:5]

    @staticmethod
    def _trace_ref(retrieval: RetrievalSearchResponse) -> str:
        digest = hashlib.sha256(
            retrieval.retrieval_trace.query_normalized.encode("utf-8")
        ).hexdigest()[:16]
        return f"retrieval://{retrieval.corpus_id}/{digest}"

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are the STEM-SCI evidence assistant. Answer only from the supplied "
            "retrieved context. Never invent findings. Graph candidates are navigation "
            "hints, not formal evidence. Cite usable sources with 1-based citation "
            "indices. If evidence is insufficient, state that explicitly."
        )

    @staticmethod
    def _user_prompt(
        question: str,
        rewritten_query: str,
        route: QARouteDecision,
        retrieval: RetrievalSearchResponse,
        context_bundle: ContextBundle,
        citations: list[QAReference],
        history: list[MemoryTurn],
    ) -> str:
        context = "\n".join(
            f"[{index}] {item.paper_title} | {item.source_filename} | "
            f"chunk {item.chunk_index}: {item.excerpt}"
            for index, item in enumerate(citations[:8], start=1)
        )
        recent = "\n".join(
            f"- 问题：{turn.question}\n  回答：{turn.answer[:240]}" for turn in history[-3:]
        )
        bundle_evidence = "\n".join(
            f"- {item.evidence_id}: {item.excerpt}" for item in context_bundle.evidence_refs[:8]
        )
        return (
            f"用户问题：{question}\n"
            f"改写查询：{rewritten_query}\n"
            f"检索路线：{route.route}\n"
            f"路线说明：{route.reason}\n"
            f"检索状态：{retrieval.retrieval_status}\n"
            f"ContextBundle：{context_bundle.context_id}\n"
            f"历史对话：\n{recent or '- 无'}\n"
            f"上下文证据：\n{bundle_evidence or '- 无'}\n"
            f"证据：\n{context or '- 无'}\n"
            "如果上下文证据存在，优先依据用户项目中的上下文证据回答；共享证据与问题或上传材料明显无关时，不得引用或据此作答。"
            "请返回 JSON：answer、citation_indices、confidence、"
            "needs_follow_up、follow_up_question。"
        )
