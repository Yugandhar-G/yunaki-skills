"""Periodic skill-bank consolidation: merge near-duplicates, drop dead weight.

Without this the bank only ever grows: near-duplicate skills accumulate, dilute
retrieval, and bloat prompts. Consolidation finds duplicate clusters by embedding
similarity, asks the skill-model LLM to fuse each cluster into one skill, and
drops skills that have proven ineffective.

Safety:
  - Defaults to dry-run; callers must opt in to apply.
  - Never drops a skill with zero usage (no evidence yet).
  - Merges sum usage/success counts (see SkillBank.merge), preserving signal.

Env knobs:
  YUNAKI_CONSOLIDATE_SIM            cosine threshold for duplicates (default 0.92)
  YUNAKI_CONSOLIDATE_MIN_USAGE      min applications before a skill can be dropped (5)
  YUNAKI_CONSOLIDATE_MAX_FAIL_RATE  drop if success_rate below this (0.34)
  YUNAKI_CONSOLIDATE_SCORE_FLOOR    drop if score below this; 0 disables (0)
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from yunaki_skills import skill_llm
from yunaki_skills.interfaces import Skill
from yunaki_skills.skill_bank import SkillBank, _env_float

logger = logging.getLogger(__name__)

MERGE_PROMPT = """You are consolidating overlapping coding skills into ONE stronger skill.
Below are several skills that target the same situation. Fuse them into a single
skill that keeps every distinct, useful instruction and drops redundancy.

SKILLS TO MERGE:
{skills_json}

Respond with ONLY a JSON object, no markdown, with this exact schema:
{{
  "title": "<concise merged title>",
  "when_to_apply": "<when this merged skill applies>",
  "instructions": ["<step 1>", "<step 2>", ...]
}}"""


def _embed_text(skill: Skill) -> str:
    return f"{skill.title} {skill.when_to_apply} {skill.trigger.query}"


class SkillConsolidator:
    """Merges duplicate skills and drops ineffective ones."""

    def __init__(self, bank: Optional[SkillBank] = None):
        self._bank = bank or SkillBank()

    def consolidate(self, dry_run: bool = True) -> dict:
        """Run a consolidation pass. Returns a report dict.

        When ``dry_run`` is True (default) nothing is mutated — the report shows
        exactly what would happen.
        """
        sim_threshold = _env_float("YUNAKI_CONSOLIDATE_SIM", 0.92)
        min_usage = int(_env_float("YUNAKI_CONSOLIDATE_MIN_USAGE", 5))
        max_fail_rate = _env_float("YUNAKI_CONSOLIDATE_MAX_FAIL_RATE", 0.34)
        score_floor = _env_float("YUNAKI_CONSOLIDATE_SCORE_FLOOR", 0.0)

        skills = self._bank.list_all()
        clusters = self._cluster(skills, sim_threshold)

        merges: list[dict] = []
        merged_ids: set[str] = set()
        for cluster in clusters:
            if len(cluster) < 2:
                continue
            merged = self._merge_cluster(cluster, dry_run)
            if merged is not None:
                merges.append({"merged_id": merged.id, "sources": [s.id for s in cluster]})
                merged_ids.update(s.id for s in cluster)

        drops: list[dict] = []
        for skill in skills:
            if skill.id in merged_ids:
                continue
            reason = self._drop_reason(skill, min_usage, max_fail_rate, score_floor)
            if reason:
                drops.append({"id": skill.id, "reason": reason})
                if not dry_run:
                    self._bank.drop(skill.id, reason=reason)

        return {"dry_run": dry_run, "merges": merges, "drops": drops}

    def _cluster(self, skills: list[Skill], threshold: float) -> list[list[Skill]]:
        """Greedy single-pass clustering by embedding cosine similarity."""
        vectors = [self._bank._compute_embedding(_embed_text(s)) for s in skills]
        used = [False] * len(skills)
        clusters: list[list[Skill]] = []
        for i in range(len(skills)):
            if used[i]:
                continue
            group = [skills[i]]
            used[i] = True
            for j in range(i + 1, len(skills)):
                if used[j]:
                    continue
                if self._bank._cosine_similarity(vectors[i], vectors[j]) >= threshold:
                    group.append(skills[j])
                    used[j] = True
            clusters.append(group)
        return clusters

    def _merge_cluster(self, cluster: list[Skill], dry_run: bool) -> Optional[Skill]:
        """Fuse a cluster into one skill via the skill-model LLM.

        Structural fields (id, granularity, trigger) come from the best-scoring
        source so triggers stay valid; the LLM only rewrites the human text.
        Returns None (skip) if the LLM output can't be parsed.
        """
        best = max(cluster, key=lambda s: s.score)
        skills_json = json.dumps(
            [{"title": s.title, "when_to_apply": s.when_to_apply, "instructions": s.instructions} for s in cluster],
            indent=2,
        )
        try:
            text = (skill_llm.complete_json(MERGE_PROMPT.format(skills_json=skills_json)) or "").strip()
            data = json.loads(text)
            instructions = [str(i) for i in data.get("instructions", []) if str(i).strip()]
            if not instructions:
                return None
            merged = best.model_copy(
                update={
                    "title": str(data.get("title", best.title)),
                    "when_to_apply": str(data.get("when_to_apply", best.when_to_apply)),
                    "instructions": instructions,
                    "score": max(s.score for s in cluster),
                }
            )
        except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
            logger.warning("Merge skipped for cluster %s: %s", [s.id for s in cluster], e)
            return None

        if not dry_run:
            self._bank.merge([s.id for s in cluster], merged)
        return merged

    @staticmethod
    def _drop_reason(skill: Skill, min_usage: int, max_fail_rate: float, score_floor: float) -> str:
        """Return a drop reason, or '' to keep. Never drops unproven skills."""
        if skill.usage_count == 0:
            return ""  # no evidence yet — keep
        success_rate = skill.success_count / skill.usage_count
        if skill.usage_count >= min_usage and success_rate < max_fail_rate:
            return f"low success rate {success_rate:.0%} over {skill.usage_count} uses"
        if score_floor > 0 and skill.score < score_floor:
            return f"score {skill.score:.0f} below floor {score_floor:.0f}"
        return ""
