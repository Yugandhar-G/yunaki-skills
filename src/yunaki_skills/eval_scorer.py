"""
EvalScorer — test-based evaluation.

Implements the EvalScorer interface from yunaki_skills.interfaces.
Strategy: run pytest on the target repo and count pass/fail.
Also performs a basic Python syntax/import check.
"""

import logging
import os
import re
import subprocess

from yunaki_skills.interfaces import EvalResult
from yunaki_skills.interfaces import EvalScorer as IEvalScorer

logger = logging.getLogger(__name__)

# Score (%) at or above which a task counts as passed. Configurable so a demo
# can require full completion (100) instead of the default partial-credit bar.
_DEFAULT_PASS_THRESHOLD = 80.0


def _pass_threshold() -> float:
    raw = os.environ.get("YUNAKI_PASS_THRESHOLD", "")
    if not raw:
        return _DEFAULT_PASS_THRESHOLD
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid YUNAKI_PASS_THRESHOLD=%r — using default", raw)
        return _DEFAULT_PASS_THRESHOLD


class EvalScorer(IEvalScorer):
    """Scores agent output by running pytest against the target repo."""

    def evaluate(self, task_description: str, repo_path: str) -> EvalResult:
        """Run tests + syntax check against the target repo. Return score."""
        # Step 1: Basic syntax/import check
        syntax_ok = self._syntax_check(repo_path)
        if not syntax_ok:
            logger.warning("Syntax check failed for %s", repo_path)
            return EvalResult(
                passed=False,
                score=0.0,
                details="Syntax/import check failed — app.py has errors",
                test_output="",
                tasks_passed=0,
                tasks_total=0,
            )

        # Step 2: Run pytest
        test_output = self._run_pytest(repo_path)
        logger.info("pytest output (first 500 chars):\n%s", test_output[:500])

        # Step 3: Parse results
        passed, total = self._parse_pytest_output(test_output)

        if total == 0:
            logger.warning("No tests found in pytest output")
            return EvalResult(
                passed=False,
                score=0.0,
                details="No tests found",
                test_output=test_output[:2000],
                tasks_passed=0,
                tasks_total=0,
            )

        score = (passed / total) * 100
        details = f"{passed}/{total} tests passed ({score:.0f}%)"

        result = EvalResult(
            passed=(score >= _pass_threshold()),
            score=score,
            details=details,
            test_output=test_output[:2000],
            tasks_passed=passed,
            tasks_total=total,
        )
        logger.info("EvalResult: score=%.1f passed=%s", score, result.passed)
        return result

    def _syntax_check(self, repo_path: str) -> bool:
        """Run `python -c "import app"` in the repo dir to check syntax."""
        try:
            result = subprocess.run(
                ["python3", "-c", "import app"],
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=30,
                env={**os.environ, "PYTHONPATH": repo_path},
            )
            if result.returncode != 0:
                logger.warning("Syntax check stderr: %s", result.stderr)
            return result.returncode == 0
        except Exception as e:
            logger.error("Syntax check exception: %s", e)
            return False

    def _run_pytest(self, repo_path: str) -> str:
        """Run pytest and return the combined stdout+stderr output."""
        try:
            result = subprocess.run(
                ["python3", "-m", "pytest", "test_app.py", "-v", "--tb=short"],
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=120,
                env={**os.environ, "PYTHONPATH": repo_path},
            )
            output = result.stdout + "\n" + result.stderr
            return output
        except subprocess.TimeoutExpired:
            logger.error("pytest timed out")
            return "ERROR: pytest timed out after 120s"
        except Exception as e:
            logger.error("pytest exception: %s", e)
            return f"ERROR: {e}"

    def _parse_pytest_output(self, output: str) -> tuple[int, int]:
        """Parse pytest output to count passed and total tests.

        Looks for the standard pytest summary line like:
          "7 passed, 2 failed"
          "3 passed, 4 failed"
          "5 passed"

        Also counts PASSED/FAILED lines in verbose output as fallback.

        Returns (passed_count, total_count).
        """
        passed = 0
        total = 0

        # Strategy 1: Count individual PASSED/FAILED lines in verbose output
        for line in output.split("\n"):
            if " PASSED" in line:
                passed += 1
                total += 1
            elif " FAILED" in line:
                total += 1

        # Strategy 2: If no individual lines found, try summary line
        if total == 0:
            match = re.search(r"(\d+)\s+passed", output)
            if match:
                passed = int(match.group(1))
                total = passed
            match_fail = re.search(r"(\d+)\s+failed", output)
            if match_fail:
                total += int(match_fail.group(1))
            match_errors = re.search(r"(\d+)\s+error", output)
            if match_errors:
                total += int(match_errors.group(1))

        return passed, total
