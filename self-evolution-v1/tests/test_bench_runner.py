"""Tests for the benchmark runner — split correctness, read-only eval, honest aggregation."""

from __future__ import annotations

import mongomock
import pytest

import yunaki_skills.bench.runner as runner_mod
from yunaki_skills import skill_bank as sb_mod
from yunaki_skills.bench.runner import run_benchmark
from yunaki_skills.bench.task_spec import TaskCorpus, TaskSpec
from yunaki_skills.interfaces import TaskResult


@pytest.fixture(autouse=True)
def _no_git_no_mongo(monkeypatch):
    # Skip real git materialization and back the bench bank with mongomock.
    monkeypatch.setattr(runner_mod, "materialize", lambda spec, dest: None)
    monkeypatch.setattr(sb_mod, "MongoClient", lambda *a, **k: mongomock.MongoClient())


def _spec(i: int) -> TaskSpec:
    return TaskSpec(
        id=f"t{i}",
        repo_path="/x",
        base_commit="abc^",
        fix_commit="abc",
        test_paths=["test_x.py"],
        test_command=["pytest"],
        prompt=f"task {i}",
    )


def _corpus(n: int) -> TaskCorpus:
    return TaskCorpus(repo_path="/x", test_command=["pytest"], tasks=[_spec(i) for i in range(n)])


def _fake_runner_factory(calls: list):
    class FakeRunner:
        def __init__(self, org):
            self.org = org

        def run_repo(self, task_description, repo_path, test_command=None, max_iterations=3, learn=True):
            calls.append({"task": task_description, "learn": learn, "max_iterations": max_iterations})
            # Eval arm: skilled (60) beats control (20) -> skill_delta = +40.
            return TaskResult(
                task_description=task_description,
                score_before=0.0,
                score_control=20.0,
                score_after=60.0,
                skills_used=["s1"],
                skills_created=[],
                skills_evolved=[],
                iterations=1,
            )

    return lambda org: FakeRunner(org)


def test_split_sizes_and_readonly_eval():
    calls: list = []
    report = run_benchmark(_corpus(4), train_frac=0.5, seed=1, runner_factory=_fake_runner_factory(calls))

    assert report.n_train == 2
    assert report.n_eval == 2
    train_calls = [c for c in calls if c["learn"]]
    eval_calls = [c for c in calls if not c["learn"]]
    assert len(train_calls) == 2
    assert len(eval_calls) == 2
    # Held-out eval must be read-only AND single-pass.
    assert all(c["learn"] is False for c in eval_calls)
    assert all(c["max_iterations"] == 1 for c in eval_calls)


def test_held_out_skill_delta_is_honest_mean():
    calls: list = []
    report = run_benchmark(_corpus(4), train_frac=0.5, seed=1, runner_factory=_fake_runner_factory(calls))
    # skill_delta = score_after - score_control = 60 - 20 = 40 per held-out task.
    assert report.mean_held_out_skill_delta == 40.0
    # 60 < 100 so neither arm "passed" — pass rates honest, not inflated.
    assert report.skilled_pass_rate == 0.0
    assert report.control_pass_rate == 0.0
    assert len(report.outcomes) == 2


def test_train_eval_split_is_disjoint():
    seen = {"train": [], "eval": []}

    class FakeRunner:
        def __init__(self, org):
            pass

        def run_repo(self, task_description, repo_path, test_command=None, max_iterations=3, learn=True):
            seen["train" if learn else "eval"].append(task_description)
            return TaskResult(
                task_description=task_description,
                score_before=0.0,
                score_control=0.0,
                score_after=0.0,
                skills_used=[],
                skills_created=[],
                skills_evolved=[],
                iterations=1,
            )

    run_benchmark(_corpus(10), train_frac=0.7, seed=42, runner_factory=lambda o: FakeRunner(o))
    assert len(seen["train"]) == 7
    assert len(seen["eval"]) == 3
    assert set(seen["train"]).isdisjoint(set(seen["eval"]))


def test_empty_eval_reports_none_delta():
    calls: list = []
    # train_frac=1.0 -> no eval tasks -> mean delta is None, not a fake 0.
    report = run_benchmark(_corpus(3), train_frac=1.0, seed=1, runner_factory=_fake_runner_factory(calls))
    assert report.n_eval == 0
    assert report.mean_held_out_skill_delta is None
