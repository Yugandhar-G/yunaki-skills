"""Skill retrieval — combines semantic + pattern matching + prompt injection."""

from yunaki_skills.interfaces import Skill, SkillRetriever
from yunaki_skills.skill_bank import SkillBank


class SkillRetriever(SkillRetriever):
    """Combines semantic + pattern skill retrieval with prompt injection."""

    def __init__(self, bank: SkillBank = None):
        self._bank = bank if bank is not None else SkillBank()

    def retrieve_for_task(self, task_description: str) -> list[Skill]:
        """Get task-level skills via semantic search."""
        return self._bank.search_semantic(task_description)

    def check_triggers(self, agent_output: str) -> list[Skill]:
        """Get event-driven skills whose patterns match the output."""
        return self._bank.search_pattern(agent_output)

    def inject_skills(self, system_prompt: str, skills: list[Skill]) -> str:
        """Format skills as markdown blocks and append to system prompt."""
        if not skills:
            return system_prompt

        skill_blocks = []
        skill_blocks.append("\n\n# 🎯 Active Skills\n")
        skill_blocks.append("The following skills have been activated for this task. Follow their instructions:\n")

        for skill in skills:
            lines = [
                f"## {skill.title} (v{skill.version}, score: {skill.score:.0f})",
                f"**When to apply:** {skill.when_to_apply}",
                "**Instructions:**",
            ]
            for i, instruction in enumerate(skill.instructions, 1):
                lines.append(f"{i}. {instruction}")
            lines.append("")  # blank line between skills
            skill_blocks.append("\n".join(lines))

        skill_blocks.append("---\n")

        return system_prompt + "\n".join(skill_blocks)
