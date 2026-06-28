#!/usr/bin/env python3
"""Grading + aggregation for the 3-arm eval. Pure and unit-testable (no agents, no network).

Two metrics per candidate file:
  - conventions-followed: how many of the repo's 4 house rules it keeps (reuses codegraph).
  - tests-passed: whether the task's behavioral check succeeds against the written module.
"""

from __future__ import annotations

import importlib.util
import os
import statistics
import sys
from collections.abc import Callable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root

import codegraph  # noqa: E402  (after sys.path bootstrap)

# The repo's four provable house rules — the same set codegraph derives.
TARGET_CONVENTIONS = ("stdlib-only", "future-annotations", "argparse-cli", "never-raises")


def conventions_present(path: str) -> list[str]:
    """Which of the 4 conventions a single file follows. Mirrors codegraph's node-level logic
    (analyze() gives future-annotations/argparse-cli/never-raises; stdlib-only is the absence
    of third-party imports)."""
    imports, conv, _src = codegraph.analyze(path)
    present = {c for c in conv if c in TARGET_CONVENTIONS}
    if not (imports - codegraph._STDLIB):  # no third-party import -> stdlib-only
        present.add("stdlib-only")
    return sorted(present)


def conventions_score(path: str) -> float:
    """Fraction of the 4 repo conventions the file follows (0.0 .. 1.0)."""
    return len(conventions_present(path)) / len(TARGET_CONVENTIONS)


def tests_score(path: str, check: Callable[[object], bool]) -> tuple[float, bool]:
    """Run the task's behavioral check against the written module.

    Returns (score, runnable): import/exec failure -> (0.0, False); a check that runs but
    fails or raises -> (0.0, True); a passing check -> (1.0, True)."""
    try:
        spec = importlib.util.spec_from_file_location("candidate", path)
        if spec is None or spec.loader is None:
            return 0.0, False
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except BaseException:  # noqa: BLE001 — agent code may raise/SystemExit on import; not runnable
        return 0.0, False
    try:
        return (1.0 if check(mod) else 0.0), True
    except Exception:  # noqa: BLE001 — check raised -> behavioral fail, but it did run
        return 0.0, True


def aggregate(values: list[float]) -> dict:
    """mean / std / n across rollout scores. std is 0 for n < 2."""
    n = len(values)
    return {
        "mean": statistics.fmean(values) if n else 0.0,
        "std": statistics.pstdev(values) if n > 1 else 0.0,
        "n": n,
    }
