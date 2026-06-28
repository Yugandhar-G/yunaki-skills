"""
AntigravityClient — Gemini-powered coding agent.

Implements the AgentClient interface from yunaki_skills.interfaces.
Uses the google-genai SDK with model "gemini-2.5-flash".
Tries Antigravity agents API first (if available), then falls back
to direct models.generate_content.

Also provides FallbackClient — direct Gemini API (no sandbox).
"""

import logging
import os
import re

from google import genai
from google.genai import types

from yunaki_skills.config import get
from yunaki_skills.interfaces import AgentClient as IAgentClient
from yunaki_skills.interfaces import Skill

logger = logging.getLogger(__name__)

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _read_repo_files(repo_path: str) -> dict[str, str]:
    """Read all Python source files from the repo directory (skip test files)."""
    files = {}
    for fname in os.listdir(repo_path):
        if fname.endswith(".py") and not fname.startswith("test_"):
            fpath = os.path.join(repo_path, fname)
            try:
                with open(fpath) as f:
                    files[fname] = f.read()
            except Exception:
                continue
    return files


def _format_skills_block(skills: list[Skill]) -> str:
    """Format skills as instruction blocks for injection into the prompt."""
    if not skills:
        return ""
    lines = ["\n## INJECTED SKILLS — Follow these proven instructions:\n"]
    for skill in skills:
        lines.append(f"### Skill: {skill.title} (id={skill.id}, score={skill.score})")
        lines.append(f"When to apply: {skill.when_to_apply}")
        for i, instr in enumerate(skill.instructions, 1):
            lines.append(f"  {i}. {instr}")
        lines.append("")
    return "\n".join(lines)


def _build_prompts(
    task_description: str,
    repo_files: dict[str, str],
    skills: list[Skill],
) -> tuple[str, str]:
    """Build the system instruction and user prompt separately.

    Returns (system_instruction, user_message).
    """
    files_section = "\n".join(f"--- {name} ---\n{content}" for name, content in repo_files.items())
    skills_section = _format_skills_block(skills)

    system_instruction = f"""You are a coding agent. Your job is to modify a FastAPI application to complete the given task.

RULES:
- Output the COMPLETE modified file content for each file you change
- Use the format: <<<FILE:filename.py>>> followed by the complete file content, then <<<ENDFILE>>>
- You may create new files using the same format
- Follow existing code patterns and conventions exactly
- Do NOT modify test files
- Make minimal changes — only what's needed for the task
{skills_section}"""

    user_message = f"""TASK: {task_description}

CURRENT FILES:
{files_section}

Complete this task. Output the modified files using the <<<FILE:...>>> <<<ENDFILE>>> format."""

    return system_instruction, user_message


def _parse_and_write_files(output: str, repo_path: str) -> list[str]:
    """Parse <<<FILE:name>>>...<<<ENDFILE>>> blocks and write them.

    Falls back to ```python blocks with filename hints.

    Returns list of files written.
    """
    written = []

    # Primary: <<<FILE:name>>>...<<<ENDFILE>>>
    pattern = r"<<<FILE:(.+?)>>>\n(.*?)<<<ENDFILE>>>"
    matches = re.findall(pattern, output, re.DOTALL)

    if matches:
        for fname, content in matches:
            fname = fname.strip()
            if fname.startswith("test_"):
                continue
            fpath = os.path.join(repo_path, fname)
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            with open(fpath, "w") as f:
                f.write(content.strip() + "\n")
            written.append(fname)
            logger.info("Wrote file: %s", fname)
    else:
        # Fallback: ### File: name.py + ```python blocks
        file_pattern = r"###\s*File:\s*(\S+\.py)\s*\n```python\n(.*?)```"
        fallback_matches = re.findall(file_pattern, output, re.DOTALL)
        if fallback_matches:
            for fname, content in fallback_matches:
                fname = fname.strip()
                if fname.startswith("test_"):
                    continue
                fpath = os.path.join(repo_path, fname)
                os.makedirs(os.path.dirname(fpath), exist_ok=True)
                with open(fpath, "w") as f:
                    f.write(content.strip() + "\n")
                written.append(fname)
                logger.info("Wrote file (fallback): %s", fname)
        else:
            logger.warning("Could not parse any file blocks from agent response")

    return written


def _extract_text(response) -> str:
    """Extract text from a GenerateContentResponse."""
    try:
        if hasattr(response, "text") and response.text:
            return response.text
        if hasattr(response, "candidates") and response.candidates:
            parts = []
            for candidate in response.candidates:
                if hasattr(candidate, "content") and candidate.content:
                    for part in candidate.content.parts:
                        if hasattr(part, "text") and part.text:
                            parts.append(part.text)
            if parts:
                return "\n".join(parts)
    except Exception as e:
        logger.warning("Error extracting text from response: %s", e)
    return str(response)


# ─── FallbackClient ───────────────────────────────────────────────────────────


class FallbackClient(IAgentClient):
    """Direct Gemini API client — no sandbox, uses models.generate_content."""

    def __init__(self):
        api_key = get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set in environment")
        self._client = genai.Client(api_key=api_key)
        self._model = "gemini-2.5-flash"

    def run_task(self, task_description: str, skills: list[Skill], repo_path: str) -> str:
        """Run a coding task with injected skills. Returns the agent's trace."""
        repo_files = _read_repo_files(repo_path)
        logger.info("[Fallback] Read %d files from %s", len(repo_files), repo_path)

        system_instruction, user_message = _build_prompts(task_description, repo_files, skills)

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=user_message,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.2,
                    max_output_tokens=16384,
                ),
            )
            output = _extract_text(response)
        except Exception as e:
            logger.error("Gemini API call failed: %s", e)
            return f"ERROR: Gemini API call failed: {e}"

        # Parse and write files back
        written = _parse_and_write_files(output, repo_path)
        logger.info("[Fallback] Wrote %d files back to repo", len(written))

        # Build trace
        trace = f"=== SYSTEM INSTRUCTION ===\n{system_instruction}\n\n=== USER MESSAGE ===\n{user_message}\n\n=== AGENT RESPONSE ===\n{output}\n"
        return trace


# ─── AntigravityClient ────────────────────────────────────────────────────────


class AntigravityClient(IAgentClient):
    """Gemini-powered coding agent using google-genai SDK.

    Tries the Antigravity agents API first (if available),
    then falls back to direct models.generate_content.
    """

    def __init__(self):
        api_key = get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set in environment")
        self._client = genai.Client(api_key=api_key)
        self._model = "gemini-2.5-flash"
        self._use_agents = self._check_agents_available()

    def _check_agents_available(self) -> bool:
        """Check if the Antigravity agents.run API is available on the client."""
        try:
            agents = getattr(self._client, "agents", None)
            if agents is not None and hasattr(agents, "run"):
                logger.info("Antigravity agents API available")
                return True
        except Exception:
            pass
        logger.info("Antigravity agents API not available, using direct model calls")
        return False

    def run_task(self, task_description: str, skills: list[Skill], repo_path: str) -> str:
        """Run a coding task with injected skills. Returns the agent's trace."""
        repo_files = _read_repo_files(repo_path)
        logger.info("Read %d files from %s", len(repo_files), repo_path)

        system_instruction, user_message = _build_prompts(task_description, repo_files, skills)

        # Try agents API first, then fallback
        if self._use_agents:
            try:
                output = self._run_via_agents(system_instruction, user_message)
            except Exception as e:
                logger.warning("Agents API failed, falling back: %s", e)
                output = self._run_via_generate(system_instruction, user_message)
        else:
            output = self._run_via_generate(system_instruction, user_message)

        # Parse and write files
        written = _parse_and_write_files(output, repo_path)
        logger.info("Wrote %d files back to repo", len(written))

        # Build trace
        trace = f"=== SYSTEM INSTRUCTION ===\n{system_instruction}\n\n=== USER MESSAGE ===\n{user_message}\n\n=== AGENT RESPONSE ===\n{output}\n"
        return trace

    def _run_via_agents(self, system_instruction: str, user_message: str) -> str:
        """Run via Antigravity agents API (sandboxed execution)."""
        agents = self._client.agents
        result = agents.run(
            model=self._model,
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.2,
                max_output_tokens=16384,
            ),
        )
        return _extract_text(result)

    def _run_via_generate(self, system_instruction: str, user_message: str) -> str:
        """Run via direct models.generate_content."""
        response = self._client.models.generate_content(
            model=self._model,
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.2,
                max_output_tokens=16384,
            ),
        )
        return _extract_text(response)
