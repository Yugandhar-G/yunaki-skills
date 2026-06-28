"""Verification gate: measure a skill's real effect, recommend, let a human apply.

This operationalizes the project's central finding (and two papers' conclusion):
a self-generated skill's measured effect is unpredictable and can degrade the
agent, so its true lift must be VERIFIED against a no-skill control before it is
trusted. Curated/verified skills help; unverified ones are a coin flip.

Design (human-in-the-loop):
  - `recommend(ab)` is a PURE policy: ABResult -> a recommendation. No side effects.
  - `record_measurement(bank, skill, ab)` persists the measurement + recommendation
    onto the skill but NEVER changes its status, score, or retrievability.
  - `apply_acceptance(bank, skill, accept)` is the human action: only here does a
    skill's score/status actually change.

The honest bar: a lift that comes with MORE crashes (lower runnable rate) is not a
real win and is recommended for rejection even if the mean improved.
"""

import logging
import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from yunaki_skills.config import get as cfg
from yunaki_skills.interfaces import ABResult, Skill, SkillStatus

logger = logging.getLogger(__name__)

_DEFAULT_GATE_THRESHOLD = 5.0  # percentage points of raw lift required to recommend promotion
_DEFAULT_GATE_Z = 1.645  # ~90% one-sided: lower CI bound must clear 0 to call a lift real
_NEUTRAL_SCORE = 50.0  # the un-measured default Skill.score


# ─── Recommendation result ──────────────────────────────────────────────────


@dataclass(frozen=True)
class GateRecommendation:
    """Advisory output of the gate. Applied only on explicit human acceptance."""

    recommendation: str  # "promote" | "reject" | "inconclusive" | "no_measurement"
    reason: str
    lift: Optional[float] = None
    suggested_score: Optional[float] = None  # set for promote/inconclusive only
    ci_low: Optional[float] = None  # lower bound of the lift confidence interval
    ci_high: Optional[float] = None  # upper bound of the lift confidence interval


# ─── Policy ─────────────────────────────────────────────────────────────────


def _gate_threshold() -> float:
    """Minimum raw lift (pp) to recommend promotion. Env: YUNAKI_GATE_THRESHOLD."""
    raw = cfg("YUNAKI_GATE_THRESHOLD", "")
    if not raw:
        return _DEFAULT_GATE_THRESHOLD
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid YUNAKI_GATE_THRESHOLD=%r — using default %s", raw, _DEFAULT_GATE_THRESHOLD)
        return _DEFAULT_GATE_THRESHOLD


def _gate_z() -> float:
    """Z multiplier for the lift confidence interval. Env: YUNAKI_GATE_Z."""
    raw = cfg("YUNAKI_GATE_Z", "")
    if not raw:
        return _DEFAULT_GATE_Z
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid YUNAKI_GATE_Z=%r — using default %s", raw, _DEFAULT_GATE_Z)
        return _DEFAULT_GATE_Z


def _score_from_lift(lift: float) -> float:
    """Map a measured lift onto the 0-100 score scale: neutral 50 + lift, clamped."""
    return max(0.0, min(100.0, _NEUTRAL_SCORE + lift))


def _lift_ci(control_scores: list[float], treatment_scores: list[float], lift: float):
    """Confidence interval for the lift via the Welch standard error of the
    difference of means. Returns (low, high), or None when either arm has fewer
    than 2 runnable scores (variance, hence significance, is undefined)."""
    if len(control_scores) < 2 or len(treatment_scores) < 2:
        return None
    se = math.sqrt(
        statistics.variance(control_scores) / len(control_scores)
        + statistics.variance(treatment_scores) / len(treatment_scores)
    )
    margin = _gate_z() * se
    return (lift - margin, lift + margin)


def recommend(ab: ABResult) -> GateRecommendation:
    """Pure gate policy: turn an A/B measurement into an advisory recommendation.

    A lift is only worth promoting if it (1) clears the effect-size threshold,
    (2) holds reliability (no drop in runnable rate), AND (3) is statistically
    distinguishable from zero — its confidence interval lower bound clears 0.
    A large point-estimate lift on a noisy/small sample is NOT promotable; it is
    inconclusive. Never rejects on absence of evidence.
    """
    lift = ab.skill_lift
    if lift is None or ab.control_mean is None or ab.treatment_mean is None:
        return GateRecommendation(
            "no_measurement",
            "no measurement: at least one arm had zero runnable rollouts",
            lift=lift,
        )

    if ab.treatment_runnable_rate < ab.control_runnable_rate:
        return GateRecommendation(
            "reject",
            f"reliability regression: treatment runnable {ab.treatment_runnable_rate:.0%} "
            f"< control {ab.control_runnable_rate:.0%}",
            lift=lift,
        )

    threshold = _gate_threshold()
    if lift >= threshold:
        ci = _lift_ci(ab.control_scores, ab.treatment_scores, lift)
        if ci is None:
            return GateRecommendation(
                "inconclusive",
                f"lift {lift:+.1f}pp >= threshold but too few rollouts to establish "
                f"significance (need >= 2 runnable per arm)",
                lift=lift,
                suggested_score=_score_from_lift(lift),
            )
        low, high = ci
        if low > 0:
            return GateRecommendation(
                "promote",
                f"lift {lift:+.1f}pp >= threshold {threshold:+.1f}pp, reliability held, "
                f"CI [{low:+.1f}, {high:+.1f}] clears 0",
                lift=lift,
                suggested_score=_score_from_lift(lift),
                ci_low=round(low, 1),
                ci_high=round(high, 1),
            )
        return GateRecommendation(
            "inconclusive",
            f"lift {lift:+.1f}pp >= threshold but CI [{low:+.1f}, {high:+.1f}] includes 0 "
            f"— not distinguishable from noise",
            lift=lift,
            suggested_score=_score_from_lift(lift),
            ci_low=round(low, 1),
            ci_high=round(high, 1),
        )
    if lift <= 0:
        return GateRecommendation("reject", f"non-positive lift {lift:+.1f}pp", lift=lift)
    return GateRecommendation(
        "inconclusive",
        f"0 < lift {lift:+.1f}pp < threshold {threshold:+.1f}pp",
        lift=lift,
        suggested_score=_score_from_lift(lift),
    )


# ─── Persistence adapters ───────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_measurement(bank, skill: Skill, ab: ABResult) -> GateRecommendation:
    """Persist the measurement + recommendation onto the skill. Advisory only:
    does NOT change status, score, or retrievability. Returns the recommendation."""
    rec = recommend(ab)
    updated = skill.model_copy(
        update={
            "measured_lift": ab.skill_lift,
            "measured_lift_low": rec.ci_low,
            "measured_lift_high": rec.ci_high,
            "measured_at": _now_iso(),
            "gate_recommendation": rec.recommendation,
        }
    )
    bank.update(skill.id, updated)
    return rec


def apply_acceptance(bank, skill: Skill, accept: bool) -> bool:
    """Human acceptance action — the ONLY place a skill's score/status changes.

    accept=True  : promote a measured skill (score = 50 + measured_lift, verified,
                   status APPROVED). No-op (returns False) if never measured.
    accept=False : human-initiated demotion to REJECTED (score/measurement kept).
    """
    if accept:
        if skill.measured_lift is None:
            logger.info("apply_acceptance: %s has no measurement to accept — no-op", skill.id)
            return False
        updated = skill.model_copy(
            update={
                "score": _score_from_lift(skill.measured_lift),
                "verified": True,
                "status": SkillStatus.APPROVED,
            }
        )
        return bank.update(skill.id, updated)

    updated = skill.model_copy(update={"status": SkillStatus.REJECTED})
    return bank.update(skill.id, updated)
