"""Gemini-powered skill extraction from failed task traces."""

import json
import uuid
from typing import Optional

from yunaki_skills import skill_llm
from yunaki_skills.interfaces import (
    EvalResult,
    Granularity,
    Provenance,
    Skill,
    SkillExtractor,
    Trigger,
    TriggerMatchOn,
    TriggerType,
)

EXTRACTION_PROMPT = """You are a skill extraction engine for a coding agent. Analyze the following task execution and extract a reusable, actionable skill that would help the agent succeed on similar tasks in the future.

The execution may have PASSED or FAILED:
- If it FAILED, extract a skill that addresses what went wrong so the agent avoids the same mistake next time.
- If it PASSED, extract a skill that captures the winning approach (the pattern that made it work) so it can be reused on similar future tasks.

TASK DESCRIPTION:
{task_description}

EXECUTION TRACE:
{trace}

EVALUATION RESULT:
- Passed: {passed}
- Score: {score}/100
- Details: {details}
- Tests: {tasks_passed}/{tasks_total} passed
- Test output: {test_output}

Based on this failure, extract a reusable skill as JSON with this exact schema:
{{
  "id": "skill_<short_snake_case_name>",
  "title": "<human-readable title>",
  "granularity": "<task-level or event-driven>",
  "version": "0.1",
  "score": 50.0,
  "trigger": {{
    "type": "<semantic for task-level, pattern for event-driven>",
    "patterns": ["<regex>"] ,
    "query": "<semantic search query>",
    "match_on": "<task_description or observation or error>"
  }},
  "when_to_apply": "<when should this skill be applied?>",
  "instructions": ["<step 1>", "<step 2>", ...]
}}

Rules:
- id must start with "skill_" and use snake_case
- instructions should be 2-10 concrete, actionable steps
- If the execution hit an error/exception, use granularity "event-driven" with a pattern trigger matching the error
- Otherwise (logic/implementation work, or a successful approach worth reusing), use granularity "task-level" with a semantic trigger
- trigger.query should capture the intent for semantic search
- trigger.patterns should be regex patterns that match the error text for event-driven skills
- Be specific and practical — the skill should directly address what made this task succeed or fail

Respond with ONLY the JSON object, no markdown formatting, no explanation."""


CONTRASTIVE_PROMPT = """You are a skill extraction engine for a coding agent. You are given TWO execution \
traces for the SAME task: one that PASSED and one that FAILED. Your job is to extract the single most \
valuable reusable skill that captures the DIFFERENCE — what the passing run did right that the failing \
run did not. This contrast is high signal: focus on the specific decision, pattern, or step that \
separated success from failure.

TASK DESCRIPTION:
{task_description}

PASSING TRACE (score {pass_score}/100):
{pass_trace}

FAILING TRACE (score {fail_score}/100):
{fail_trace}

Extract a reusable skill as JSON with this exact schema:
{{
  "id": "skill_<short_snake_case_name>",
  "title": "<human-readable title>",
  "granularity": "<task-level or event-driven>",
  "version": "0.1",
  "score": 60.0,
  "trigger": {{
    "type": "<semantic for task-level, pattern for event-driven>",
    "patterns": ["<regex>"],
    "query": "<semantic search query>",
    "match_on": "<task_description or observation or error>"
  }},
  "when_to_apply": "<when should this skill be applied?>",
  "instructions": ["<step 1>", "<step 2>", ...]
}}

Rules:
- id must start with "skill_" and use snake_case
- instructions must encode the winning behavior the failing run lacked — be concrete and actionable
- Prefer task-level/semantic unless the difference is clearly an error the failing run hit
- Respond with ONLY the JSON object, no markdown formatting, no explanation."""


class SkillExtractor(SkillExtractor):
    """Skill extraction from traces, via the configured skill-model backend."""

    def extract(self, task_description: str, trace: str, eval_result: EvalResult) -> Optional[Skill]:
        """Analyze a single task execution and extract a reusable skill.
        Returns None if no skill can be extracted."""
        prompt = EXTRACTION_PROMPT.format(
            task_description=task_description,
            trace=trace[:8000],  # Limit trace to avoid token limits
            passed=eval_result.passed,
            score=eval_result.score,
            details=eval_result.details,
            tasks_passed=eval_result.tasks_passed,
            tasks_total=eval_result.tasks_total,
            test_output=eval_result.test_output[:2000],
        )
        return self._extract_from_prompt(prompt, task_description)

    def extract_contrastive(
        self,
        task_description: str,
        pass_trace: str,
        fail_trace: str,
        pass_eval: EvalResult,
        fail_eval: EvalResult,
    ) -> Optional[Skill]:
        """Extract the skill that captures the DIFFERENCE between a passing and a
        failing rollout of the same task. Higher signal than a single trace.
        Returns None if no skill can be extracted."""
        prompt = CONTRASTIVE_PROMPT.format(
            task_description=task_description,
            pass_score=pass_eval.score,
            fail_score=fail_eval.score,
            pass_trace=pass_trace[:6000],
            fail_trace=fail_trace[:6000],
        )
        return self._extract_from_prompt(prompt, task_description)

    def _extract_from_prompt(self, prompt: str, task_description: str) -> Optional[Skill]:
        """Run the skill-model on `prompt` and build a Skill from its JSON."""
        try:
            text = (skill_llm.complete_json(prompt) or "").strip()
            if not text:
                return None
            data = json.loads(text)
            return self._build_skill(data, task_description)
        except (json.JSONDecodeError, ValueError, KeyError, Exception) as e:
            # If extraction fails for any reason, return None (fail soft).
            print(f"[SkillExtractor] Failed to extract skill: {e}")
            return None

    @staticmethod
    def _build_skill(data: dict, task_description: str) -> Skill:
        """Construct a Skill from a parsed model JSON object."""
        trigger_data = data.get("trigger", {})
        trigger = Trigger(
            type=TriggerType(trigger_data.get("type", "semantic")),
            patterns=trigger_data.get("patterns", []),
            query=trigger_data.get("query", ""),
            match_on=TriggerMatchOn(trigger_data.get("match_on", "task_description")),
        )

        provenance = Provenance(
            created_from=f"trace_{uuid.uuid4().hex[:12]}",
            task=task_description,
            iteration=1,
            parent_skill=None,
            merged_from=[],
            evolved_at="",
        )

        return Skill(
            id=data.get("id", f"skill_{uuid.uuid4().hex[:8]}"),
            title=data.get("title", "Extracted Skill"),
            granularity=Granularity(data.get("granularity", "task-level")),
            version=data.get("version", "0.1"),
            score=float(data.get("score", 50.0)),
            trigger=trigger,
            when_to_apply=data.get("when_to_apply", ""),
            instructions=data.get("instructions", []),
            provenance=provenance,
        )
