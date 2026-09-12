"""
Adaptive Difficulty Assessment Agent.
Generates a quick knowledge quiz before project entry,
then adjusts teaching plan difficulty based on results.
"""
import json
import os
import re
import sys
import time
from typing import Dict, List, Optional, Tuple

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.llm_config import resolve_chat_config

# ---- Config ----
_LLM_CONFIG = resolve_chat_config()
LLM_API_URL = _LLM_CONFIG["url"]
LLM_MODEL = _LLM_CONFIG["model"]
API_KEY = _LLM_CONFIG["api_key"]


class DifficultyAdapter:
    """Generates knowledge quizzes and adjusts teaching plan difficulty."""

    def __init__(self):
        self._quiz_cache: Dict[str, tuple] = {}
        self._cache_ttl = 600  # 10 min

    def generate_quiz(self, topic: str, grade_level: str, num_questions: int = 5) -> Dict:
        """Generate a quick knowledge assessment quiz."""
        # Check cache
        import time
        cache_key = f"{topic}|{grade_level}"
        if cache_key in self._quiz_cache:
            cached, t = self._quiz_cache[cache_key]
            if time.time() - t < self._cache_ttl:
                return cached

        grade_desc = {
            "小学低段": "小学1-2年级", "小学中段": "小学3-4年级",
            "小学高段": "小学5-6年级", "初中": "初中7-9年级", "高中": "高中10-12年级"
        }.get(grade_level, grade_level)

        prompt = f"""你是一位STEM教育评估专家。请为一位{grade_desc}的学生生成{num_questions}道知识测评题。

学生想学习的主题: {topic}

要求：
1. 题目覆盖该主题所需的前置知识（科学概念、数学基础、技术基础）
2. 题型为选择题（4个选项），方便快速作答
3. 难度从简单到中等，不要出太难的问题
4. 每道题考察一个具体的前置知识点
5. 返回纯JSON格式（不要markdown代码块标记），包含:
  - topic: 主题
  - grade_level: 学段
  - questions: 题目数组，每个包含:
    - id: 题目编号(q1-q{num_questions})
    - text: 题干
    - options: {{A:, B:, C:, D:}}
    - answer: 正确答案
    - concept: 考察的知识点
    - level: 难度(basic/intermediate)
    - prerequisite_for: 对本项目的作用说明

直接返回JSON:"""

        try:
            resp = requests.post(
                LLM_API_URL,
                json={
                    "model": LLM_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 2048, "temperature": 0.5,
                },
                headers={"Authorization": f"Bearer {API_KEY}"},
                timeout=15
            )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                    self._quiz_cache[cache_key] = (result, time.time())
                    return result
        except Exception as e:
            print(f"Quiz generation failed: {e}")

        # Fallback quiz
        fb = self._fallback_quiz(topic, grade_level, num_questions)
        self._quiz_cache[cache_key] = (fb, time.time())
        return fb

    def assess_results(self, quiz: Dict, user_answers: Dict[str, str]) -> Dict:
        """Analyze quiz results and determine knowledge gaps."""
        questions = quiz.get("questions", [])
        if not questions:
            return {"level": "intermediate", "gaps": [], "score": 100}

        correct = 0
        gaps = []
        details = []

        for q in questions:
            qid = q.get("id", "")
            user_ans = user_answers.get(qid, "").upper()
            correct_ans = q.get("answer", "").upper()
            is_correct = user_ans == correct_ans

            if is_correct:
                correct += 1
            else:
                gaps.append(q.get("concept", ""))

            details.append({
                "question_id": qid,
                "concept": q.get("concept", ""),
                "correct": is_correct,
                "user_answer": user_ans,
                "correct_answer": correct_ans,
                "prerequisite_for": q.get("prerequisite_for", "")
            })

        total = len(questions)
        score = round(correct / total * 100) if total > 0 else 100

        # Determine level
        if score >= 80:
            level = "advanced"
        elif score >= 60:
            level = "intermediate"
        elif score >= 40:
            level = "basic"
        else:
            level = "beginner"

        return {
            "score": score,
            "correct_count": correct,
            "total_count": total,
            "level": level,
            "knowledge_gaps": list(set(gaps)),
            "detail": details
        }

    def generate_prerequisites(self, gaps: List[str], topic: str,
                                grade_level: str) -> str:
        """Generate prerequisite knowledge content for identified gaps."""
        if not gaps:
            return ""

        prompt = f"""请为一位{grade_level}的学生，简要解释以下前置知识点。
学生将要学习的项目: {topic}
需要补充的知识点: {', '.join(gaps)}

要求:
1. 每个知识点用2-3句通俗的话解释
2. 用学生能理解的语言和例子
3. 解释为什么学习项目前需要先懂这个
4. Markdown格式，每个知识点一个小标题

直接返回解释内容:"""

        try:
            resp = requests.post(
                LLM_API_URL,
                json={
                    "model": LLM_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 1024, "temperature": 0.5,
                },
                headers={"Authorization": f"Bearer {API_KEY}"},
                timeout=30
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
        except:
            pass

        return "\n".join([f"### {g}\n在开始项目前，建议先了解这个概念的基本含义。" for g in gaps])

    def inject_prerequisites(self, plan_markdown: str, prerequisites_content: str) -> str:
        """Inject prerequisite knowledge section into the teaching plan."""
        if not prerequisites_content:
            return plan_markdown

        prereq_section = f"""## 📚 课前准备：你需要先了解这些

根据你的知识测评结果，在开始项目之前，建议先看看这些知识点：

{prerequisites_content}

---

"""
        # Insert after the first ## section (usually 项目名片 or overview)
        match = re.search(r'(## .+?\n\n)', plan_markdown)
        if match:
            pos = match.end()
            return plan_markdown[:pos] + prereq_section + plan_markdown[pos:]
        else:
            return prereq_section + plan_markdown

    def _fallback_quiz(self, topic: str, grade_level: str, num: int) -> Dict:
        """Generate a simple fallback quiz."""
        questions = []
        concepts = ["基础科学概念", "数学基础", "动手能力", "逻辑思维", "观察能力"]
        for i in range(num):
            questions.append({
                "id": f"q{i+1}",
                "text": f"关于{topic}，你是否了解{concepts[i]}？",
                "options": {"A": "非常了解", "B": "基本了解", "C": "听说过", "D": "不了解"},
                "answer": "B",
                "concept": concepts[i],
                "level": "basic",
                "prerequisite_for": f"理解{topic}的基础"
            })
        return {"topic": topic, "grade_level": grade_level, "questions": questions}


if __name__ == "__main__":
    adapter = DifficultyAdapter()
    quiz = adapter.generate_quiz("智能自动浇花系统", "初中")
    print(json.dumps(quiz, ensure_ascii=False, indent=2)[:1000])
