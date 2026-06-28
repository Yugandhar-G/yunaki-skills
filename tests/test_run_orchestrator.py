"""Tests for run_orchestrator — honest event emission + execute_run coverage.

All tests use a fake TaskRunner and a real RunEventBroker so no real LLM,
MongoDB, or network call is made.

Honesty focus:
  1. _run_real emits a ``control_arm`` event carrying score_control when the
     TaskResult has a non-None score_control.
  2. No ``control_arm`` event when score_control is None.
  3. Per-iteration ``iteration`` events produced by linear interpolation carry
     ``interpolated=True``.
  4. The stub path keeps setting score=None and simulated=True — no fabrication.

Coverage focus: the helpers (_title_lookup, _stream_agent_output,
_emit_skill_events, _run_stub) and both execute_run paths end-to-end.
"""

from __future__ import annotations

from typing import Any

import pytest

from yunaki_skills.interfaces import TaskResult
from yunaki_skills.live_runs import RunEventBroker
from yunaki_skills.run_orchestrator import (
    _emit_skill_events,
    _run_stub,
    _stream_agent_output,
    _title_lookup,
    execute_run,
)

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


def _list_skills_empty():
    return []


def _add_run_noop(run_data):
    pass


async def _run_and_collect(
    run_id: str,
    task: str,
    max_iterations: int,
    broker: RunEventBroker,
    runner_cls=None,
    list_skills=_list_skills_empty,
    add_run=_add_run_noop,
) -> list[dict[str, Any]]:
    """Run execute_run while collecting all events via a subscriber queue.

    subscribe() before the run so the broker retains history. Without a
    subscriber the broker purges history on finish(), leaving nothing to assert.
    """
    queue = broker.subscribe(run_id)
    try:
        await execute_run(
            run_id,
            task,
            max_iterations,
            broker=broker,
            list_skills=list_skills,
            add_run=add_run,
            task_runner_cls=runner_cls,
        )
    finally:
        broker.unsubscribe(run_id, queue)
    return broker.history(run_id)


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def fresh_broker():
    return RunEventBroker()


# ─── control_arm event ─────────────────────────────────────────────────────────


async def test_control_arm_event_emitted_when_score_control_present(fresh_broker):
    """A control_arm event must be emitted when TaskResult.score_control is set."""
    runner_cls = _make_runner_cls(_make_result(score_control=40.0))
    events = await _run_and_collect("run-001", "test task", 2, fresh_broker, runner_cls)

    control_events = [e for e in events if e.get("type") == "control_arm"]
    assert len(control_events) == 1, "exactly one control_arm event expected"
    ev = control_events[0]
    assert ev["phase"] == "control_no_skills"
    assert ev["score_control"] == pytest.approx(40.0)


async def test_no_control_arm_event_when_score_control_is_none(fresh_broker):
    """If TaskResult.score_control is None, no control_arm event should be emitted."""
    runner_cls = _make_runner_cls(_make_result(score_control=None))
    events = await _run_and_collect("run-002", "test task", 2, fresh_broker, runner_cls)

    control_events = [e for e in events if e.get("type") == "control_arm"]
    assert control_events == [], "no control_arm event when score_control is None"


async def test_control_arm_emitted_before_iteration_events(fresh_broker):
    """control_arm must appear before the per-iteration replay events."""
    runner_cls = _make_runner_cls(_make_result(score_control=40.0, iterations=2))
    events = await _run_and_collect("run-009", "test task", 2, fresh_broker, runner_cls)

    types = [e["type"] for e in events]
    ctrl_idx = types.index("control_arm")
    iter_indices = [i for i, e in enumerate(events) if e.get("type") == "iteration" and e.get("iteration", 0) >= 1]
    assert iter_indices, "expected at least one numbered iteration event"
    assert ctrl_idx < iter_indices[0], "control_arm must precede the first iteration event"


# ─── interpolated flag on iteration events ───────────────────────────────────


async def test_interpolated_flag_set_on_iteration_events(fresh_broker):
    """All per-iteration events from the real path must carry interpolated=True."""
    runner_cls = _make_runner_cls(_make_result(score_control=40.0, iterations=3))
    events = await _run_and_collect("run-003", "test task", 3, fresh_broker, runner_cls)

    iter_events = [e for e in events if e.get("type") == "iteration" and e.get("iteration", 0) >= 1]
    assert len(iter_events) == 3, f"expected 3 iteration events, got {len(iter_events)}"
    for ev in iter_events:
        assert ev.get("interpolated") is True, f"iteration {ev.get('iteration')} missing interpolated=True: {ev}"


async def test_iteration_scores_are_linearly_interpolated(fresh_broker):
    """Scores in iteration events must follow the before→after linear ramp."""
    result = _make_result(score_control=40.0, iterations=4).model_copy(
        update={"score_before": 0.0, "score_after": 100.0}
    )
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


# ─── run_completed carries score_control ─────────────────────────────────────


async def test_run_completed_result_contains_score_control(fresh_broker):
    """The run_completed event result must expose score_control."""
    runner_cls = _make_runner_cls(_make_result(score_control=40.0))
    events = await _run_and_collect("run-005", "test task", 2, fresh_broker, runner_cls)

    completed = [e for e in events if e.get("type") == "run_completed"]
    assert len(completed) == 1
    assert completed[0]["result"]["score_control"] == pytest.approx(40.0)


# ─── stub path remains honest ────────────────────────────────────────────────


async def test_stub_path_emits_no_control_arm_event(fresh_broker):
    events = await _run_and_collect("run-006", "simulated task", 2, fresh_broker, runner_cls=None)
    assert [e for e in events if e.get("type") == "control_arm"] == []


async def test_stub_path_iteration_scores_are_none(fresh_broker):
    events = await _run_and_collect("run-007", "simulated task", 2, fresh_broker, runner_cls=None)
    iter_events = [e for e in events if e.get("type") == "iteration"]
    for ev in iter_events:
        assert ev["score"] is None, f"stub iteration score must be None, got {ev['score']}"
        assert ev.get("simulated") is True


async def test_stub_path_run_completed_has_none_scores(fresh_broker):
    collected: list[dict] = []
    queue = fresh_broker.subscribe("run-008")
    try:
        await execute_run(
            "run-008",
            "simulated task",
            max_iterations=1,
            broker=fresh_broker,
            list_skills=_list_skills_empty,
            add_run=collected.append,
            task_runner_cls=None,
        )
    finally:
        fresh_broker.unsubscribe("run-008", queue)

    assert len(collected) == 1
    run = collected[0]
    assert run["score_before"] is None
    assert run["score_after"] is None
    assert run.get("simulated") is True


# ─── helper coverage: _title_lookup ──────────────────────────────────────────


def test_title_lookup_returns_title_by_id():
    lookup = _title_lookup([{"id": "s1", "title": "Skill One"}, {"id": "s2", "title": "Skill Two"}])
    assert lookup("s1") == "Skill One"
    assert lookup("s2") == "Skill Two"


def test_title_lookup_returns_id_for_unknown():
    assert _title_lookup([])("unknown_id") == "unknown_id"


def test_title_lookup_falls_back_to_id_when_title_missing():
    assert _title_lookup([{"id": "s3"}])("s3") == "s3"


# ─── helper coverage: _stream_agent_output ───────────────────────────────────


async def test_stream_agent_output_publishes_lines(fresh_broker):
    await _stream_agent_output(fresh_broker, "run1", "line1\nline2\nline3")
    history = fresh_broker.history("run1")
    assert len(history) == 3
    assert all(e["type"] == "agent_output" for e in history)
    assert history[0]["chunk"] == "line1\n"


async def test_stream_agent_output_empty_trace(fresh_broker):
    await _stream_agent_output(fresh_broker, "run_empty", "")
    assert fresh_broker.history("run_empty") == []


# ─── helper coverage: _emit_skill_events ─────────────────────────────────────


async def test_emit_skill_events_publishes_one_per_skill(fresh_broker):
    await _emit_skill_events(fresh_broker, "run2", "retrieved", ["s1", "s2"], lambda sid: f"Title-{sid}")
    events = fresh_broker.history("run2")
    assert len(events) == 2
    assert events[0]["action"] == "retrieved"
    assert events[0]["skill_id"] == "s1"
    assert events[1]["skill_id"] == "s2"


async def test_emit_skill_events_empty_list(fresh_broker):
    await _emit_skill_events(fresh_broker, "run_no_skills", "created", [], lambda s: s)
    assert fresh_broker.history("run_no_skills") == []


# ─── helper coverage: _run_stub ──────────────────────────────────────────────


async def test_run_stub_emits_run_events(fresh_broker):
    runs = []
    skills = [{"id": "a", "title": "Skill A"}, {"id": "b", "title": "Skill B"}]
    await _run_stub(
        "stub1",
        "some task",
        max_iterations=2,
        broker=fresh_broker,
        list_skills=lambda: skills,
        add_run=runs.append,
    )
    history = fresh_broker.history("stub1")
    assert "iteration" in [e["type"] for e in history]
    for ev in [e for e in history if e["type"] == "iteration"]:
        assert ev["score"] is None
        assert ev.get("simulated") is True


async def test_run_stub_records_run(fresh_broker):
    runs = []
    await _run_stub(
        "stub2", "task2", max_iterations=1, broker=fresh_broker, list_skills=lambda: [], add_run=runs.append
    )
    assert len(runs) == 1
    assert runs[0]["status"] == "simulated"
    assert runs[0]["simulated"] is True
    assert runs[0]["score_before"] is None
    assert runs[0]["score_after"] is None


async def test_run_stub_trace_is_simulated_label(fresh_broker):
    runs = []
    await _run_stub(
        "stub3", "task3", max_iterations=1, broker=fresh_broker, list_skills=lambda: [], add_run=runs.append
    )
    assert "SIMULATED" in runs[0]["trace"]


# ─── execute_run: stub path ──────────────────────────────────────────────────


async def test_execute_run_stub_path_publishes_run_started(fresh_broker):
    events = await _run_and_collect("exec1", "my task", 2, fresh_broker, runner_cls=None)
    assert [e["type"] for e in events][0] == "run_started"


async def test_execute_run_stub_path_publishes_run_completed(fresh_broker):
    events = await _run_and_collect("exec2", "task", 1, fresh_broker, runner_cls=None)
    assert "run_completed" in [e["type"] for e in events]


# ─── execute_run: real path ──────────────────────────────────────────────────


async def test_execute_run_real_path_publishes_run_started(fresh_broker):
    runner_cls = _make_runner_cls(_make_result())
    events = await _run_and_collect(
        "real1", "real task", 2, fresh_broker, runner_cls, list_skills=lambda: [{"id": "sk1", "title": "Skill 1"}]
    )
    assert events[0]["type"] == "run_started"


async def test_execute_run_real_path_emits_iteration_events(fresh_broker):
    runner_cls = _make_runner_cls(_make_result())
    events = await _run_and_collect("real2", "task", 2, fresh_broker, runner_cls)
    assert len([e for e in events if e["type"] == "iteration"]) >= 2


async def test_execute_run_real_path_emits_run_completed(fresh_broker):
    runner_cls = _make_runner_cls(_make_result())
    events = await _run_and_collect("real4", "task", 1, fresh_broker, runner_cls)
    assert "run_completed" in [e["type"] for e in events]


async def test_execute_run_real_path_returns_dict(fresh_broker):
    runner_cls = _make_runner_cls(_make_result())
    record = await execute_run(
        "real5",
        "task",
        1,
        broker=fresh_broker,
        list_skills=_list_skills_empty,
        add_run=_add_run_noop,
        task_runner_cls=runner_cls,
    )
    assert isinstance(record, dict)
    assert record["status"] == "completed"
    assert "timestamp" in record


async def test_execute_run_propagates_exception_and_publishes_run_failed(fresh_broker):
    """When the task_runner raises, execute_run must emit run_failed and re-raise."""

    class _BrokenRunner:
        def __init__(self, **kwargs):
            pass

        def run(self, *a, **kw):
            raise ValueError("boom")

    queue = fresh_broker.subscribe("err1")
    with pytest.raises(ValueError, match="boom"):
        await execute_run(
            "err1",
            "task",
            1,
            broker=fresh_broker,
            list_skills=_list_skills_empty,
            add_run=_add_run_noop,
            task_runner_cls=_BrokenRunner,
        )
    assert "run_failed" in [e["type"] for e in fresh_broker.history("err1")]
    fresh_broker.unsubscribe("err1", queue)
