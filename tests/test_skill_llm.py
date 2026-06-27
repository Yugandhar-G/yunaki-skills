"""Tests for the skill-model LLM seam (routing + fence stripping)."""

from __future__ import annotations

from yunaki_skills import agent_specs, skill_llm
from yunaki_skills.agent_specs import AgentSpec


def test_strip_fences_plain():
    assert skill_llm._strip_fences('{"a": 1}') == '{"a": 1}'


def test_strip_fences_json_block():
    fenced = '```json\n{"a": 1}\n```'
    assert skill_llm._strip_fences(fenced) == '{"a": 1}'


def test_strip_fences_bare_block():
    fenced = '```\n{"a": 1}\n```'
    assert skill_llm._strip_fences(fenced) == '{"a": 1}'


def test_model_override_routes_to_sdk(monkeypatch):
    monkeypatch.setenv("YUNAKI_SKILL_MODEL", "gemini-2.5-flash-lite")
    captured = {}

    def fake_sdk(prompt, model):
        captured["model"] = model
        return '{"ok": true}'

    monkeypatch.setattr(skill_llm, "_complete_via_sdk", fake_sdk)
    # CLI must NOT be consulted when the model is pinned.
    monkeypatch.setattr(skill_llm, "_complete_via_cli", lambda *a, **k: pytest_fail())

    out = skill_llm.complete_json("prompt")
    assert out == '{"ok": true}'
    assert captured["model"] == "gemini-2.5-flash-lite"


def pytest_fail():  # helper used as a poisoned callable
    raise AssertionError("CLI backend should not be used when YUNAKI_SKILL_MODEL is set")


def test_autodetect_routes_to_cli(monkeypatch):
    monkeypatch.delenv("YUNAKI_SKILL_MODEL", raising=False)
    spec = AgentSpec("claude", "claude", ("-p", "{prompt}"), "text")
    monkeypatch.setattr(agent_specs, "available_specs", lambda: [spec])

    captured = {}

    def fake_cli(prompt, used_spec):
        captured["spec"] = used_spec
        return '{"via": "cli"}'

    monkeypatch.setattr(skill_llm, "_complete_via_cli", fake_cli)
    out = skill_llm.complete_json("prompt")
    assert out == '{"via": "cli"}'
    assert captured["spec"] is spec


def test_fallback_to_sdk_when_no_cli(monkeypatch):
    monkeypatch.delenv("YUNAKI_SKILL_MODEL", raising=False)
    monkeypatch.setattr(agent_specs, "available_specs", lambda: [])
    monkeypatch.setattr(skill_llm, "_complete_via_sdk", lambda prompt, model: f"sdk:{model}")
    out = skill_llm.complete_json("prompt")
    assert out == f"sdk:{skill_llm._DEFAULT_SDK_MODEL}"


def test_cli_backend_returns_empty_on_failure(monkeypatch):
    spec = AgentSpec("claude", "claude", ("-p", "{prompt}"), "text")
    # returncode None simulates a missing binary / timeout.
    monkeypatch.setattr("yunaki_skills.cli_agent.run_cli", lambda *a, **k: ("", "boom", None))
    assert skill_llm._complete_via_cli("p", spec) == ""


def test_active_model_label(monkeypatch):
    monkeypatch.setenv("YUNAKI_SKILL_MODEL", "gemini-x")
    assert skill_llm.active_model_label() == "gemini-x"
    monkeypatch.delenv("YUNAKI_SKILL_MODEL", raising=False)
    monkeypatch.setattr(agent_specs, "available_specs", lambda: [])
    assert skill_llm.active_model_label() == skill_llm._DEFAULT_SDK_MODEL
