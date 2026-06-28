"""Tests for EvalScorer — subprocess (syntax check + pytest) mocked."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yunaki_skills import eval_scorer as es_mod
from yunaki_skills.eval_scorer import EvalScorer

PYTEST_MIXED = """\
test_app.py::test_create_user PASSED
test_app.py::test_get_user PASSED
test_app.py::test_delete_user FAILED
test_app.py::test_list_users PASSED
=================== 3 passed, 1 failed in 0.42s ===================
"""

PYTEST_ALL_PASS = """\
test_app.py::test_a PASSED
test_app.py::test_b PASSED
=================== 2 passed in 0.10s ===================
"""

PYTEST_SUMMARY_ONLY = "=========== 7 passed, 2 failed, 1 error in 1.0s ==========="


def _proc(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _patch_subprocess(monkeypatch, syntax_rc, pytest_output):
    """Patch subprocess.run: 1st call = syntax check, 2nd = pytest."""
    calls = iter([_proc(returncode=syntax_rc), _proc(returncode=0, stdout=pytest_output)])
    monkeypatch.setattr(es_mod.subprocess, "run", lambda *a, **k: next(calls))


def test_evaluate_mixed_results(monkeypatch):
    _patch_subprocess(monkeypatch, syntax_rc=0, pytest_output=PYTEST_MIXED)
    result = EvalScorer().evaluate("task", "/fake/repo")

    assert result.tasks_passed == 3
    assert result.tasks_total == 4
    assert result.score == pytest.approx(75.0)
    assert result.passed is False  # 75 < default threshold 80


def test_evaluate_all_pass(monkeypatch):
    _patch_subprocess(monkeypatch, syntax_rc=0, pytest_output=PYTEST_ALL_PASS)
    result = EvalScorer().evaluate("task", "/fake/repo")

    assert result.score == pytest.approx(100.0)
    assert result.passed is True
    assert result.tasks_passed == 2


def test_evaluate_syntax_failure_short_circuits(monkeypatch):
    # Syntax check returns non-zero; pytest must never run.
    monkeypatch.setattr(es_mod.subprocess, "run", lambda *a, **k: _proc(returncode=1, stderr="SyntaxError"))
    result = EvalScorer().evaluate("task", "/fake/repo")

    assert result.passed is False
    assert result.score == 0.0
    assert "Syntax" in result.details


def test_evaluate_no_tests_found(monkeypatch):
    _patch_subprocess(monkeypatch, syntax_rc=0, pytest_output="collected 0 items")
    result = EvalScorer().evaluate("task", "/fake/repo")
    assert result.score == 0.0
    assert result.tasks_total == 0


def test_parse_summary_only(monkeypatch):
    scorer = EvalScorer()
    parsed = scorer._parse_pytest_output(PYTEST_SUMMARY_ONLY)
    assert parsed.passed == 7
    assert parsed.total == 10  # 7 passed + 2 failed + 1 error
    assert parsed.runnable is True


def test_parse_verbose_lines():
    scorer = EvalScorer()
    parsed = scorer._parse_pytest_output(PYTEST_MIXED)
    assert parsed.passed == 3
    assert parsed.total == 4
    assert parsed.runnable is True


def test_pass_threshold_env_override(monkeypatch):
    monkeypatch.setenv("YUNAKI_PASS_THRESHOLD", "70")
    _patch_subprocess(monkeypatch, syntax_rc=0, pytest_output=PYTEST_MIXED)
    result = EvalScorer().evaluate("task", "/fake/repo")
    assert result.passed is True  # 75 >= 70


def test_pass_threshold_invalid_env_falls_back(monkeypatch):
    monkeypatch.setenv("YUNAKI_PASS_THRESHOLD", "not-a-number")
    assert es_mod._pass_threshold() == 80.0


# ─── New parser coverage: -q summary, not-runnable, no tests ran ──────────────

PYTEST_Q_PASS = "....                                                       [100%]\n4 passed in 0.10s"

PYTEST_Q_MIXED = "..F.                                                       [100%]\n3 passed, 1 failed in 0.12s"

PYTEST_IMPORT_ERROR = """\
ImportError while importing test module 'test_app.py'.
E   ModuleNotFoundError: No module named 'email_validator'
=================== 1 error in 0.05s ===================
"""

PYTEST_COLLECTION_ERROR = """\
==================== ERRORS ====================
_______ ERROR collecting test_app.py _______
E   errors during collection
==================== 2 errors in 0.08s ====================
"""

PYTEST_NO_TESTS_RAN = "===================== no tests ran in 0.01s ====================="


def test_parse_q_all_pass():
    parsed = EvalScorer()._parse_pytest_output(PYTEST_Q_PASS)
    assert parsed.passed == 4
    assert parsed.total == 4
    assert parsed.runnable is True


def test_parse_q_mixed():
    parsed = EvalScorer()._parse_pytest_output(PYTEST_Q_MIXED)
    assert parsed.passed == 3
    assert parsed.total == 4
    assert parsed.runnable is True


def test_parse_import_error_not_runnable():
    parsed = EvalScorer()._parse_pytest_output(PYTEST_IMPORT_ERROR)
    assert parsed.runnable is False
    assert parsed.total == 0
    assert "email_validator" in parsed.reason  # names the missing dep


def test_parse_collection_error_not_runnable():
    parsed = EvalScorer()._parse_pytest_output(PYTEST_COLLECTION_ERROR)
    assert parsed.runnable is False
    assert parsed.total == 0
    assert parsed.reason  # non-empty cause surfaced


def test_parse_no_tests_ran_not_runnable():
    parsed = EvalScorer()._parse_pytest_output(PYTEST_NO_TESTS_RAN)
    assert parsed.runnable is False
    assert parsed.total == 0


def test_evaluate_q_output_scores_correctly(monkeypatch):
    """A passing -q run must NOT silently score 0 (the original bug)."""
    _patch_subprocess(monkeypatch, syntax_rc=0, pytest_output=PYTEST_Q_PASS)
    result = EvalScorer().evaluate("task", "/fake/repo")
    assert result.score == pytest.approx(100.0)
    assert result.passed is True
    assert result.runnable is True


def test_evaluate_import_error_marks_not_runnable(monkeypatch):
    _patch_subprocess(monkeypatch, syntax_rc=0, pytest_output=PYTEST_IMPORT_ERROR)
    result = EvalScorer().evaluate("task", "/fake/repo")
    assert result.runnable is False
    assert result.score == 0.0
    assert result.details.startswith("NOT RUNNABLE")
    assert "email_validator" in result.details


def test_evaluate_no_tests_marks_not_runnable(monkeypatch):
    _patch_subprocess(monkeypatch, syntax_rc=0, pytest_output="collected 0 items")
    result = EvalScorer().evaluate("task", "/fake/repo")
    assert result.runnable is False
    assert result.details.startswith("NOT RUNNABLE")


def test_evaluate_syntax_failure_not_runnable(monkeypatch):
    monkeypatch.setattr(es_mod.subprocess, "run", lambda *a, **k: _proc(returncode=1, stderr="SyntaxError"))
    result = EvalScorer().evaluate("task", "/fake/repo")
    assert result.runnable is False
    assert result.details.startswith("NOT RUNNABLE")


def test_run_pytest_timeout(monkeypatch):
    import subprocess

    def _raise(*a, **k):
        raise subprocess.TimeoutExpired(cmd="pytest", timeout=120)

    monkeypatch.setattr(es_mod.subprocess, "run", _raise)
    out = EvalScorer()._run_tests("/fake/repo", ["pytest", "--timeout=5"])
    assert "timed out" in out
