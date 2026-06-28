"""Offline tests for eval/score.py — grading + aggregation, no agents, no network."""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "eval"))

import score  # noqa: E402  (after sys.path bootstrap to eval/)

GOOD = """from __future__ import annotations
import argparse

# this module is careful and should never raise to the caller


def f() -> int:
    return 42


def main(argv=None) -> int:
    argparse.ArgumentParser().parse_args(argv)
    return 0
"""

THIRD_PARTY = """import requests


def f():
    return 41
"""

WRONG_BEHAVIOR = """def f():
    return 41
"""

SYNTAX_ERROR = "def (oops\n"


def _write(tmp_path, name, code):
    p = tmp_path / name
    p.write_text(code)
    return str(p)


def test_conventions_score_full(tmp_path):
    path = _write(tmp_path, "good.py", GOOD)
    assert score.conventions_score(path) == 1.0
    assert set(score.conventions_present(path)) == set(score.TARGET_CONVENTIONS)


def test_conventions_score_low(tmp_path):
    # third-party import, no future/argparse/never-raise -> follows none (analyze only parses)
    path = _write(tmp_path, "tp.py", THIRD_PARTY)
    assert score.conventions_score(path) == 0.0


def test_tests_score_pass(tmp_path):
    path = _write(tmp_path, "good.py", GOOD)
    assert score.tests_score(path, lambda m: m.f() == 42) == (1.0, True)


def test_tests_score_behavior_fail_is_runnable(tmp_path):
    path = _write(tmp_path, "wrong.py", WRONG_BEHAVIOR)
    assert score.tests_score(path, lambda m: m.f() == 42) == (0.0, True)


def test_tests_score_syntax_error_not_runnable(tmp_path):
    path = _write(tmp_path, "broken.py", SYNTAX_ERROR)
    assert score.tests_score(path, lambda m: True) == (0.0, False)


def test_aggregate():
    a = score.aggregate([1.0, 1.0, 0.0])
    assert a["n"] == 3
    assert abs(a["mean"] - 2 / 3) < 1e-9
    assert a["std"] > 0
    assert score.aggregate([])["mean"] == 0.0
