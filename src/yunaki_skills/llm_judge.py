"""
LLMJudge — Gemini-powered code-quality evaluation.

Complements the pytest-based EvalScorer (which only measures test pass rate)
by scoring the *quality* of the agent's code across four axes: correctness,
style, security, and performance (0-100 each). Results are persisted to the
MongoDB `evaluations` collection so the dashboard can chart quality alongside
raw pass rate.

This is an alternative or complement to pytest eval — it never runs the code,
it reads it and reasons about it.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from yunaki_skills.config import build_mongo_uri, get

logger = logging.getLogger(__name__)

# Equal weighting by default; tune per product priorities if needed.
_AXIS_WEIGHTS = {
    "correctness": 0.40,
    "style": 0.20,
    "security": 0.25,
    "performance": 0.15,
}
_MAX_CODE_CHARS = 20000


class JudgeScores(BaseModel):
    """Per-axis quality scores, each 0-100."""

    correctness: float = Field(ge=0.0, le=100.0)
    style: float = Field(ge=0.0, le=100.0)
    security: float = Field(ge=0.0, le=100.0)
    performance: float = Field(ge=0.0, le=100.0)


class JudgeResult(BaseModel):
    """Result of an LLM-as-judge code-quality evaluation."""

    task_description: str
    scores: JudgeScores
    overall: float = Field(ge=0.0, le=100.0)
    rationale: str = ""
    model: str = ""
    evaluated_at: str = ""


JUDGE_PROMPT = """You are a senior staff engineer performing a rigorous code review. \
Evaluate the code below against the task it was meant to accomplish. Judge the \
CODE itself — do not run it.

TASK:
{task_description}

CODE UNDER REVIEW:
{code}

Score the code on four axes, each from 0 to 100:
- correctness: does the code actually implement the task correctly and completely?
- style: readability, naming, structure, idiomatic use of the language/framework
- security: input validation, injection risks, secret handling, error leakage
- performance: algorithmic efficiency, I/O patterns, obvious bottlenecks

Respond with ONLY a JSON object, no markdown, with this exact schema:
{{
  "correctness": <0-100>,
  "style": <0-100>,
  "security": <0-100>,
  "performance": <0-100>,
  "rationale": "<2-4 sentences justifying the scores, citing specifics>"
}}"""


def _read_code(target: str) -> str:
    """Return code text from either a directory of .py files or a raw string.

    If `target` is an existing directory, concatenates its non-test .py files.
    Otherwise treats `target` as the code itself.
    """
    if os.path.isdir(target):
        chunks: list[str] = []
        for fname in sorted(os.listdir(target)):
            if fname.endswith(".py") and not fname.startswith("test_"):
                fpath = os.path.join(target, fname)
                try:
                    with open(fpath) as f:
                        chunks.append(f"--- {fname} ---\n{f.read()}")
                except OSError as e:
                    logger.warning("Could not read %s: %s", fpath, e)
        return "\n\n".join(chunks)
    return target


def _weighted_overall(scores: JudgeScores) -> float:
    """Compute the weighted overall quality score from per-axis scores."""
    data = scores.model_dump()
    total = sum(data[axis] * weight for axis, weight in _AXIS_WEIGHTS.items())
    return round(total, 1)


class LLMJudge:
    """Gemini-powered code-quality judge with MongoDB persistence."""

    def __init__(self, persist: bool = True):
        api_key = get("GEMINI_API_KEY")
        self._client = genai.Client(api_key=api_key)
        self._model = "gemini-2.5-flash"
        self._evaluations = None
        if persist:
            self._evaluations = self._connect_evaluations()

    def _connect_evaluations(self):
        """Connect to the `evaluations` collection. Returns None on failure."""
        try:
            from pymongo import MongoClient

            client = MongoClient(build_mongo_uri(), serverSelectionTimeoutMS=3000)
            return client["yunaki"]["evaluations"]
        except Exception as e:
            logger.warning("LLMJudge: MongoDB unavailable (%s) — not persisting", e)
            return None

    def judge(self, task_description: str, target: str) -> JudgeResult:
        """Evaluate code quality. `target` is a repo dir path or raw code string.

        Always returns a JudgeResult. On model/parse failure, returns a
        zero-score result whose rationale explains the failure (fail loud).
        """
        code = _read_code(target)[:_MAX_CODE_CHARS]
        prompt = JUDGE_PROMPT.format(task_description=task_description, code=code)

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    response_mime_type="application/json",
                ),
            )
            text = (response.text or "").strip()
            data = json.loads(text)
            scores = JudgeScores(
                correctness=float(data["correctness"]),
                style=float(data["style"]),
                security=float(data["security"]),
                performance=float(data["performance"]),
            )
            result = JudgeResult(
                task_description=task_description,
                scores=scores,
                overall=_weighted_overall(scores),
                rationale=str(data.get("rationale", "")),
                model=self._model,
                evaluated_at=datetime.now(UTC).isoformat(),
            )
        except Exception as e:
            logger.error("LLMJudge evaluation failed: %s", e)
            zero = JudgeScores(correctness=0, style=0, security=0, performance=0)
            result = JudgeResult(
                task_description=task_description,
                scores=zero,
                overall=0.0,
                rationale=f"LLM judge failed: {e}",
                model=self._model,
                evaluated_at=datetime.now(UTC).isoformat(),
            )

        self._persist(result)
        return result

    def _persist(self, result: JudgeResult) -> None:
        """Store a judge result in the `evaluations` collection if connected."""
        if self._evaluations is None:
            return
        try:
            self._evaluations.insert_one(result.model_dump())
        except Exception as e:
            logger.warning("LLMJudge: failed to persist evaluation: %s", e)
