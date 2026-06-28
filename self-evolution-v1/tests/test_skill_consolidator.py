"""Tests for SkillConsolidator — mongomock bank + mocked skill LLM."""

from __future__ import annotations

import json

from tests.conftest import make_task_skill
from yunaki_skills import skill_consolidator as cons_mod
from yunaki_skills.skill_consolidator import SkillConsolidator

MERGED_JSON = json.dumps(
    {
        "title": "Implement FastAPI endpoint (merged)",
        "when_to_apply": "When implementing or completing an endpoint",
        "instructions": ["Add the route", "Validate input", "Return the model"],
    }
)


def _dupe(skill_id: str, score: float = 50.0):
    """A task skill with identical embedding text so clustering treats them as dupes."""
    s = make_task_skill(skill_id, score=score)
    s.title = "Implement users endpoint"
    s.trigger.query = "implement get users endpoint"
    s.when_to_apply = "when implementing endpoints"
    return s


def test_dry_run_reports_merge_without_mutating(monkeypatch, skill_bank):
    monkeypatch.setattr(cons_mod.skill_llm, "complete_json", lambda p: MERGED_JSON)
    skill_bank.add(_dupe("skill_a", score=70.0))
    skill_bank.add(_dupe("skill_b", score=40.0))

    report = SkillConsolidator(bank=skill_bank).consolidate(dry_run=True)

    assert len(report["merges"]) == 1
    # Nothing actually changed.
    assert skill_bank.get("skill_a") is not None
    assert skill_bank.get("skill_b") is not None


def test_apply_merges_duplicates(monkeypatch, skill_bank):
    monkeypatch.setattr(cons_mod.skill_llm, "complete_json", lambda p: MERGED_JSON)
    skill_bank.add(_dupe("skill_a", score=70.0))  # best score -> kept id
    skill_bank.add(_dupe("skill_b", score=40.0))

    report = SkillConsolidator(bank=skill_bank).consolidate(dry_run=False)

    assert len(report["merges"]) == 1
    # Best-scoring source id is kept; the other is dropped.
    kept = skill_bank.get("skill_a")
    assert kept is not None
    assert "Add the route" in kept.instructions
    assert skill_bank.get("skill_b") is None


def test_distinct_skills_not_merged(monkeypatch, skill_bank):
    monkeypatch.setattr(cons_mod.skill_llm, "complete_json", lambda p: MERGED_JSON)
    a = make_task_skill("skill_a")
    a.title = "Implement users endpoint"
    a.trigger.query = "implement get users endpoint"
    b = make_task_skill("skill_b")
    b.title = "Configure rotating logging"
    b.trigger.query = "set up file logging handlers"
    skill_bank.add(a)
    skill_bank.add(b)

    report = SkillConsolidator(bank=skill_bank).consolidate(dry_run=False)
    assert report["merges"] == []
    assert skill_bank.get("skill_a") is not None
    assert skill_bank.get("skill_b") is not None


def test_drops_ineffective_skill(monkeypatch, skill_bank):
    monkeypatch.setattr(cons_mod.skill_llm, "complete_json", lambda p: MERGED_JSON)
    bad = make_task_skill("skill_bad")
    bad.usage_count, bad.success_count = 10, 1  # 10% success over 10 uses
    skill_bank.add(bad)

    report = SkillConsolidator(bank=skill_bank).consolidate(dry_run=False)

    assert any(d["id"] == "skill_bad" for d in report["drops"])
    assert skill_bank.get("skill_bad") is None


def test_never_drops_unproven_skill(monkeypatch, skill_bank):
    monkeypatch.setattr(cons_mod.skill_llm, "complete_json", lambda p: MERGED_JSON)
    fresh = make_task_skill("skill_fresh")  # 0 usage
    skill_bank.add(fresh)

    report = SkillConsolidator(bank=skill_bank).consolidate(dry_run=False)

    assert report["drops"] == []
    assert skill_bank.get("skill_fresh") is not None


def test_bad_merge_json_skips_merge(monkeypatch, skill_bank):
    monkeypatch.setattr(cons_mod.skill_llm, "complete_json", lambda p: "not json")
    skill_bank.add(_dupe("skill_a"))
    skill_bank.add(_dupe("skill_b"))

    report = SkillConsolidator(bank=skill_bank).consolidate(dry_run=False)

    assert report["merges"] == []
    # Both survive — a failed merge must not destroy skills.
    assert skill_bank.get("skill_a") is not None
    assert skill_bank.get("skill_b") is not None
