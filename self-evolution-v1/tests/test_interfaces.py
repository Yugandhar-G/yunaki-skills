"""Tests for the TaskResult.skill_delta property — the project's integrity metric."""

from __future__ import annotations

from yunaki_skills.interfaces import TaskResult


def _result(*, before, after, control):
    return TaskResult(
        task_description="t",
        score_before=before,
        score_control=control,
        score_after=after,
        skills_used=[],
        skills_created=[],
        skills_evolved=[],
        iterations=1,
    )


def test_skill_delta_positive():
    # Skills beat the no-skills control arm.
    assert _result(before=20, after=90, control=60).skill_delta == 30.0


def test_skill_delta_negative():
    # Skills did worse than the control arm — must be reported honestly.
    assert _result(before=20, after=50, control=70).skill_delta == -20.0


def test_skill_delta_zero():
    assert _result(before=20, after=60, control=60).skill_delta == 0.0


def test_skill_delta_none_when_control_missing():
    # No control arm -> the honest metric is undefined, not a conflated number.
    assert _result(before=20, after=90, control=None).skill_delta is None


def test_skill_delta_is_rounded():
    assert _result(before=0, after=33.33, control=11.11).skill_delta == 22.2
