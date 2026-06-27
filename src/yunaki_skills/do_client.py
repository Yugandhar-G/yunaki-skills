"""
DOClient — DigitalOcean Inference fallback agent.

Implements the AgentClient interface from yunaki_skills.interfaces using the
DigitalOcean Inference endpoint (https://inference.do-ai.run/v1/), which speaks
the OpenAI-compatible chat-completions protocol. Serves as the fallback agent
when Gemini fails or is rate-limited.

Reuses the prompt-building / repo-IO / file-parsing helpers from
antigravity_client so the DO path produces byte-identical traces and applies
files the same way as the Gemini path.
"""

from __future__ import annotations

import logging

import requests

from yunaki_skills.antigravity_client import (
    _build_prompts,
    _parse_and_write_files,
    _read_repo_files,
)
from yunaki_skills.config import get
from yunaki_skills.interfaces import AgentClient as IAgentClient
from yunaki_skills.interfaces import Skill

logger = logging.getLogger(__name__)

# DigitalOcean Inference — OpenAI-compatible chat completions.
DO_BASE_URL = "https://inference.do-ai.run/v1"
DO_CHAT_PATH = "/chat/completions"
DO_DEFAULT_MODEL = "llama3.3-70b-instruct"
_REQUEST_TIMEOUT_S = 120
_MAX_OUTPUT_TOKENS = 8192


def _extract_choice_text(payload: dict) -> str:
    """Pull the assistant message text from an OpenAI-compatible response.

    Raises ValueError if the payload doesn't carry a usable choice so callers
    fail loud instead of silently writing empty files.
    """
    choices = payload.get("choices") or []
    if not choices:
        raise ValueError(f"DO Inference returned no choices: {payload}")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not content:
        raise ValueError(f"DO Inference returned empty content: {payload}")
    return content


class DOClient(IAgentClient):
    """DigitalOcean Inference agent (Llama 3.3 70B by default).

    Same interface and trace format as FallbackClient in antigravity_client,
    so it is a drop-in fallback when the Gemini path is unavailable.
    """

    def __init__(self, model: str | None = None, base_url: str | None = None):
        access_key = get("DO_MODEL_ACCESS_KEY")
        if not access_key:
            raise ValueError("DO_MODEL_ACCESS_KEY not set in environment")
        self._access_key = access_key
        self._model = model or get("DO_MODEL", DO_DEFAULT_MODEL)
        self._base_url = (base_url or get("DO_BASE_URL", DO_BASE_URL)).rstrip("/")
        self._session = requests.Session()

    # ── internals ────────────────────────────────────────────────────────

    def _chat(self, system_instruction: str, user_message: str) -> str:
        """Call the DO chat-completions endpoint and return the message text."""
        url = f"{self._base_url}{DO_CHAT_PATH}"
        headers = {
            "Authorization": f"Bearer {self._access_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.2,
            "max_completion_tokens": _MAX_OUTPUT_TOKENS,
        }

        response = self._session.post(url, headers=headers, json=payload, timeout=_REQUEST_TIMEOUT_S)
        response.raise_for_status()
        return _extract_choice_text(response.json())

    # ── public API ───────────────────────────────────────────────────────

    def run_task(self, task_description: str, skills: list[Skill], repo_path: str) -> str:
        """Run a coding task with injected skills. Returns the agent's trace."""
        repo_files = _read_repo_files(repo_path)
        logger.info("[DO] Read %d files from %s", len(repo_files), repo_path)

        system_instruction, user_message = _build_prompts(task_description, repo_files, skills)

        try:
            output = self._chat(system_instruction, user_message)
        except (requests.RequestException, ValueError) as e:
            logger.error("DO Inference call failed: %s", e)
            return f"ERROR: DO Inference call failed: {e}"

        written = _parse_and_write_files(output, repo_path)
        logger.info("[DO] Wrote %d files back to repo", len(written))

        return (
            "=== SYSTEM INSTRUCTION ===\n"
            f"{system_instruction}\n\n"
            "=== USER MESSAGE ===\n"
            f"{user_message}\n\n"
            "=== AGENT RESPONSE ===\n"
            f"{output}\n"
        )
