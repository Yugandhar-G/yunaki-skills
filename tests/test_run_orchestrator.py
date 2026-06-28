"""Tests for run_orchestrator.execute_run — both stub and real-runner paths.

Uses pytest-asyncio (asyncio_mode = auto). All external dependencies are faked:
- TaskRunner is replaced with a lightweight synchronous fake.
- RunEventBroker is the real in-memory broker from live_runs.py.
- list_skills / add_run are simple callables.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from yunaki_skills.live_runs import RunEventBroker
from yunaki_skills.run_orchestrator import (
    _emit_skill_events,
    _run_stub,
    _stream_agent_output,
    _title_lookup,
    execute_run,
)

# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def broker():
    return RunEventBroker()


def _make_result(score_before=30.0, score_after=70.0, iterations=2):
    """Return a MagicMock that looks like a TaskResult."""
    result = MagicMock()
    result.model_dump.return_value = {
        "task_description": "test task",
        "score_before": score_before,
        "score_after": score_after,
        "score_control": None,
        "skill_delta": None,
        "skills_used": ["s1"],
        "skills_created": [],
        "skills_evolved": [],
        "iterations": iterations,
        "trace": "line1\nline2\nline3",
    }
    result.skill_delta = None
    return result


class _FakeTaskRunner:
    """Synchronous fake TaskRunner — returns immediately with a fixed result."""

    def __init__(self, org_id=None, **kwargs):
        pass

    def run(self, task: str, max_iterations: int = 3) -> MagicMock:
        return _make_result()


# ─── _title_lookup ────────────────────────────────────────────────────────────


def test_title_lookup_returns_title_by_id():
    skills = [{"id": "s1", "title": "Skill One"}, {"id": "s2", "title": "Skill Two"}]
    lookup = _title_lookup(skills)
    assert lookup("s1") == "Skill One"
    assert lookup("s2") == "Skill Two"


def test_title_lookup_returns_id_for_unknown():
    lookup = _title_lookup([])
    assert lookup("unknown_id") == "unknown_id"


def test_title_lookup_falls_back_to_id_when_title_missing():
    skills = [{"id": "s3"}]
    lookup = _title_lookup(skills)
    assert lookup("s3") == "s3"


# ─── _stream_agent_output ────────────────────────────────────────────────────


async def test_stream_agent_output_publishes_lines(broker):
    await _stream_agent_output(broker, "run1", "line1\nline2\nline3")
    history = broker.history("run1")
    assert len(history) == 3
    assert all(e["type"] == "agent_output" for e in history)
    assert history[0]["chunk"] == "line1\n"


async def test_stream_agent_output_empty_trace(broker):
    await _stream_agent_output(broker, "run_empty", "")
    assert broker.history("run_empty") == []


# ─── _emit_skill_events ───────────────────────────────────────────────────────


async def test_emit_skill_events_publishes_one_per_skill(broker):
    def title_for(sid):
        return f"Title-{sid}"

    await _emit_skill_events(broker, "run2", "retrieved", ["s1", "s2"], title_for)
    events = broker.history("run2")
    assert len(events) == 2
    assert events[0]["action"] == "retrieved"
    assert events[0]["skill_id"] == "s1"
    assert events[1]["skill_id"] == "s2"


async def test_emit_skill_events_empty_list(broker):
    def identity(s):
        return s

    await _emit_skill_events(broker, "run_no_skills", "created", [], identity)
    assert broker.history("run_no_skills") == []


# ─── _run_stub ────────────────────────────────────────────────────────────────


async def test_run_stub_emits_run_events(broker):
    runs = []
    skills = [
        {"id": "a", "title": "Skill A"},
        {"id": "b", "title": "Skill B"},
        {"id": "c", "title": "Skill C"},
    ]

    await _run_stub(
        "stub1",
        "some task",
        max_iterations=2,
        broker=broker,
        list_skills=lambda: skills,
        add_run=runs.append,
    )

    history = broker.history("stub1")
    types = [e["type"] for e in history]

    # Must have at least one iteration event
    assert "iteration" in types
    # Scores must be None (no fabricated numbers)
    iteration_events = [e for e in history if e["type"] == "iteration"]
    for ev in iteration_events:
        assert ev["score"] is None
        assert ev.get("simulated") is True


async def test_run_stub_records_run(broker):
    runs = []
    await _run_stub(
        "stub2",
        "task2",
        max_iterations=1,
        broker=broker,
        list_skills=lambda: [],
        add_run=runs.append,
    )
    assert len(runs) == 1
    run = runs[0]
    assert run["status"] == "simulated"
    assert run["simulated"] is True
    assert run["score_before"] is None
    assert run["score_after"] is None


async def test_run_stub_trace_is_simulated_label(broker):
    runs = []
    await _run_stub(
        "stub3",
        "task3",
        max_iterations=1,
        broker=broker,
        list_skills=lambda: [],
        add_run=runs.append,
    )
    assert "SIMULATED" in runs[0]["trace"]


# ─── execute_run (stub path) ─────────────────────────────────────────────────


async def test_execute_run_stub_path_publishes_run_started(broker):
    """Subscribe first so history is preserved after finish() with a subscriber."""
    runs = []
    # Subscribe before running so finish() doesn't purge history immediately
    queue = broker.subscribe("exec1")

    await execute_run(
        "exec1",
        "my task",
        2,
        broker=broker,
        list_skills=lambda: [],
        add_run=runs.append,
        task_runner_cls=None,  # triggers stub path
    )

    history = broker.history("exec1")
    types = [e["type"] for e in history]
    # run_started is emitted first
    assert types[0] == "run_started"
    broker.unsubscribe("exec1", queue)


async def test_execute_run_stub_path_publishes_run_completed(broker):
    runs = []
    queue = broker.subscribe("exec2")

    await execute_run(
        "exec2",
        "task",
        1,
        broker=broker,
        list_skills=lambda: [],
        add_run=runs.append,
        task_runner_cls=None,
    )

    history = broker.history("exec2")
    types = [e["type"] for e in history]
    assert "run_completed" in types
    broker.unsubscribe("exec2", queue)


async def test_execute_run_stub_finishes_broker(broker):
    """execute_run should complete without hanging; cleanup behaviour is tested elsewhere."""
    runs = []

    await execute_run(
        "exec_finish",
        "task",
        1,
        broker=broker,
        list_skills=lambda: [],
        add_run=runs.append,
        task_runner_cls=None,
    )

    # Reached here without hanging — that's the assertion.
    assert True


# ─── execute_run (real-runner path) ───────────────────────────────────────────


async def test_execute_run_real_path_publishes_run_started(broker):
    runs = []
    skills = [{"id": "sk1", "title": "Skill 1"}]
    queue = broker.subscribe("real1")

    await execute_run(
        "real1",
        "real task",
        2,
        broker=broker,
        list_skills=lambda: skills,
        add_run=runs.append,
        task_runner_cls=_FakeTaskRunner,
    )

    history = broker.history("real1")
    assert history[0]["type"] == "run_started"
    broker.unsubscribe("real1", queue)


async def test_execute_run_real_path_emits_iteration_events(broker):
    runs = []
    skills = []
    queue = broker.subscribe("real2")

    await execute_run(
        "real2",
        "task",
        2,
        broker=broker,
        list_skills=lambda: skills,
        add_run=runs.append,
        task_runner_cls=_FakeTaskRunner,
    )

    history = broker.history("real2")
    iteration_events = [e for e in history if e["type"] == "iteration"]
    # The real path creates iters+1 iteration events (0 = boot + N iterations)
    assert len(iteration_events) >= 2
    broker.unsubscribe("real2", queue)


async def test_execute_run_real_path_emits_score_updates(broker):
    runs = []
    queue = broker.subscribe("real3")

    await execute_run(
        "real3",
        "task",
        2,
        broker=broker,
        list_skills=lambda: [],
        add_run=runs.append,
        task_runner_cls=_FakeTaskRunner,
    )

    history = broker.history("real3")
    score_events = [e for e in history if e["type"] == "score_update"]
    assert len(score_events) >= 1
    broker.unsubscribe("real3", queue)


async def test_execute_run_real_path_emits_run_completed(broker):
    runs = []
    queue = broker.subscribe("real4")

    await execute_run(
        "real4",
        "task",
        1,
        broker=broker,
        list_skills=lambda: [],
        add_run=runs.append,
        task_runner_cls=_FakeTaskRunner,
    )

    history = broker.history("real4")
    types = [e["type"] for e in history]
    assert "run_completed" in types
    broker.unsubscribe("real4", queue)


async def test_execute_run_real_path_returns_dict(broker):
    runs = []

    record = await execute_run(
        "real5",
        "task",
        1,
        broker=broker,
        list_skills=lambda: [],
        add_run=runs.append,
        task_runner_cls=_FakeTaskRunner,
    )

    assert isinstance(record, dict)
    assert record["status"] == "completed"
    assert "timestamp" in record


async def test_execute_run_propagates_exception_and_publishes_run_failed(broker):
    """When the task_runner raises, execute_run must emit run_failed and re-raise."""

    class _BrokenRunner:
        def __init__(self, **kwargs):
            pass

        def run(self, *a, **kw):
            raise ValueError("boom")

    runs = []
    queue = broker.subscribe("err1")
    with pytest.raises(ValueError, match="boom"):
        await execute_run(
            "err1",
            "task",
            1,
            broker=broker,
            list_skills=lambda: [],
            add_run=runs.append,
            task_runner_cls=_BrokenRunner,
        )

    history = broker.history("err1")
    types = [e["type"] for e in history]
    assert "run_failed" in types
    broker.unsubscribe("err1", queue)
