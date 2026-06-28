"""Tests for SkillIngestor — freeform extraction routes through skill_llm."""

from __future__ import annotations

import json

from yunaki_skills import skill_ingestor as ing_mod
from yunaki_skills.skill_ingestor import SkillIngestor

FREEFORM = "When the API returns 500, check the database connection pool before retrying."

STRUCTURED_JSON = json.dumps(
    {
        "title": "Diagnose 500s via connection pool",
        "when_to_apply": "When an endpoint intermittently returns 500",
        "instructions": ["Inspect the pool size", "Check for leaked connections"],
        "query": "api 500 database connection pool",
    }
)


def test_freeform_text_uses_skill_llm(monkeypatch):
    monkeypatch.setattr(ing_mod.skill_llm, "complete_json", lambda p: STRUCTURED_JSON)
    result = SkillIngestor().ingest(FREEFORM, filename="note.txt")

    assert result.skill.title == "Diagnose 500s via connection pool"
    assert "Inspect the pool size" in result.skill.instructions
    assert result.format_detected == "txt"


def test_freeform_falls_back_when_model_empty(monkeypatch):
    # Empty model output must not crash — heuristic fallback kicks in.
    monkeypatch.setattr(ing_mod.skill_llm, "complete_json", lambda p: "")
    result = SkillIngestor().ingest(FREEFORM, filename="note.txt")

    assert result.skill is not None
    assert any("heuristic" in w for w in result.warnings)


def test_structured_json_does_not_call_model(monkeypatch):
    # A well-formed JSON skill must be parsed directly, never hitting the model.
    def boom(_):
        raise AssertionError("skill_llm must not be called for structured JSON input")

    monkeypatch.setattr(ing_mod.skill_llm, "complete_json", boom)
    payload = json.dumps({"title": "Already structured", "when_to_apply": "x", "instructions": ["a", "b"]})
    result = SkillIngestor().ingest(payload, filename="skill.json")
    assert result.skill.title == "Already structured"
    assert result.format_detected == "json"


def test_no_gemini_key_needed(monkeypatch):
    # Ingestor must not construct a genai client / require GEMINI_API_KEY.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(ing_mod.skill_llm, "complete_json", lambda p: STRUCTURED_JSON)
    result = SkillIngestor().ingest(FREEFORM, filename="note.txt")
    assert result.skill.title == "Diagnose 500s via connection pool"
