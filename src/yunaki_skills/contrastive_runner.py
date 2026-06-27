"""Contrastive extraction: run N rollouts, learn from the pass/fail difference.

A single failed trace tells you something broke; a *passing* trace next to a
*failing* one on the same task tells you exactly what mattered. This runner fans
out N independent rollouts from the same pre-agent workspace snapshot, scores
each, then asks the extractor to distill the skill from the best-passing vs
worst-failing pair.

Disabled by default (YUNAKI_CONTRASTIVE_ROLLOUTS=1): the loop falls back to
single-trace extraction, so there is zero added cost unless explicitly opted in.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from typing import Optional

from yunaki_skills.interfaces import AgentClient, EvalResult, Skill

logger = logging.getLogger(__name__)


class ContrastiveRunner:
    """Fans out rollouts and extracts a skill from a passing/failing contrast."""

    def __init__(self, agent: AgentClient, scorer, extractor):
        self._agent = agent
        self._scorer = scorer
        self._extractor = extractor

    def run(
        self,
        task_description: str,
        snapshot_dir: str,
        skills: list[Skill],
        test_command: Optional[list[str]],
        n: int,
    ) -> Optional[Skill]:
        """Run ``n`` rollouts and return a contrastively-extracted skill, or None.

        Returns None (caller should fall back to single-trace extraction) when
        n < 2 or the rollouts don't yield both a passing and a failing result.
        """
        if n < 2:
            return None

        rollouts: list[tuple[str, EvalResult]] = []
        for i in range(n):
            workspace = tempfile.mkdtemp(prefix="yunaki_rollout_")
            shutil.rmtree(workspace, ignore_errors=True)
            shutil.copytree(snapshot_dir, workspace)
            try:
                trace = self._agent.run_task(
                    task_description=task_description, skills=skills, repo_path=workspace
                )
                ev = self._scorer.evaluate(
                    task_description, test_command=test_command, workspace=workspace
                )
                rollouts.append((trace, ev))
            except Exception as e:
                logger.warning("Contrastive rollout %d failed: %s", i, e)
            finally:
                shutil.rmtree(workspace, ignore_errors=True)

        passes = [(t, e) for t, e in rollouts if e.passed]
        fails = [(t, e) for t, e in rollouts if not e.passed]
        if not passes or not fails:
            logger.info("Contrastive extraction skipped: need both a pass and a fail")
            return None

        best_pass = max(passes, key=lambda x: x[1].score)
        worst_fail = min(fails, key=lambda x: x[1].score)
        logger.info(
            "Contrastive pair: pass=%.0f vs fail=%.0f", best_pass[1].score, worst_fail[1].score
        )
        return self._extractor.extract_contrastive(
            task_description,
            pass_trace=best_pass[0],
            fail_trace=worst_fail[0],
            pass_eval=best_pass[1],
            fail_eval=worst_fail[1],
        )


def rollouts_from_env(explicit: Optional[int] = None) -> int:
    """Resolve the rollout count: explicit arg, else env, else 1."""
    if explicit is not None:
        return max(1, explicit)
    raw = os.environ.get("YUNAKI_CONTRASTIVE_ROLLOUTS", "1")
    try:
        return max(1, int(raw))
    except ValueError:
        return 1
