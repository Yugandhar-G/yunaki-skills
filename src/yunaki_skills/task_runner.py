"""
TaskRunner — the orchestration loop.

Implements the TaskRunner interface from yunaki_skills.interfaces.
Orchestrates the full skill evolution loop:
  1. Get baseline score (run eval without skills)
  2. Retrieve relevant skills via SkillRetriever
  3. Run agent with injected skills
  4. Evaluate the result
  5. If failed, extract a new skill via SkillExtractor
  6. If existing skill didn't help, evolve it via SkillEvolver
  7. Repeat until passed or max_iterations reached
"""

import logging
import os
from typing import Callable, Optional

from yunaki_skills import governance
from yunaki_skills.antigravity_client import AntigravityClient
from yunaki_skills.eval_scorer import EvalScorer
from yunaki_skills.interfaces import (
    EvalResult,
    Skill,
    TaskResult,
)
from yunaki_skills.interfaces import (
    TaskRunner as ITaskRunner,
)
from yunaki_skills.skill_bank import SkillBank
from yunaki_skills.skill_evolver import SkillEvolver
from yunaki_skills.skill_extractor import SkillExtractor
from yunaki_skills.skill_retriever import SkillRetriever

logger = logging.getLogger(__name__)

# Project root — two levels up from this source file
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_DEFAULT_REPO_PATH = os.path.join(_PROJECT_ROOT, "target_repo")


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _demo_handicap_clause(iteration: int) -> str:
    """Staged demo constraint appended to the agent's task for early iterations.

    Enabled by YUNAKI_DEMO_MODE. The agent is told to implement only the first
    K required endpoints (in listed order) on a given pass, where K comes from
    YUNAKI_DEMO_HANDICAP (default "1,2" => iter1 does 1, iter2 does 2, iter3+
    unconstrained). This forces genuine sub-threshold scores on early passes so
    the extract -> evolve -> pass cycle is exercised live, instead of the agent
    one-shotting the whole task and skipping the learning paths.

    Returns "" when demo mode is off or the iteration is past the schedule.
    """
    if not _truthy(os.environ.get("YUNAKI_DEMO_MODE", "")):
        return ""

    raw = os.environ.get("YUNAKI_DEMO_HANDICAP", "1,2")
    try:
        schedule = [int(x) for x in raw.split(",") if x.strip()]
    except ValueError:
        schedule = [1, 2]

    if iteration < 1 or iteration > len(schedule):
        return ""

    k = schedule[iteration - 1]
    return (
        "\n\n[STAGED DEMO CONSTRAINT] The task above lists several required "
        f"endpoints. In THIS pass, implement ONLY the first {k} endpoint(s) in "
        "the exact order they are listed in the task. Do NOT add the remaining "
        "endpoints — leave them entirely unimplemented (no route, no handler). "
        "This staging is intentional; a later pass will add the rest."
    )


class TaskRunner(ITaskRunner):
    """Orchestrates the full skill evolution loop."""

    def __init__(self, repo_id: Optional[str] = None):
        # repo_id namespaces the skill bank so each registered repo evolves its
        # own isolated set of skills. None = the shared/global bank.
        self._repo_id = repo_id
        self._bank = SkillBank(repo_id=repo_id)
        self._extractor = SkillExtractor()
        self._evolver = SkillEvolver()
        self._retriever = SkillRetriever(bank=self._bank)
        self._agent = AntigravityClient()
        self._scorer = EvalScorer()
        self._repo_path = os.environ.get("TARGET_REPO", _DEFAULT_REPO_PATH)

    @staticmethod
    def _emit(progress: Optional[Callable[[dict], None]], event: dict) -> None:
        """Fire a progress event, swallowing any sink errors.

        Progress reporting is best-effort observability; a broken sink must
        never break the evolution run.
        """
        if progress is None:
            return
        try:
            progress(event)
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("progress sink failed: %s", e)

    def _learn_from_success(self, task_description: str, trace: str, eval_result: EvalResult) -> Optional[str]:
        """Extract and store a reusable skill from a SUCCESSFUL trace.

        Safety net invoked only when a task passed without ever triggering the
        failure-driven extract/evolve path. Captures the winning approach so it
        persists in the bank and surfaces on future related tasks via semantic
        retrieval. Returns the stored skill id, or None if nothing could be
        extracted or it already existed.

        If the extracted skill already exists, the existing version is kept — we
        do not overwrite a battle-tested skill on the strength of a fresh
        one-shot success.
        """
        try:
            skill = self._extractor.extract(
                task_description=task_description,
                trace=trace,
                eval_result=eval_result,
            )
        except Exception as e:
            logger.warning("Learn-on-success extraction failed: %s", e)
            return None

        if not skill:
            return None

        try:
            if self._bank.get(skill.id) is not None:
                logger.info(
                    "Learn-on-success: skill %s already in bank — keeping existing",
                    skill.id,
                )
                return None
            stored_id = self._bank.add(skill)
            print(f"  [learn] Captured winning approach as skill: {stored_id}")
            return stored_id
        except Exception as e:
            logger.warning("Learn-on-success store failed: %s", e)
            return None

    def run(
        self,
        task_description: str,
        max_iterations: int = 3,
        progress: Optional[Callable[[dict], None]] = None,
    ) -> TaskResult:
        """Run a task through the full skill evolution loop.

        `progress` is an optional sink invoked with structured event dicts
        (run_start, iteration_start, eval_result, skill_created, skill_evolved,
        run_complete) so callers can stream live progress over WebSocket.
        """
        repo_path = self._repo_path
        logger.info(
            "TaskRunner starting: task=%r  repo=%s  repo_id=%s  max_iterations=%d",
            task_description,
            repo_path,
            self._repo_id,
            max_iterations,
        )
        print(f"\n{'=' * 60}")
        print(f"TASK: {task_description}")
        print(f"{'=' * 60}")
        self._emit(
            progress,
            {
                "type": "run_start",
                "task_description": task_description,
                "repo_id": self._repo_id,
                "max_iterations": max_iterations,
            },
        )

        # ─── Step 1: Baseline score (no skills) ─────────────────────────
        print("\n[1] Running baseline evaluation (no skills)...")
        baseline_eval = self._scorer.evaluate(task_description, repo_path)
        score_before = baseline_eval.score
        print(f"  Baseline: {baseline_eval.tasks_passed}/{baseline_eval.tasks_total} passed = {score_before:.0f}%")
        self._emit(
            progress,
            {
                "type": "eval_result",
                "iteration": 0,
                "phase": "baseline",
                "score": score_before,
                "passed": baseline_eval.passed,
                "tasks_passed": baseline_eval.tasks_passed,
                "tasks_total": baseline_eval.tasks_total,
            },
        )

        # Track results
        skills_used: list[str] = []
        skills_created: list[str] = []
        skills_evolved: list[str] = []
        current_score = score_before
        full_trace = ""
        iterations = 0
        # Skill created during THIS run — subsequent failures evolve it rather
        # than spawning near-duplicate siblings.
        last_created_skill_id: Optional[str] = None

        # If already passing, short-circuit
        if baseline_eval.passed:
            logger.info("Task already passing at baseline — done")
            print("  Already passing! No skills needed.")
            self._emit(
                progress,
                {
                    "type": "run_complete",
                    "score_before": score_before,
                    "score_after": score_before,
                    "skills_used": skills_used,
                    "skills_created": skills_created,
                    "skills_evolved": skills_evolved,
                    "iterations": 0,
                },
            )
            return TaskResult(
                task_description=task_description,
                score_before=score_before,
                score_after=score_before,
                skills_used=skills_used,
                skills_created=skills_created,
                skills_evolved=skills_evolved,
                iterations=0,
                trace="Already passing at baseline",
            )

        # ─── Step 2: Retrieve relevant skills ────────────────────────────
        print("\n[2] Retrieving relevant skills...")
        task_skills = self._retriever.retrieve_for_task(task_description)
        print(f"  Found {len(task_skills)} task-level skills: {[s.id for s in task_skills]}")
        for s in task_skills:
            if s.id not in skills_used:
                skills_used.append(s.id)

        # ─── Main loop ───────────────────────────────────────────────────
        for iteration in range(1, max_iterations + 1):
            iterations = iteration
            print(f"\n{'=' * 40} Iteration {iteration}/{max_iterations} {'=' * 40}")
            self._emit(
                progress,
                {
                    "type": "iteration_start",
                    "iteration": iteration,
                    "max_iterations": max_iterations,
                    "skills_injected": [s.id for s in task_skills],
                },
            )

            # ─── Step 3: Run agent with injected skills ──────────────────
            iter_task = task_description + _demo_handicap_clause(iteration)
            if iter_task != task_description:
                print(f"  [demo] Staged constraint active for iteration {iteration}")
            print(f"  [3] Running agent with {len(task_skills)} skills...")
            try:
                trace = self._agent.run_task(
                    task_description=iter_task,
                    skills=task_skills,
                    repo_path=repo_path,
                )
                full_trace += f"\n--- Iteration {iteration} Trace ---\n{trace}\n"
            except Exception as e:
                logger.error("Agent failed in iteration %d: %s", iteration, e)
                full_trace += f"\n--- Iteration {iteration} Agent Error ---\n{e}\n"
                trace = f"Agent error: {e}"

            # Check event-driven triggers on agent output
            try:
                triggered = self._retriever.check_triggers(trace)
                if triggered:
                    print(f"  Event-driven triggers matched: {[s.id for s in triggered]}")
                    # Re-run with event-driven skills included
                    all_skills = task_skills + [s for s in triggered if s.id not in {sk.id for sk in task_skills}]
                    try:
                        trace = self._agent.run_task(
                            task_description=iter_task,
                            skills=all_skills,
                            repo_path=repo_path,
                        )
                        full_trace += f"\n--- Iteration {iteration} (with triggers) Trace ---\n{trace}\n"
                    except Exception as e:
                        logger.error("Agent re-run with triggers failed: %s", e)
                    for s in triggered:
                        if s.id not in skills_used:
                            skills_used.append(s.id)
            except Exception as e:
                logger.warning("Trigger check failed: %s", e)

            # ─── Step 4: Evaluate the result ─────────────────────────────
            print(f"  [4] Evaluating iteration {iteration}...")
            eval_result = self._scorer.evaluate(task_description, repo_path)
            current_score = eval_result.score
            print(f"  Result: {eval_result.tasks_passed}/{eval_result.tasks_total} = {current_score:.0f}%")
            self._emit(
                progress,
                {
                    "type": "eval_result",
                    "iteration": iteration,
                    "phase": "iteration",
                    "score": current_score,
                    "passed": eval_result.passed,
                    "tasks_passed": eval_result.tasks_passed,
                    "tasks_total": eval_result.tasks_total,
                },
            )

            # ─── Step 5: If passed, we're done ───────────────────────────
            if eval_result.passed:
                print(f"  ✅ PASSED at iteration {iteration}!")
                # Learn-on-success safety net: if this run passed without ever
                # exercising the failure-driven extract/evolve path, still
                # capture the winning approach as a reusable skill. A clean
                # one-shot success otherwise teaches the bank nothing — this is
                # what lets a solved task help the NEXT task (the cross-task
                # transfer the loop exists to demonstrate).
                if not skills_created and not skills_evolved:
                    created_id = self._learn_from_success(
                        task_description,
                        trace,
                        eval_result,
                    )
                    if created_id:
                        skills_created.append(created_id)
                        if created_id not in skills_used:
                            skills_used.append(created_id)
                        self._emit(
                            progress,
                            {
                                "type": "skill_created",
                                "skill_id": created_id,
                                "iteration": iteration,
                                "source": "learn_on_success",
                            },
                        )
                break

            # ─── Step 6: Failed — learn from it ──────────────────────────
            print("  [5] Learning from failure...")

            # If we already created a skill earlier in THIS run and still
            # failed, the skill is incomplete — evolve it on the new evidence
            # rather than extracting a near-duplicate sibling.
            if last_created_skill_id is not None:
                parent = None
                try:
                    parent = self._bank.get(last_created_skill_id)
                except Exception as e:
                    logger.warning("Lookup of %s failed: %s", last_created_skill_id, e)

                if parent is not None:
                    try:
                        evolved = self._evolver.evolve(
                            skill=parent,
                            new_trace=trace,
                            new_eval=eval_result,
                        )
                        # Governance: evolved versions get the policy status
                        # (DRAFT pending review, or ACTIVE when auto-approve is on).
                        evolved = evolved.model_copy(update={"status": governance.status_for_evolved_skill()})
                        self._bank.update(last_created_skill_id, evolved)
                        if last_created_skill_id not in skills_evolved:
                            skills_evolved.append(last_created_skill_id)
                        print(f"  Evolved skill: {last_created_skill_id} -> v{evolved.version}")
                        self._emit(
                            progress,
                            {
                                "type": "skill_evolved",
                                "skill_id": last_created_skill_id,
                                "version": evolved.version,
                                "status": evolved.status.value,
                                "iteration": iteration,
                            },
                        )
                        task_skills = [evolved if s.id == last_created_skill_id else s for s in task_skills]
                        if all(s.id != last_created_skill_id for s in task_skills):
                            task_skills.append(evolved)
                    except Exception as e:
                        logger.warning(
                            "Skill evolution failed for %s: %s",
                            last_created_skill_id,
                            e,
                        )
                continue

            # First failure of the run — extract a fresh skill from the trace.
            new_skill: Optional[Skill] = None
            try:
                new_skill = self._extractor.extract(
                    task_description=task_description,
                    trace=trace,
                    eval_result=eval_result,
                )
            except Exception as e:
                logger.warning("Skill extraction failed: %s", e)

            if not new_skill:
                continue

            # If the extracted skill already exists in the bank, evolve it.
            existing = None
            try:
                existing = self._bank.get(new_skill.id)
            except Exception:
                pass

            if existing:
                print(f"  Evolving existing skill: {new_skill.id}")
                try:
                    evolved = self._evolver.evolve(
                        skill=existing,
                        new_trace=trace,
                        new_eval=eval_result,
                    )
                    evolved = evolved.model_copy(update={"status": governance.status_for_evolved_skill()})
                    self._bank.update(new_skill.id, evolved)
                    if new_skill.id not in skills_evolved:
                        skills_evolved.append(new_skill.id)
                    last_created_skill_id = new_skill.id
                    self._emit(
                        progress,
                        {
                            "type": "skill_evolved",
                            "skill_id": new_skill.id,
                            "version": evolved.version,
                            "status": evolved.status.value,
                            "iteration": iteration,
                        },
                    )
                    task_skills = [evolved if s.id == new_skill.id else s for s in task_skills]
                except Exception as e:
                    logger.warning("Skill evolution failed for %s: %s", new_skill.id, e)
            else:
                # Brand-new skill — add it and re-retrieve for the next pass.
                try:
                    new_skill = new_skill.model_copy(update={"status": governance.status_for_new_skill()})
                    skill_id = self._bank.add(new_skill)
                    skills_created.append(skill_id)
                    last_created_skill_id = skill_id
                    print(f"  Extracted new skill: {skill_id}")
                    self._emit(
                        progress,
                        {
                            "type": "skill_created",
                            "skill_id": skill_id,
                            "iteration": iteration,
                            "source": "extraction",
                        },
                    )
                    task_skills = self._retriever.retrieve_for_task(task_description)
                    for s in task_skills:
                        if s.id not in skills_used:
                            skills_used.append(s.id)
                except Exception as e:
                    logger.warning("Failed to store new skill: %s", e)

        # ─── Build final result ──────────────────────────────────────────
        score_after = current_score
        logger.info(
            "TaskRunner complete: score %.1f -> %.1f, iterations=%d",
            score_before,
            score_after,
            iterations,
        )

        print(f"\n{'=' * 60}")
        print(f"RESULT: {score_before:.0f}% → {score_after:.0f}% (Δ{score_after - score_before:+.0f})")
        print(f"Skills used: {skills_used}")
        print(f"Skills created: {skills_created}")
        print(f"Skills evolved: {skills_evolved}")
        print(f"Iterations: {iterations}")
        print(f"{'=' * 60}\n")

        self._emit(
            progress,
            {
                "type": "run_complete",
                "score_before": score_before,
                "score_after": score_after,
                "skills_used": skills_used,
                "skills_created": skills_created,
                "skills_evolved": skills_evolved,
                "iterations": iterations,
            },
        )

        result = TaskResult(
            task_description=task_description,
            score_before=score_before,
            score_after=score_after,
            skills_used=skills_used,
            skills_created=skills_created,
            skills_evolved=skills_evolved,
            iterations=iterations,
            trace=full_trace[:5000],
        )

        # Persist the run so CLI-triggered runs feed dashboard stats too.
        # Failure to persist must not lose the computed result — log and continue.
        try:
            run_data = result.model_dump()
            run_data["timestamp"] = __import__("datetime").datetime.utcnow().isoformat()
            run_data["status"] = "completed"
            self._bank.save_run(run_data)
        except Exception as e:
            logger.warning("Failed to persist run to runs collection: %s", e)

        return result
