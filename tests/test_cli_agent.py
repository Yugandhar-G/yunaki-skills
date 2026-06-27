"""Tests for the generic CLI coding-agent adapter (no real CLIs invoked)."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from tests.conftest import make_task_skill
from yunaki_skills import cli_agent
from yunaki_skills.agent_specs import AgentSpec


def _completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=["x"], returncode=returncode, stdout=stdout, stderr=stderr)


def _spec(parser_kind="text", argv=("-p", "{prompt}")):
    return AgentSpec(name="fake", binary="fake-bin", argv_template=argv, parser_kind=parser_kind)


def test_argv_built_with_prompt_as_single_element(monkeypatch):
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return _completed(stdout="ok")

    monkeypatch.setattr(cli_agent.subprocess, "run", fake_run)
    adapter = cli_agent.CliAgentAdapter(_spec(argv=("-p", "{prompt}", "--json")))
    adapter.run_task("implement GET /users", [make_task_skill()], "/work/dir")

    argv = captured["argv"]
    assert argv[0] == "fake-bin"
    assert argv[1] == "-p"
    # the whole prompt is one argv element
    prompt = argv[2]
    assert "implement GET /users" in prompt
    assert "INJECTED SKILLS" in prompt  # skills block was composed in
    assert argv[3] == "--json"
    assert captured["kwargs"]["cwd"] == "/work/dir"
    assert captured["kwargs"]["timeout"] == 300


def test_claude_json_parsed(monkeypatch):
    payload = json.dumps({"type": "result", "result": "I edited app.py", "is_error": False})
    monkeypatch.setattr(cli_agent.subprocess, "run", lambda *a, **k: _completed(stdout=payload))
    adapter = cli_agent.CliAgentAdapter(_spec(parser_kind="claude_json"))
    trace = adapter.run_task("t", [], "/w")
    assert "I edited app.py" in trace
    assert "backend=fake" in trace


def test_codex_jsonl_parsed(monkeypatch):
    lines = "\n".join(
        [
            json.dumps({"type": "thread.started"}),
            json.dumps({"type": "item", "item": {"text": "first chunk"}}),
            json.dumps({"type": "item", "item": {"text": "second chunk"}}),
            json.dumps({"type": "turn.completed"}),
        ]
    )
    monkeypatch.setattr(cli_agent.subprocess, "run", lambda *a, **k: _completed(stdout=lines))
    adapter = cli_agent.CliAgentAdapter(_spec(parser_kind="codex_jsonl"))
    trace = adapter.run_task("t", [], "/w")
    assert "first chunk" in trace
    assert "second chunk" in trace


def test_text_parser_uses_raw_stdout(monkeypatch):
    monkeypatch.setattr(cli_agent.subprocess, "run", lambda *a, **k: _completed(stdout="plain agent output"))
    adapter = cli_agent.CliAgentAdapter(_spec(parser_kind="text"))
    trace = adapter.run_task("t", [], "/w")
    assert "plain agent output" in trace


def test_malformed_json_falls_back_to_raw(monkeypatch):
    monkeypatch.setattr(cli_agent.subprocess, "run", lambda *a, **k: _completed(stdout="not json at all"))
    adapter = cli_agent.CliAgentAdapter(_spec(parser_kind="claude_json"))
    trace = adapter.run_task("t", [], "/w")
    assert "not json at all" in trace


def test_nonzero_exit_surfaced_no_raise(monkeypatch):
    monkeypatch.setattr(
        cli_agent.subprocess,
        "run",
        lambda *a, **k: _completed(stdout="", stderr="auth required", returncode=2),
    )
    adapter = cli_agent.CliAgentAdapter(_spec(parser_kind="text"))
    trace = adapter.run_task("t", [], "/w")
    assert "code 2" in trace.lower()
    assert "auth required" in trace


def test_timeout_surfaced_no_raise(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="fake-bin", timeout=240)

    monkeypatch.setattr(cli_agent.subprocess, "run", boom)
    adapter = cli_agent.CliAgentAdapter(_spec(parser_kind="text"))
    trace = adapter.run_task("t", [], "/w")
    assert "timed out" in trace.lower()


def test_missing_binary_surfaced_no_raise(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("fake-bin")

    monkeypatch.setattr(cli_agent.subprocess, "run", boom)
    adapter = cli_agent.CliAgentAdapter(_spec(parser_kind="text"))
    trace = adapter.run_task("t", [], "/w")
    assert "not found" in trace.lower()


def test_trace_is_capped(monkeypatch):
    huge = "x" * 100_000
    monkeypatch.setattr(cli_agent.subprocess, "run", lambda *a, **k: _completed(stdout=huge))
    adapter = cli_agent.CliAgentAdapter(_spec(parser_kind="text"))
    trace = adapter.run_task("t", [], "/w")
    assert len(trace) <= cli_agent._MAX_TRACE_CHARS + 200  # header + cap
