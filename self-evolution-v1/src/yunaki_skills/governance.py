"""Skill governance policy helpers.

Centralizes the rules around the skill lifecycle so the bank, the runner, and
the API agree on a single source of truth:

  - which statuses are eligible for retrieval/injection
  - what status a freshly-extracted skill receives
  - what status an evolved skill receives (and whether it needs review)

The evolution policy is configurable via SKILL_AUTO_APPROVE. With auto-approve
ON (default), evolved skills go straight to ACTIVE so the live evolution loop
keeps demonstrating measurable improvement run-over-run. With it OFF (stricter
production posture), evolution produces a DRAFT that a human must approve before
it is ever retrieved again.
"""

from yunaki_skills.config import get as cfg
from yunaki_skills.interfaces import SkillStatus

# Statuses whose skills are eligible to be retrieved and injected into agents.
RETRIEVABLE_STATUSES: frozenset[SkillStatus] = frozenset({SkillStatus.APPROVED, SkillStatus.ACTIVE})


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def auto_approve_enabled() -> bool:
    """Whether loop-evolved skills are auto-approved (default True)."""
    raw = cfg("SKILL_AUTO_APPROVE", "true")
    return _truthy(raw)


def require_verified_enabled() -> bool:
    """Whether task-level retrieval is restricted to human-verified skills.

    Default False → today's behavior (verified and unverified both retrievable).
    Set YUNAKI_REQUIRE_VERIFIED to require that a human has accepted a skill's
    measured lift before it can be injected.
    """
    return _truthy(cfg("YUNAKI_REQUIRE_VERIFIED", "false"))


def retrievable_statuses() -> list[str]:
    """String values of statuses eligible for retrieval (for DB filters)."""
    return [s.value for s in RETRIEVABLE_STATUSES]


def is_retrievable(status: SkillStatus | str | None) -> bool:
    """True if a skill in the given status may be injected into an agent.

    A missing/None status is treated as ACTIVE for backward compatibility with
    legacy skill documents written before governance existed.
    """
    if status is None:
        return True
    value = status.value if isinstance(status, SkillStatus) else str(status)
    return value in {s.value for s in RETRIEVABLE_STATUSES}


def status_for_new_skill() -> SkillStatus:
    """Status assigned to a skill freshly extracted by the live loop.

    Machine-extracted skills enter ACTIVE so the loop can re-retrieve and reuse
    them immediately; human-driven evolutions are what require review.
    """
    return SkillStatus.ACTIVE


def status_for_evolved_skill() -> SkillStatus:
    """Status assigned to an evolved skill, per the auto-approve policy."""
    return SkillStatus.ACTIVE if auto_approve_enabled() else SkillStatus.DRAFT
