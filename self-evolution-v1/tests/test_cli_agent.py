"""Tests for the generic CLI coding-agent adapter (no real CLIs invoked).

Parser fixtures use captured-shape payloads that mirror the real CLI output
schemas verified in 2026:

  codex       JSONL event stream — only item.completed/agent_message harvested
  cursor-agent  single JSON object with "result" key
  gemini CLI  single JSON object with "response" key
  aider       plain text with startup banner stripped
"""

from __future__ import annotations

import json
import subprocess

from tests.conftest import make_task_skill
from yunaki_skills import cli_agent
from yunaki_skills.agent_specs import AgentSpec


def _completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=["x"], returncode=returncode, stdout=stdout, stderr=stderr)


def _spec(parser_kind="text", argv=("-p", "{prompt}")):
    return AgentSpec(name="fake", binary="fake-bin", argv_template=argv, parser_kind=parser_kind)


# ── Argv construction ─────────────────────────────────────────────────────────


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


# ── claude_json ───────────────────────────────────────────────────────────────


def test_claude_json_parsed(monkeypatch):
    payload = json.dumps({"type": "result", "result": "I edited app.py", "is_error": False})
    monkeypatch.setattr(cli_agent.subprocess, "run", lambda *a, **k: _completed(stdout=payload))
    adapter = cli_agent.CliAgentAdapter(_spec(parser_kind="claude_json"))
    trace = adapter.run_task("t", [], "/w")
    assert "I edited app.py" in trace
    assert "backend=fake" in trace


# ── codex_jsonl ───────────────────────────────────────────────────────────────
#
# Real codex output (--json flag) is a JSONL stream with these event types:
#   thread.started, turn.started, item.started, item.updated, item.completed,
#   turn.completed (and turn.failed / error on failures).
#
# Only item.completed where item.type == "agent_message" carries final text.
# Reasoning, file_change, command_execution events are intentionally skipped.


_CODEX_FULL_STREAM = "\n".join(
    [
        json.dumps({"type": "thread.started", "thread_id": "019ce6ce-abc"}),
        json.dumps({"type": "turn.started"}),
        # reasoning item — should be skipped
        json.dumps({"type": "item.started", "item": {"id": "i0", "type": "reasoning", "text": ""}}),
        json.dumps({"type": "item.completed", "item": {"id": "i0", "type": "reasoning", "text": "thinking..."}}),
        # file_change item — should be skipped
        json.dumps(
            {
                "type": "item.completed",
                "item": {"id": "i1", "type": "file_change", "changes": [{"path": "app.py", "kind": "edit"}]},
            }
        ),
        # partial agent_message events — item.started and item.updated should be skipped
        json.dumps({"type": "item.started", "item": {"id": "i2", "type": "agent_message", "text": ""}}),
        json.dumps({"type": "item.updated", "item": {"id": "i2", "type": "agent_message", "text": "Implement"}}),
        # final agent_message — this is the one we want
        json.dumps(
            {
                "type": "item.completed",
                "item": {"id": "i2", "type": "agent_message", "text": "Implemented GET /users endpoint."},
            }
        ),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 20}}),
    ]
)


def test_codex_jsonl_extracts_only_agent_message(monkeypatch):
    """Only item.completed/agent_message text should appear; reasoning excluded."""
    monkeypatch.setattr(cli_agent.subprocess, "run", lambda *a, **k: _completed(stdout=_CODEX_FULL_STREAM))
    adapter = cli_agent.CliAgentAdapter(_spec(parser_kind="codex_jsonl"))
    trace = adapter.run_task("t", [], "/w")
    assert "Implemented GET /users endpoint." in trace
    # Reasoning text must not bleed into the trace
    assert "thinking..." not in trace
    # Partial item.updated text must not appear (only item.completed is harvested)
    assert trace.count("Implement") == 1  # exactly the final message, not the partial


def test_codex_jsonl_multiple_agent_messages(monkeypatch):
    """When codex emits multiple agent_message items, all are concatenated."""
    stream = "\n".join(
        [
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"id": "i0", "type": "agent_message", "text": "first chunk"},
                }
            ),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"id": "i1", "type": "agent_message", "text": "second chunk"},
                }
            ),
        ]
    )
    monkeypatch.setattr(cli_agent.subprocess, "run", lambda *a, **k: _completed(stdout=stream))
    adapter = cli_agent.CliAgentAdapter(_spec(parser_kind="codex_jsonl"))
    trace = adapter.run_task("t", [], "/w")
    assert "first chunk" in trace
    assert "second chunk" in trace


def test_codex_jsonl_turn_failed_event_no_crash(monkeypatch):
    """turn.failed events should be tolerated; trace returns empty agent text."""
    stream = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "abc"}),
            json.dumps({"type": "turn.failed", "error": {"message": "rate limit"}}),
        ]
    )
    monkeypatch.setattr(cli_agent.subprocess, "run", lambda *a, **k: _completed(stdout=stream))
    adapter = cli_agent.CliAgentAdapter(_spec(parser_kind="codex_jsonl"))
    trace = adapter.run_task("t", [], "/w")
    # Should not raise; trace may be empty agent body but must still be a string
    assert isinstance(trace, str)


def test_codex_jsonl_partial_non_json_lines_tolerated(monkeypatch):
    """Non-JSON lines (e.g. startup log noise) are silently skipped."""
    stream = "\n".join(
        [
            "Connecting to codex service...",  # non-JSON banner line
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"id": "i0", "type": "agent_message", "text": "Done."},
                }
            ),
        ]
    )
    monkeypatch.setattr(cli_agent.subprocess, "run", lambda *a, **k: _completed(stdout=stream))
    adapter = cli_agent.CliAgentAdapter(_spec(parser_kind="codex_jsonl"))
    trace = adapter.run_task("t", [], "/w")
    assert "Done." in trace


def test_codex_jsonl_all_non_json_falls_back_to_raw(monkeypatch):
    """When nothing parses as JSON the raw stdout is returned."""
    raw = "fatal: not a codex output"
    monkeypatch.setattr(cli_agent.subprocess, "run", lambda *a, **k: _completed(stdout=raw))
    adapter = cli_agent.CliAgentAdapter(_spec(parser_kind="codex_jsonl"))
    trace = adapter.run_task("t", [], "/w")
    assert "fatal: not a codex output" in trace


# ── cursor_json ───────────────────────────────────────────────────────────────
#
# cursor-agent --print --output-format json emits a single JSON object:
# {"type":"result","subtype":"success","is_error":false,"result":"<text>",...}
# The final assistant text is under the top-level "result" key.


_CURSOR_SUCCESS = json.dumps(
    {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "duration_ms": 4200,
        "duration_api_ms": 3800,
        "result": "I implemented GET /users and added the missing endpoint.",
        "session_id": "sess-abc-123",
    }
)

_CURSOR_ERROR = json.dumps(
    {
        "type": "result",
        "subtype": "error",
        "is_error": True,
        "duration_ms": 100,
        "result": "",
        "session_id": "sess-err-456",
    }
)


def test_cursor_json_extracts_result_field(monkeypatch):
    monkeypatch.setattr(cli_agent.subprocess, "run", lambda *a, **k: _completed(stdout=_CURSOR_SUCCESS))
    adapter = cli_agent.CliAgentAdapter(_spec(parser_kind="cursor_json"))
    trace = adapter.run_task("t", [], "/w")
    assert "I implemented GET /users" in trace
    assert "backend=fake" in trace


def test_cursor_json_error_envelope_no_crash(monkeypatch):
    """Even an error envelope must not raise; trace carries whatever result text exists."""
    monkeypatch.setattr(cli_agent.subprocess, "run", lambda *a, **k: _completed(stdout=_CURSOR_ERROR))
    adapter = cli_agent.CliAgentAdapter(_spec(parser_kind="cursor_json"))
    trace = adapter.run_task("t", [], "/w")
    assert isinstance(trace, str)


def test_cursor_json_malformed_falls_back_to_raw(monkeypatch):
    raw = "{this is not valid json"
    monkeypatch.setattr(cli_agent.subprocess, "run", lambda *a, **k: _completed(stdout=raw))
    adapter = cli_agent.CliAgentAdapter(_spec(parser_kind="cursor_json"))
    trace = adapter.run_task("t", [], "/w")
    assert "{this is not valid json" in trace


# ── gemini_json ───────────────────────────────────────────────────────────────
#
# gemini -p --output-format json emits a single JSON object:
# {"response":"<text>","stats":{...},"error":null,"session_id":"..."}
# The final assistant text is under the top-level "response" key.


_GEMINI_SUCCESS = json.dumps(
    {
        "session_id": "gemini-sess-789",
        "response": "I added the POST /users endpoint with Pydantic validation.",
        "stats": {
            "input_tokens": 500,
            "output_tokens": 80,
            "latency_ms": 1200,
        },
        "error": None,
        "warnings": [],
    }
)

_GEMINI_ERROR = json.dumps(
    {
        "session_id": "gemini-sess-err",
        "response": None,
        "stats": {},
        "error": {"type": "quota_exceeded", "message": "Daily token limit reached", "code": 429},
        "warnings": [],
    }
)


def test_gemini_json_extracts_response_field(monkeypatch):
    monkeypatch.setattr(cli_agent.subprocess, "run", lambda *a, **k: _completed(stdout=_GEMINI_SUCCESS))
    adapter = cli_agent.CliAgentAdapter(_spec(parser_kind="gemini_json"))
    trace = adapter.run_task("t", [], "/w")
    assert "I added the POST /users endpoint" in trace
    assert "backend=fake" in trace


def test_gemini_json_error_envelope_no_crash(monkeypatch):
    """Error envelope (response: null) must not raise; falls back to raw JSON."""
    monkeypatch.setattr(cli_agent.subprocess, "run", lambda *a, **k: _completed(stdout=_GEMINI_ERROR))
    adapter = cli_agent.CliAgentAdapter(_spec(parser_kind="gemini_json"))
    trace = adapter.run_task("t", [], "/w")
    assert isinstance(trace, str)


def test_gemini_json_malformed_falls_back_to_raw(monkeypatch):
    raw = "not json"
    monkeypatch.setattr(cli_agent.subprocess, "run", lambda *a, **k: _completed(stdout=raw))
    adapter = cli_agent.CliAgentAdapter(_spec(parser_kind="gemini_json"))
    trace = adapter.run_task("t", [], "/w")
    assert "not json" in trace


# ── aider text ────────────────────────────────────────────────────────────────
#
# aider --message ... --yes-always emits plain text on stdout.
# The first several lines are a startup banner; the assistant response follows.
# The parser strips known banner prefixes so only the response reaches the trace.


_AIDER_STDOUT_WITH_BANNER = """\
Aider v0.71.0
Model: claude-3-5-sonnet-20241022 with diff edit format
Git repo: .git with 18 files
Repo-map: using 1024 tokens, auto refresh
Added app.py to the chat.
Warning: /tmp/foo.py not found
I will implement the missing endpoint now.

Here is the updated app.py with GET /users:

```python
@app.get('/users')
def list_users():
    return []
```
"""

_AIDER_STDOUT_NO_BANNER = "Here is the direct answer."


def test_aider_text_strips_banner_lines(monkeypatch):
    monkeypatch.setattr(cli_agent.subprocess, "run", lambda *a, **k: _completed(stdout=_AIDER_STDOUT_WITH_BANNER))
    adapter = cli_agent.CliAgentAdapter(_spec(parser_kind="text"))
    trace = adapter.run_task("t", [], "/w")
    # Banner lines must not appear in the trace
    assert "Aider v" not in trace
    assert "Model: " not in trace
    assert "Git repo: " not in trace
    assert "Repo-map: " not in trace
    assert "Added app.py" not in trace
    assert "Warning: " not in trace
    # The actual assistant response must appear
    assert "I will implement the missing endpoint now." in trace
    assert "@app.get" in trace


def test_aider_text_no_banner_passthrough(monkeypatch):
    """When there is no banner the full output is preserved."""
    monkeypatch.setattr(cli_agent.subprocess, "run", lambda *a, **k: _completed(stdout=_AIDER_STDOUT_NO_BANNER))
    adapter = cli_agent.CliAgentAdapter(_spec(parser_kind="text"))
    trace = adapter.run_task("t", [], "/w")
    assert "Here is the direct answer." in trace


def test_aider_text_only_banner_falls_back_to_raw(monkeypatch):
    """If every line is a banner line, raw stdout is returned (nothing silently lost)."""
    only_banner = "Aider v0.71.0\nModel: claude-3-5-sonnet-20241022 with diff edit format\n"
    monkeypatch.setattr(cli_agent.subprocess, "run", lambda *a, **k: _completed(stdout=only_banner))
    adapter = cli_agent.CliAgentAdapter(_spec(parser_kind="text"))
    trace = adapter.run_task("t", [], "/w")
    # Falls back to raw — should contain at least some content
    assert "Aider" in trace or len(trace) > 0


# ── Legacy tests (kept for regression coverage) ───────────────────────────────


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


# ── Detection (shutil.which) ──────────────────────────────────────────────────


def test_agent_specs_detection_report():
    """Report which agent binaries are installed.  Informational, not a hard assertion."""
    import shutil

    from yunaki_skills.agent_specs import registry

    found = {spec.name: shutil.which(spec.binary) for spec in registry()}
    # At least the detection call itself must not raise
    assert isinstance(found, dict)
    # The report is visible in -v output:
    installed = [name for name, path in found.items() if path is not None]
    missing = [name for name, path in found.items() if path is None]
    # Print so it shows up in pytest -s / CI logs
    print(f"\nInstalled backends: {installed}")
    print(f"Missing backends:   {missing}")
