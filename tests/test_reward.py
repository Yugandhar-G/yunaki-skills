"""Tests for the composite reward overlay."""

from __future__ import annotations

from yunaki_skills.interfaces import EvalResult
from yunaki_skills.llm_judge import JudgeResult, JudgeScores
from yunaki_skills.reward import RewardComposer


class _FakeJudge:
    def __init__(self, correctness=80.0, overall=70.0):
        self._c = correctness
        self._o = overall

    def judge(self, task_description, target):
        return JudgeResult(
            task_description=task_description,
            scores=JudgeScores(correctness=self._c, style=50, security=50, performance=50),
            overall=self._o,
            rationale="x",
        )


def _eval(score=100.0, passed=True):
    return EvalResult(passed=passed, score=score, tasks_passed=9, tasks_total=9)


def test_disabled_returns_unchanged(monkeypatch):
    monkeypatch.delenv("YUNAKI_COMPOSITE_REWARD", raising=False)
    ev = _eval()
    out = RewardComposer(judge=_FakeJudge()).compose("t", ev, "code")
    assert out is ev
    assert out.composite_score is None


def test_composite_math(monkeypatch):
    monkeypatch.setenv("YUNAKI_COMPOSITE_REWARD", "1")
    # exec=1.0, align=0.8, quality=70 ; defaults w_exec=0.75 w_quality=0.25
    # composite = 0.75*(1.0*0.8*100) + 0.25*70 = 60 + 17.5 = 77.5
    out = RewardComposer(judge=_FakeJudge(correctness=80.0, overall=70.0)).compose("t", _eval(), "code")
    assert out.composite_score == 77.5
    assert out.align_score == 80.0
    assert out.quality_score == 70.0


def test_composite_never_flips_pass_fail(monkeypatch):
    monkeypatch.setenv("YUNAKI_COMPOSITE_REWARD", "1")
    failing = _eval(score=0.0, passed=False)
    # Even with a glowing judge, a pytest failure stays failed and exec term is 0.
    out = RewardComposer(judge=_FakeJudge(correctness=100.0, overall=100.0)).compose("t", failing, "code")
    assert out.passed is False
    assert out.score == 0.0
    # exec_fraction 0 -> exec term 0; composite = 0.25*100 = 25 (signal only)
    assert out.composite_score == 25.0


def test_judge_failure_returns_unchanged(monkeypatch):
    monkeypatch.setenv("YUNAKI_COMPOSITE_REWARD", "1")

    class _Boom:
        def judge(self, *a, **k):
            raise RuntimeError("judge down")

    ev = _eval()
    out = RewardComposer(judge=_Boom()).compose("t", ev, "code")
    assert out is ev
    assert out.composite_score is None


def test_weights_are_tunable(monkeypatch):
    monkeypatch.setenv("YUNAKI_COMPOSITE_REWARD", "1")
    monkeypatch.setenv("YUNAKI_REWARD_W_EXEC", "1.0")
    monkeypatch.setenv("YUNAKI_REWARD_W_QUALITY", "0.0")
    # composite = 1.0*(1.0*0.8*100) + 0 = 80
    out = RewardComposer(judge=_FakeJudge(correctness=80.0, overall=70.0)).compose("t", _eval(), "code")
    assert out.composite_score == 80.0
