"""Gemini-powered skill extraction from failed task traces."""

import json
import uuid
from typing import Optional

from google import genai
from google.genai import types

from yunaki_skills.config import get
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


class SkillExtractor(SkillExtractor):
    """Gemini-powered skill extraction from traces."""

    def __init__(self):
        api_key = get("GEMINI_API_KEY")
        self._client = genai.Client(api_key=api_key)
        self._model = "gemini-2.5-flash"

    def extract(self, task_description: str, trace: str, eval_result: EvalResult) -> Optional[Skill]:
        """Analyze a failed task execution and extract a reusable skill.
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

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    response_mime_type="application/json",
                ),
            )

            text = response.text.strip()
            if not text:
                return None

            # Parse the JSON response
            data = json.loads(text)

            # Build the Skill object from parsed JSON
            trigger_data = data.get("trigger", {})
            trigger = Trigger(
                type=TriggerType(trigger_data.get("type", "semantic")),
                patterns=trigger_data.get("patterns", []),
                query=trigger_data.get("query", ""),
                match_on=TriggerMatchOn(trigger_data.get("match_on", "task_description")),
            )

            trace_id = f"trace_{uuid.uuid4().hex[:12]}"

            provenance = Provenance(
                created_from=trace_id,
                task=task_description,
                iteration=1,
                parent_skill=None,
                merged_from=[],
                evolved_at="",
            )

            skill = Skill(
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

            return skill

        except (json.JSONDecodeError, ValueError, KeyError, Exception) as e:
            # If extraction fails for any reason, return None
            print(f"[SkillExtractor] Failed to extract skill: {e}")
            return None
