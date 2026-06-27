"""Tests for the declarative coding-agent backend registry."""

from __future__ import annotations

from yunaki_skills import agent_specs


def test_registry_contains_known_backends():
    names = {s.name for s in agent_specs.registry()}
    assert {"claude", "codex", "cursor", "gemini-cli", "aider"} <= names


def test_specs_are_immutable():
    spec = agent_specs.registry()[0]
    # frozen dataclass — assignment must raise
    try:
        spec.name = "mutated"  # type: ignore[misc]
    except Exception as e:
        assert e.__class__.__name__ in {"FrozenInstanceError", "AttributeError"}
    else:
        raise AssertionError("AgentSpec should be frozen")


def test_argv_template_substitutes_prompt():
    spec = agent_specs.spec_by_name("claude")
    assert spec is not None
    argv = [spec.binary] + [tok.format(prompt="DO THING") for tok in spec.argv_template]
    assert argv[0] == "claude"
    assert "DO THING" in argv
    # the prompt must be a single argv element, never split
    assert argv.count("DO THING") == 1


def test_available_specs_filters_by_which(monkeypatch):
    # Only "codex" is on PATH.
    monkeypatch.setattr(
        agent_specs.shutil,
        "which",
        lambda binary: "/usr/bin/codex" if binary == "codex" else None,
    )
    available = agent_specs.available_specs()
    assert [s.name for s in available] == ["codex"]


def test_available_specs_preserves_registry_order(monkeypatch):
    # claude and aider both present -> claude first (registry preference order).
    monkeypatch.setattr(
        agent_specs.shutil,
        "which",
        lambda binary: "/x" if binary in {"claude", "aider"} else None,
    )
    available = agent_specs.available_specs()
    assert [s.name for s in available] == ["claude", "aider"]


def test_spec_by_name_unknown_returns_none():
    assert agent_specs.spec_by_name("does-not-exist") is None
