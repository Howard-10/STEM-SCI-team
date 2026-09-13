"""
Teaching Plan Generation Agent.
Uses Few-shot RAG from school teaching plans + DeepSeek V3 to generate
personalized STEM project-based learning plans for students.
"""
import json
import os
import re
import sys
import time
from typing import Dict, List, Optional

import requests

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data_pipeline.retriever import (
    retrieve_fewshot_examples,
    retrieve_relevant_sections,
)
from agents.teaching_plan_skill import build_system_prompt, build_user_message

# ---- Config ----
LLM_API_URL = "https://api.siliconflow.cn/v1/chat/completions"
LLM_MODEL = "deepseek-ai/DeepSeek-V3"
LLM_TIMEOUT = float(os.environ.get("TEACHING_LLM_TIMEOUT", "120"))
DEFAULT_MAX_TOKENS = int(os.environ.get("TEACHING_MAX_TOKENS", "1800"))
MAX_REPAIR_ATTEMPTS = max(
    0,
    int(os.environ.get("TEACHING_REPAIR_ATTEMPTS", "2")),
)


def _resolve_llm_config() -> Dict[str, str]:
    """Resolve the configured provider at request time.

    ResearchPilot historically used SiliconFlow, while this workstation is
    configured with an Alibaba DashScope key. Reading environment variables
    per request avoids stale values when the backend is restarted or embedded
    in another launcher and keeps the provider choice out of UI code.
    """
    siliconflow_key = os.environ.get("SILICONFLOW_API_KEY", "").strip()
    if siliconflow_key:
        return {"url": LLM_API_URL, "model": os.environ.get("TEACHING_LLM_MODEL", LLM_MODEL), "api_key": siliconflow_key}

    dashscope_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if dashscope_key:
        return {
            "url": os.environ.get(
                "DASHSCOPE_CHAT_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            ),
            "model": os.environ.get("DASHSCOPE_CHAT_MODEL", "qwen-plus"),
            "api_key": dashscope_key,
        }
    return {"url": LLM_API_URL, "model": LLM_MODEL, "api_key": ""}

# Grade level mapping
GRADE_MAP = {
    "小学低段": "小学1-2年级",
    "小学中段": "小学3-4年级",
    "小学高段": "小学5-6年级",
    "初中": "初中7-9年级",
    "高中": "高中10-12年级",
}

# Subject areas
STEM_SUBJECTS = [
    "物理", "化学", "生物", "地球与空间科学",
    "工程技术", "电子与编程", "数学与逻辑", "环境科学",
    "社会科学", "数据科学", "语言学", "艺术设计"
]

# 12 bubble topics — balanced across science, engineering, humanities
BUBBLE_TOPICS = [
    # 纯科学探究
    {"id": "light_refraction", "title": "光的折射与透镜探究", "subjects": ["物理", "数学与逻辑"], "difficulty": 2},
    {"id": "acid_base_indicator", "title": "自制酸碱指示剂", "subjects": ["化学", "生物"], "difficulty": 2},
    {"id": "seed_germination", "title": "种子发芽条件探究", "subjects": ["生物", "环境科学", "数学与逻辑"], "difficulty": 2},
    # 工程与技术
    {"id": "paper_bridge", "title": "纸桥承重挑战赛", "subjects": ["物理", "工程技术", "数学与逻辑"], "difficulty": 2},
    {"id": "auto_watering", "title": "智能自动浇花系统", "subjects": ["生物", "电子与编程", "工程技术"], "difficulty": 3},
    {"id": "obstacle_robot", "title": "避障机器人挑战", "subjects": ["工程技术", "电子与编程", "物理"], "difficulty": 4},
    # 人文与社会科学
    {"id": "waste_sorting_survey", "title": "社区垃圾分类调查", "subjects": ["环境科学", "数学与逻辑", "社会科学"], "difficulty": 2},
    {"id": "dialect_survey", "title": "方言保护小调查", "subjects": ["社会科学", "数据科学", "语言学"], "difficulty": 2},
    {"id": "history_timeline", "title": "历史事件时间线可视化", "subjects": ["社会科学", "电子与编程", "数据科学"], "difficulty": 3},
    {"id": "carbon_footprint", "title": "我的家庭碳足迹计算", "subjects": ["环境科学", "数学与逻辑", "社会科学"], "difficulty": 3},
    {"id": "campus_plant_atlas", "title": "校园植物图鉴制作", "subjects": ["生物", "艺术设计", "数据科学"], "difficulty": 2},
    {"id": "future_city_design", "title": "设计未来城市模型", "subjects": ["工程技术", "艺术设计", "社会科学"], "difficulty": 3},
]


import concurrent.futures

# Simple in-memory cache
_plan_cache: Dict[str, tuple] = {}
CACHE_TTL = 600  # 10 minutes
PLAN_FORMAT_VERSION = "v4"

# Phrases that indicate the model stopped at an outline instead of delivering
# a classroom-ready plan. These are checked before a result can be cached.
_INCOMPLETE_PLAN_MARKERS = (
    "后续课时同样详细展开",
    "后续课时",
    "详见下文",
    "同上",
    "待补充",
    "待完善",
    "视情况而定",
)


def _safe_retrieve_fewshot(query: str, top_k: int = 2) -> List[str]:
    """Use local examples when available, but never block generation on RAG."""
    if not (os.environ.get("SILICONFLOW_API_KEY", "").strip() or os.environ.get("DASHSCOPE_API_KEY", "").strip()):
        return []
    try:
        return retrieve_fewshot_examples(query, top_k)
    except Exception as exc:
        print(f"Few-shot retrieval unavailable; continuing without it: {exc}")
        return []


def _safe_retrieve_sections(query: str, top_k: int = 4):
    """Use section retrieval opportunistically; model generation remains the source of truth."""
    if not (os.environ.get("SILICONFLOW_API_KEY", "").strip() or os.environ.get("DASHSCOPE_API_KEY", "").strip()):
        return []
    try:
        return retrieve_relevant_sections(query, top_k)
    except Exception as exc:
        print(f"Section retrieval unavailable; continuing without it: {exc}")
        return []

def generate_teaching_plan(
    user_query: str,
    grade_level: str = "初中",
    difficulty: int = None,
    include_3d_print: bool = True,
    max_tokens: int = DEFAULT_MAX_TOKENS
) -> Dict:
    """
    Generate a complete STEM teaching plan for a student.
    """
    started_at = time.monotonic()
    # Check cache
    cache_key = f"{PLAN_FORMAT_VERSION}|{user_query}|{grade_level}|{include_3d_print}"
    if cache_key in _plan_cache:
        cached_result, cached_time = _plan_cache[cache_key]
        if time.time() - cached_time < CACHE_TTL:
            return cached_result

    # Step 1+2: Parallel embedding searches
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        future_examples = pool.submit(_safe_retrieve_fewshot, user_query, 2)
        future_sections = pool.submit(_safe_retrieve_sections, user_query, 4)

        examples = future_examples.result(timeout=15)
        relevant_sections = future_sections.result(timeout=15)

    knowledge_context = "\n".join([
        f"【{meta.get('section_title', '')}】{meta.get('content', '')[:500]}"
        for meta, score in relevant_sections
    ]) if relevant_sections else ""

    # Step 3: Build system prompt (from teaching_plan_skill)
    system_prompt = build_system_prompt(grade_level, difficulty, include_3d_print)

    # Step 4: Build user message (from teaching_plan_skill)
    grade_desc = GRADE_MAP.get(grade_level, grade_level)
    user_message = build_user_message(
        user_query, grade_desc, examples, knowledge_context, include_3d_print
    )

    # Step 5: Call DeepSeek V3
    plan_markdown, raw_response = _call_llm(system_prompt, user_message, max_tokens)

    # Apply deterministic presentation guarantees without rewriting the model's content.
    plan_markdown = _normalize_plan_markdown(plan_markdown, grade_level, user_query)

    quality = _validate_plan_quality(plan_markdown)
    revision_attempted = False
    repair_attempts = 0
    if not quality["ok"]:
        revision_attempted = True
        current_markdown = plan_markdown
        repair_max_tokens = max(max_tokens, 5000)
        for _ in range(MAX_REPAIR_ATTEMPTS):
            repair_attempts += 1
            structure_repair = False
            if quality["lesson_count"] == 0:
                revision_prompt = _build_completion_prompt(
                    current_markdown,
                    quality["errors"],
                )
            else:
                incomplete_lesson = next(
                    (
                        lesson_index
                        for lesson_index, lesson_report in enumerate(
                            quality.get("lesson_reports", []),
                            start=1,
                        )
                        if lesson_report.get("errors")
                    ),
                    None,
                )
                needs_more_lessons = quality["lesson_count"] < 3
                if incomplete_lesson is None and not needs_more_lessons:
                    structure_repair = True
                    revision_prompt = _build_structure_completion_prompt(
                        current_markdown,
                        quality["errors"],
                    )
                else:
                    target_lesson = (
                        incomplete_lesson
                        or quality["lesson_count"] + 1
                    )
                    revision_prompt = _build_missing_lessons_prompt(
                        current_markdown,
                        quality["errors"],
                        target_lesson=target_lesson,
                    )

            try:
                revised_markdown, _ = _call_llm(
                    system_prompt,
                    revision_prompt,
                    repair_max_tokens,
                )
            except Exception as exc:
                quality["errors"].append(f"自动补全请求失败：{exc}")
                break

            revised_markdown = _normalize_plan_markdown(
                revised_markdown,
                grade_level,
                user_query,
                ensure_grade=False,
            )
            standalone_quality = _validate_plan_quality(revised_markdown)

            # A repair model may return a complete replacement despite being
            # asked for a section. Prefer it directly when it passes the gate.
            if standalone_quality["ok"]:
                current_markdown = revised_markdown
                quality = standalone_quality
                break

            # Otherwise merge the newly generated section/lessons into the
            # existing draft and keep the candidate only when it improves it.
            if structure_repair:
                candidate_markdown = _merge_supplemental_sections(
                    current_markdown,
                    revised_markdown,
                    quality["errors"],
                )
            elif quality["lesson_count"] == 0:
                process_heading = (
                    ""
                    if re.search(
                        r"^##\s+教学过程",
                        current_markdown,
                        re.MULTILINE,
                    )
                    else "\n\n## 教学过程（分课时）\n"
                )
                candidate_markdown = (
                    current_markdown.rstrip()
                    + process_heading
                    + revised_markdown.lstrip()
                )
            else:
                # Some providers omit the first requested heading and return
                # only the lesson body. Give that body an explicit next
                # lesson heading so it remains parseable and can be merged
                # with later numbered lessons in the same response.
                next_lesson = incomplete_lesson or quality["lesson_count"] + 1
                chinese_numbers = "一二三四五六"
                expected_number = (
                    f"(?:{next_lesson}|{chinese_numbers[next_lesson - 1]})"
                    if 1 <= next_lesson <= len(chinese_numbers)
                    else str(next_lesson)
                )
                if not re.search(
                    rf"^###\s+第\s*{expected_number}\s*课时",
                    revised_markdown,
                    re.MULTILINE,
                ):
                    revised_markdown = (
                        f"### 第{next_lesson}课时：补充探究\n"
                        + revised_markdown.lstrip()
                    )
                existing_heading = re.search(
                    rf"^###\s+第\s*{expected_number}\s*课时[^\n]*$",
                    current_markdown,
                    re.MULTILINE,
                )
                following_existing = (
                    re.search(
                        r"^###\s+第\s*[0-9一二三四五六]+\s*课时[^\n]*$",
                        current_markdown[existing_heading.end():],
                        re.MULTILINE,
                    )
                    if existing_heading
                    else None
                )
                revised_fragment = (
                    _extract_lesson_fragment(revised_markdown, next_lesson)
                    if incomplete_lesson and following_existing
                    else revised_markdown.strip()
                )
                if not re.search(
                    rf"^###\s+第\s*{expected_number}\s*课时",
                    revised_fragment,
                    re.MULTILINE,
                ):
                    revised_fragment = (
                        f"### 第{next_lesson}课时：补充探究\n"
                        + revised_fragment.lstrip()
                    )
                if existing_heading:
                    suffix = (
                        current_markdown[
                            existing_heading.end() + following_existing.start():
                        ].lstrip()
                        if following_existing
                        else ""
                    )
                    prefix = current_markdown[: existing_heading.start()].rstrip()
                    candidate_markdown = prefix + "\n\n" + revised_fragment
                    if suffix:
                        candidate_markdown += "\n\n" + suffix
                else:
                    candidate_markdown = (
                        current_markdown.rstrip()
                        + "\n\n"
                        + revised_fragment.lstrip()
                    )

            candidate_markdown = _normalize_plan_markdown(
                candidate_markdown,
                grade_level,
                user_query,
            )
            candidate_quality = _validate_plan_quality(candidate_markdown)
            if (
                candidate_quality["ok"]
                or len(candidate_markdown) > len(current_markdown)
            ):
                current_markdown = candidate_markdown
                quality = candidate_quality

            if quality["ok"]:
                break

        plan_markdown = current_markdown

    # Step 6: Parse and structure the result
    result = _parse_plan(plan_markdown, user_query, grade_level)
    # The user's resource choice is authoritative. A lesson may discuss a
    # three-dimensional model without requesting printable assets.
    result["has_3d_print"] = bool(include_3d_print)

    result["quality"] = quality
    result["revision_attempted"] = revision_attempted
    result["repair_attempts"] = repair_attempts
    result["generation_elapsed_seconds"] = round(
        time.monotonic() - started_at,
        2,
    )
    if not quality["ok"]:
        result["quality_warning"] = (
            "模型返回的教案仍未达到完整性要求，已保留为草稿且未写入缓存。"
            "请重试生成或缩小主题范围。"
        )
    else:
        # Do not cache an incomplete plan: a low-quality response should never
        # be served again just because it was generated once.
        _plan_cache[cache_key] = (result, time.time())

    return result


def _specific_grade(markdown: str, grade_level: str) -> str:
    """Return an explicit grade fallback when the model omits one."""
    if grade_level in {"小学低段", "小学中段", "小学高段", "高中"}:
        return GRADE_MAP.get(grade_level, grade_level)

    # Quantitative optics and trigonometry in this topic require the upper junior-high band.
    advanced_keywords = ("三角函数", "正弦", "余弦", "折射率", "斯涅尔", "成像公式", "相似三角形")
    if any(keyword in markdown for keyword in advanced_keywords):
        return "初中三年级"
    return "初中二年级"


def _normalize_plan_markdown(
    markdown: str,
    grade_level: str,
    title: str,
    ensure_grade: bool = True,
) -> str:
    """Normalize heading-local numbering and guarantee a visible grade section."""
    text = (markdown or "").replace("\r\n", "\n").strip()
    if not text:
        text = f"# {title}"

    lines = text.split("\n")
    counters: Dict[int, int] = {}
    normalized: List[str] = []
    for line in lines:
        heading = re.match(r"^\s*#{1,6}\s+", line)
        if heading:
            counters.clear()

        ordered = re.match(r"^(\s*)(\d+)[.、)]\s+(.+)$", line)
        if ordered:
            indent, _, content = ordered.groups()
            level = len(indent.expandtabs(2))
            counters[level] = counters.get(level, 0) + 1
            # Drop deeper counters when returning to a shallower list.
            for depth in list(counters):
                if depth > level:
                    del counters[depth]
            line = f"{indent}{counters[level]}. {content}"
        normalized.append(line)

    text = "\n".join(normalized).strip()
    if ensure_grade and not re.search(r"^##\s+适用学段与年级\s*$", text, re.MULTILINE):
        grade = _specific_grade(text, grade_level)
        section = (
            "## 适用学段与年级\n"
            f"适用年级：{grade}\n"
            "前置知识：请在正式授课前根据该年级课程标准检查相关概念、数学工具与实验安全要求。\n"
        )
        overview = re.search(r"^##\s+概述\s*$", text, re.MULTILINE)
        if overview:
            text = text[: overview.start()] + section + "\n" + text[overview.start() :]
        else:
            first_body = re.search(r"^##\s+", text, re.MULTILINE)
            insert_at = first_body.start() if first_body else len(text)
            text = text[:insert_at] + section + "\n" + text[insert_at:]

    return text.strip()


def _build_revision_prompt(markdown: str, errors: List[str]) -> str:
    """Ask the model to repair a draft while preserving its topic and facts."""
    error_text = "\n".join(f"- {error}" for error in errors)
    return f"""下面是一份未通过完整性检查的 STEM 教案草稿。

请在保留主题、学段和科学事实的前提下，直接重写为一份完整可执行的 Markdown 教案。
必须按“课程信息→学情分析→教学目标→教学重点与难点→教学资源→教学过程→教学评价”的顺序组织。教学过程包含 3—6 个完整课时；每个课时只需简洁说明课时目标，但至少安排 2 个教学环节。每个环节写清教师组织、学生至少 3 步操作、过程记录或产出，并把“设计意图”放在该环节最后。每个课时必须有课时小结和课后任务；正式评价标准、评价表和多元评价统一放在全部课时之后的“教学评价”章节。不得使用“略”“同上”“后续课时”“视情况而定”等省略语。只输出修订后的教案，不要解释修订过程。

本次检查发现的问题：
{error_text}

草稿：
{markdown}
"""


def _build_completion_prompt(markdown: str, errors: List[str]) -> str:
    """Request only the missing lesson section after an intro was truncated."""
    error_text = "\n".join(f"- {error}" for error in errors)
    return f"""下面是已经生成的 STEM 教案前半部分，但模型在教学过程开始前停止了。

请不要重复标题、导言、概述、课程信息、学情分析、教学目标、教学重点与难点或教学资源。先输出缺失的“教学过程（分课时）”，从“### 第1课时”开始；全部课时完成后再输出独立的“## 教学评价”。
必须写 3 个完整课时；每个课时用 1—3 条简洁课时目标说明本课时要达成什么，并至少安排 2 个活动。每个活动包含教师组织、学生至少 3 步操作、记录/产出，并将“设计意图”放在活动最后；每个课时包含课时小结和课后任务。正式评价标准、评价表与多元评价只写在文末“教学评价”章节。禁止使用“略”“同上”“后续课时”“视情况而定”。只输出 Markdown 教学过程和教学评价，不要解释。

当前检查问题：
{error_text}

已有前半部分（只用于理解主题和年级）：
{markdown}
"""


def _build_missing_lessons_prompt(
    markdown: str,
    errors: List[str],
    target_lesson: Optional[int] = None,
) -> str:
    """Request one complete replacement for the first incomplete lesson."""
    headings = list(
        re.finditer(
            r"^###\s+第\s*([0-9一二三四五六]+)\s*课时[^\n]*$",
            markdown,
            re.MULTILINE,
        )
    )
    existing_count = len(headings)
    if target_lesson is None:
        target_lesson = existing_count + 1
        for index, heading in enumerate(headings, start=1):
            title = heading.group(0)
            if any(title in error for error in errors):
                target_lesson = index
                break

    target_context = ""
    if 1 <= target_lesson <= existing_count:
        start = headings[target_lesson - 1].start()
        end = headings[target_lesson].start() if target_lesson < existing_count else len(markdown)
        target_context = markdown[start:end].strip()[:3500]
    else:
        target_context = markdown[-1800:].strip()

    error_text = "\n".join(f"- {error}" for error in errors)
    return f"""下面的 STEM 教案中，第 {target_lesson} 课时内容不完整。

请继续补写缺失课时，从第 {target_lesson} 课时开始，直到该课时完整。只输出第 {target_lesson} 课时的完整 Markdown 替换稿，不要输出其他课时，也不要重复标题、导言或概述。该课时用 1—3 条简洁课时目标说明本课时要达成什么，并至少包含 2 个教学活动。每个活动写清教师组织、学生至少 3 步操作、记录/产出，并把“设计意图”放在该活动最后；同时包含课时小结和课后任务。不要在课时内生成正式评价表或总评标准；它们统一属于文末“教学评价”。禁止“略”“同上”“后续课时”“视情况而定”。

当前问题：
{error_text}

需要修复的课时上下文：
{target_context}
"""


def _extract_lesson_fragment(markdown: str, lesson_number: int) -> str:
    """Keep only the requested lesson when a repair response includes extras."""
    chinese_numbers = "一二三四五六"
    expected = (
        f"(?:{lesson_number}|{chinese_numbers[lesson_number - 1]})"
        if 1 <= lesson_number <= len(chinese_numbers)
        else str(lesson_number)
    )
    match = re.search(
        rf"^###\s+第\s*{expected}\s*课时[^\n]*$",
        markdown,
        re.MULTILINE,
    )
    if not match:
        return markdown.strip()
    next_heading = re.search(r"^###\s+第\s*[0-9一二三四五六]+\s*课时[^\n]*$", markdown[match.end():], re.MULTILINE)
    end = match.end() + next_heading.start() if next_heading else len(markdown)
    return markdown[match.start():end].strip()


_ORDERED_SECTIONS = [
    ("课程信息", ("课程信息", "基本信息")),
    ("学情分析", ("学情分析",)),
    ("教学目标", ("教学目标",)),
    ("教学重点与难点", ("教学重点与难点", "教学重难点")),
    ("教学资源", ("教学资源",)),
    ("教学过程", ("教学过程",)),
    ("教学评价", ("教学评价", "评价与总结", "评价总结")),
]


def _section_match(text: str, aliases) -> Optional[re.Match]:
    pattern = r"^##\s+(?:" + "|".join(map(re.escape, aliases)) + r")(?:\s|（|\(|$)"
    return re.search(pattern, text, re.MULTILINE)


def _build_structure_completion_prompt(markdown: str, errors: List[str]) -> str:
    """Ask only for missing top-level sections, avoiding a full rewrite."""
    missing = [
        error.split("：", 1)[1]
        for error in errors
        if error.startswith("缺少必要章节：")
    ]
    requested = "、".join(missing) or "需要调整的课程章节"
    return f"""下面的 STEM 教案教学过程已经完整，但课前或课后章节不完整。

请只输出缺失章节：{requested}。使用“## 章节名”的 Markdown 二级标题，并按“课程信息→学情分析→教学目标→教学重点与难点→教学资源→教学评价”的相对顺序输出。不要重写已有章节，不要输出任何分课时内容。课程信息应包含课程名称、适用学段与具体年级、课时安排、课程类型、设计理念、学科与核心素养关联。教学评价应集中给出教师评价、学生自评、组内互评或展示互评及可操作的评价维度。

当前检查问题：
{chr(10).join(f'- {error}' for error in errors)}

已有教案摘要（仅用于保持主题一致）：
{markdown[:3000]}
"""


def _merge_supplemental_sections(
    markdown: str,
    supplement: str,
    errors: List[str],
) -> str:
    """Insert model-generated missing sections at their canonical positions."""
    result = markdown.strip()
    missing = {
        error.split("：", 1)[1]
        for error in errors
        if error.startswith("缺少必要章节：")
    }
    canonical_names = [name for name, _ in _ORDERED_SECTIONS]
    for canonical, aliases in _ORDERED_SECTIONS:
        if canonical not in missing or _section_match(result, aliases):
            continue
        source_match = _section_match(supplement, aliases)
        if not source_match:
            continue
        next_source = re.search(
            r"^##\s+",
            supplement[source_match.end():],
            re.MULTILINE,
        )
        source_end = (
            source_match.end() + next_source.start()
            if next_source
            else len(supplement)
        )
        block = supplement[source_match.start():source_end].strip()

        insertion = None
        current_index = canonical_names.index(canonical)
        for _, later_aliases in _ORDERED_SECTIONS[current_index + 1:]:
            later_match = _section_match(result, later_aliases)
            if later_match:
                insertion = later_match.start()
                break
        if canonical == "教学评价":
            safety = re.search(r"^##\s+安全提示(?:\s|$)", result, re.MULTILINE)
            insertion = safety.start() if safety else None

        if insertion is None:
            result = result.rstrip() + "\n\n" + block
        else:
            result = (
                result[:insertion].rstrip()
                + "\n\n"
                + block
                + "\n\n"
                + result[insertion:].lstrip()
            )
    return result


def _validate_section_structure(markdown: str) -> List[str]:
    """Check the required top-level course sections and their order."""
    text = (markdown or "").strip()
    positions = {}
    errors: List[str] = []
    for canonical, aliases in _ORDERED_SECTIONS:
        match = _section_match(text, aliases)
        if match:
            positions[canonical] = match.start()
        else:
            errors.append(f"缺少必要章节：{canonical}")

    ordered = [name for name, _ in _ORDERED_SECTIONS if name in positions]
    if ordered != sorted(ordered, key=positions.get):
        errors.append("课程章节顺序不符合模板：课程信息、学情分析、教学目标、教学重难点、教学资源应先于教学过程，教学评价应置于教学过程之后")
    lesson_headings = list(
        re.finditer(
            r"^###\s+第\s*[0-9一二三四五六]+\s*课时[^\n]*$",
            text,
            re.MULTILINE,
        )
    )
    if (
        lesson_headings
        and "教学评价" in positions
        and positions["教学评价"] < lesson_headings[-1].end()
    ):
        errors.append("教学评价必须放在全部课时之后，不得插入分课时教学过程")
    return errors


def _validate_plan_quality(markdown: str) -> Dict:
    """Validate the minimum contract for a classroom-ready teaching plan.

    This is intentionally conservative: it catches obvious truncation and
    placeholder lessons, while leaving pedagogical quality judgments to the
    model and teacher. The returned shape is stable for the API and tests.
    """
    text = (markdown or "").strip()
    errors: List[str] = []
    lessons = list(re.finditer(r"^###\s+第\s*([0-9一二三四五六])\s*课时[^\n]*$", text, re.MULTILINE))

    grade_ok = bool(re.search(
        r"适用(?:学段与)?年级[^\n：:]*[：:]?\s*(?:\*\*)?"
        r"(?:小学\s*(?:低段|中段|高段|[一二三四五六1-6](?:年级)?)|"
        r"初中\s*(?:[一二三七八九]|[1-9])?\s*年级|"
        r"高中\s*(?:[一二三]|十?一|十二|[1-3]|10-12)?\s*年级)"
        r"(?:\([^\n]*\)|（[^\n]*）)?",
        text,
        re.IGNORECASE,
    ))
    if not grade_ok:
        # Models often put the grade on the next bold line and use wording
        # such as “初中二年级（八年级）” without repeating the label.
        grade_ok = bool(re.search(
            r"(?:^|\n)\s*\*\*(?:小学\s*(?:低段|中段|高段)|初中\s*(?:[一二三七八九]|[1-9])\s*年级|高中\s*(?:[一二三]|十?一|十二|[1-3])\s*年级)",
            text,
            re.MULTILINE,
        ))
    if not grade_ok:
        errors.append("缺少明确的适用年级（例如“初中八年级”）")

    if len(lessons) < 3:
        errors.append(f"完整教学过程至少需要 3 个课时，当前仅检测到 {len(lessons)} 个")
    if len(lessons) > 6:
        errors.append(f"教学过程最多 6 个课时，当前检测到 {len(lessons)} 个")

    # Only enforce the complete document structure once the lesson count is
    # sufficient; short drafts are handled by the targeted lesson repair flow.
    if len(lessons) >= 3:
        errors.extend(_validate_section_structure(text))

    marker_hits = [marker for marker in _INCOMPLETE_PLAN_MARKERS if marker in text]
    # “略” is only a placeholder when it appears as a standalone token; it is
    # also a character in normal words such as “策略”, so substring matching
    # would reject otherwise valid plans.
    if re.search(r"(?:^|[\n（(])\s*略\s*(?:$|[\n）)])", text):
        marker_hits.append("略")
    if marker_hits:
        errors.append("包含省略或占位表达：" + "、".join(marker_hits))

    lesson_reports = []
    for index, match in enumerate(lessons):
        start = match.start()
        end = lessons[index + 1].start() if index + 1 < len(lessons) else len(text)
        body = text[start:end].strip()
        body_errors: List[str] = []
        if len(body) < 280:
            body_errors.append("课时内容过短，缺少可执行细节")
        activity_count = len(re.findall(r"(?:活动|环节)\s*[一二三四五六1-6]", body))
        if activity_count < 2:
            # Some model outputs use numbered bullets rather than 活动一.
            activity_count = len(re.findall(r"(?:^|\n)\s*[-*]\s*活动", body))
        if activity_count < 2:
            body_errors.append("至少需要 2 个教学活动或环节")
        if not re.search(r"设计意图", body):
            body_errors.append("缺少设计意图")
        if not re.search(r"课时小结", body):
            body_errors.append("缺少课时小结")
        if not re.search(r"课后任务", body):
            body_errors.append("缺少课后任务")
        if not re.search(r"教师|学生", body) or not re.search(r"(?:记录|产出|提交|数据)", body):
            body_errors.append("未同时说明师生活动及记录/产出")
        lesson_reports.append({"title": match.group(0), "length": len(body), "activity_count": activity_count, "errors": body_errors})
        errors.extend([f"{match.group(0)}：{error}" for error in body_errors])

    return {
        "ok": not errors,
        "errors": errors,
        "lesson_count": len(lessons),
        "lesson_reports": lesson_reports,
        "has_grade": grade_ok,
        "marker_hits": marker_hits,
    }


# NOTE: system prompt 与 user message 的构造已迁移到 agents/teaching_plan_skill.py，
# 通过 generate_teaching_plan 中的 build_system_prompt / build_user_message 调用。


def _call_llm(system_prompt: str, user_message: str, max_tokens: int) -> tuple:
    """Call DeepSeek V3 via SiliconFlow API."""
    config = _resolve_llm_config()
    if not config["api_key"]:
        raise RuntimeError(
            "未配置模型 API key。请设置 SILICONFLOW_API_KEY 或 DASHSCOPE_API_KEY。"
        )
    resp = requests.post(
        config["url"],
        json={
            "model": config["model"],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            "max_tokens": max_tokens,
            "temperature": 0.7,
            "top_p": 0.9,
        },
        headers={"Authorization": f"Bearer {config['api_key']}"},
        timeout=LLM_TIMEOUT
    )

    if resp.status_code != 200:
        raise RuntimeError(f"LLM API error: {resp.status_code} {resp.text[:300]}")

    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    return content, data


def _parse_plan(markdown: str, user_query: str, grade_level: str) -> Dict:
    """Parse the generated markdown into structured data."""
    # Extract title: 优先取第一个 # 一级标题（新模板的项目标题），回退到「项目名片」表（旧模板）
    title = user_query
    for m in re.finditer(r'^#\s+(.+)$', markdown, re.MULTILINE):
        t = m.group(1).strip()
        if t and not re.match(r'第[一二两]大块|前置知识|学习流程', t):
            title = t
            break
    if title == user_query:
        name_match = re.search(r'\|\s*项目名称\s*\|\s*(.+?)\s*\|', markdown)
        if name_match:
            title = name_match.group(1).strip()

    # Extract sections
    sections = []
    current_section = None

    for line in markdown.split('\n'):
        section_match = re.match(r'^(#{1,3})\s+(.+)$', line)
        if section_match:
            if current_section:
                sections.append(current_section)
            level = len(section_match.group(1))
            current_section = {
                "title": section_match.group(2),
                "level": level,
                "content": ""
            }
        elif current_section is not None:
            current_section["content"] += line + "\n"

    if current_section:
        sections.append(current_section)

    # Estimate difficulty from content
    difficulty = 2
    content_lower = markdown.lower()
    if any(kw in content_lower for kw in ["高中", "微积分", "量子", "dna", "机器学习"]):
        difficulty = 4
    elif any(kw in content_lower for kw in ["初中", "arduino", "python", "回归", "化学"]):
        difficulty = 3

    # Detect subjects
    subjects = []
    for subject in STEM_SUBJECTS:
        if subject in markdown:
            subjects.append(subject)

    # Detect 3D print opportunities
    has_3d_print = any(kw in markdown for kw in ["3D打印", "3d打印", "STL", "三维模型", "打印件"])

    # Estimate duration
    duration_match = re.search(r'(\d+)[\-~](\d+)\s*(课时|小时|分钟)', markdown)
    estimated_duration = duration_match.group(0) if duration_match else "4-6课时"

    return {
        "title": title,
        "user_query": user_query,
        "grade_level": grade_level,
        "difficulty": difficulty,
        "subjects": subjects,
        "has_3d_print": has_3d_print,
        "estimated_duration": estimated_duration,
        "markdown": markdown,
        "sections": sections,
        "word_count": len(markdown)
    }


def get_bubble_topics() -> List[Dict]:
    """Return the 12 predefined bubble topics for the homepage."""
    return BUBBLE_TOPICS


if __name__ == "__main__":
    # Quick test
    query = "我想学习如何做一个自动感应夜灯，天黑自动亮的那种"
    print(f"Generating plan for: {query}")
    print("=" * 60)

    result = generate_teaching_plan(query, grade_level="小学高段", include_3d_print=True)
    print(f"Title: {result['title']}")
    print(f"Difficulty: {result['difficulty']}")
    print(f"Subjects: {result['subjects']}")
    print(f"3D Print: {result['has_3d_print']}")
    print(f"Duration: {result['estimated_duration']}")
    print(f"Word count: {result['word_count']}")
    print(f"\nFirst 500 chars:\n{result['markdown'][:500]}")
