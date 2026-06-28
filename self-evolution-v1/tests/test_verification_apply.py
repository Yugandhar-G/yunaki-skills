"""Tests for record_measurement (advisory) and apply_acceptance (human action)."""
from yunaki_skills import verification
from yunaki_skills.interfaces import ABResult, SkillStatus


def _ab(lift, c_rate=1.0, t_rate=1.0):
    # tight per-rollout scores (zero variance) so a positive lift is significant
    return ABResult(
        task_description="impl X",
        n_rollouts=3,
        control_mean=40.0,
        treatment_mean=40.0 + lift,
        skill_lift=lift,
        control_scores=[40.0, 40.0, 40.0],
        treatment_scores=[40.0 + lift] * 3,
        control_runnable_rate=c_rate,
        treatment_runnable_rate=t_rate,
    )


def test_record_measurement_records_but_leaves_status_and_score(skill_bank, task_skill):
    skill_bank.add(task_skill)  # score 60, status ACTIVE, verified False
    rec = verification.record_measurement(skill_bank, task_skill, _ab(30.0))

    assert rec.recommendation == "promote"
    got = skill_bank.get(task_skill.id)
    # measurement recorded
    assert got.measured_lift == 30.0
    assert got.gate_recommendation == "promote"
    assert got.measured_at != ""
    # but nothing behavioral changed — advisory only
    assert got.score == 60.0
    assert got.status == SkillStatus.ACTIVE
    assert got.verified is False


def test_apply_acceptance_promotes_sets_score_and_verified(skill_bank, task_skill):
    skill_bank.add(task_skill)
    verification.record_measurement(skill_bank, task_skill, _ab(30.0))
    measured = skill_bank.get(task_skill.id)

    assert verification.apply_acceptance(skill_bank, measured, accept=True) is True
    got = skill_bank.get(task_skill.id)
    assert got.score == 80.0  # 50 + 30
    assert got.verified is True
    assert got.status == SkillStatus.APPROVED


def test_apply_acceptance_reject_demotes_and_keeps_score(skill_bank, task_skill):
    skill_bank.add(task_skill)
    verification.record_measurement(skill_bank, task_skill, _ab(-10.0))
    measured = skill_bank.get(task_skill.id)

    assert verification.apply_acceptance(skill_bank, measured, accept=False) is True
    got = skill_bank.get(task_skill.id)
    assert got.status == SkillStatus.REJECTED
    assert got.score == 60.0  # score untouched on reject
    assert got.verified is False


def test_apply_acceptance_without_measurement_is_noop(skill_bank, task_skill):
    skill_bank.add(task_skill)  # never measured
    fresh = skill_bank.get(task_skill.id)
    assert fresh.measured_lift is None

    assert verification.apply_acceptance(skill_bank, fresh, accept=True) is False
    got = skill_bank.get(task_skill.id)
    assert got.verified is False
    assert got.status == SkillStatus.ACTIVE
    assert got.score == 60.0
