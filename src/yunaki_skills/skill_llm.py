"""Single LLM seam for the skill model's meta-operations (extract / evolve / judge).

By default these route to the detected host coding-agent CLI in prompt-only mode,
so no Gemini key is required — the same auth the user already has for their IDE
powers skill extraction too. Set ``YUNAKI_SKILL_MODEL`` to pin meta-ops to a
specific Gemini model instead (faster/cheaper/more reliable structured JSON).

Resolution order for ``complete_json``:
  1. ``YUNAKI_SKILL_MODEL`` set            -> Gemini SDK with that model
  2. a coding-agent CLI is on PATH         -> that CLI in JSON-only prompt mode
  3. otherwise                             -> Gemini SDK default model

Callers expect a JSON string back and already tolerate empty/garbage responses
(extractor returns None, evolver falls back, judge returns zero-scores), so a
flaky CLI degrades gracefully rather than breaking the loop.
"""

from __future__ import annotations

import logging
import shutil
import tempfile

from yunaki_skills import agent_specs, config

logger = logging.getLogger(__name__)

_DEFAULT_SDK_MODEL = "gemini-2.5-flash"

_JSON_ONLY_PREAMBLE = (
    "You are a JSON API. Respond with ONLY a single JSON object and nothing else. "
    "Do not edit files, do not run commands, do not add prose or markdown fences.\n\n"
)


def _strip_fences(text: str) -> str:
    """Strip a leading/trailing markdown code fence if the model added one."""
    t = text.strip()
    if not t.startswith("```"):
        return t
    lines = t.splitlines()
    if lines and lines[0].lstrip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def active_model_label() -> str:
    """Human-readable label for the backend ``complete_json`` would use."""
    model = config.get("YUNAKI_SKILL_MODEL").strip()
    if model:
        return model
    specs = agent_specs.available_specs()
    if specs:
        return f"{specs[0].name} (cli)"
    return _DEFAULT_SDK_MODEL


def _complete_via_sdk(prompt: str, model: str) -> str:
    """Structured-JSON completion via the Gemini SDK."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=config.get("GEMINI_API_KEY"))
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.3,
            response_mime_type="application/json",
        ),
    )
    return (response.text or "").strip()


def _complete_via_cli(prompt: str, spec: agent_specs.AgentSpec) -> str:
    """Prompt-only completion through a coding-agent CLI (no file edits)."""
    from yunaki_skills.cli_agent import run_cli

    workdir = tempfile.mkdtemp(prefix="yunaki_skill_llm_")
    try:
        body, stderr, returncode = run_cli(spec, _JSON_ONLY_PREAMBLE + prompt, workdir)
        if returncode is None or (returncode != 0 and not body.strip()):
            logger.error("skill_llm CLI backend (%s) failed: %s", spec.name, stderr)
            return ""
        return _strip_fences(body)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def complete_json(prompt: str) -> str:
    """Return a JSON string for ``prompt`` (see module docstring for routing)."""
    model = config.get("YUNAKI_SKILL_MODEL").strip()
    if model:
        return _complete_via_sdk(prompt, model)

    specs = agent_specs.available_specs()
    if specs:
        return _complete_via_cli(prompt, specs[0])

    return _complete_via_sdk(prompt, _DEFAULT_SDK_MODEL)
