"""Selects the coding-agent backend for the evolution loop.

Resolution order:
  1. ``YUNAKI_AGENT_BACKEND`` override (explicit; raises loudly if unavailable).
     Special values ``gemini-sdk`` / ``antigravity`` force the in-process SDK path.
  2. Auto-detect: the first installed coding-agent CLI (claude, codex, cursor,
     gemini-cli, aider), reusing that CLI's own auth — no Gemini key needed.
  3. Fall back to the Gemini SDK client (``AntigravityClient``).
"""

from __future__ import annotations

import logging
from typing import Optional

from yunaki_skills import agent_specs, config
from yunaki_skills.antigravity_client import AntigravityClient
from yunaki_skills.cli_agent import CliAgentAdapter
from yunaki_skills.interfaces import AgentClient

logger = logging.getLogger(__name__)

# Override values that explicitly request the in-process Gemini SDK path.
_SDK_ALIASES = {"gemini-sdk", "antigravity"}


def _override() -> Optional[str]:
    name = config.get("YUNAKI_AGENT_BACKEND").strip()
    return name or None


def build_agent() -> AgentClient:
    """Return the coding agent the loop should use (see module docstring)."""
    name = _override()
    if name:
        if name in _SDK_ALIASES:
            return AntigravityClient()
        spec = agent_specs.spec_by_name(name)
        if spec is None:
            raise RuntimeError(
                f"YUNAKI_AGENT_BACKEND={name!r} is not a known backend. "
                f"Known: {[s.name for s in agent_specs.registry()]} or 'gemini-sdk'."
            )
        if not agent_specs.is_on_path(spec):
            raise RuntimeError(
                f"YUNAKI_AGENT_BACKEND={name!r} requested but {spec.binary!r} "
                "was not found on PATH. Install/authenticate it, or unset the override."
            )
        logger.info("Using coding-agent backend (override): %s", spec.name)
        return CliAgentAdapter(spec)

    available = agent_specs.available_specs()
    if available:
        logger.info("Auto-detected coding-agent backend: %s", available[0].name)
        return CliAgentAdapter(available[0])

    logger.info("No coding-agent CLI detected on PATH; falling back to Gemini SDK")
    return AntigravityClient()


def selection_summary() -> dict:
    """Describe what ``build_agent`` would pick, without constructing clients.

    Used by ``yunaki doctor`` so users can verify detection safely.
    """
    override = _override()
    available = [s.name for s in agent_specs.available_specs()]

    if override:
        if override in _SDK_ALIASES:
            selected = "gemini-sdk"
        else:
            spec = agent_specs.spec_by_name(override)
            if spec is None:
                selected = f"INVALID ({override})"
            elif not agent_specs.is_on_path(spec):
                selected = f"UNAVAILABLE ({override})"
            else:
                selected = override
    elif available:
        selected = available[0]
    else:
        selected = "gemini-sdk (fallback)"

    return {"override": override, "available": available, "selected": selected}
