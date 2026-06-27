"""Tests for SkillExtractor — Gemini mocked."""

from __future__ import annotations

import json

from tests.conftest import install_fake_skill_llm
from yunaki_skills import skill_extractor as ext_mod
from yunaki_skills.interfaces import Granularity, TriggerType

VALID_TASK_SKILL_JSON = json.dumps(
    {
        "id": "skill_implement_endpoint",
        "title": "Implement missing FastAPI endpoint",
        "granularity": "task-level",
        "version": "0.1",
        "score": 50.0,
        "trigger": {
            "type": "semantic",
            "patterns": [],
            "query": "implement fastapi endpoint",
            "match_on": "task_description",
        },
        "when_to_apply": "When an endpoint is unimplemented",
        "instructions": ["Add the route", "Return the model"],
    }
)

VALID_EVENT_SKILL_JSON = json.dumps(
    {
        "id": "skill_fix_keyerror",
        "title": "Fix KeyError",
        "granularity": "event-driven",
        "version": "0.1",
        "score": 50.0,
        "trigger": {
            "type": "pattern",
            "patterns": [r"KeyError"],
            "query": "",
            "match_on": "error",
        },
        "when_to_apply": "On KeyError",
        "instructions": ["Use .get()"],
    }
)


def test_extract_task_level_skill(monkeypatch, eval_fail):
    install_fake_skill_llm(monkeypatch, VALID_TASK_SKILL_JSON)
    extractor = ext_mod.SkillExtractor()

    skill = extractor.extract("Implement GET /users", "trace text", eval_fail)

    assert skill is not None
    assert skill.id == "skill_implement_endpoint"
    assert skill.granularity == Granularity.TASK_LEVEL
    assert skill.trigger.type == TriggerType.SEMANTIC
    assert skill.instructions == ["Add the route", "Return the model"]
    # Provenance is stamped by the extractor, not the model.
    assert skill.provenance.task == "Implement GET /users"
    assert skill.provenance.created_from.startswith("trace_")


def test_extract_event_driven_skill(monkeypatch, eval_fail):
    install_fake_skill_llm(monkeypatch, VALID_EVENT_SKILL_JSON)
    skill = ext_mod.SkillExtractor().extract("task", "KeyError trace", eval_fail)

    assert skill.granularity == Granularity.EVENT_DRIVEN
    assert skill.trigger.type == TriggerType.PATTERN
    assert skill.trigger.patterns == ["KeyError"]


def test_extract_invalid_json_returns_none(monkeypatch, eval_fail):
    install_fake_skill_llm(monkeypatch, "this is not json {")
    assert ext_mod.SkillExtractor().extract("task", "trace", eval_fail) is None


def test_extract_empty_response_returns_none(monkeypatch, eval_fail):
    install_fake_skill_llm(monkeypatch, "")
    assert ext_mod.SkillExtractor().extract("task", "trace", eval_fail) is None


def test_extract_passes_eval_fields_into_prompt(monkeypatch, eval_fail):
    fake = install_fake_skill_llm(monkeypatch, VALID_TASK_SKILL_JSON)
    ext_mod.SkillExtractor().extract("My Task", "the trace", eval_fail)

    prompt = fake.call_args[0][0]
    assert "My Task" in prompt
    assert "the trace" in prompt
    assert "3/9" in prompt  # tasks_passed/tasks_total rendered


def test_extract_truncates_long_trace(monkeypatch, eval_fail):
    fake = install_fake_skill_llm(monkeypatch, VALID_TASK_SKILL_JSON)
    huge = "x" * 20000
    ext_mod.SkillExtractor().extract("task", huge, eval_fail)

    prompt = fake.call_args[0][0]
    # Trace is capped at 8000 chars; full 20k must not appear verbatim.
    assert huge not in prompt


def test_extract_contrastive_uses_both_traces(monkeypatch, eval_pass, eval_fail):
    fake = install_fake_skill_llm(monkeypatch, VALID_TASK_SKILL_JSON)
    skill = ext_mod.SkillExtractor().extract_contrastive(
        "My Task", "PASS_TRACE_MARKER", "FAIL_TRACE_MARKER", eval_pass, eval_fail
    )
    assert skill is not None
    assert skill.id == "skill_implement_endpoint"
    prompt = fake.call_args[0][0]
    assert "PASS_TRACE_MARKER" in prompt
    assert "FAIL_TRACE_MARKER" in prompt


def test_extract_contrastive_bad_json_returns_none(monkeypatch, eval_pass, eval_fail):
    install_fake_skill_llm(monkeypatch, "not json")
    skill = ext_mod.SkillExtractor().extract_contrastive("t", "p", "f", eval_pass, eval_fail)
    assert skill is None
