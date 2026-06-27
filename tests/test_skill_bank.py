"""Tests for SkillBank — CRUD, search, history, runs. MongoDB is mongomock."""

from __future__ import annotations

import pytest

from tests.conftest import make_event_skill, make_task_skill


def test_add_and_get(skill_bank, task_skill):
    skill_id = skill_bank.add(task_skill)
    assert skill_id == task_skill.id

    fetched = skill_bank.get(task_skill.id)
    assert fetched is not None
    assert fetched.id == task_skill.id
    assert fetched.title == task_skill.title


def test_get_missing_returns_none(skill_bank):
    assert skill_bank.get("skill_does_not_exist") is None


def test_add_is_idempotent_on_id(skill_bank, task_skill):
    """Re-adding the same id must not raise or duplicate the live skill."""
    skill_bank.add(task_skill)
    skill_bank.add(task_skill)
    assert len([s for s in skill_bank.list_all() if s.id == task_skill.id]) == 1


def test_update_existing(skill_bank, task_skill):
    skill_bank.add(task_skill)

    evolved = task_skill.model_copy(update={"version": "0.2", "score": 75.0})
    ok = skill_bank.update(task_skill.id, evolved)
    assert ok is True

    fetched = skill_bank.get(task_skill.id)
    assert fetched.version == "0.2"
    assert fetched.score == 75.0


def test_update_missing_returns_false(skill_bank, task_skill):
    assert skill_bank.update("nope", task_skill) is False


def test_list_all_sorted_by_score_desc(skill_bank):
    low = make_task_skill("skill_low", score=10.0)
    high = make_task_skill("skill_high", score=90.0)
    skill_bank.add(low)
    skill_bank.add(high)

    listed = skill_bank.list_all()
    scores = [s.score for s in listed]
    assert scores == sorted(scores, reverse=True)
    assert listed[0].id == "skill_high"


def test_search_semantic_ranks_relevant_first(skill_bank):
    relevant = make_task_skill("skill_users_endpoint", score=50.0)
    relevant.trigger.query = "implement get users endpoint fastapi"
    relevant.title = "Implement users endpoint"

    unrelated = make_task_skill("skill_logging", score=50.0)
    unrelated.trigger.query = "configure rotating file logging handlers"
    unrelated.title = "Set up logging"

    skill_bank.add(relevant)
    skill_bank.add(unrelated)

    results = skill_bank.search_semantic("how do I implement the get users endpoint", top_k=2)
    assert results
    assert results[0].id == "skill_users_endpoint"


def test_search_semantic_empty_bank(skill_bank):
    assert skill_bank.search_semantic("anything") == []


def test_search_semantic_respects_top_k(skill_bank):
    for i in range(5):
        skill_bank.add(make_task_skill(f"skill_{i}"))
    results = skill_bank.search_semantic("fastapi", top_k=2)
    assert len(results) == 2


def test_search_pattern_matches_event_skill(skill_bank):
    skill_bank.add(make_event_skill("skill_keyerror_guard"))
    matched = skill_bank.search_pattern("Traceback ... KeyError: 'email'")
    assert [s.id for s in matched] == ["skill_keyerror_guard"]


def test_search_pattern_no_match(skill_bank):
    skill_bank.add(make_event_skill("skill_keyerror_guard"))
    assert skill_bank.search_pattern("everything is fine") == []


def test_search_pattern_ignores_invalid_regex(skill_bank):
    bad = make_event_skill("skill_bad_regex")
    bad.trigger.patterns = ["("]  # invalid regex — must be skipped, not raise
    skill_bank.add(bad)
    assert skill_bank.search_pattern("(") == []


def test_search_pattern_skips_task_level(skill_bank, task_skill):
    """Task-level (semantic) skills must not be returned by pattern search."""
    skill_bank.add(task_skill)
    assert skill_bank.search_pattern("anything") == []


def test_get_history_tracks_versions(skill_bank, task_skill):
    skill_bank.add(task_skill)
    evolved = task_skill.model_copy(update={"version": "0.2"})
    skill_bank.update(task_skill.id, evolved)

    history = skill_bank.get_history(task_skill.id)
    versions = [h.version for h in history]
    assert "0.1" in versions


def test_save_run(skill_bank):
    skill_bank.save_run({"task_description": "t", "score_after": 90.0})
    stored = list(skill_bank._runs.find())
    assert len(stored) == 1
    assert stored[0]["score_after"] == 90.0


def test_hash_embedding_is_normalized(skill_bank):
    import numpy as np

    vec = np.array(skill_bank._hash_embedding("fastapi endpoint user"))
    assert vec.shape[0] == 384
    assert np.isclose(np.linalg.norm(vec), 1.0)


def test_hash_embedding_empty_text(skill_bank):
    import numpy as np

    vec = np.array(skill_bank._hash_embedding(""))
    assert np.linalg.norm(vec) == pytest.approx(0.0)
