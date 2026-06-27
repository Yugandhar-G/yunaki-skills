"""Shared pytest fixtures for the Yunaki Skills test suite.

All external dependencies are mocked:
  - MongoDB  -> mongomock (in-memory, real query semantics)
  - Gemini   -> MagicMock genai.Client
  - DO HTTP  -> patched requests.Session.post
  - pytest/subprocess in EvalScorer -> patched subprocess.run

Embeddings are forced onto the deterministic hash fallback so no model is
downloaded in CI.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import mongomock
import pytest

from yunaki_skills.interfaces import (
    EvalResult,
    Granularity,
    Provenance,
    Skill,
    Trigger,
    TriggerMatchOn,
    TriggerType,
)

# ─── Skill factories ─────────────────────────────────────────────────────────


def make_task_skill(skill_id: str = "skill_dep_injection", score: float = 60.0) -> Skill:
    """A task-level (semantic) skill."""
    return Skill(
        id=skill_id,
        title="Use FastAPI dependency injection",
        granularity=Granularity.TASK_LEVEL,
        version="0.1",
        score=score,
        trigger=Trigger(
            type=TriggerType.SEMANTIC,
            query="fastapi endpoint dependency injection user service",
            match_on=TriggerMatchOn.TASK_DESCRIPTION,
        ),
        when_to_apply="When implementing FastAPI endpoints that share resources",
        instructions=["Define a dependency", "Inject it via Depends"],
        provenance=Provenance(task="Implement the GET /users endpoint"),
    )


def make_event_skill(skill_id: str = "skill_keyerror_guard") -> Skill:
    """An event-driven (pattern) skill."""
    return Skill(
        id=skill_id,
        title="Guard against KeyError on missing fields",
        granularity=Granularity.EVENT_DRIVEN,
        version="0.1",
        score=55.0,
        trigger=Trigger(
            type=TriggerType.PATTERN,
            patterns=[r"KeyError", r"\bModuleNotFoundError\b"],
            match_on=TriggerMatchOn.ERROR,
        ),
        when_to_apply="When the trace shows a KeyError",
        instructions=["Use .get() with a default", "Validate input with Pydantic"],
    )


@pytest.fixture
def task_skill() -> Skill:
    return make_task_skill()


@pytest.fixture
def event_skill() -> Skill:
    return make_event_skill()


@pytest.fixture
def eval_pass() -> EvalResult:
    return EvalResult(passed=True, score=100.0, details="9/9 passed", tasks_passed=9, tasks_total=9)


@pytest.fixture
def eval_fail() -> EvalResult:
    return EvalResult(
        passed=False,
        score=33.0,
        details="3/9 passed",
        test_output="FAILED test_app.py::test_get_user - assert 404 == 200",
        tasks_passed=3,
        tasks_total=9,
    )


# ─── MongoDB-backed SkillBank (mongomock) ─────────────────────────────────────


@pytest.fixture
def skill_bank(monkeypatch):
    """A real SkillBank wired to an in-memory mongomock client.

    The encoder is forced into its hash-fallback so retrieval is deterministic
    and offline.
    """
    from yunaki_skills import skill_bank as sb_mod

    monkeypatch.setattr(sb_mod, "MongoClient", lambda *a, **k: mongomock.MongoClient())
    bank = sb_mod.SkillBank()
    bank._encoder_failed = True  # force deterministic hash embeddings
    return bank


# ─── Fake Gemini ──────────────────────────────────────────────────────────────


def make_gemini_response(text: str):
    """Build a fake GenerateContentResponse exposing `.text`."""
    return SimpleNamespace(text=text, candidates=[])


def install_fake_gemini(monkeypatch, module, response_text: str) -> MagicMock:
    """Patch genai.Client in `module` so generate_content returns response_text.

    Returns the MagicMock client so tests can assert call counts.
    """
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = make_gemini_response(response_text)
    monkeypatch.setattr(module.genai, "Client", lambda *a, **k: fake_client)
    return fake_client


def install_fake_skill_llm(monkeypatch, response_text: str) -> MagicMock:
    """Patch ``skill_llm.complete_json`` to return ``response_text``.

    This is the seam the meta-ops (extractor/evolver/judge) now route through.
    Returns the MagicMock so tests can assert on the prompt it received via
    ``mock.call_args[0][0]``.
    """
    from yunaki_skills import skill_llm

    mock = MagicMock(return_value=response_text)
    monkeypatch.setattr(skill_llm, "complete_json", mock)
    return mock
