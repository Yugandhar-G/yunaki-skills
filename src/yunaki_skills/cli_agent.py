"""Generic adapter that drives an installed coding-agent CLI in headless mode.

``CliAgentAdapter`` consumes an :class:`AgentSpec`, builds the argv, runs the CLI
inside ``repo_path`` (the CLI edits files in place), and parses stdout into the
trace string the evolution loop expects. It never raises into the loop: missing
binary, non-zero exit, and timeout are all folded into the returned trace so the
loop's existing error handling records them and proceeds.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import Callable

from yunaki_skills.agent_specs import AgentSpec
from yunaki_skills.antigravity_client import _format_skills_block
from yunaki_skills.interfaces import AgentClient, Skill

logger = logging.getLogger(__name__)

# Bound the trace so a runaway CLI can't blow up memory or downstream prompts.
_MAX_TRACE_CHARS = 16000
_MAX_STDERR_CHARS = 2000

# Keys a single-object JSON CLI response might carry the final text under.
_JSON_TEXT_KEYS = ("result", "response", "text", "content", "message", "output")


def _compose_prompt(task_description: str, skills: list[Skill]) -> str:
    """Build the single prompt string passed to the CLI.

    Unlike the Gemini SDK path (which uses a <<<FILE>>> protocol), real coding
    CLIs edit files directly, so we just instruct in-place edits and append the
    injected skills block verbatim.
    """
    skills_block = _format_skills_block(skills)
    return (
        "You are a coding agent. Complete the task by editing files directly in the "
        "current working directory. Make minimal changes and do NOT modify test files. "
        "Do not ask questions; implement the change.\n\n"
        f"TASK: {task_description}\n"
        f"{skills_block}"
    )


def _extract_from_obj(obj: object) -> str:
    """Pull the most likely 'final text' out of a parsed JSON object."""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        # Prefer a known text key at this level.
        for key in _JSON_TEXT_KEYS:
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                return val
        # Otherwise recurse into nested objects (e.g. codex's {"item": {"text": ...}}).
        for val in obj.values():
            if isinstance(val, dict):
                nested = _extract_from_obj(val)
                if nested:
                    return nested
    return ""


def _parse_single_json(stdout: str) -> str:
    """Parser for claude/cursor/gemini single-object JSON output."""
    try:
        obj = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return stdout  # fall back to raw
    text = _extract_from_obj(obj)
    return text or stdout


def _parse_jsonl(stdout: str) -> str:
    """Parser for codex JSONL streams — concatenate text from each event."""
    chunks: list[str] = []
    decoded_any = False
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue  # tolerate partial/non-JSON lines
        decoded_any = True
        text = _extract_from_obj(event)
        if text:
            chunks.append(text)
    if not decoded_any:
        return stdout  # nothing parseable — fall back to raw
    return "\n".join(chunks)


def _parse_text(stdout: str) -> str:
    return stdout


_PARSERS: dict[str, Callable[[str], str]] = {
    "claude_json": _parse_single_json,
    "cursor_json": _parse_single_json,
    "gemini_json": _parse_single_json,
    "codex_jsonl": _parse_jsonl,
    "text": _parse_text,
}


def run_cli(spec: AgentSpec, prompt: str, cwd: str) -> tuple[str, str, int | None]:
    """Invoke a coding-agent CLI once and return (parsed_body, stderr, returncode).

    ``returncode`` is None when the binary is missing or the run timed out (in
    which case ``stderr`` carries a human-readable reason). Never raises — every
    failure mode is folded into the return value. Shared by the coding-agent
    adapter and the skill-model LLM seam.
    """
    argv = [spec.binary] + [tok.format(prompt=prompt) for tok in spec.argv_template]
    env = {**os.environ, **dict(spec.extra_env)}
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=spec.timeout_s,
            env=env,
        )
    except FileNotFoundError as e:
        logger.error("Coding-agent binary %r not found on PATH", spec.binary)
        return ("", f"binary not found: {e}", None)
    except subprocess.TimeoutExpired:
        logger.error("Backend %s timed out after %ds", spec.name, spec.timeout_s)
        return ("", f"agent timed out after {spec.timeout_s}s", None)

    body = _PARSERS.get(spec.parser_kind, _parse_text)(proc.stdout or "")
    return (body, proc.stderr or "", proc.returncode)


class CliAgentAdapter(AgentClient):
    """Drives one coding-agent CLI described by an :class:`AgentSpec`."""

    def __init__(self, spec: AgentSpec):
        self._spec = spec

    def run_task(self, task_description: str, skills: list[Skill], repo_path: str) -> str:
        prompt = _compose_prompt(task_description, skills)
        body, stderr, returncode = run_cli(self._spec, prompt, repo_path)

        if returncode is None:
            # Missing binary or timeout — stderr holds the reason.
            return self._trace(stderr, "")
        if returncode != 0:
            logger.error("Backend %s exited with code %d", self._spec.name, returncode)
            body = f"[agent exited with code {returncode}]\n{body}"
        return self._trace(body, stderr)

    def _trace(self, body: str, stderr: str) -> str:
        body = body[:_MAX_TRACE_CHARS]
        stderr = stderr[:_MAX_STDERR_CHARS]
        return f"=== AGENT (backend={self._spec.name}) ===\n{body}\n=== STDERR ===\n{stderr}\n"
