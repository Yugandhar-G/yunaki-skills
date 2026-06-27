"""Tests for the RunEventBroker — in-memory pub/sub for live run streaming."""

from __future__ import annotations

import pytest

from yunaki_skills.live_runs import STREAM_DONE, RunEventBroker


@pytest.fixture
def broker():
    return RunEventBroker()


async def test_publish_records_history(broker):
    await broker.publish("run1", {"type": "iteration", "score": 50})
    history = broker.history("run1")
    assert history == [{"type": "iteration", "score": 50}]


async def test_publish_fans_out_to_subscribers(broker):
    queue = broker.subscribe("run1")
    await broker.publish("run1", {"type": "score_update", "score": 80})
    event = await queue.get()
    assert event == {"type": "score_update", "score": 80}


async def test_published_events_are_copied(broker):
    """Mutating a received event must not corrupt history."""
    queue = broker.subscribe("run1")
    await broker.publish("run1", {"type": "x", "n": 1})
    event = await queue.get()
    event["n"] = 999
    assert broker.history("run1")[0]["n"] == 1


async def test_finish_signals_subscribers(broker):
    queue = broker.subscribe("run1")
    await broker.finish("run1")
    assert await queue.get() == STREAM_DONE
    assert broker.is_finished("run1")


async def test_finish_with_no_subscribers_purges_history(broker):
    await broker.publish("run1", {"type": "x"})
    await broker.finish("run1")
    # No subscribers -> immediate cleanup, history gone, finished flag cleared.
    assert broker.history("run1") == []
    assert broker.is_finished("run1") is False


def test_unsubscribe_removes_queue(broker):
    queue = broker.subscribe("run1")
    broker.unsubscribe("run1", queue)
    assert queue not in broker._subscribers.get("run1", [])


def test_unsubscribe_unknown_is_noop(broker):
    import asyncio

    broker.unsubscribe("missing", asyncio.Queue())  # must not raise


async def test_cleanup_keeps_history_for_unfinished_run(broker):
    await broker.publish("run1", {"type": "x"})
    broker.cleanup("run1")  # not finished -> history retained
    assert broker.history("run1") == [{"type": "x"}]


async def test_cleanup_skips_when_subscribers_present(broker):
    broker.subscribe("run1")
    await broker.publish("run1", {"type": "x"})
    broker._finished.add("run1")
    broker.cleanup("run1")  # subscribers present -> no purge
    assert broker.history("run1") == [{"type": "x"}]


def test_history_for_unknown_run_is_empty(broker):
    assert broker.history("nope") == []
