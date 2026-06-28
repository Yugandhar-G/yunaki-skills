"""Tests for SkillIngestor — format detection, parsing, normalization, and the
skill_llm freeform path.

The skill model is stubbed to return "" by default (an autouse fixture), which
forces the deterministic heuristic fallback so the suite never calls a real
CLI/LLM regardless of which coding agent is installed. Tests that exercise the
structured freeform path override the stub explicitly.
"""

from __future__ import annotations

import json

import pytest

import yunaki_skills.skill_ingestor as ing_mod
from yunaki_skills.skill_ingestor import (
    SkillIngestor,
    _coerce_float,
    _coerce_instructions,
    _first_present,
    _first_str,
)


@pytest.fixture(autouse=True)
def _stub_skill_llm(monkeypatch):
    """Default: the skill model returns nothing, so the ingestor takes its
    deterministic heuristic path. Keeps every test hermetic no matter which
    coding-agent CLI happens to be on PATH."""
    monkeypatch.setattr(ing_mod.skill_llm, "complete_json", lambda p: "")


@pytest.fixture
def ingestor() -> SkillIngestor:
    return SkillIngestor()


# ─── detect_format ────────────────────────────────────────────────────────────


def test_detect_format_json_by_extension(ingestor):
    assert ingestor.detect_format("{}", "skill.json") == "json"


def test_detect_format_md_by_extension(ingestor):
    assert ingestor.detect_format("# Title", "skill.md") == "md"


def test_detect_format_markdown_extension(ingestor):
    assert ingestor.detect_format("# T", "skill.markdown") == "md"


def test_detect_format_yaml_by_extension(ingestor):
    assert ingestor.detect_format("title: x", "skill.yaml") == "yaml"


def test_detect_format_yml_by_extension(ingestor):
    assert ingestor.detect_format("title: x", "skill.yml") == "yaml"


def test_detect_format_txt_by_extension(ingestor):
    assert ingestor.detect_format("hello world", "skill.txt") == "txt"


def test_detect_format_text_by_extension(ingestor):
    assert ingestor.detect_format("hello world", "skill.text") == "txt"


def test_detect_format_json_sniff_from_content(ingestor):
    content = '{"title": "test"}'
    assert ingestor.detect_format(content, "skill") == "json"


def test_detect_format_md_sniff_from_content(ingestor):
    content = "# My Skill\nSome description"
    assert ingestor.detect_format(content, "skill") == "md"


def test_detect_format_yaml_sniff_from_content(ingestor):
    content = "title: My Skill\nwhen: always"
    assert ingestor.detect_format(content, "skill") == "yaml"


def test_detect_format_empty_is_txt(ingestor):
    assert ingestor.detect_format("", "skill") == "txt"


def test_detect_format_json_list_sniff(ingestor):
    content = '[{"title": "x"}]'
    result = ingestor.detect_format(content, "skill")
    assert result in ("json", "txt", "yaml", "md")


# ─── ingest — JSON format ─────────────────────────────────────────────────────


def test_ingest_json_canonical_skill(ingestor):
    skill_data = {
        "id": "skill_test",
        "title": "Test Skill",
        "granularity": "task_level",
        "version": "0.1",
        "score": 75.0,
        "trigger": {
            "type": "semantic",
            "query": "test query",
            "match_on": "task_description",
        },
        "when_to_apply": "when testing",
        "instructions": ["step1", "step2"],
        "provenance": {"task": "test"},
    }
    content = json.dumps(skill_data)
    result = ingestor.ingest(content, "skill.json")
    assert result.format_detected == "json"
    assert result.skill.title == "Test Skill"
    assert result.skill.id == "skill_test"


def test_ingest_json_flexible_keys(ingestor):
    data = {
        "name": "My Skill",
        "context": "When implementing APIs",
        "steps": ["step one", "step two"],
        "version": "1.0",
        "score": 80.0,
    }
    result = ingestor.ingest(json.dumps(data), "skill.json")
    assert result.format_detected == "json"
    assert result.skill.title == "My Skill"
    assert "step one" in result.skill.instructions


def test_ingest_json_with_query_alias(ingestor):
    data = {
        "heading": "API Patterns",
        "description": "Use REST conventions",
        "checklist": ["check auth", "validate input"],
        "intent": "rest api conventions",
    }
    result = ingestor.ingest(json.dumps(data), "skill.json")
    assert result.skill.trigger.query == "rest api conventions"


def test_ingest_json_no_instructions_derives_them(ingestor):
    data = {"title": "No Steps Skill", "when_to_apply": "always"}
    result = ingestor.ingest(json.dumps(data), "skill.json")
    assert len(result.skill.instructions) >= 1
    assert any("no instructions found" in w for w in result.warnings)


def test_ingest_json_with_score_coercion(ingestor):
    data = {"title": "Score Test", "steps": ["do it"], "score": "85"}
    result = ingestor.ingest(json.dumps(data), "skill.json")
    assert result.skill.score == 85.0


def test_ingest_json_non_dict_falls_back_to_text(ingestor):
    result = ingestor.ingest("[1, 2, 3]", "skill.json")
    assert result.skill is not None  # always returns something


def test_ingest_json_stamps_org_id(ingestor):
    data = {"title": "Org Skill", "steps": ["do it"]}
    result = ingestor.ingest(json.dumps(data), "skill.json", org_id="org_123")
    assert result.skill.org_id == "org_123"


def test_ingest_json_stamps_source_format(ingestor):
    data = {"title": "Format Skill", "steps": ["do it"]}
    result = ingestor.ingest(json.dumps(data), "skill.json")
    assert result.skill.source_format == "json"


def test_ingest_json_stamps_source_uri(ingestor):
    data = {"title": "URI Skill", "steps": ["do it"]}
    result = ingestor.ingest(json.dumps(data), "my_skill.json")
    assert result.skill.source_uri == "my_skill.json"


# ─── ingest — Markdown format ─────────────────────────────────────────────────


def test_ingest_md_basic(ingestor):
    content = "# My Markdown Skill\n\nUse this when writing Python code.\n\n- Step 1\n- Step 2\n- Step 3"
    result = ingestor.ingest(content, "skill.md")
    assert result.format_detected == "md"
    assert result.skill.title == "My Markdown Skill"
    assert "Step 1" in result.skill.instructions


def test_ingest_md_numbered_list(ingestor):
    content = "# Numbered\n\n1. First step\n2. Second step"
    result = ingestor.ingest(content, "skill.md")
    assert "First step" in result.skill.instructions
    assert "Second step" in result.skill.instructions


def test_ingest_md_asterisk_bullets(ingestor):
    content = "# Asterisk Skill\n\n* step A\n* step B"
    result = ingestor.ingest(content, "skill.md")
    assert "step A" in result.skill.instructions


def test_ingest_md_plus_bullets(ingestor):
    content = "# Plus Skill\n\n+ step X\n+ step Y"
    result = ingestor.ingest(content, "skill.md")
    assert "step X" in result.skill.instructions


def test_ingest_md_no_bullets_warns(ingestor):
    content = "# No Bullets\n\nThis is just prose without any bullets."
    result = ingestor.ingest(content, "skill.md")
    assert any("no bullet" in w for w in result.warnings)
    assert len(result.skill.instructions) >= 1


def test_ingest_md_extracts_when_to_apply_from_prose(ingestor):
    content = "# Skill\n\nUse when building REST APIs.\n\n- step one"
    result = ingestor.ingest(content, "skill.md")
    assert "REST" in result.skill.when_to_apply


def test_ingest_md_no_header_warns(ingestor):
    """Markdown without any header falls back to first line as title."""
    content = "Just some text\n\n- do this\n- do that"
    result = ingestor.ingest(content, "skill.md")
    assert any("no markdown header" in w for w in result.warnings)
    assert result.skill.title  # still has a title


def test_ingest_md_h2_header_used(ingestor):
    content = "## Section Two Skill\n\n- step"
    result = ingestor.ingest(content, "skill.md")
    assert "Section Two Skill" in result.skill.title


# ─── ingest — Text format (deterministic heuristic fallback) ─────────────────


def test_ingest_txt_basic(ingestor):
    content = "Always validate user input at API boundaries. Reject invalid data early."
    result = ingestor.ingest(content, "skill.txt")
    assert result.format_detected == "txt"
    assert result.skill is not None
    # Stubbed skill model returns "" -> heuristic path -> this warning.
    assert any("structured extraction unavailable" in w for w in result.warnings)


def test_ingest_txt_with_bullets(ingestor):
    content = "Use these steps:\n- validate input\n- log errors\n- return 400 on failure"
    result = ingestor.ingest(content, "skill.txt")
    assert "validate input" in result.skill.instructions


def test_ingest_txt_fallback_instructions(ingestor):
    """When content has no bullets, sentences are used as instructions."""
    content = "Validate all inputs. Log errors to the server. Return proper status codes."
    result = ingestor.ingest(content, "skill.txt")
    assert len(result.skill.instructions) >= 1


def test_ingest_empty_content(ingestor):
    result = ingestor.ingest("", "skill.txt")
    assert result.skill is not None
    assert result.skill.title  # must always produce something


# ─── ingest — YAML format ────────────────────────────────────────────────────


def test_ingest_yaml_basic(ingestor):
    content = "title: YAML Skill\nwhen_to_apply: when needed\ninstructions:\n  - step a\n  - step b"
    result = ingestor.ingest(content, "skill.yaml")
    assert result.format_detected == "yaml"
    assert result.skill is not None
    assert result.skill.title  # has some title


def test_ingest_yaml_with_pyyaml(ingestor):
    """When PyYAML is available, YAML is parsed correctly."""
    try:
        import yaml  # noqa: F401
    except ImportError:
        pytest.skip("PyYAML not installed")
    content = "title: YAML Skill\nwhen_to_apply: when needed\ninstructions:\n  - step a\n  - step b"
    result = ingestor.ingest(content, "skill.yaml")
    assert result.format_detected == "yaml"
    assert result.skill.title == "YAML Skill"
    assert "step a" in result.skill.instructions


def test_ingest_yaml_without_pyyaml_falls_back(monkeypatch):
    """If PyYAML is missing, gracefully falls back to text."""
    import sys

    ingestor = SkillIngestor()
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(sys.modules, "yaml", None)
        content = "title: No YAML Lib\nsteps:\n  - do it"
        result = ingestor.ingest(content, "skill.yaml")
    assert result.skill is not None


# ─── _build_skill / _gen_id ──────────────────────────────────────────────────


def test_build_skill_produces_valid_skill(ingestor):
    skill = ingestor._build_skill(
        skill_id="test_id",
        title="Test",
        when_to_apply="when needed",
        instructions=["step 1", "step 2"],
        query="test query",
    )
    assert skill.id == "test_id"
    assert skill.title == "Test"


def test_build_skill_empty_instructions_gets_fallback(ingestor):
    skill = ingestor._build_skill(
        skill_id="id",
        title="Title",
        when_to_apply="when",
        instructions=[],
        query="query",
    )
    assert len(skill.instructions) >= 1
    assert "Title" in skill.instructions[0]


def test_gen_id_slugifies_title():
    sid = SkillIngestor._gen_id("My FastAPI Skill!")
    assert "skill_" in sid
    assert " " not in sid
    assert "!" not in sid


def test_gen_id_empty_title_uses_uuid():
    sid = SkillIngestor._gen_id("")
    assert sid.startswith("skill_")
    assert len(sid) > 6


# ─── _derive_* helpers ────────────────────────────────────────────────────────


def test_derive_title_from_first_line():
    title = SkillIngestor._derive_title("Hello World\nSecond line")
    assert title == "Hello World"


def test_derive_title_strips_hash():
    title = SkillIngestor._derive_title("# Skill Title\nContent")
    assert title == "Skill Title"


def test_derive_title_empty_content():
    title = SkillIngestor._derive_title("")
    assert title == "Imported Skill"


def test_derive_when_from_first_paragraph():
    content = "This is the first paragraph.\n\nThis is the second."
    when = SkillIngestor._derive_when(content, "My Skill")
    assert "first paragraph" in when


def test_derive_when_empty_content():
    when = SkillIngestor._derive_when("", "My Skill")
    assert "My Skill" in when


def test_derive_instructions_bullets():
    content = "Some text\n- step one\n- step two\n- step three"
    steps = SkillIngestor._derive_instructions(content)
    assert "step one" in steps
    assert "step two" in steps


def test_derive_instructions_numbered():
    content = "1. First step\n2. Second step"
    steps = SkillIngestor._derive_instructions(content)
    assert "First step" in steps


def test_derive_instructions_sentences_fallback():
    content = "Always validate inputs. Return 400 on failure. Log all errors to the server."
    steps = SkillIngestor._derive_instructions(content)
    assert len(steps) >= 1


def test_derive_instructions_empty_fallback():
    steps = SkillIngestor._derive_instructions("")
    assert steps == ["Apply the described approach to the task"]


# ─── _semantic_query ──────────────────────────────────────────────────────────


def test_semantic_query_removes_stopwords(ingestor):
    query = ingestor._semantic_query("this is a simple test for the system")
    assert "this" not in query
    assert "simple" in query or "test" in query or "system" in query


def test_semantic_query_empty_content(ingestor):
    query = ingestor._semantic_query("")
    assert isinstance(query, str)


def test_semantic_query_limits_tokens(ingestor):
    long_content = " ".join(f"word{i}" for i in range(100))
    query = ingestor._semantic_query(long_content)
    assert len(query.split()) <= 12


# ─── Module-level helper functions ──────────────────────────────────────────


def test_first_present_finds_first_matching_key():
    data = {"title": "x", "name": "y"}
    result = _first_present(data, ("name", "title"))
    assert result == "y"


def test_first_present_returns_none_when_not_found():
    assert _first_present({}, ("a", "b")) is None


def test_first_present_skips_none_values():
    data = {"a": None, "b": "found"}
    assert _first_present(data, ("a", "b")) == "found"


def test_first_str_returns_string():
    data = {"title": "  Hello  "}
    assert _first_str(data, ("title",)) == "Hello"


def test_first_str_coerces_non_string():
    data = {"score": 42}
    assert _first_str(data, ("score",)) == "42"


def test_first_str_returns_empty_when_not_found():
    assert _first_str({}, ("missing",)) == ""


def test_coerce_instructions_list_of_strings():
    result = _coerce_instructions(["step a", "step b"])
    assert result == ["step a", "step b"]


def test_coerce_instructions_string_multiline():
    result = _coerce_instructions("- step 1\n- step 2")
    assert "step 1" in result


def test_coerce_instructions_list_of_dicts():
    items = [{"step": "First"}, {"text": "Second"}, {"action": "Third"}]
    result = _coerce_instructions(items)
    assert "First" in result
    assert "Second" in result
    assert "Third" in result


def test_coerce_instructions_none_returns_empty():
    assert _coerce_instructions(None) == []


def test_coerce_instructions_skips_blank_strings():
    result = _coerce_instructions(["valid step", "  ", "another step"])
    assert "  " not in result


def test_coerce_float_valid():
    assert _coerce_float("3.14", 0.0) == 3.14


def test_coerce_float_int():
    assert _coerce_float(5, 0.0) == 5.0


def test_coerce_float_invalid_returns_default():
    assert _coerce_float("not a number", 42.0) == 42.0


def test_coerce_float_none_returns_default():
    assert _coerce_float(None, 99.0) == 99.0


# ─── freeform path through skill_llm (explicit stub overrides) ───────────────

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
