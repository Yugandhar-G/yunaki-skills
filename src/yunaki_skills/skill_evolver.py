"""Skill evolution — refines skills based on new execution evidence."""

import json
import logging
from datetime import datetime, timezone

from yunaki_skills import skill_llm
from yunaki_skills.interfaces import (
    EvalResult,
    Provenance,
    Skill,
    SkillEvolver,
)

logger = logging.getLogger(__name__)

EVOLUTION_PROMPT = """You are a skill evolution engine for a coding agent. An existing skill was applied during a task execution. Reflect on the outcome, then refine and improve the skill so it is more effective next time.

EXISTING SKILL:
{skill_json}

USAGE HISTORY:
- Times applied: {usage_count}
- Times it led to a passing result: {success_count}

NEW EXECUTION TRACE:
{new_trace}

NEW EVALUATION RESULT:
- Passed: {passed}
- Score: {score}/100
- Details: {details}
- Tests: {tasks_passed}/{tasks_total} passed
- Test output: {test_output}

STEP 1 — REFLECT. Before rewriting anything, reason internally about three things:
  (a) What did this skill get RIGHT? Which instructions clearly helped?
  (b) What did it get WRONG or fail to cover? Which part of the task still broke?
  (c) Given the skill was used and the result was as shown above, what SPECIFIC instructions would make this skill more effective?

STEP 2 — REWRITE. Fold the reflection into improved instructions. Return the improved skill as JSON with the same schema:
{{
  "title": "<updated title if needed>",
  "granularity": "<task-level or event-driven>",
  "version": "<incremented version>",
  "score": <0-100 effectiveness score>,
  "trigger": {{
    "type": "<semantic or pattern>",
    "patterns": ["<regex>"],
    "query": "<semantic search query>",
    "match_on": "<task_description or observation or error>"
  }},
  "when_to_apply": "<updated when to apply>",
  "instructions": ["<improved step 1>", "<improved step 2>", ...]
}}

Rules:
- Ground every change in the reflection — keep what worked, fix what failed.
- Add or modify steps to address the specific failure mode in the trace.
- If the trigger patterns missed a relevant error, update them.
- Adjust the score: increase if the new trace shows improvement, decrease if it's worse.
- Increment the version (e.g., "0.1" -> "0.2").
- Keep the same id and granularity unless there's a strong reason to change.
- Be specific and concrete — vague instructions are not useful.

Respond with ONLY the JSON object, no markdown formatting, no explanation."""


class SkillEvolver(SkillEvolver):
    """Skill evolution via the configured skill-model backend."""

    def evolve(self, skill: Skill, new_trace: str, new_eval: EvalResult) -> Skill:
        """Evolve an existing skill based on new execution evidence."""
        prompt = EVOLUTION_PROMPT.format(
            skill_json=skill.model_dump_json(indent=2),
            usage_count=skill.usage_count,
            success_count=skill.success_count,
            new_trace=new_trace[:8000],
            passed=new_eval.passed,
            score=new_eval.score,
            details=new_eval.details,
            tasks_passed=new_eval.tasks_passed,
            tasks_total=new_eval.tasks_total,
            test_output=new_eval.test_output[:2000],
        )

        try:
            text = (skill_llm.complete_json(prompt) or "").strip()
            if not text:
                logger.warning(
                    "Skill evolution got an empty response from the skill model "
                    "(backend=%s) — using minimal fallback for %s",
                    skill_llm.active_model_label(),
                    skill.id,
                )
                return self._fallback_evolve(skill, new_eval)

            data = json.loads(text)

            # Increment version
            old_version = skill.version
            try:
                parts = old_version.split(".")
                new_version = f"{parts[0]}.{int(parts[1]) + 1}"
            except (ValueError, IndexError):
                new_version = data.get("version", old_version)

            # Adjust score based on the new evidence: a full pass earns a bigger
            # bump than partial progress; a complete failure nudges the score down.
            old_score = skill.score
            new_score = float(data.get("score", old_score))
            if new_eval.passed:
                new_score = min(100.0, new_score + 5.0)
            elif new_eval.score > 0:
                new_score = min(100.0, new_score + 2.0)  # partial progress
            else:
                new_score = max(0.0, new_score - 5.0)

            # Build updated trigger
            trigger_data = data.get("trigger", {})
            from yunaki_skills.interfaces import Trigger, TriggerMatchOn, TriggerType

            trigger = Trigger(
                type=TriggerType(trigger_data.get("type", skill.trigger.type)),
                patterns=trigger_data.get("patterns", skill.trigger.patterns),
                query=trigger_data.get("query", skill.trigger.query),
                match_on=TriggerMatchOn(trigger_data.get("match_on", skill.trigger.match_on)),
            )

            now_iso = datetime.now(timezone.utc).isoformat()

            provenance = Provenance(
                created_from=skill.provenance.created_from,
                task=skill.provenance.task,
                iteration=skill.provenance.iteration + 1,
                parent_skill=skill.id,
                merged_from=skill.provenance.merged_from,
                evolved_at=now_iso,
            )

            evolved_skill = Skill(
                id=skill.id,
                title=data.get("title", skill.title),
                granularity=skill.granularity,
                version=new_version,
                score=new_score,
                trigger=trigger,
                when_to_apply=data.get("when_to_apply", skill.when_to_apply),
                instructions=data.get("instructions", skill.instructions),
                provenance=provenance,
                # Carry universal metadata across the evolution — an evolved
                # skill stays in the same namespace and keeps its usage history.
                status=skill.status,
                org_id=skill.org_id,
                visibility=skill.visibility,
                source_format=skill.source_format,
                source_uri=skill.source_uri,
                usage_count=skill.usage_count,
                success_count=skill.success_count,
            )

            return evolved_skill

        except (json.JSONDecodeError, ValueError, KeyError, Exception) as e:
            logger.warning("Skill evolution failed to parse skill-model output, using fallback: %s", e)
            return self._fallback_evolve(skill, new_eval)

    def _fallback_evolve(self, skill: Skill, new_eval: EvalResult) -> Skill:
        """Minimal evolution when Gemini call fails — increment version and adjust score."""
        try:
            parts = skill.version.split(".")
            new_version = f"{parts[0]}.{int(parts[1]) + 1}"
        except (ValueError, IndexError):
            new_version = skill.version

        # Adjust score slightly
        new_score = skill.score
        if new_eval.passed:
            new_score = min(100.0, new_score + 5.0)
        elif new_eval.score > 0:
            new_score = min(100.0, new_score + 2.0)
        else:
            new_score = max(0.0, new_score - 5.0)

        now_iso = datetime.now(timezone.utc).isoformat()

        provenance = Provenance(
            created_from=skill.provenance.created_from,
            task=skill.provenance.task,
            iteration=skill.provenance.iteration + 1,
            parent_skill=skill.id,
            merged_from=skill.provenance.merged_from,
            evolved_at=now_iso,
        )

        return Skill(
            id=skill.id,
            title=skill.title,
            granularity=skill.granularity,
            version=new_version,
            score=new_score,
            trigger=skill.trigger,
            when_to_apply=skill.when_to_apply,
            instructions=skill.instructions,
            provenance=provenance,
            status=skill.status,
            org_id=skill.org_id,
            visibility=skill.visibility,
            source_format=skill.source_format,
            source_uri=skill.source_uri,
            usage_count=skill.usage_count,
            success_count=skill.success_count,
        )
