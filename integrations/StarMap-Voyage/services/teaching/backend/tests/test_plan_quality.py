import agents.plan_generator as plan_generator
import inspect
from agents.plan_generator import (
    _normalize_plan_markdown,
    _validate_plan_quality,
    _validate_section_structure,
    _resolve_llm_config,
)
from agents.teaching_plan_skill import build_system_prompt


def test_prompt_requires_grade_specific_and_executable_lesson_design():
    prompt = build_system_prompt("初中", None, True)

    assert "具体年级" in prompt
    assert "怎么做" in prompt
    assert "设计意图必须放在该环节最后" in prompt
    assert "每个课时都必须完整展开" in prompt


def test_prompt_requires_course_information_before_lessons_and_evaluation_after():
    prompt = build_system_prompt("初中", None, True)

    assert prompt.index("## 课程信息") < prompt.index("## 学情分析")
    assert prompt.index("## 教学资源") < prompt.index("## 教学过程（分课时）")
    assert prompt.index("## 教学过程（分课时）") < prompt.index("## 教学评价")
    assert "每个活动包含教师组织、学生至少 3 步操作、记录/产出" in prompt
    assert "每个活动至少给出 3 个连续可执行步骤" in prompt
    assert "每个活动至少包含评价标准" not in prompt


def test_section_structure_requires_ordered_course_sections():
    markdown = """# 项目

## 学情分析
内容

## 课程信息
内容

## 教学过程（分课时）
### 第1课时：主题
内容

## 教学评价
内容
"""

    errors = _validate_section_structure(markdown)

    assert any("课程信息" in error for error in errors)
    assert any("教学资源" in error for error in errors)
    assert any("顺序" in error for error in errors)


def test_section_structure_requires_evaluation_after_all_lessons():
    markdown = """# 项目

## 课程信息
内容
## 学情分析
内容
## 教学目标
内容
## 教学重点与难点
内容
## 教学资源
内容
## 教学过程
## 教学评价
内容
### 第1课时：主题
内容
"""

    errors = _validate_section_structure(markdown)

    assert any("全部课时之后" in error for error in errors)


def test_llm_config_uses_dashscope_when_siliconflow_key_is_unset(monkeypatch):
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-test-key")

    config = _resolve_llm_config()

    assert config["api_key"] == "dashscope-test-key"
    assert config["url"].startswith("https://dashscope.aliyuncs.com/")
    assert config["model"] == "qwen-plus"


def test_normalize_plan_resets_ordered_lists_at_each_major_heading():
    markdown = """# 项目

## 教学目标
1. 目标一
2. 目标二

## 教学过程
4. 活动一
5. 活动二
"""

    normalized = _normalize_plan_markdown(markdown, "初中", "项目")

    assert "## 适用学段与年级" in normalized
    assert "## 教学目标\n1. 目标一\n2. 目标二" in normalized
    assert "## 教学过程\n1. 活动一\n2. 活动二" in normalized


def test_normalize_recognizes_grade_heading_with_markdown_trailing_spaces():
    markdown = "# 项目\n\n## 适用学段与年级  \n**初中二年级（八年级）**"

    normalized = _normalize_plan_markdown(markdown, "初中", "项目")
    report = _validate_plan_quality(normalized)

    assert normalized.count("## 适用学段与年级") == 1
    assert report["has_grade"] is True


def test_incomplete_plan_is_rejected_when_later_lessons_are_placeholder():
    markdown = """# 光影魔术师

## 适用学段与年级
适用年级：初中八年级

## 教学过程（分课时）
### 第1课时：折射
- 活动设计：教师演示，学生测量并记录数据，形成实验表。
- 设计意图：建立问题情境。
- 课时小结：完成记录。
### 第2课时：透镜
（后续课时同样详细展开）
"""

    report = _validate_plan_quality(markdown)

    assert report["ok"] is False
    assert any("省略" in error or "课时" in error for error in report["errors"])


def test_complete_plan_passes_quality_gate():
    lesson = """### 第{n}课时：主题
- 课时目标：理解核心概念并完成测量。
- 活动一（15分钟）：教师先展示装置并说明变量，示范一次完整操作并强调安全边界；学生按顺序摆放材料、操作三次、记录每次读数和异常情况；产出包含变量、步骤、数据和单位的实验记录表；教师追问“为什么只改变一个变量”，学生依据记录回答；设计意图：建立可观察证据。
- 活动二（20分钟）：教师提供操作清单并巡视追问，要求各组先预测再动手；学生分组改变一个变量、重复测量、比较结果并计算平均值，最后用证据支持或修正预测；产出小组结论卡和一张带标注的结果图；教师根据评分标准检查操作顺序、数据完整性和结论对应关系；设计意图：训练控制变量。
- 课时小结：学生用三句话复述发现并提交记录。
- 课后任务：整理数据并写出一个新问题。
"""
    markdown = "# 光影魔术师\n\n## 课程信息\n学科与主题：光的折射\n\n## 学情分析\n已掌握光的直线传播。\n\n## 教学目标\n能够完成折射实验。\n\n## 教学重点与难点\n重点是控制变量。\n\n## 教学资源\n激光笔、水槽、量角器。\n\n## 适用学段与年级\n适用年级：初中八年级\n\n## 教学过程（分课时）\n" + "\n".join(lesson.format(n=n) for n in (1, 2, 3)) + "\n\n## 教学评价\n教师评价表、学生自评与展示互评。"

    report = _validate_plan_quality(markdown)

    assert report["ok"] is True
    assert report["errors"] == []


def test_quality_gate_does_not_treat_normal_word_containing_lue_as_placeholder():
    report = _validate_plan_quality(_complete_plan().replace("光影魔术师", "光影策略设计"))

    assert "略" not in report["marker_hits"]


def _complete_plan():
    lesson = """### 第{n}课时：主题
- 课时目标：理解核心概念并完成测量。
- 活动一（15分钟）：教师先展示装置并说明变量，示范一次完整操作并强调安全边界；学生按顺序摆放材料、操作三次、记录每次读数和异常情况；产出包含变量、步骤、数据和单位的实验记录表；教师追问“为什么只改变一个变量”，学生依据记录回答；设计意图：建立可观察证据。
- 活动二（20分钟）：教师提供操作清单并巡视追问，要求各组先预测再动手；学生分组改变一个变量、重复测量、比较结果并计算平均值，最后用证据支持或修正预测；产出小组结论卡和一张带标注的结果图；教师根据评分标准检查操作顺序、数据完整性和结论对应关系；设计意图：训练控制变量。
- 课时小结：学生用三句话复述发现并提交记录。
- 课后任务：整理数据并写出一个新问题。
"""
    return "# 光影魔术师\n\n## 课程信息\n学科与主题：光的折射\n\n## 学情分析\n已掌握光的直线传播。\n\n## 教学目标\n能够完成折射实验。\n\n## 教学重点与难点\n重点是控制变量。\n\n## 教学资源\n激光笔、水槽、量角器。\n\n## 适用学段与年级\n适用年级：初中八年级\n\n## 教学过程（分课时）\n" + "\n".join(lesson.format(n=n) for n in (1, 2, 3)) + "\n\n## 教学评价\n教师评价表、学生自评与展示互评。"


def test_generation_revises_short_model_output_and_caches_only_valid_result(monkeypatch):
    short = "# 光影魔术师\n\n## 教学过程\n### 第1课时：导入\n活动：教师讲解，学生讨论。\n### 第2课时：探究\n（后续课时同样详细展开）"
    calls = []

    monkeypatch.setattr(plan_generator, "retrieve_fewshot_examples", lambda *args: [])
    monkeypatch.setattr(plan_generator, "retrieve_relevant_sections", lambda *args: [])

    def fake_call(system, user, max_tokens):
        calls.append(user)
        return (short if len(calls) == 1 else _complete_plan(), {})

    monkeypatch.setattr(plan_generator, "_call_llm", fake_call)
    plan_generator._plan_cache.clear()

    result = plan_generator.generate_teaching_plan("探索光的折射", grade_level="初中")

    assert len(calls) == 2
    assert result["quality"]["ok"] is True
    assert result["revision_attempted"] is True
    assert len(plan_generator._plan_cache) == 1


def test_generation_respects_disabled_3d_print_option(monkeypatch):
    markdown = _complete_plan().replace(
        "激光笔、水槽、量角器。",
        "激光笔、水槽、量角器和三维模型。",
    )
    monkeypatch.setattr(plan_generator, "retrieve_fewshot_examples", lambda *args: [])
    monkeypatch.setattr(plan_generator, "retrieve_relevant_sections", lambda *args: [])
    monkeypatch.setattr(plan_generator, "_call_llm", lambda *args: (markdown, {}))
    plan_generator._plan_cache.clear()

    result = plan_generator.generate_teaching_plan(
        "探索光的折射",
        grade_level="初中",
        include_3d_print=False,
    )

    assert result["has_3d_print"] is False


def test_repair_calls_use_a_larger_budget_for_complete_lesson_content(monkeypatch):
    short = "# 项目\n\n## 教学过程\n### 第1课时：导入\n活动：教师讲解，学生讨论。"
    calls = []

    monkeypatch.setattr(plan_generator, "retrieve_fewshot_examples", lambda *args: [])
    monkeypatch.setattr(plan_generator, "retrieve_relevant_sections", lambda *args: [])

    def fake_call(system, user, max_tokens):
        calls.append((user, max_tokens))
        return (short if len(calls) == 1 else _complete_plan(), {})

    monkeypatch.setattr(plan_generator, "_call_llm", fake_call)
    plan_generator._plan_cache.clear()

    result = plan_generator.generate_teaching_plan("探究光的折射", grade_level="初中")

    assert result["quality"]["ok"] is True
    assert calls[1][1] >= 5000


def test_truncated_intro_requests_only_missing_lesson_section(monkeypatch):
    intro = _complete_plan().split("## 教学过程（分课时）", 1)[0]
    calls = []

    monkeypatch.setattr(plan_generator, "retrieve_fewshot_examples", lambda *args: [])
    monkeypatch.setattr(plan_generator, "retrieve_relevant_sections", lambda *args: [])

    def fake_call(system, user, max_tokens):
        calls.append(user)
        return (intro if len(calls) == 1 else _complete_plan().split("## 教学过程（分课时）", 1)[1], {})

    monkeypatch.setattr(plan_generator, "_call_llm", fake_call)
    plan_generator._plan_cache.clear()

    result = plan_generator.generate_teaching_plan("纸桥承重挑战赛", grade_level="初中")

    assert len(calls) == 2
    assert "不要重复标题、导言、概述" in calls[1]
    assert result["quality"]["ok"] is True
    assert result["markdown"].count("## 适用学段与年级") == 1


def test_partial_lessons_are_completed_incrementally(monkeypatch):
    first = _complete_plan().split("### 第2课时：主题", 1)[0]
    calls = []

    monkeypatch.setattr(plan_generator, "retrieve_fewshot_examples", lambda *args: [])
    monkeypatch.setattr(plan_generator, "retrieve_relevant_sections", lambda *args: [])

    def fake_call(system, user, max_tokens):
        calls.append(user)
        if len(calls) == 1:
            return first, {}
        return _complete_plan().split("### 第2课时：主题", 1)[1], {}

    monkeypatch.setattr(plan_generator, "_call_llm", fake_call)
    plan_generator._plan_cache.clear()
    result = plan_generator.generate_teaching_plan("纸桥承重", grade_level="初中")

    assert len(calls) == 2
    assert "继续补写缺失课时" in calls[1]
    assert result["quality"]["lesson_count"] >= 3


def test_repair_replaces_truncated_lesson_instead_of_appending_duplicate(monkeypatch):
    complete = _complete_plan()
    first = (
        complete.split("### 第2课时：主题", 1)[0]
        + "\n### 第2课时：主题\n- 课时目标：内容被截断。"
    )
    replacement = complete.split("### 第2课时：主题", 1)[1]
    calls = []

    monkeypatch.setattr(plan_generator, "retrieve_fewshot_examples", lambda *args: [])
    monkeypatch.setattr(plan_generator, "retrieve_relevant_sections", lambda *args: [])

    def fake_call(system, user, max_tokens):
        calls.append(user)
        return (first if len(calls) == 1 else "### 第2课时：主题" + replacement, {})

    monkeypatch.setattr(plan_generator, "_call_llm", fake_call)
    plan_generator._plan_cache.clear()

    result = plan_generator.generate_teaching_plan("纸桥承重", grade_level="初中")

    assert len(calls) == 2
    assert result["quality"]["ok"] is True
    assert result["markdown"].count("### 第2课时：主题") == 1


def test_structure_repair_uses_complete_replacement_without_inventing_lesson(monkeypatch):
    complete = _complete_plan()
    missing_resources = complete.replace(
        "## 教学资源\n激光笔、水槽、量角器。\n\n",
        "",
    )
    calls = []

    monkeypatch.setattr(plan_generator, "retrieve_fewshot_examples", lambda *args: [])
    monkeypatch.setattr(plan_generator, "retrieve_relevant_sections", lambda *args: [])

    def fake_call(system, user, max_tokens):
        calls.append(user)
        return (missing_resources if len(calls) == 1 else complete, {})

    monkeypatch.setattr(plan_generator, "_call_llm", fake_call)
    plan_generator._plan_cache.clear()

    result = plan_generator.generate_teaching_plan("纸桥承重", grade_level="初中")

    assert len(calls) == 2
    assert result["quality"]["ok"] is True
    assert result["quality"]["lesson_count"] == 3
    assert "第4课时：补充探究" not in result["markdown"]


def test_structure_repair_requests_only_missing_sections_and_merges_them(monkeypatch):
    complete = _complete_plan()
    missing = complete.replace(
        "## 教学重点与难点\n重点是控制变量。\n\n## 教学资源\n激光笔、水槽、量角器。\n\n",
        "",
    )
    supplement = """## 教学重点与难点
1. 教学重点：控制变量。
2. 教学难点：依据数据解释现象。

## 教学资源
激光笔、水槽、量角器和实验记录单。
"""
    calls = []

    monkeypatch.setattr(plan_generator, "retrieve_fewshot_examples", lambda *args: [])
    monkeypatch.setattr(plan_generator, "retrieve_relevant_sections", lambda *args: [])

    def fake_call(system, user, max_tokens):
        calls.append(user)
        return (missing if len(calls) == 1 else supplement, {})

    monkeypatch.setattr(plan_generator, "_call_llm", fake_call)
    plan_generator._plan_cache.clear()

    result = plan_generator.generate_teaching_plan("纸桥承重", grade_level="初中")

    assert len(calls) == 2
    assert "只输出缺失章节" in calls[1]
    assert result["quality"]["ok"] is True
    assert result["markdown"].index("## 教学资源") < result["markdown"].index("## 教学过程")


def test_generation_continues_when_optional_rag_retrieval_is_unavailable(monkeypatch):
    monkeypatch.setattr(plan_generator, "retrieve_fewshot_examples", lambda *args: (_ for _ in ()).throw(RuntimeError("missing index")))
    monkeypatch.setattr(plan_generator, "retrieve_relevant_sections", lambda *args: (_ for _ in ()).throw(RuntimeError("invalid embedding key")))
    monkeypatch.setattr(plan_generator, "_call_llm", lambda *args: (_complete_plan(), {}))
    plan_generator._plan_cache.clear()

    result = plan_generator.generate_teaching_plan("探究光的折射", grade_level="初中")

    assert result["quality"]["ok"] is True


def test_optional_rag_is_skipped_without_embedding_credentials(monkeypatch):
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    called = []
    monkeypatch.setattr(plan_generator, "retrieve_fewshot_examples", lambda *args: called.append("fewshot"))
    monkeypatch.setattr(plan_generator, "retrieve_relevant_sections", lambda *args: called.append("sections"))

    assert plan_generator._safe_retrieve_fewshot("主题") == []
    assert plan_generator._safe_retrieve_sections("主题") == []
    assert called == []


def test_generation_route_does_not_block_fastapi_event_loop():
    from api_server import api_generate_plan

    assert inspect.iscoroutinefunction(api_generate_plan) is False


def test_default_generation_budget_is_bounded_for_interactive_requests():
    signature = inspect.signature(plan_generator.generate_teaching_plan)

    assert signature.parameters["max_tokens"].default <= 2500
