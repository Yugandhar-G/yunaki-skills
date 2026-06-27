"""Factory that selects the coding-agent backend.

Phase 1 (the DI seam): ``build_agent`` returns the Gemini SDK client, preserving
today's behavior. Phase 2 enriches this to detect an installed coding-agent CLI
(claude / codex / cursor-agent / gemini / aider) and fall back to the SDK only
when no CLI is available. The public signature stays ``build_agent() -> AgentClient``
so callers never change.
"""

from __future__ import annotations

from yunaki_skills.antigravity_client import AntigravityClient
from yunaki_skills.interfaces import AgentClient


def build_agent() -> AgentClient:
    """Return the coding agent the loop should use.

    Phase 1: the Gemini SDK client. Phase 2 will layer CLI detection in front
    of this fallback.
    """
    return AntigravityClient()
