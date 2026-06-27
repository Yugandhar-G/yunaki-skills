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
  iteration      {iteration, max_iterations, score, message}
  skill_event    {action: retrieved|created|evolved, skill_id, title}
  agent_output   {chunk}
  score_update   {score}
  run_completed  {result: TaskResult+status+timestamp}
  run_failed     {error}
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime
from typing import Any, Callable, Optional

from yunaki_skills.live_runs import RunEventBroker

# Pacing for replayed/simulated events. Small enough to feel live, large
# enough to read. Named constants — no magic numbers in the loop body.
_ITERATION_DELAY_S = 0.6
_SKILL_EVENT_DELAY_S = 0.25
_AGENT_CHUNK_DELAY_S = 0.04


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
    repo_id: Optional[str] = None,
) -> dict[str, Any]:
    """Execute one run, emitting live events. Returns the final run record.

    `repo_id` namespaces the skill bank for multi-repo isolation (None = global).
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
                repo_id=repo_id,
            )
        else:
            record = await _run_stub(
                run_id,
                task,
                max_iterations,
                broker=broker,
                list_skills=list_skills,
                add_run=add_run,
            )
        await broker.publish(run_id, {"type": "run_completed", "result": record})
        return record
    except Exception as exc:  # fail loud — surface to the UI and the log
        print(f"[ERROR] run {run_id} failed: {exc}")
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
    repo_id: Optional[str] = None,
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
    # Run it off the event loop so streaming stays responsive. repo_id scopes
    # the skill bank to the registered repo's namespace.
    runner = task_runner_cls(repo_id=repo_id)
    result = await asyncio.to_thread(runner.run, task, max_iterations)
    record = result.model_dump()
    record["timestamp"] = datetime.utcnow().isoformat()
    record["status"] = "completed"

    # Replay the trace + skill deltas as paced events for a live feel.
    await _stream_agent_output(broker, run_id, record.get("trace", ""))
    await _emit_skill_events(broker, run_id, "retrieved", record.get("skills_used", []), title_for)
    await _emit_skill_events(broker, run_id, "created", record.get("skills_created", []), title_for)
    await _emit_skill_events(broker, run_id, "evolved", record.get("skills_evolved", []), title_for)

    before = record.get("score_before", 0.0)
    after = record.get("score_after", 0.0)
    iters = max(record.get("iterations", max_iterations), 1)
    for i in range(1, iters + 1):
        score = before + (after - before) * (i / iters)
        await broker.publish(
            run_id,
            {
                "type": "iteration",
                "iteration": i,
                "max_iterations": iters,
                "score": round(score, 1),
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
    skills = list_skills()
    title_for = _title_lookup(skills)
    all_ids = [s.get("id") for s in skills if s.get("id")]

    score_before = round(random.uniform(10, 35), 1)
    score_after = round(min(score_before + random.uniform(30, 55), 100), 1)
    used = random.sample(all_ids, min(2, len(all_ids))) if all_ids else []
    created = [all_ids[0]] if all_ids and random.random() > 0.3 else []
    evolved = [all_ids[1]] if len(all_ids) > 1 and random.random() > 0.4 else []

    await _emit_skill_events(broker, run_id, "retrieved", used, title_for)

    trace_lines: list[str] = []
    for i in range(1, max_iterations + 1):
        frac = i / max_iterations
        score = round(score_before + (score_after - score_before) * frac, 1)
        msg = "No skills yet — baseline run." if i == 1 else "Skills injected: " + ", ".join(used[:i])
        line = f"Iteration {i}/{max_iterations}: score={score:.0f}. {msg}"
        trace_lines.append(line)
        await broker.publish(run_id, {"type": "agent_output", "chunk": line + "\n"})
        await broker.publish(
            run_id,
            {"type": "iteration", "iteration": i, "max_iterations": max_iterations, "score": score, "message": msg},
        )
        await broker.publish(run_id, {"type": "score_update", "score": score})
        await asyncio.sleep(_ITERATION_DELAY_S)

    await _emit_skill_events(broker, run_id, "created", created, title_for)
    await _emit_skill_events(broker, run_id, "evolved", evolved, title_for)

    record = {
        "task_description": task,
        "score_before": score_before,
        "score_after": score_after,
        "skills_used": used,
        "skills_created": created,
        "skills_evolved": evolved,
        "iterations": max_iterations,
        "trace": "\n".join(trace_lines),
        "timestamp": datetime.utcnow().isoformat(),
        "status": "completed",
    }
    add_run(record)
    return record
