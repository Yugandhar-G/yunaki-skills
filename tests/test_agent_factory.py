"""Tests for backend selection / detection."""

from __future__ import annotations

import pytest

from yunaki_skills import agent_factory, agent_specs
from yunaki_skills.cli_agent import CliAgentAdapter


@pytest.fixture
def no_clis(monkeypatch):
    """Nothing on PATH."""
    monkeypatch.setattr(agent_specs.shutil, "which", lambda binary: None)


@pytest.fixture
def fake_sdk(monkeypatch):
    """Stub AntigravityClient so the SDK fallback needs no API key."""
    sentinel = object()
    monkeypatch.setattr(agent_factory, "AntigravityClient", lambda: sentinel)
    return sentinel


def _only(monkeypatch, *available):
    monkeypatch.setattr(
        agent_specs.shutil, "which", lambda binary: "/x" if binary in available else None
    )


def test_override_selects_named_backend(monkeypatch, fake_sdk):
    _only(monkeypatch, "claude", "codex")
    monkeypatch.setenv("YUNAKI_AGENT_BACKEND", "codex")
    agent = agent_factory.build_agent()
    assert isinstance(agent, CliAgentAdapter)
    assert agent._spec.name == "codex"


def test_override_missing_binary_raises(monkeypatch, fake_sdk):
    _only(monkeypatch)  # nothing available
    monkeypatch.setenv("YUNAKI_AGENT_BACKEND", "cursor")
    with pytest.raises(RuntimeError, match="not found on PATH"):
        agent_factory.build_agent()


def test_override_unknown_backend_raises(monkeypatch, fake_sdk):
    monkeypatch.setenv("YUNAKI_AGENT_BACKEND", "totally-made-up")
    with pytest.raises(RuntimeError, match="not a known backend"):
        agent_factory.build_agent()


def test_override_gemini_sdk(monkeypatch, fake_sdk):
    monkeypatch.setenv("YUNAKI_AGENT_BACKEND", "gemini-sdk")
    assert agent_factory.build_agent() is fake_sdk


def test_autodetect_picks_first_available(monkeypatch, fake_sdk):
    monkeypatch.delenv("YUNAKI_AGENT_BACKEND", raising=False)
    _only(monkeypatch, "aider", "cursor-agent")  # cursor + aider present
    agent = agent_factory.build_agent()
    assert isinstance(agent, CliAgentAdapter)
    assert agent._spec.name == "cursor"  # registry order: cursor before aider


def test_fallback_to_sdk_when_no_cli(monkeypatch, fake_sdk, no_clis):
    monkeypatch.delenv("YUNAKI_AGENT_BACKEND", raising=False)
    assert agent_factory.build_agent() is fake_sdk


def test_selection_summary_does_not_construct_clients(monkeypatch):
    monkeypatch.delenv("YUNAKI_AGENT_BACKEND", raising=False)
    _only(monkeypatch, "claude")
    summary = agent_factory.selection_summary()
    assert summary["selected"] == "claude"
    assert "claude" in summary["available"]
    assert summary["override"] is None
