"""Declarative registry of coding-agent CLI backends.

Each backend is one ``AgentSpec`` literal — adding a new IDE is *data*, not code.
The loop drives whichever CLI is installed on the host (reusing that CLI's own
auth), so no Gemini key is required unless we fall back to the SDK path.

Grounded headless invocations (2026):
  claude      claude -p "<prompt>" --output-format json
  codex       codex exec "<prompt>" --json            (JSONL on stdout)
  cursor      cursor-agent -p "<prompt>" --output-format json --force
  gemini-cli  gemini -p "<prompt>" --output-format json
  aider       aider --message "<prompt>" --yes-always

Windsurf and Antigravity expose no documented headless agent CLI — Antigravity
stays on the existing SDK path; Windsurf is intentionally absent.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Optional

# The single placeholder substituted into argv_template at invocation time.
PROMPT_PLACEHOLDER = "{prompt}"


@dataclass(frozen=True)
class AgentSpec:
    """How to invoke one coding-agent CLI in headless mode.

    argv_template is a positional template whose only placeholder is ``{prompt}``.
    The prompt is always passed as a single argv element (``shell=False``), so
    there is no quoting or injection risk.
    """

    name: str
    binary: str
    argv_template: tuple[str, ...]
    parser_kind: str  # claude_json | codex_jsonl | cursor_json | gemini_json | text
    cwd_is_repo: bool = True
    extra_env: tuple[tuple[str, str], ...] = ()
    timeout_s: int = 300


# Detection-preference order (most capable / most common first).
_REGISTRY: tuple[AgentSpec, ...] = (
    AgentSpec("claude", "claude", ("-p", PROMPT_PLACEHOLDER, "--output-format", "json"), "claude_json"),
    AgentSpec("codex", "codex", ("exec", PROMPT_PLACEHOLDER, "--json"), "codex_jsonl"),
    AgentSpec(
        "cursor",
        "cursor-agent",
        ("-p", PROMPT_PLACEHOLDER, "--output-format", "json", "--force"),
        "cursor_json",
        # Cursor's headless mode has a known hang bug; keep the leash short.
        timeout_s=240,
    ),
    AgentSpec("gemini-cli", "gemini", ("-p", PROMPT_PLACEHOLDER, "--output-format", "json"), "gemini_json"),
    AgentSpec("aider", "aider", ("--message", PROMPT_PLACEHOLDER, "--yes-always"), "text"),
)


def registry() -> tuple[AgentSpec, ...]:
    """The full, immutable backend registry in detection-preference order."""
    return _REGISTRY


def is_on_path(spec: AgentSpec) -> bool:
    """Whether this spec's binary is resolvable on PATH."""
    return shutil.which(spec.binary) is not None


def available_specs() -> list[AgentSpec]:
    """Specs whose binary is resolvable on PATH, in registry order."""
    return [spec for spec in _REGISTRY if is_on_path(spec)]


def spec_by_name(name: str) -> Optional[AgentSpec]:
    """Look up a spec by its short name (e.g. 'claude'), or None."""
    for spec in _REGISTRY:
        if spec.name == name:
            return spec
    return None
