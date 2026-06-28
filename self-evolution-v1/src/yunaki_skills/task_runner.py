"""
TaskRunner — the orchestration loop.

Implements the TaskRunner interface from yunaki_skills.interfaces.

Universal: a task is a description + inline code context (a string), NOT a repo
path. The runner materializes the code into an ephemeral workspace, lets the
agent edit it, and scores it with a test command. Skills self-evolve as they are
used: every iteration records usage on the injected skills.

Orchestrates the full skill evolution loop:
  1. Get baseline score (run eval without skills)
  2. Retrieve relevant skills via SkillRetriever
  3. Run agent with injected skills
  4. Evaluate the result
  5. Record usage on injected skills (increment_usage)
  6. If failed, extract a new skill via SkillExtractor
  7. If existing skill didn't help, evolve it via SkillEvolver
  8. Repeat until passed or max_iterations reached
"""

import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from typing import Callable, Optional

from yunaki_skills import governance, verification
from yunaki_skills.agent_factory import build_agent
from yunaki_skills.contrastive_runner import ContrastiveRunner, rollouts_from_env
from yunaki_skills.eval_scorer import EvalScorer
from yunaki_skills.interfaces import (
    ABResult,
    AgentClient,
    EvalResult,
    Skill,
    TaskResult,
)
from yunaki_skills.interfaces import (
    TaskRunner as ITaskRunner,
)
from yunaki_skills.reward import RewardComposer
from yunaki_skills.skill_bank import SkillBank
from yunaki_skills.skill_evolver import SkillEvolver
from yunaki_skills.skill_extractor import SkillExtractor
from yunaki_skills.skill_retriever import SkillRetriever

logger = logging.getLogger(__name__)

# Filename used when materializing the inline code snapshot into the workspace.
_SNAPSHOT_FILENAME = "solution.py"


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _mean(values: list[float]) -> Optional[float]:
    """Arithmetic mean rounded to 1dp, or None for an empty list.

    None (not 0.0) signals "no measurement" so an arm with zero runnable
    rollouts cannot masquerade as a real 0% score.
    """
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _snapshot_workspace(workspace: str) -> str:
    """Copy the whole workspace tree to a sibling temp dir and return its path.

    Real coding-agent CLIs edit a directory of files, so the pre-agent state is a
    full tree, not a single file. This snapshot is what the control-arm reset
    restores from.
    """
    snapshot = tempfile.mkdtemp(prefix="yunaki_snap_")
    shutil.copytree(workspace, snapshot, dirs_exist_ok=True)
    return snapshot


def _restore_workspace(workspace: str, snapshot: str) -> None:
    """Revert the workspace to the snapshot, discarding any agent edits."""
    shutil.rmtree(workspace, ignore_errors=True)
    shutil.copytree(snapshot, workspace)


class TaskRunner(ITaskRunner):
    """Orchestrates the full skill evolution loop."""

    def __init__(self, org_id: Optional[str] = None, agent: Optional[AgentClient] = None):
        # org_id namespaces the skill bank so each org evolves its own isolated
        # set of skills. None = the personal/global bank.
        self._org_id = org_id
        self._bank = SkillBank(org_id=org_id)
        self._extractor = SkillExtractor()
        self._evolver = SkillEvolver()
        self._retriever = SkillRetriever(bank=self._bank)
        # The coding agent is dependency-injected. When not supplied, the factory
        # detects an installed coding-agent CLI and falls back to the Gemini SDK.
        self._agent = agent if agent is not None else build_agent()
        self._scorer = EvalScorer()
        # Composite-reward overlay (no-op unless YUNAKI_COMPOSITE_REWARD is set).
        self._reward = RewardComposer()
        # Contrastive multi-rollout extraction (no-op unless rollouts > 1).
        self._contrastive = ContrastiveRunner(self._agent, self._scorer, self._extractor)

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

    def _record_usage(self, skills: list[Skill], success: bool) -> None:
        """Record an application of each injected skill (best-effort).

        This is the self-evolution signal: usage/success counts accumulate every
        time a skill is applied, so the bank learns which skills actually work as
        they are reused. Failures here must never break the loop.
        """
        for skill in skills:
            try:
                self._bank.increment_usage(skill.id, success=success)
            except Exception as e:  # pragma: no cover - defensive
                logger.warning("increment_usage failed for %s: %s", skill.id, e)

    def _learn_from_success(self, task_description: str, trace: str, eval_result: EvalResult) -> Optional[str]:
        """Extract and store a reusable skill from a SUCCESSFUL trace.

        Safety net invoked only when a task passed without ever triggering the
        failure-driven extract/evolve path. Captures the winning approach so it
        persists in the bank and surfaces on future related tasks via semantic
        retrieval. Returns the stored skill id, or None if nothing could be
        extracted or it already existed.
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

    def run_ab(
        self,
        task_description: str,
        code_snapshot: str = "",
        test_command: Optional[list[str]] = None,
        n_rollouts: int = 3,
        max_iterations: int = 1,
        progress: Optional[Callable[[dict], None]] = None,
        skills: Optional[list[Skill]] = None,
    ) -> ABResult:
        """Controlled A/B measurement of skill value on a single task.

        Both arms start from the IDENTICAL baseline workspace and run the same
        agent `n_rollouts` times. The control arm injects NO skills; the
        treatment arm injects skills. By default the treatment arm uses the
        task-level skills retrieved for the task; pass `skills=[...]` to inject
        an EXACT set instead (used by `verify` to measure one specific skill so
        the lift is unambiguously attributable to it).

        Reporting `skill_lift = treatment_mean - control_mean` isolates the skill
        effect from raw agent capability — the product thesis.

        Means are over RUNNABLE rollouts only (EvalResult.runnable), so one
        import error does not zero an arm. `max_iterations` is reserved for a
        future multi-pass arm; each rollout currently runs the agent once from
        the shared baseline.
        """
        if n_rollouts < 1:
            raise ValueError(f"n_rollouts must be >= 1, got {n_rollouts}")

        workspace = tempfile.mkdtemp(prefix="yunaki_ab_")
        if code_snapshot:
            with open(os.path.join(workspace, _SNAPSHOT_FILENAME), "w") as f:
                f.write(code_snapshot)
        snapshot_dir = _snapshot_workspace(workspace)

        try:
            return self._run_ab_in_workspace(
                task_description=task_description,
                workspace=workspace,
                snapshot_dir=snapshot_dir,
                test_command=test_command,
                n_rollouts=n_rollouts,
                progress=progress,
                skills_override=skills,
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
            shutil.rmtree(snapshot_dir, ignore_errors=True)

    def verify(
        self,
        skill_id: str,
        test_command: Optional[list[str]] = None,
        n_rollouts: int = 3,
        progress: Optional[Callable[[dict], None]] = None,
    ) -> Optional[verification.GateRecommendation]:
        """Measure a single skill's real effect and record an advisory recommendation.

        Runs the control-arm A/B on the skill's originating task, injecting ONLY
        this skill in the treatment arm so the lift is attributable to it. Records
        the measurement on the skill (advisory) but does NOT change its status or
        score — that requires explicit human acceptance. Returns None if the skill
        is not found.
        """
        skill = self._bank.get(skill_id)
        if skill is None:
            logger.warning("verify: skill %s not found", skill_id)
            return None
        task = skill.provenance.task or skill.when_to_apply
        ab = self.run_ab(
            task_description=task,
            test_command=test_command,
            n_rollouts=n_rollouts,
            progress=progress,
            skills=[skill],
        )
        return verification.record_measurement(self._bank, skill, ab)

    def _run_ab_in_workspace(
        self,
        task_description: str,
        workspace: str,
        snapshot_dir: str,
        test_command: Optional[list[str]],
        n_rollouts: int,
        progress: Optional[Callable[[dict], None]],
        skills_override: Optional[list[Skill]] = None,
    ) -> ABResult:
        logger.info("A/B run: task=%r n_rollouts=%d", task_description, n_rollouts)
        self._emit(
            progress,
            {"type": "ab_start", "task_description": task_description, "n_rollouts": n_rollouts},
        )

        # ── Control arm: agent WITHOUT skills ──────────────────────────────
        print(f"\n[A/B] Control arm: {n_rollouts} rollouts WITHOUT skills...")
        control_scores = self._run_arm(
            task_description=task_description,
            skills=[],
            workspace=workspace,
            snapshot_dir=snapshot_dir,
            test_command=test_command,
            n_rollouts=n_rollouts,
            arm="control",
            progress=progress,
        )

        # ── Skills for the treatment arm: explicit override or retrieved ───
        if skills_override is not None:
            task_skills = skills_override
        else:
            task_skills = self._retriever.retrieve_for_task(task_description)
        skill_ids = [s.id for s in task_skills]
        print(f"[A/B] Treatment arm: {n_rollouts} rollouts WITH skills {skill_ids}...")
        treatment_scores = self._run_arm(
            task_description=task_description,
            skills=task_skills,
            workspace=workspace,
            snapshot_dir=snapshot_dir,
            test_command=test_command,
            n_rollouts=n_rollouts,
            arm="treatment",
            progress=progress,
        )

        control_mean = _mean(control_scores)
        treatment_mean = _mean(treatment_scores)
        skill_lift = (
            round(treatment_mean - control_mean, 1)
            if control_mean is not None and treatment_mean is not None
            else None
        )

        result = ABResult(
            task_description=task_description,
            n_rollouts=n_rollouts,
            control_mean=control_mean,
            treatment_mean=treatment_mean,
            skill_lift=skill_lift,
            control_scores=control_scores,
            treatment_scores=treatment_scores,
            control_runnable_rate=round(len(control_scores) / n_rollouts, 3),
            treatment_runnable_rate=round(len(treatment_scores) / n_rollouts, 3),
            skills_used=skill_ids,
        )
        print(
            f"[A/B] control={control_mean} treatment={treatment_mean} "
            f"lift={skill_lift} (runnable {result.control_runnable_rate}/{result.treatment_runnable_rate})"
        )
        self._emit(progress, {"type": "ab_complete", **result.model_dump()})
        return result

    def _run_arm(
        self,
        task_description: str,
        skills: list[Skill],
        workspace: str,
        snapshot_dir: str,
        test_command: Optional[list[str]],
        n_rollouts: int,
        arm: str,
        progress: Optional[Callable[[dict], None]],
    ) -> list[float]:
        """Run one A/B arm n_rollouts times; return RUNNABLE scores only.

        Each rollout restores the shared baseline so every rollout (and both
        arms) starts from identical state. Agent crashes and not-runnable
        rollouts are excluded from the returned scores (but counted against the
        runnable rate by the caller via n_rollouts).
        """
        scores: list[float] = []
        for i in range(1, n_rollouts + 1):
            _restore_workspace(workspace, snapshot_dir)
            try:
                self._agent.run_task(
                    task_description=task_description,
                    skills=skills,
                    repo_path=workspace,
                )
            except Exception as e:
                logger.warning("[%s] rollout %d agent failed: %s", arm, i, e)
                self._emit(
                    progress,
                    {"type": "ab_rollout", "arm": arm, "rollout": i, "runnable": False, "error": str(e)},
                )
                continue

            eval_result = self._scorer.evaluate(
                task_description, test_command=test_command, workspace=workspace
            )
            if eval_result.runnable:
                scores.append(eval_result.score)
            else:
                logger.info("[%s] rollout %d not runnable: %s", arm, i, eval_result.details)
            self._emit(
                progress,
                {
                    "type": "ab_rollout",
                    "arm": arm,
                    "rollout": i,
                    "runnable": eval_result.runnable,
                    "score": eval_result.score,
                },
            )
        return scores

    def run(
        self,
        task_description: str,
        code_snapshot: str = "",
        test_command: Optional[list[str]] = None,
        max_iterations: int = 3,
        progress: Optional[Callable[[dict], None]] = None,
        rollouts: Optional[int] = None,
        learn: bool = True,
    ) -> TaskResult:
        """Run a task through the full skill evolution loop.

        `code_snapshot` is the inline code context the agent edits (a string).
        `test_command` is the command used to score it (defaults to pytest).
        `progress` is an optional sink invoked with structured event dicts
        (run_start, iteration_start, eval_result, skill_created, skill_evolved,
        run_complete) so callers can stream live progress over WebSocket.
        `learn` controls whether the bank is mutated: when False the run is
        read-only (no extract/evolve/usage), used to measure held-out transfer.
        """
        workspace = tempfile.mkdtemp(prefix="yunaki_run_")
        if code_snapshot:
            with open(os.path.join(workspace, _SNAPSHOT_FILENAME), "w") as f:
                f.write(code_snapshot)

        # Snapshot the pre-agent tree so the control-arm reset can restore it
        # exactly, regardless of how many files the agent creates/edits/deletes.
        snapshot_dir = _snapshot_workspace(workspace)

        try:
            return self._run_in_workspace(
                task_description=task_description,
                workspace=workspace,
                test_command=test_command,
                max_iterations=max_iterations,
                progress=progress,
                snapshot_dir=snapshot_dir,
                rollouts=rollouts_from_env(rollouts),
                learn=learn,
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
            shutil.rmtree(snapshot_dir, ignore_errors=True)

    def run_repo(
        self,
        task_description: str,
        repo_path: str,
        test_command: Optional[list[str]] = None,
        max_iterations: int = 3,
        progress: Optional[Callable[[dict], None]] = None,
        rollouts: Optional[int] = None,
        learn: bool = True,
    ) -> TaskResult:
        """Run the evolution loop against a materialized multi-file repo.

        Unlike `run` (which seeds the workspace from a single inline snapshot),
        this copies an existing repo directory into the ephemeral workspace and
        drives the same loop over it. Used by the benchmark to run real
        harvested tasks. `repo_path` is copied, never mutated in place.
        """
        workspace = tempfile.mkdtemp(prefix="yunaki_repo_")
        shutil.rmtree(workspace, ignore_errors=True)
        shutil.copytree(repo_path, workspace)
        snapshot_dir = _snapshot_workspace(workspace)
        try:
            return self._run_in_workspace(
                task_description=task_description,
                workspace=workspace,
                test_command=test_command,
                max_iterations=max_iterations,
                progress=progress,
                snapshot_dir=snapshot_dir,
                rollouts=rollouts_from_env(rollouts),
                learn=learn,
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
            shutil.rmtree(snapshot_dir, ignore_errors=True)

    def _run_in_workspace(
        self,
        task_description: str,
        workspace: str,
        test_command: Optional[list[str]],
        max_iterations: int,
        progress: Optional[Callable[[dict], None]],
        snapshot_dir: str,
        rollouts: int = 1,
        learn: bool = True,
    ) -> TaskResult:
        logger.info(
            "TaskRunner starting: task=%r  org_id=%s  max_iterations=%d",
            task_description,
            self._org_id,
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
                "org_id": self._org_id,
                "max_iterations": max_iterations,
            },
        )

        def _evaluate() -> EvalResult:
            return self._scorer.evaluate(
                task_description,
                test_command=test_command,
                workspace=workspace,
            )

        # ─── Step 1: Baseline score (no agent at all) ──────────────────────
        print("\n[1] Running baseline evaluation (no agent, no skills)...")
        baseline_eval = _evaluate()
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
        score_control: Optional[float] = None
        current_score = score_before
        full_trace = ""
        iterations = 0
        # Skill created during THIS run — subsequent failures evolve it rather
        # than spawning near-duplicate siblings.
        last_created_skill_id: Optional[str] = None

        # If already passing, short-circuit (skip control arm too — nothing to prove)
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
                score_control=None,
                score_after=score_before,
                skills_used=skills_used,
                skills_created=skills_created,
                skills_evolved=skills_evolved,
                iterations=0,
                trace="Already passing at baseline",
            )

        # ─── Step 2: CONTROL ARM — agent WITHOUT skills ─────────────────
        # This is the number that isolates the skill effect.  Without it,
        # score_after - score_before conflates "the agent can code" with
        # "skills helped."  The control arm measures what the agent does
        # on its own, so skill_delta = score_after - score_control
        # measures ONLY the skill contribution.
        try:
            print("\n[2] Control arm: running agent WITHOUT skills...")
            self._agent.run_task(
                task_description=task_description,
                skills=[],  # <-- NO SKILLS
                repo_path=workspace,
            )
            control_eval = _evaluate()
            score_control = control_eval.score
            print(
                f"  Control (no skills): {control_eval.tasks_passed}/{control_eval.tasks_total} = {score_control:.0f}%"
            )
            self._emit(
                progress,
                {
                    "type": "eval_result",
                    "iteration": 0,
                    "phase": "control_no_skills",
                    "score": score_control,
                    "passed": control_eval.passed,
                    "tasks_passed": control_eval.tasks_passed,
                    "tasks_total": control_eval.tasks_total,
                },
            )
            # Reset workspace to pre-control state for the skilled run, so it
            # starts from the same baseline rather than the control arm's output.
            # Full-tree restore handles agents that edit/create/delete many files.
            _restore_workspace(workspace, snapshot_dir)
        except Exception as e:
            logger.warning("Control arm failed (agent without skills): %s", e)
            print(f"  [WARN] Control arm failed: {e}. skill_delta will be None.")

        # ─── Step 3: Retrieve relevant skills ────────────────────────────
        print("\n[3] Retrieving relevant skills...")
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

            # ─── Step 4: Run agent with injected skills ──────────────────
            iter_task = task_description
            print(f"  [4] Running agent with {len(task_skills)} skills...")
            # Skills actually applied this iteration (for usage accounting).
            applied_skills = list(task_skills)
            try:
                trace = self._agent.run_task(
                    task_description=iter_task,
                    skills=task_skills,
                    repo_path=workspace,
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
                    applied_skills = list(all_skills)
                    try:
                        trace = self._agent.run_task(
                            task_description=iter_task,
                            skills=all_skills,
                            repo_path=workspace,
                        )
                        full_trace += f"\n--- Iteration {iteration} (with triggers) Trace ---\n{trace}\n"
                    except Exception as e:
                        logger.error("Agent re-run with triggers failed: %s", e)
                    for s in triggered:
                        if s.id not in skills_used:
                            skills_used.append(s.id)
            except Exception as e:
                logger.warning("Trigger check failed: %s", e)

            # ─── Step 5: Evaluate the result ─────────────────────────────
            print(f"  [5] Evaluating iteration {iteration}...")
            eval_result = _evaluate()
            # Composite-reward overlay (signal only; never changes passed/score).
            eval_result = self._reward.compose(task_description, eval_result, workspace)
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
                    "composite_score": eval_result.composite_score,
                },
            )

            # ─── Step 6: Record usage on the injected skills ─────────────
            # Self-evolution signal — every applied skill gets a usage tick, and
            # a success tick when this iteration passed. Skipped in read-only
            # (eval) mode so held-out measurement never mutates the bank.
            if learn:
                self._record_usage(applied_skills, success=eval_result.passed)

            # ─── Step 7: If passed, we're done ───────────────────────────
            if eval_result.passed:
                print(f"  ✅ PASSED at iteration {iteration}!")
                # Learn-on-success safety net: if this run passed without ever
                # exercising the failure-driven extract/evolve path, still
                # capture the winning approach as a reusable skill. A clean
                # one-shot success otherwise teaches the bank nothing — this is
                # what lets a solved task help the NEXT task (the cross-task
                # transfer the loop exists to demonstrate).
                if learn and not skills_created and not skills_evolved:
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

            # ─── Step 8: Failed — learn from it ──────────────────────────
            # Read-only (eval) mode: never mutate the bank on the held-out set.
            if not learn:
                continue
            print("  [8] Learning from failure...")

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

            # First failure of the run — extract a fresh skill. With rollouts > 1,
            # try contrastive extraction (best-passing vs worst-failing rollout)
            # first; fall back to single-trace extraction when there's no contrast.
            new_skill: Optional[Skill] = None
            if rollouts > 1:
                try:
                    print(f"  [8] Contrastive extraction over {rollouts} rollouts...")
                    new_skill = self._contrastive.run(
                        task_description=task_description,
                        snapshot_dir=snapshot_dir,
                        skills=task_skills,
                        test_command=test_command,
                        n=rollouts,
                    )
                except Exception as e:
                    logger.warning("Contrastive extraction failed: %s", e)

            if new_skill is None:
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
            score_control=score_control,
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
            run_data["timestamp"] = datetime.now(timezone.utc).isoformat()
            run_data["status"] = "completed"
            self._bank.save_run(run_data)
        except Exception as e:
            logger.warning("Failed to persist run to runs collection: %s", e)

        return result
