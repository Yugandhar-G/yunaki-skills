"""Tests for LLMJudge — Gemini mocked, persistence disabled."""

from __future__ import annotations

import json

from tests.conftest import install_fake_skill_llm
from yunaki_skills import llm_judge as judge_mod
from yunaki_skills.llm_judge import JudgeScores, LLMJudge, _read_code, _weighted_overall

GOOD_JUDGMENT = json.dumps(
    {
        "correctness": 90,
        "style": 80,
        "security": 70,
        "performance": 60,
        "rationale": "Endpoints implemented correctly with minor style nits.",
    }
)


def test_judge_parses_scores(monkeypatch):
    install_fake_skill_llm(monkeypatch, GOOD_JUDGMENT)
    result = LLMJudge(persist=False).judge("Implement endpoints", "def f(): pass")

    assert result.scores.correctness == 90
    assert result.scores.performance == 60
    assert result.rationale.startswith("Endpoints implemented")
    # Weighted overall: 90*.4 + 80*.2 + 70*.25 + 60*.15 = 78.5
    assert result.overall == 78.5


def test_judge_failure_returns_zero_scores(monkeypatch):
    install_fake_skill_llm(monkeypatch, "not json at all")
    result = LLMJudge(persist=False).judge("task", "code")

    assert result.overall == 0.0
    assert result.scores.correctness == 0
    assert "failed" in result.rationale.lower()


def test_judge_persists_when_collection_present(monkeypatch):
    fake = install_fake_skill_llm(monkeypatch, GOOD_JUDGMENT)
    judge = LLMJudge(persist=False)
    # Wire a fake evaluations collection in after construction.
    from unittest.mock import MagicMock

    judge._evaluations = MagicMock()
    judge.judge("task", "code")
    judge._evaluations.insert_one.assert_called_once()
    assert fake.called


def test_weighted_overall():
    scores = JudgeScores(correctness=100, style=100, security=100, performance=100)
    assert _weighted_overall(scores) == 100.0


def test_read_code_from_directory(tmp_path):
    (tmp_path / "app.py").write_text("print('hi')")
    (tmp_path / "test_app.py").write_text("def test(): pass")  # excluded
    code = _read_code(str(tmp_path))
    assert "print('hi')" in code
    assert "def test()" not in code


def test_read_code_from_raw_string():
    assert _read_code("x = 1") == "x = 1"


def test_judge_includes_code_in_prompt(monkeypatch):
    fake = install_fake_skill_llm(monkeypatch, GOOD_JUDGMENT)
    LLMJudge(persist=False).judge("My task", "SECRET_MARKER_CODE")
    prompt = fake.call_args[0][0]
    assert "SECRET_MARKER_CODE" in prompt
    assert "My task" in prompt
