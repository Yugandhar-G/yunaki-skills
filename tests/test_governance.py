"""Tests for governance — the policy gating whether skills re-enter the loop."""

from __future__ import annotations

from yunaki_skills import governance
from yunaki_skills.interfaces import SkillStatus


def test_new_skills_enter_active():
    assert governance.status_for_new_skill() == SkillStatus.ACTIVE


def test_evolved_skill_active_when_auto_approve_on(monkeypatch):
    monkeypatch.setenv("SKILL_AUTO_APPROVE", "true")
    assert governance.status_for_evolved_skill() == SkillStatus.ACTIVE


def test_evolved_skill_draft_when_auto_approve_off(monkeypatch):
    monkeypatch.setenv("SKILL_AUTO_APPROVE", "false")
    assert governance.status_for_evolved_skill() == SkillStatus.DRAFT


def test_auto_approve_defaults_on(monkeypatch):
    monkeypatch.delenv("SKILL_AUTO_APPROVE", raising=False)
    assert governance.auto_approve_enabled() is True


def test_retrievable_statuses():
    statuses = governance.retrievable_statuses()
    assert SkillStatus.ACTIVE.value in statuses
    assert SkillStatus.APPROVED.value in statuses
    assert SkillStatus.DRAFT.value not in statuses


def test_is_retrievable():
    assert governance.is_retrievable(SkillStatus.ACTIVE) is True
    assert governance.is_retrievable(SkillStatus.APPROVED) is True
    assert governance.is_retrievable(SkillStatus.DRAFT) is False
    assert governance.is_retrievable(SkillStatus.PENDING_REVIEW) is False
    # Legacy docs with no status are treated as retrievable (backward compat).
    assert governance.is_retrievable(None) is True
