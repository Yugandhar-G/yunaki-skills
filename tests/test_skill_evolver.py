"""Tests for SkillEvolver — Gemini mocked."""

from __future__ import annotations

import json

from tests.conftest import install_fake_skill_llm, make_task_skill
from yunaki_skills import skill_evolver as evo_mod

EVOLVED_JSON = json.dumps(
    {
        "title": "Implement endpoint (refined)",
        "granularity": "task-level",
        "version": "0.9",  # model's suggestion is ignored in favor of increment
        "score": 70.0,
        "trigger": {
            "type": "semantic",
            "patterns": [],
            "query": "implement fastapi endpoint carefully",
            "match_on": "task_description",
        },
        "when_to_apply": "When an endpoint is unimplemented or partially done",
        "instructions": ["Add the route", "Return the model", "Add validation"],
    }
)


def test_evolve_increments_version_and_bumps_score(monkeypatch, eval_fail):
    install_fake_skill_llm(monkeypatch, EVOLVED_JSON)
    parent = make_task_skill(score=60.0)

    evolved = evo_mod.SkillEvolver().evolve(parent, "new trace", eval_fail)

    assert evolved.id == parent.id  # id is preserved
    assert evolved.version == "0.2"  # incremented from 0.1, not the model's 0.9
    assert evolved.title == "Implement endpoint (refined)"
    assert "Add validation" in evolved.instructions
    # Partial-progress eval nudges the score up by 5.
    assert evolved.score == 75.0


def test_evolve_records_parent_in_provenance(monkeypatch, eval_fail):
    install_fake_skill_llm(monkeypatch, EVOLVED_JSON)
    parent = make_task_skill()

    evolved = evo_mod.SkillEvolver().evolve(parent, "trace", eval_fail)

    assert evolved.provenance.parent_skill == parent.id
    assert evolved.provenance.iteration == parent.provenance.iteration + 1
    assert evolved.provenance.evolved_at  # ISO timestamp stamped


def test_evolve_falls_back_on_bad_json(monkeypatch, eval_fail):
    install_fake_skill_llm(monkeypatch, "not json")
    parent = make_task_skill(score=50.0)

    evolved = evo_mod.SkillEvolver().evolve(parent, "trace", eval_fail)

    # Fallback keeps instructions/title, increments version, nudges score.
    assert evolved.version == "0.2"
    assert evolved.title == parent.title
    assert evolved.instructions == parent.instructions


def test_fallback_evolve_passing_eval_bumps_score(eval_pass):
    parent = make_task_skill(score=50.0)
    evolved = evo_mod.SkillEvolver._fallback_evolve(
        evo_mod.SkillEvolver.__new__(evo_mod.SkillEvolver), parent, eval_pass
    )
    assert evolved.score == 55.0
    assert evolved.version == "0.2"
