"""Composite reward: deterministic pytest execution × LLM-judge alignment + quality.

pytest stays the gate — ``EvalResult.passed`` and ``.score`` are never modified
here. When ``YUNAKI_COMPOSITE_REWARD`` is enabled, this layers an LLM-as-judge
signal on top of the pass rate:

    composite = w_exec * (exec_fraction * alignment * 100) + w_quality * quality

where
    exec_fraction = pytest score / 100        (did the tests pass)
    alignment     = judge correctness / 100   (does the code address the task)
    quality       = judge weighted overall    (0-100)

The composite is advisory signal only: it enriches extraction/evolution and the
dashboard, but a pytest failure can never become a pass. Defaults match the
paper's emphasis (exec 0.75, quality 0.25) and are env-tunable.
"""

from __future__ import annotations

import logging

from yunaki_skills import config
from yunaki_skills.interfaces import EvalResult

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return config.get("YUNAKI_COMPOSITE_REWARD", "").strip().lower() in {"1", "true", "yes", "on"}


def _w(key: str, default: float) -> float:
    raw = config.get(key, "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid float for %s=%r; using default %s", key, raw, default)
        return default


class RewardComposer:
    """Overlays an LLM-judge composite score onto a pytest EvalResult."""

    def __init__(self, judge=None):
        # Judge is lazily constructed so disabling the feature costs nothing.
        self._judge = judge

    def compose(self, task_description: str, eval_result: EvalResult, target: str) -> EvalResult:
        """Return a new EvalResult enriched with composite fields.

        `target` is a repo dir path or raw code string for the judge. When the
        feature is off or the judge fails, the input is returned unchanged
        (fail-safe: the loop keeps running on the deterministic signal).
        """
        if not _enabled():
            return eval_result

        try:
            judge = self._judge or self._default_judge()
            jr = judge.judge(task_description, target)
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("Composite reward judge failed: %s", e)
            return eval_result

        exec_fraction = max(0.0, min(eval_result.score / 100.0, 1.0))
        alignment = max(0.0, min(jr.scores.correctness / 100.0, 1.0))
        quality = jr.overall

        w_exec = _w("YUNAKI_REWARD_W_EXEC", 0.75)
        w_quality = _w("YUNAKI_REWARD_W_QUALITY", 0.25)
        composite = w_exec * (exec_fraction * alignment * 100.0) + w_quality * quality

        return eval_result.model_copy(
            update={
                "composite_score": round(composite, 1),
                "align_score": round(jr.scores.correctness, 1),
                "quality_score": round(quality, 1),
            }
        )

    @staticmethod
    def _default_judge():
        from yunaki_skills.llm_judge import LLMJudge

        return LLMJudge(persist=False)
