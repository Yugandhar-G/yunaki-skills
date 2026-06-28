"""Tests for the verification-gate recommendation policy (pure, offline)."""
from yunaki_skills import verification as v
from yunaki_skills.interfaces import ABResult


def _ab(lift, *, control=40.0, treatment=None, c_rate=1.0, t_rate=1.0,
        c_scores=None, t_scores=None):
    """Build an ABResult with the fields the gate inspects.

    By default each arm gets 3 identical per-rollout scores at its mean (zero
    variance) so a positive lift is unambiguously significant; pass explicit
    c_scores/t_scores to model real spread.
    """
    if treatment is None and lift is not None and control is not None:
        treatment = control + lift
    if c_scores is None and control is not None:
        c_scores = [control] * 3
    if t_scores is None and treatment is not None:
        t_scores = [treatment] * 3
    return ABResult(
        task_description="impl X",
        n_rollouts=3,
        control_mean=control,
        treatment_mean=treatment,
        skill_lift=lift,
        control_scores=c_scores or [],
        treatment_scores=t_scores or [],
        control_runnable_rate=c_rate,
        treatment_runnable_rate=t_rate,
    )


def test_positive_lift_promotes_and_suggests_score():
    rec = v.recommend(_ab(30.0))
    assert rec.recommendation == "promote"
    assert rec.suggested_score == 80.0  # 50 + 30
    assert rec.lift == 30.0


def test_lift_below_threshold_is_inconclusive():
    rec = v.recommend(_ab(3.0))  # default threshold +5
    assert rec.recommendation == "inconclusive"


def test_zero_lift_rejects():
    rec = v.recommend(_ab(0.0))
    assert rec.recommendation == "reject"


def test_negative_lift_rejects():
    rec = v.recommend(_ab(-10.0))
    assert rec.recommendation == "reject"


def test_reliability_regression_rejects_even_with_positive_lift():
    rec = v.recommend(_ab(30.0, c_rate=1.0, t_rate=0.5))
    assert rec.recommendation == "reject"
    assert "reliab" in rec.reason.lower()


def test_none_lift_is_no_measurement():
    rec = v.recommend(_ab(None, control=None, treatment=None, c_rate=0.0, t_rate=0.0))
    assert rec.recommendation == "no_measurement"


def test_threshold_env_override(monkeypatch):
    monkeypatch.setenv("YUNAKI_GATE_THRESHOLD", "20")
    assert v.recommend(_ab(10.0)).recommendation == "inconclusive"
    assert v.recommend(_ab(25.0)).recommendation == "promote"


def test_threshold_bad_value_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("YUNAKI_GATE_THRESHOLD", "abc")
    # default +5 -> +10 promotes
    assert v.recommend(_ab(10.0)).recommendation == "promote"


def test_suggested_score_clamped_to_100():
    rec = v.recommend(_ab(80.0))
    assert rec.recommendation == "promote"
    assert rec.suggested_score == 100.0


def test_high_variance_positive_lift_is_inconclusive():
    # mean lift +30 but wide spread -> CI includes 0 -> not promotable (the noisy-ruler guard)
    rec = v.recommend(_ab(30.0, c_scores=[10.0, 40.0, 70.0], t_scores=[40.0, 70.0, 100.0]))
    assert rec.recommendation == "inconclusive"
    assert rec.ci_low is not None and rec.ci_low < 0 < rec.ci_high


def test_tight_positive_lift_is_significant_and_promotes():
    # mean lift +30 with tight spread -> CI clears 0 -> promote
    rec = v.recommend(_ab(30.0, c_scores=[39.0, 40.0, 41.0], t_scores=[69.0, 70.0, 71.0]))
    assert rec.recommendation == "promote"
    assert rec.ci_low is not None and rec.ci_low > 0


def test_insufficient_samples_is_inconclusive():
    # only 1 runnable score per arm -> variance/significance undefined -> inconclusive
    rec = v.recommend(_ab(30.0, c_scores=[40.0], t_scores=[70.0]))
    assert rec.recommendation == "inconclusive"
    assert "significance" in rec.reason.lower()
