"""
Yunaki Skills — Live Run Orchestrator

Drives a single evolution run and streams progress events through the
RunEventBroker so the dashboard can render it in real time. Two execution
paths share one event protocol:

  * real  — delegates to the concrete TaskRunner (runs in a thread so the
            event loop stays responsive), then replays its trace + result
            as paced events for a live-feeling UI.
  * stub  — simulates an evolution loop iteration-by-iteration when the real
            runner / MongoDB stack is unavailable.

Event protocol (type → payload) consumed by dashboard/static/js/live.js:
  run_started    {run_id, task, max_iterations}
  control_arm    {score_control, phase: "control_no_skills"}   ← NEW
  iteration      {iteration, max_iterations, score, message,
                  interpolated: bool}  ← interpolated=True when synthesised
  skill_event    {action: retrieved|created|evolved, skill_id, title}
  agent_output   {chunk}
  score_update   {score}
  run_completed  {result: TaskResult+status+timestamp}
  run_failed     {error}

Honesty contract
----------------
* ``control_arm`` mirrors the ``phase: "control_no_skills"`` event that
  TaskRunner already emits via its progress hook.  The live path must
  surface the same information so the dashboard can show skill_delta in
  real time, not just at completion.
* Per-iteration ``iteration`` events produced by linear interpolation carry
  ``"interpolated": true`` so consumers can distinguish synthesised curves
  from real measurements.  Real per-iteration data (if available from
  TaskResult in the future) should set ``"interpolated": false`` or omit
  the field.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable, Optional

from yunaki_skills.live_runs import RunEventBroker

logger = logging.getLogger(__name__)

# Pacing for replayed/simulated events. Small enough to feel live, large
# enough to read. Named constants — no magic numbers in the loop body.
_ITERATION_DELAY_S = 0.6
_SKILL_EVENT_DELAY_S = 0.25
_AGENT_CHUNK_DELAY_S = 0.04

# Explicit opt-in for the simulated/demo path. Without this, an unavailable
# real TaskRunner is a LOUD failure, never a silent slide into fake data.
_SIMULATED_STATUS = "SIMULATED"


class RealRunnerUnavailableError(RuntimeError):
    """Raised when no real TaskRunner is available and simulation is not opted in.

    Fail loud: the caller (FastAPI path) maps this to an explicit 503 degraded
    response instead of fabricating a run. Never swallow this into a fake curve.
    """


async def _emit_skill_events(
    broker: RunEventBroker,
    run_id: str,
    action: str,
    skill_ids: list[str],
    title_for: Callable[[str], str],
) -> None:
    for sid in skill_ids:
        await broker.publish(
            run_id,
            {
                "type": "skill_event",
                "action": action,
                "skill_id": sid,
                "title": title_for(sid),
            },
        )
        await asyncio.sleep(_SKILL_EVENT_DELAY_S)


async def _stream_agent_output(broker: RunEventBroker, run_id: str, trace: str) -> None:
    """Stream a trace into the terminal box line-by-line."""
    for line in trace.splitlines():
        await broker.publish(run_id, {"type": "agent_output", "chunk": line + "\n"})
        await asyncio.sleep(_AGENT_CHUNK_DELAY_S)


def _title_lookup(skills: list[dict[str, Any]]) -> Callable[[str], str]:
    index = {s.get("id"): s.get("title", s.get("id", "")) for s in skills}
    return lambda sid: index.get(sid, sid)


async def execute_run(
    run_id: str,
    task: str,
    max_iterations: int,
    *,
    broker: RunEventBroker,
    list_skills: Callable[[], list[dict[str, Any]]],
    add_run: Callable[[dict[str, Any]], None],
    task_runner_cls: Optional[type] = None,
    org_id: Optional[str] = None,
    allow_simulated: bool = False,
) -> dict[str, Any]:
    """Execute one run, emitting live events. Returns the final run record.

    `org_id` namespaces the skill bank for org-level isolation (None = global).

    Honesty contract:
      * When a real ``task_runner_cls`` is supplied, run it for real.
      * When it is NOT supplied, the run only proceeds in SIMULATED mode if the
        caller explicitly opts in via ``allow_simulated=True`` (driven by the
        ``YUNAKI_ALLOW_SIMULATED`` env var upstream). Otherwise we raise
        ``RealRunnerUnavailableError`` — a loud, explicit failure surfaced as a
        ``run_failed`` event and a 503 in the HTTP path. We never silently fall
        back to fabricated data.
    """
    await broker.publish(
        run_id,
        {"type": "run_started", "run_id": run_id, "task": task, "max_iterations": max_iterations},
    )

    try:
        if task_runner_cls is not None:
            record = await _run_real(
                run_id,
                task,
                max_iterations,
                broker=broker,
                list_skills=list_skills,
                task_runner_cls=task_runner_cls,
                org_id=org_id,
            )
        elif allow_simulated:
            record = await _run_stub(
                run_id,
                task,
                max_iterations,
                broker=broker,
                list_skills=list_skills,
                add_run=add_run,
            )
        else:
            # No real runner and simulation not opted in → fail loud.
            raise RealRunnerUnavailableError(
                "No real TaskRunner available and YUNAKI_ALLOW_SIMULATED is not "
                "set. Refusing to fabricate a run. Set GEMINI_API_KEY + "
                "MONGODB_URI for live runs, or YUNAKI_ALLOW_SIMULATED=1 for an "
                "explicitly-labelled SIMULATED demo."
            )
        await broker.publish(run_id, {"type": "run_completed", "result": record})
        return record
    except Exception as exc:  # fail loud — surface to the UI and the log
        logger.exception("run %s failed", run_id)
        await broker.publish(run_id, {"type": "run_failed", "error": str(exc)})
        raise
    finally:
        await broker.finish(run_id)


async def _run_real(
    run_id: str,
    task: str,
    max_iterations: int,
    *,
    broker: RunEventBroker,
    list_skills: Callable[[], list[dict[str, Any]]],
    task_runner_cls: type,
    org_id: Optional[str] = None,
) -> dict[str, Any]:
    title_for = _title_lookup(list_skills())

    await broker.publish(
        run_id,
        {
            "type": "iteration",
            "iteration": 0,
            "max_iterations": max_iterations,
            "score": 0,
            "message": "Booting agent + scoring baseline…",
        },
    )

    # The concrete TaskRunner is synchronous and self-persists its run record.
    # Run it off the event loop so streaming stays responsive. org_id scopes
    # the skill bank to the org's namespace.
    runner = task_runner_cls(org_id=org_id)
    result = await asyncio.to_thread(lambda: runner.run(task, max_iterations=max_iterations))
    record = result.model_dump()
    record["timestamp"] = datetime.utcnow().isoformat()
    record["status"] = "completed"

    # ── Emit control-arm event ────────────────────────────────────────────
    # Mirrors the phase="control_no_skills" event that TaskRunner already
    # emits via its internal progress hook.  We surface it here so the
    # dashboard can show skill_delta as soon as the run completes rather
    # than only deriving it at the run_completed payload.
    score_control = record.get("score_control")
    if score_control is not None:
        await broker.publish(
            run_id,
            {
                "type": "control_arm",
                "phase": "control_no_skills",
                "score_control": score_control,
            },
        )

    # Replay the trace + skill deltas as paced events for a live feel.
    await _stream_agent_output(broker, run_id, record.get("trace", ""))
    await _emit_skill_events(broker, run_id, "retrieved", record.get("skills_used", []), title_for)
    await _emit_skill_events(broker, run_id, "created", record.get("skills_created", []), title_for)
    await _emit_skill_events(broker, run_id, "evolved", record.get("skills_evolved", []), title_for)

    before = record.get("score_before", 0.0)
    after = record.get("score_after", 0.0)
    iters = max(record.get("iterations", max_iterations), 1)
    # Per-iteration scores are synthesised by linear interpolation from the
    # start/end measurements — TaskResult does not yet carry per-iteration
    # scores.  We label every point interpolated=True so consumers never
    # mistake the smooth curve for real, measured data points.
    for i in range(1, iters + 1):
        score = before + (after - before) * (i / iters)
        await broker.publish(
            run_id,
            {
                "type": "iteration",
                "iteration": i,
                "max_iterations": iters,
                "score": round(score, 1),
                "interpolated": True,
                "message": f"Iteration {i}/{iters}",
            },
        )
        await broker.publish(run_id, {"type": "score_update", "score": round(score, 1)})
        await asyncio.sleep(_ITERATION_DELAY_S)

    return record


async def _run_stub(
    run_id: str,
    task: str,
    max_iterations: int,
    *,
    broker: RunEventBroker,
    list_skills: Callable[[], list[dict[str, Any]]],
    add_run: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    """Simulated run — NO SCORES ARE FABRICATED.

    This path exists ONLY for UI/UX testing (dashboard layout, WebSocket
    streaming, event sequencing). It deliberately does NOT produce
    score_before / score_after numbers because there is no real agent run
    to measure. Any number we emit would be fake, and fake numbers are
    worse than no numbers.

    The dashboard receives a single event with simulated=True so it can
    render a clear "SIMULATED — NO LIVE RUN" banner.  If a judge or user
    sees this run, they know it is not evidence of self-evolution.

    Reached ONLY when the caller explicitly opted in (allow_simulated=True).
    We log a loud WARNING on every invocation so simulated runs can never hide
    in the logs as if they were real measurements.
    """
    logger.warning(
        "SIMULATED RUN %s — YUNAKI_ALLOW_SIMULATED is enabled. No real agent, "
        "no real scores. This record is labelled status=%s / simulated=True and "
        "is NOT evidence of self-evolution.",
        run_id,
        _SIMULATED_STATUS,
    )
    skills = list_skills()
    title_for = _title_lookup(skills)
    all_ids = [s.get("id") for s in skills if s.get("id")]

    # We surface a deterministic subset to exercise the event pipeline, but we
    # explicitly do NOT assign scores and do NOT claim any skill was created or
    # evolved. Nothing here is random or fabricated — a simulated run produces no
    # measurements at all.
    used = all_ids[:2]
    created: list = []
    evolved: list = []

    await _emit_skill_events(broker, run_id, "retrieved", used, title_for)

    for i in range(1, max_iterations + 1):
        msg = (
            f"[SIMULATED — NO LIVE RUN] Iteration {i}/{max_iterations}. "
            "No real agent execution; scores are unavailable."
        )
        await broker.publish(run_id, {"type": "agent_output", "chunk": msg + "\n"})
        await broker.publish(
            run_id,
            {
                "type": "iteration",
                "iteration": i,
                "max_iterations": max_iterations,
                "score": None,  # deliberately None, not a fabricated number
                "simulated": True,
                "message": msg,
            },
        )
        await asyncio.sleep(_ITERATION_DELAY_S)

    await _emit_skill_events(broker, run_id, "created", created, title_for)
    await _emit_skill_events(broker, run_id, "evolved", evolved, title_for)

    record = {
        "task_description": task,
        "score_before": None,
        "score_after": None,
        "skills_used": used,
        "skills_created": created,
        "skills_evolved": evolved,
        "iterations": max_iterations,
        "trace": "[SIMULATED — NO LIVE RUN] No real agent was executed.",
        "timestamp": datetime.utcnow().isoformat(),
        "status": _SIMULATED_STATUS,
        "simulated": True,
    }
    add_run(record)
    return record
