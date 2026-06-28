"""
EvalScorer — test-based evaluation.

Implements the EvalScorer interface from yunaki_skills.interfaces.

Universal: not tied to a fixed repo. The caller supplies inline code (a string)
and/or a prepared workspace directory, plus a test command. The scorer
materializes the code into a workspace, runs a basic syntax check, runs the test
command, and counts pass/fail.
"""

import logging
import os
import re
import shutil
import subprocess
import tempfile
from typing import Optional

from yunaki_skills.interfaces import EvalResult
from yunaki_skills.interfaces import EvalScorer as IEvalScorer

logger = logging.getLogger(__name__)

# Score (%) at or above which a task counts as passed. Configurable so a demo
# can require full completion (100) instead of the default partial-credit bar.
_DEFAULT_PASS_THRESHOLD = 80.0

# Default test command when the caller does not supply one.
_DEFAULT_TEST_COMMAND = ["python3", "-m", "pytest", "-v", "--tb=short"]

# Filename used when materializing a single inline code snapshot.
_SNAPSHOT_FILENAME = "solution.py"

_SYNTAX_TIMEOUT_S = 30
_TEST_TIMEOUT_S = 120


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
    """Scores agent output by running a test command against inline code."""

    def evaluate(
        self,
        task_description: str,
        code_snapshot: str = "",
        test_command: Optional[list[str]] = None,
        workspace: Optional[str] = None,
    ) -> EvalResult:
        """Run a syntax check + test command against the code/workspace.

        Resolution order for where to run:
          1. `workspace` — an existing directory (used as-is, not cleaned up).
          2. otherwise a fresh temp dir into which `code_snapshot` is written.
        """
        workdir, cleanup = self._resolve_workspace(code_snapshot, workspace)
        command = test_command or _DEFAULT_TEST_COMMAND
        try:
            # Step 1: Basic syntax check on the workspace's Python files.
            if not self._syntax_check(workdir):
                logger.warning("Syntax check failed in %s", workdir)
                return EvalResult(
                    passed=False,
                    score=0.0,
                    details="Syntax check failed — code has errors",
                    test_output="",
                    tasks_passed=0,
                    tasks_total=0,
                )

            # Step 2: Run the test command.
            test_output = self._run_tests(workdir, command)
            logger.info("test output (first 500 chars):\n%s", test_output[:500])

            # Step 3: Parse results.
            passed, total = self._parse_pytest_output(test_output)
            if total == 0:
                logger.warning("No tests found in test output")
                return EvalResult(
                    passed=False,
                    score=0.0,
                    details="No tests found",
                    test_output=test_output[:2000],
                    tasks_passed=0,
                    tasks_total=0,
                )

            score = (passed / total) * 100
            result = EvalResult(
                passed=(score >= _pass_threshold()),
                score=score,
                details=f"{passed}/{total} tests passed ({score:.0f}%)",
                test_output=test_output[:2000],
                tasks_passed=passed,
                tasks_total=total,
            )
            logger.info("EvalResult: score=%.1f passed=%s", score, result.passed)
            return result
        finally:
            cleanup()

    # ── workspace materialization ────────────────────────────────────────

    def _resolve_workspace(self, code_snapshot: str, workspace: Optional[str]):
        """Return (workdir, cleanup_callable).

        A caller-provided workspace is used as-is and never deleted. An inline
        snapshot is written into a temp dir that is removed afterward.
        """
        if workspace:
            return workspace, lambda: None

        tmp = tempfile.mkdtemp(prefix="yunaki_eval_")
        if code_snapshot:
            with open(os.path.join(tmp, _SNAPSHOT_FILENAME), "w") as f:
                f.write(code_snapshot)

        def _cleanup() -> None:
            shutil.rmtree(tmp, ignore_errors=True)

        return tmp, _cleanup

    # ── subprocess steps ─────────────────────────────────────────────────

    def _syntax_check(self, workdir: str) -> bool:
        """Compile every Python file in the workspace to catch syntax errors.

        Generic across projects (no `import app` assumption). An empty/no-Python
        workspace compiles cleanly (returncode 0).
        """
        try:
            result = subprocess.run(
                ["python3", "-m", "compileall", "-q", workdir],
                capture_output=True,
                text=True,
                cwd=workdir,
                timeout=_SYNTAX_TIMEOUT_S,
                env={**os.environ, "PYTHONPATH": workdir},
            )
            if result.returncode != 0:
                logger.warning("Syntax check stderr: %s", result.stderr)
            return result.returncode == 0
        except Exception as e:
            logger.error("Syntax check exception: %s", e)
            return False

    def _run_tests(self, workdir: str, command: list[str]) -> str:
        """Run the test command in the workspace; return combined stdout+stderr."""
        # Put both the workspace root and its src/ dir on PYTHONPATH so flat-layout
        # repos (package at root) and src-layout repos (package under src/) both
        # import correctly, while preserving any inherited PYTHONPATH.
        pythonpath = os.pathsep.join(
            p for p in [workdir, os.path.join(workdir, "src"), os.environ.get("PYTHONPATH", "")] if p
        )
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                cwd=workdir,
                timeout=_TEST_TIMEOUT_S,
                env={**os.environ, "PYTHONPATH": pythonpath},
            )
            return result.stdout + "\n" + result.stderr
        except subprocess.TimeoutExpired:
            logger.error("test command timed out")
            return f"ERROR: test command timed out after {_TEST_TIMEOUT_S}s"
        except Exception as e:
            logger.error("test command exception: %s", e)
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
