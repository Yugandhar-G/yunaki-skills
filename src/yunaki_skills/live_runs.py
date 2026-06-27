"""
Yunaki Skills — Live Run Event Broker

In-memory pub/sub for streaming run progress to dashboard WebSocket clients.
Each run gets an event history (for late-joining / reconnecting clients to
replay) and a set of live subscriber queues. There is no external dependency
(no Redis) — this is intentionally process-local for the hackathon/single-node
deployment. Swap the broker for a Redis-backed one to scale horizontally.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

# Sentinel pushed into a subscriber queue once a run terminates so the
# WebSocket handler can drain remaining events and close cleanly.
STREAM_DONE = {"type": "_stream_done"}


class RunEventBroker:
    """Process-local pub/sub keyed by run_id.

    Immutability note: published events are copied before fan-out so a
    subscriber mutating its received dict cannot corrupt the shared history
    or another subscriber's view.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._history: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._finished: set[str] = set()

    # ── Publishing side (run orchestrator) ────────────────────────────────

    async def publish(self, run_id: str, event: dict[str, Any]) -> None:
        """Record an event in history and fan it out to live subscribers."""
        snapshot = dict(event)
        self._history[run_id].append(snapshot)
        for queue in list(self._subscribers.get(run_id, [])):
            await queue.put(dict(snapshot))

    async def finish(self, run_id: str) -> None:
        """Mark a run complete and signal all subscribers to close."""
        self._finished.add(run_id)
        subs = self._subscribers.get(run_id, [])
        for queue in list(subs):
            await queue.put(dict(STREAM_DONE))
        # No one is listening to a finished run — purge now so history doesn't
        # leak. If clients are connected, their disconnect triggers cleanup().
        if not subs:
            self.cleanup(run_id)

    def is_finished(self, run_id: str) -> bool:
        return run_id in self._finished

    # ── Subscribing side (WebSocket handler) ──────────────────────────────

    def history(self, run_id: str) -> list[dict[str, Any]]:
        """Replay buffer for a reconnecting client. Returns copies."""
        return [dict(e) for e in self._history.get(run_id, [])]

    def subscribe(self, run_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers[run_id].append(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue) -> None:
        subs = self._subscribers.get(run_id)
        if subs and queue in subs:
            subs.remove(queue)

    def cleanup(self, run_id: str) -> None:
        """Drop all state for a finished run once nobody is listening.

        Only purges finished runs — an in-flight run with no current
        subscribers must keep its history so a reconnecting client can replay.
        """
        if self._subscribers.get(run_id):
            return
        if run_id not in self._finished:
            return
        self._history.pop(run_id, None)
        self._subscribers.pop(run_id, None)
        self._finished.discard(run_id)


# Module-level singleton used by the FastAPI app.
broker = RunEventBroker()
