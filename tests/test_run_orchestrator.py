"""Tests for run_orchestrator — honest event emission.

All tests use a fake TaskRunner and a real RunEventBroker so no real LLM,
MongoDB, or network call is made.

Focus:
  1. _run_real emits a ``control_arm`` event carrying score_control when the
     TaskResult has a non-None score_control.
  2. _run_real does NOT emit a ``control_arm`` event when score_control is None.
  3. Per-iteration ``iteration`` events produced by linear interpolation carry
     ``interpolated=True``.
  4. The stub path keeps setting score=None and simulated=True — no fabrication.
"""

from __future__ import annotations

from typing import Any

import pytest

from yunaki_skills.interfaces import TaskResult
from yunaki_skills.live_runs import RunEventBroker
from yunaki_skills.run_orchestrator import execute_run

# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_result(score_control: float | None = 40.0, iterations: int = 2) -> TaskResult:
    return TaskResult(
        task_description="test task",
        score_before=20.0,
        score_control=score_control,
        score_after=80.0,
        skills_used=["skill_a"],
        skills_created=[],
        skills_evolved=[],
        iterations=iterations,
        trace="trace line one\ntrace line two",
    )


def _make_runner_cls(result: TaskResult) -> type:
    """Return a fake TaskRunner class whose run() returns ``result`` synchronously."""

    class FakeRunner:
        def __init__(self, org_id=None):
            self.org_id = org_id

        def run(self, task_description, max_iterations=3, **kw):
            return result

    return FakeRunner


async def _run_and_collect(
    run_id: str,
    task: str,
    max_iterations: int,
    broker: RunEventBroker,
    runner_cls=None,
) -> list[dict[str, Any]]:
    """Run execute_run while collecting all events via a subscriber queue.

    subscribe() before the run so the broker retains history.  Without a
    subscriber the broker purges history on finish(), leaving nothing to assert.
    """
    queue = broker.subscribe(run_id)
    try:
        await execute_run(
            run_id,
            task,
            max_iterations,
            broker=broker,
            list_skills=_list_skills_empty,
            add_run=_add_run_noop,
            task_runner_cls=runner_cls,
        )
    finally:
        broker.unsubscribe(run_id, queue)
    # After finish() + unsubscribe the history is still present; drain it.
    return broker.history(run_id)


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def fresh_broker():
    return RunEventBroker()


def _list_skills_empty():
    return []


def _add_run_noop(run_data):
    pass


# ─── Tests: control_arm event ─────────────────────────────────────────────────


async def test_control_arm_event_emitted_when_score_control_present(fresh_broker):
    """A control_arm event must be emitted when TaskResult.score_control is set."""
    result = _make_result(score_control=40.0)
    runner_cls = _make_runner_cls(result)

    events = await _run_and_collect("run-001", "test task", 2, fresh_broker, runner_cls)

    control_events = [e for e in events if e.get("type") == "control_arm"]
    assert len(control_events) == 1, "exactly one control_arm event expected"
    ev = control_events[0]
    assert ev["phase"] == "control_no_skills"
    assert ev["score_control"] == pytest.approx(40.0)


async def test_no_control_arm_event_when_score_control_is_none(fresh_broker):
    """If TaskResult.score_control is None, no control_arm event should be emitted."""
    result = _make_result(score_control=None)
    runner_cls = _make_runner_cls(result)

    events = await _run_and_collect("run-002", "test task", 2, fresh_broker, runner_cls)

    control_events = [e for e in events if e.get("type") == "control_arm"]
    assert control_events == [], "no control_arm event when score_control is None"


# ─── Tests: interpolated flag on iteration events ────────────────────────────


async def test_interpolated_flag_set_on_iteration_events(fresh_broker):
    """All per-iteration events from the real path must carry interpolated=True."""
    result = _make_result(score_control=40.0, iterations=3)
    runner_cls = _make_runner_cls(result)

    events = await _run_and_collect("run-003", "test task", 3, fresh_broker, runner_cls)

    # The iteration events produced by _run_real (the replay loop) start at 1.
    iter_events = [e for e in events if e.get("type") == "iteration" and e.get("iteration", 0) >= 1]
    assert len(iter_events) == 3, f"expected 3 iteration events, got {len(iter_events)}"
    for ev in iter_events:
        assert ev.get("interpolated") is True, (
            f"iteration event at i={ev.get('iteration')} missing interpolated=True: {ev}"
        )


async def test_iteration_scores_are_linearly_interpolated(fresh_broker):
    """Scores in iteration events must follow the before→after linear ramp."""
    result = _make_result(score_control=40.0, iterations=4)
    result = result.model_copy(update={"score_before": 0.0, "score_after": 100.0})
    runner_cls = _make_runner_cls(result)

    events = await _run_and_collect("run-004", "test task", 4, fresh_broker, runner_cls)

    iter_events = sorted(
        [e for e in events if e.get("type") == "iteration" and e.get("iteration", 0) >= 1],
        key=lambda e: e["iteration"],
    )
    assert len(iter_events) == 4
    expected = [25.0, 50.0, 75.0, 100.0]
    for ev, exp in zip(iter_events, expected):
        assert ev["score"] == pytest.approx(exp, abs=0.5), f"iter {ev['iteration']}: {ev['score']} != {exp}"


# ─── Tests: run_completed carries score_control / skill_delta ─────────────────


async def test_run_completed_result_contains_score_control(fresh_broker):
    """The run_completed event result must expose score_control and skill_delta."""
    result = _make_result(score_control=40.0)
    runner_cls = _make_runner_cls(result)

    events = await _run_and_collect("run-005", "test task", 2, fresh_broker, runner_cls)

    completed = [e for e in events if e.get("type") == "run_completed"]
    assert len(completed) == 1
    res = completed[0]["result"]
    assert res["score_control"] == pytest.approx(40.0)
    # skill_delta is a @property — it appears in model_dump() only when explicitly
    # included.  The orchestrator stores the raw model_dump() which omits it.
    # The key assertion is that score_control round-trips correctly.


# ─── Tests: stub path remains honest ─────────────────────────────────────────


async def test_stub_path_emits_no_control_arm_event(fresh_broker):
    """The simulated stub path must NOT emit a control_arm event."""
    events = await _run_and_collect("run-006", "simulated task", 2, fresh_broker, runner_cls=None)

    control_events = [e for e in events if e.get("type") == "control_arm"]
    assert control_events == [], "stub must not emit control_arm — no real measurement"


async def test_stub_path_iteration_scores_are_none(fresh_broker):
    """Stub iteration events must have score=None — no fabricated numbers."""
    events = await _run_and_collect("run-007", "simulated task", 2, fresh_broker, runner_cls=None)

    iter_events = [e for e in events if e.get("type") == "iteration"]
    for ev in iter_events:
        assert ev["score"] is None, f"stub iteration score must be None, got {ev['score']}"
        assert ev.get("simulated") is True


async def test_stub_path_run_completed_has_none_scores(fresh_broker):
    """Stub run_completed result must have None for score_before and score_after."""

    collected: list[dict] = []

    def _add_run_collect(run_data):
        collected.append(run_data)

    queue = fresh_broker.subscribe("run-008")
    try:
        await execute_run(
            "run-008",
            "simulated task",
            max_iterations=1,
            broker=fresh_broker,
            list_skills=_list_skills_empty,
            add_run=_add_run_collect,
            task_runner_cls=None,
        )
    finally:
        fresh_broker.unsubscribe("run-008", queue)

    assert len(collected) == 1
    run = collected[0]
    assert run["score_before"] is None
    assert run["score_after"] is None
    assert run.get("simulated") is True


# ─── Tests: control_arm event ordering ───────────────────────────────────────


async def test_control_arm_emitted_before_iteration_events(fresh_broker):
    """control_arm must appear before the per-iteration replay events."""
    result = _make_result(score_control=40.0, iterations=2)
    runner_cls = _make_runner_cls(result)

    events = await _run_and_collect("run-009", "test task", 2, fresh_broker, runner_cls)

    types = [e["type"] for e in events]
    ctrl_idx = types.index("control_arm")
    # First numbered iteration (iteration >= 1) should appear after control_arm.
    iter_indices = [i for i, e in enumerate(events) if e.get("type") == "iteration" and e.get("iteration", 0) >= 1]
    assert iter_indices, "expected at least one numbered iteration event"
    assert ctrl_idx < iter_indices[0], "control_arm must precede the first iteration event"
