"""Tests for SkillRetriever — retrieval + injection. Backed by mongomock bank."""

from __future__ import annotations

from tests.conftest import make_event_skill, make_task_skill
from yunaki_skills.skill_retriever import SkillRetriever


def test_retrieve_for_task_uses_semantic_search(skill_bank):
    skill_bank.add(make_task_skill("skill_users", score=50.0))
    retriever = SkillRetriever(bank=skill_bank)

    results = retriever.retrieve_for_task("implement the users endpoint")
    assert any(s.id == "skill_users" for s in results)


def test_check_triggers_matches_event_skill(skill_bank):
    skill_bank.add(make_event_skill("skill_keyerror_guard"))
    retriever = SkillRetriever(bank=skill_bank)

    matched = retriever.check_triggers("boom: KeyError: 'name'")
    assert [s.id for s in matched] == ["skill_keyerror_guard"]


def test_check_triggers_no_match(skill_bank):
    skill_bank.add(make_event_skill())
    retriever = SkillRetriever(bank=skill_bank)
    assert retriever.check_triggers("all good") == []


def test_inject_skills_empty_returns_prompt_unchanged(skill_bank):
    retriever = SkillRetriever(bank=skill_bank)
    base = "You are an agent."
    assert retriever.inject_skills(base, []) == base


def test_inject_skills_appends_blocks(skill_bank):
    retriever = SkillRetriever(bank=skill_bank)
    skill = make_task_skill()
    result = retriever.inject_skills("BASE PROMPT", [skill])

    assert result.startswith("BASE PROMPT")
    assert "Active Skills" in result
    assert skill.title in result
    for instruction in skill.instructions:
        assert instruction in result


def test_inject_skills_numbers_instructions(skill_bank):
    retriever = SkillRetriever(bank=skill_bank)
    skill = make_task_skill()
    result = retriever.inject_skills("BASE", [skill])
    assert "1. Define a dependency" in result
    assert "2. Inject it via Depends" in result


def test_retriever_creates_default_bank(monkeypatch):
    """No-arg construction must build its own SkillBank."""
    sentinel = object()
    monkeypatch.setattr("yunaki_skills.skill_retriever.SkillBank", lambda: sentinel)
    retriever = SkillRetriever()
    assert retriever._bank is sentinel
