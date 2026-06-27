"""Tests for ContrastiveRunner — N-rollout fan-out + pass/fail extraction."""

from __future__ import annotations

from unittest.mock import MagicMock

from tests.conftest import make_task_skill
from yunaki_skills.contrastive_runner import ContrastiveRunner, rollouts_from_env


def _snapshot(tmp_path):
    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / "solution.py").write_text("x = 1\n")
    return str(snap)


def test_rollouts_from_env(monkeypatch):
    monkeypatch.delenv("YUNAKI_CONTRASTIVE_ROLLOUTS", raising=False)
    assert rollouts_from_env() == 1
    assert rollouts_from_env(3) == 3
    monkeypatch.setenv("YUNAKI_CONTRASTIVE_ROLLOUTS", "4")
    assert rollouts_from_env() == 4
    monkeypatch.setenv("YUNAKI_CONTRASTIVE_ROLLOUTS", "garbage")
    assert rollouts_from_env() == 1


def test_run_returns_none_below_two():
    runner = ContrastiveRunner(MagicMock(), MagicMock(), MagicMock())
    assert runner.run("t", "/snap", [], None, 1) is None


def test_run_extracts_from_pass_fail_pair(tmp_path, eval_pass, eval_fail):
    snap = _snapshot(tmp_path)
    agent = MagicMock()
    agent.run_task.return_value = "trace"
    scorer = MagicMock()
    scorer.evaluate.side_effect = [eval_fail, eval_pass]  # one fail, one pass
    extractor = MagicMock()
    extractor.extract_contrastive.return_value = make_task_skill("skill_contrast")

    runner = ContrastiveRunner(agent, scorer, extractor)
    skill = runner.run("t", snap, [], None, 2)

    assert skill is not None
    assert skill.id == "skill_contrast"
    extractor.extract_contrastive.assert_called_once()
    # The passing trace/eval and failing trace/eval are both forwarded.
    kwargs = extractor.extract_contrastive.call_args.kwargs
    assert kwargs["pass_eval"].passed is True
    assert kwargs["fail_eval"].passed is False


def test_run_returns_none_without_contrast(tmp_path, eval_fail):
    snap = _snapshot(tmp_path)
    agent = MagicMock()
    agent.run_task.return_value = "trace"
    scorer = MagicMock()
    scorer.evaluate.side_effect = [eval_fail, eval_fail]  # all fail -> no contrast
    extractor = MagicMock()

    runner = ContrastiveRunner(agent, scorer, extractor)
    assert runner.run("t", snap, [], None, 2) is None
    extractor.extract_contrastive.assert_not_called()
