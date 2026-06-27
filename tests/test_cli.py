"""Tests for the yunaki CLI."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tests.conftest import make_task_skill
from yunaki_skills.cli import build_parser, main
from yunaki_skills.interfaces import TaskResult


def test_run_command_invokes_task_runner(monkeypatch, capsys):
    result = TaskResult(
        task_description="t",
        score_before=20.0,
        score_after=90.0,
        skills_used=["skill_a"],
        skills_created=["skill_b"],
        skills_evolved=[],
        iterations=2,
    )
    runner = MagicMock()
    runner.run.return_value = result
    monkeypatch.setattr("yunaki_skills.task_runner.TaskRunner", lambda: runner)

    rc = main(["run", "implement endpoint", "--max-iterations", "2"])

    assert rc == 0
    runner.run.assert_called_once_with("implement endpoint", max_iterations=2, rollouts=None)
    out = capsys.readouterr().out
    assert "20% -> 90%" in out


def test_run_command_json_output(monkeypatch, capsys):
    result = TaskResult(
        task_description="t",
        score_before=0,
        score_after=50,
        skills_used=[],
        skills_created=[],
        skills_evolved=[],
        iterations=1,
    )
    runner = MagicMock()
    runner.run.return_value = result
    monkeypatch.setattr("yunaki_skills.task_runner.TaskRunner", lambda: runner)

    rc = main(["--json", "run", "task"])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"score_after": 50.0' in out


def test_skills_list(monkeypatch, capsys):
    bank = MagicMock()
    bank.list_all.return_value = [make_task_skill("skill_a"), make_task_skill("skill_b")]
    monkeypatch.setattr("yunaki_skills.skill_bank.SkillBank", lambda: bank)

    rc = main(["skills", "list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "skill_a" in out
    assert "skill_b" in out


def test_skills_list_empty(monkeypatch, capsys):
    bank = MagicMock()
    bank.list_all.return_value = []
    monkeypatch.setattr("yunaki_skills.skill_bank.SkillBank", lambda: bank)

    rc = main(["skills", "list"])
    assert rc == 0
    assert "No skills" in capsys.readouterr().out


def test_skills_evolve_missing_skill(monkeypatch, capsys):
    bank = MagicMock()
    bank.get.return_value = None
    monkeypatch.setattr("yunaki_skills.skill_bank.SkillBank", lambda: bank)

    rc = main(["skills", "evolve", "skill_unknown"])
    assert rc == 1
    assert "not found" in capsys.readouterr().err


def test_skills_evolve_success(monkeypatch, capsys):
    parent = make_task_skill("skill_x")
    bank = MagicMock()
    bank.get.return_value = parent
    bank.update.return_value = True
    monkeypatch.setattr("yunaki_skills.skill_bank.SkillBank", lambda: bank)

    agent = MagicMock()
    agent.run_task.return_value = "trace"
    monkeypatch.setattr("yunaki_skills.agent_factory.build_agent", lambda: agent)

    from yunaki_skills.interfaces import EvalResult

    scorer = MagicMock()
    scorer.evaluate.return_value = EvalResult(passed=False, score=50.0, details="5/10")
    monkeypatch.setattr("yunaki_skills.eval_scorer.EvalScorer", lambda: scorer)

    evolved = parent.model_copy(update={"version": "0.2", "score": 60.0})
    evolver = MagicMock()
    evolver.evolve.return_value = evolved
    monkeypatch.setattr("yunaki_skills.skill_evolver.SkillEvolver", lambda: evolver)

    rc = main(["skills", "evolve", "skill_x"])
    assert rc == 0
    bank.update.assert_called_once()
    assert "v0.1 -> v0.2" in capsys.readouterr().out


def test_parser_requires_command():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_doctor_reports_selection(monkeypatch, capsys):
    monkeypatch.setattr(
        "yunaki_skills.agent_factory.selection_summary",
        lambda: {"override": None, "available": ["claude", "aider"], "selected": "claude"},
    )
    rc = main(["doctor"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "claude" in out
    assert "selected: claude" in out


def test_doctor_json(monkeypatch, capsys):
    monkeypatch.setattr(
        "yunaki_skills.agent_factory.selection_summary",
        lambda: {"override": "codex", "available": ["codex"], "selected": "codex"},
    )
    rc = main(["--json", "doctor"])
    assert rc == 0
    assert '"selected": "codex"' in capsys.readouterr().out
