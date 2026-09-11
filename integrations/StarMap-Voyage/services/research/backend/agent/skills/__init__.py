"""技能加载器 — 为 Agent 提供领域专项技能"""

import os
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Skill:
    name: str
    description: str
    triggers: list[str]
    tools: list[str]
    content: str  # 技能工作流描述（System Prompt 注入）
    file_path: str = ""

    def matches(self, user_input: str) -> bool:
        """检查用户输入是否触发此技能"""
        user_lower = user_input.lower()
        for trigger in self.triggers:
            if trigger.lower() in user_lower:
                return True
        return False

    def to_system_prompt(self) -> str:
        """生成用于注入 System Prompt 的技能描述"""
        return f"""## 技能: {self.name}
{self.description}

{self.content}

适用工具: {', '.join(self.tools)}
"""


class SkillLoader:
    """技能加载器：从 skills/ 目录读取所有技能定义"""

    def __init__(self, skills_dir: str = None):
        if skills_dir is None:
            skills_dir = Path(__file__).parent
        self.skills_dir = Path(skills_dir)
        self.skills: dict[str, Skill] = {}
        self._load_all()

    def _load_all(self):
        """加载所有技能文件"""
        for f in sorted(self.skills_dir.glob("*.md")):
            if f.name == "__init__.md":
                continue
            try:
                skill = self._parse_skill_file(f)
                if skill:
                    self.skills[skill.name] = skill
            except Exception:
                continue

    def _parse_skill_file(self, path: Path) -> Optional[Skill]:
        """解析技能 Markdown 文件"""
        text = path.read_text(encoding="utf-8")
        # 解析 YAML frontmatter
        frontmatter = {}
        body_start = 0
        if text.startswith("---"):
            end = text.find("---", 3)
            if end > 0:
                fm_text = text[3:end].strip()
                for line in fm_text.split("\n"):
                    line = line.strip()
                    if ":" in line:
                        key, _, val = line.partition(":")
                        key = key.strip()
                        val = val.strip()
                        if key == "triggers" or key == "tools":
                            frontmatter[key] = [v.strip() for v in val.strip("[]").split(",")]
                        else:
                            frontmatter[key] = val
                body_start = end + 3

        body = text[body_start:].strip()
        if not body or "name" not in frontmatter:
            return None

        return Skill(
            name=frontmatter.get("name", ""),
            description=frontmatter.get("description", ""),
            triggers=frontmatter.get("triggers", []),
            tools=frontmatter.get("tools", []),
            content=body,
            file_path=str(path),
        )

    def match_skill(self, user_input: str) -> Optional[Skill]:
        """根据用户输入匹配最相关的技能"""
        best: Optional[Skill] = None
        best_score = 0
        for skill in self.skills.values():
            score = sum(1 for t in skill.triggers if t.lower() in user_input.lower())
            if score > best_score:
                best_score = score
                best = skill
        return best if best_score > 0 else None

    def get_all_skills_prompt(self) -> str:
        """生成所有技能的摘要 System Prompt"""
        lines = ["## 可用技能\n"]
        for skill in self.skills.values():
            lines.append(f"- **{skill.name}**: {skill.description}")
        return "\n".join(lines)

    def get_skill_list(self) -> list[dict]:
        """返回技能列表（供 API 使用）"""
        return [
            {"name": s.name, "description": s.description,
             "triggers": s.triggers, "tools": s.tools}
            for s in self.skills.values()
        ]


_loader: Optional[SkillLoader] = None


def get_skill_loader() -> SkillLoader:
    global _loader
    if _loader is None:
        _loader = SkillLoader()
    return _loader
