"""Benchmark runner: train a skill bank on real tasks, then measure cross-task
transfer on a held-out split.

Honesty guarantees:
  - Held-out tasks are never trained on (disjoint split) and run read-only
    (`learn=False`), so the eval set never mutates the bank.
  - The skilled arm only benefits from skills learned on *other* (train) tasks,
    via the loop's own retrieval.
  - The control arm (no skills) gives the baseline; `skill_delta = skilled −
    control` per task. The mean held-out delta — reported with its full
    distribution, negatives included — is the transfer signal.
"""

from __future__ import annotations

import logging
import random
import shutil
import tempfile
import uuid
from typing import Callable, Optional

from pydantic import BaseModel

from yunaki_skills.bench.task_spec import TaskCorpus, TaskSpec, materialize
from yunaki_skills.skill_bank import SkillBank
from yunaki_skills.task_runner import TaskRunner

logger = logging.getLogger(__name__)


class TaskOutcome(BaseModel):
    task_id: str
    score_control: Optional[float]
    score_after: Optional[float]
    skill_delta: Optional[float]
    skills_used: list[str]
    passed_control: bool
    passed_skilled: bool


class BenchReport(BaseModel):
    org_id: str
    n_train: int
    n_eval: int
    bank_size_after_train: int
    mean_held_out_skill_delta: Optional[float]  # None if no comparable eval tasks
    control_pass_rate: float
    skilled_pass_rate: float
    outcomes: list[TaskOutcome]
    note: str

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            f.write(self.model_dump_json(indent=2))


def _split(task_ids: list[str], train_frac: float, seed: int) -> tuple[set[str], list[str]]:
    shuffled = list(task_ids)
    random.Random(seed).shuffle(shuffled)
    n_train = int(round(len(shuffled) * train_frac))
    return set(shuffled[:n_train]), shuffled[n_train:]


def _materialize_tmp(spec: TaskSpec) -> str:
    dest = tempfile.mkdtemp(prefix="yunaki_bench_")
    materialize(spec, dest)
    return dest


def run_benchmark(
    corpus: TaskCorpus,
    train_frac: float = 0.7,
    org_id: Optional[str] = None,
    max_iterations: int = 3,
    eval_max_iterations: int = 1,
    seed: int = 1337,
    agent=None,
    runner_factory: Optional[Callable[[str], TaskRunner]] = None,
) -> BenchReport:
    """Train on the train split, then measure held-out transfer.

    `org_id` namespaces the (isolated, throwaway) bench bank so the user's real
    bank is never touched. `runner_factory(org) -> TaskRunner` is injectable for
    testing; by default it builds `TaskRunner(org_id=org, agent=agent)`.
    """
    org = org_id or f"bench_{uuid.uuid4().hex[:10]}"
    make_runner = runner_factory or (lambda o: TaskRunner(org_id=o, agent=agent))

    train_ids, eval_ids = _split([t.id for t in corpus.tasks], train_frac, seed)
    by_id = {t.id: t for t in corpus.tasks}

    # ── Train: grow the bench bank on the train split (learning ON) ──────────
    for tid in [t.id for t in corpus.tasks if t.id in train_ids]:
        spec = by_id[tid]
        ws = _materialize_tmp(spec)
        try:
            make_runner(org).run_repo(
                spec.prompt, ws, test_command=spec.test_command, max_iterations=max_iterations, learn=True
            )
        except Exception as e:  # one bad task must not sink the run
            logger.warning("Train task %s failed: %s", tid, e)
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    bank_size = len(SkillBank(org_id=org).list_all())

    # ── Eval: held-out, read-only (learn OFF) — pure transfer measurement ────
    outcomes: list[TaskOutcome] = []
    for tid in eval_ids:
        spec = by_id[tid]
        ws = _materialize_tmp(spec)
        try:
            res = make_runner(org).run_repo(
                spec.prompt, ws, test_command=spec.test_command, max_iterations=eval_max_iterations, learn=False
            )
            outcomes.append(
                TaskOutcome(
                    task_id=tid,
                    score_control=res.score_control,
                    score_after=res.score_after,
                    skill_delta=res.skill_delta,
                    skills_used=res.skills_used,
                    passed_control=(res.score_control is not None and res.score_control >= 100.0),
                    passed_skilled=(res.score_after >= 100.0),
                )
            )
        except Exception as e:
            logger.warning("Eval task %s failed: %s", tid, e)
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    deltas = [o.skill_delta for o in outcomes if o.skill_delta is not None]
    mean_delta = round(sum(deltas) / len(deltas), 1) if deltas else None
    n = len(outcomes)
    control_pass = round(sum(o.passed_control for o in outcomes) / n, 3) if n else 0.0
    skilled_pass = round(sum(o.passed_skilled for o in outcomes) / n, 3) if n else 0.0

    return BenchReport(
        org_id=org,
        n_train=len(train_ids),
        n_eval=len(eval_ids),
        bank_size_after_train=bank_size,
        mean_held_out_skill_delta=mean_delta,
        control_pass_rate=control_pass,
        skilled_pass_rate=skilled_pass,
        outcomes=outcomes,
        note=(
            "Single stochastic run per arm; treat small deltas as noise. "
            "mean_held_out_skill_delta is the honest transfer signal (negatives included)."
        ),
    )
