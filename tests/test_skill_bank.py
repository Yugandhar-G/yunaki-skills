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


def test_search_semantic_breaks_ties_by_quality(skill_bank, monkeypatch):
    """At equal similarity, the higher-scoring skill ranks first (weighting on)."""
    monkeypatch.setenv("YUNAKI_RANK_W_SCORE", "0.15")
    high = make_task_skill("skill_high", score=90.0)
    low = make_task_skill("skill_low", score=20.0)
    # Identical embedding text -> identical similarity; quality is the tiebreaker.
    for s in (high, low):
        s.title = "Implement users endpoint"
        s.trigger.query = "implement get users endpoint"
        s.when_to_apply = "when implementing endpoints"
    skill_bank.add(high)
    skill_bank.add(low)

    results = skill_bank.search_semantic("implement get users endpoint", top_k=2)
    assert results[0].id == "skill_high"


def test_search_semantic_prefers_proven_skill(skill_bank, monkeypatch):
    """At equal similarity and score, a proven success record wins (weighting on)."""
    monkeypatch.setenv("YUNAKI_RANK_W_RATE", "0.15")
    proven = make_task_skill("skill_proven", score=50.0)
    proven.usage_count = 10
    proven.success_count = 9  # 0.9 success rate
    fresh = make_task_skill("skill_fresh", score=50.0)  # 0 usage -> neutral prior
    for s in (proven, fresh):
        s.title = "Implement users endpoint"
        s.trigger.query = "implement get users endpoint"
        s.when_to_apply = "when implementing endpoints"
    skill_bank.add(proven)
    skill_bank.add(fresh)

    results = skill_bank.search_semantic("implement get users endpoint", top_k=2)
    assert results[0].id == "skill_proven"


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


def test_increment_usage_tracks_success(skill_bank, task_skill):
    skill_bank.add(task_skill)
    assert skill_bank.increment_usage(task_skill.id, success=True) is True
    skill_bank.increment_usage(task_skill.id, success=False)
    got = skill_bank.get(task_skill.id)
    assert got.usage_count == 2
    assert got.success_count == 1


def test_increment_usage_missing_returns_false(skill_bank):
    assert skill_bank.increment_usage("ghost", success=True) is False


def test_set_status_transitions_and_archives(skill_bank, task_skill):
    from yunaki_skills.interfaces import SkillStatus

    skill_bank.add(task_skill)
    assert skill_bank.set_status(task_skill.id, SkillStatus.REJECTED) is True
    assert skill_bank.get(task_skill.id).status == SkillStatus.REJECTED
    # the pre-change version is archived for the audit trail
    assert skill_bank.get_history(task_skill.id)


def test_namespace_filter_matches_legacy_missing_org_id(skill_bank, task_skill):
    # A global-bank (org_id=None) query must see legacy docs that have no org_id
    # field at all (MongoDB {field: null} matches both null and absent).
    skill_bank.add(task_skill)
    skill_bank._skills.update_one({"id": task_skill.id}, {"$unset": {"org_id": ""}})
    assert skill_bank.get(task_skill.id) is not None
    assert any(s.id == task_skill.id for s in skill_bank.list_all())


def test_drop_removes_and_archives(skill_bank, task_skill):
    skill_bank.add(task_skill)
    assert skill_bank.drop(task_skill.id, reason="stale") is True
    assert skill_bank.get(task_skill.id) is None
    # Soft-delete: still recoverable from history.
    assert any(h.id == task_skill.id for h in skill_bank.get_history(task_skill.id))


def test_drop_missing_returns_false(skill_bank):
    assert skill_bank.drop("ghost") is False


def test_merge_combines_counts_and_drops_sources(skill_bank):
    a = make_task_skill("skill_a")
    a.usage_count, a.success_count = 4, 3
    b = make_task_skill("skill_b")
    b.usage_count, b.success_count = 6, 2
    skill_bank.add(a)
    skill_bank.add(b)

    merged_id = skill_bank.merge(["skill_a", "skill_b"], make_task_skill("skill_merged"))

    assert merged_id == "skill_merged"
    got = skill_bank.get("skill_merged")
    assert got.usage_count == 10  # summed, not reset
    assert got.success_count == 5
    assert set(got.provenance.merged_from) == {"skill_a", "skill_b"}
    assert skill_bank.get("skill_a") is None
    assert skill_bank.get("skill_b") is None


def test_merge_no_sources_returns_none(skill_bank):
    assert skill_bank.merge(["ghost"], make_task_skill("skill_m")) is None


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
    import math

    vec = skill_bank._hash_embedding("fastapi endpoint user")
    assert len(vec) == 384
    norm = math.sqrt(sum(v * v for v in vec))
    assert math.isclose(norm, 1.0, rel_tol=1e-6)


def test_hash_embedding_empty_text(skill_bank):
    import math

    vec = skill_bank._hash_embedding("")
    norm = math.sqrt(sum(v * v for v in vec))
    assert norm == pytest.approx(0.0)
