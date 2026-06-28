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
from dataclasses import dataclass
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

# Substrings in pytest/subprocess output that mean the agent code never ran —
# the suite could not be collected/imported, so 0 executed is NOT a real failure.
_NOT_RUNNABLE_MARKERS = (
    "ModuleNotFoundError",
    "ImportError",
    "errors during collection",
    "error during collection",
    "ERROR collecting",
    "INTERNALERROR",
    "no tests ran",
    "timed out",
)


@dataclass(frozen=True)
class _ParseResult:
    """Outcome of parsing a pytest run.

    `runnable` is False when the test command could not execute agent code
    (import/collection error, no tests ran, 0 executed). `reason` carries a
    short human-readable cause to surface in EvalResult.details.
    """

    passed: int
    total: int
    runnable: bool
    reason: str = ""


def _pass_threshold() -> float:
    raw = os.environ.get("YUNAKI_PASS_THRESHOLD", "")
    if not raw:
        return _DEFAULT_PASS_THRESHOLD
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid YUNAKI_PASS_THRESHOLD=%r — using default", raw)
        return _DEFAULT_PASS_THRESHOLD


def _detect_not_runnable_reason(output: str) -> str:
    """Return a short cause string if the output signals the suite never ran.

    Empty string means no not-runnable marker was found. When a
    ModuleNotFoundError/ImportError names a module, that name is included so the
    caller sees e.g. "ModuleNotFoundError: email_validator".
    """
    for marker in _NOT_RUNNABLE_MARKERS:
        if marker in output:
            named = _named_missing_module(output)
            if named and marker in ("ModuleNotFoundError", "ImportError"):
                return f"{marker}: {named}"
            return marker
    return ""


def _named_missing_module(output: str) -> str:
    """Extract the module name from a ModuleNotFoundError, if present."""
    match = re.search(r"ModuleNotFoundError: No module named ['\"]([^'\"]+)['\"]", output)
    return match.group(1) if match else ""


def _parse_summary_counts(output: str) -> Optional[tuple[int, int, int]]:
    """Parse the pytest summary line into (passed, failed, errors).

    Handles `-q` and `-v` alike since both emit the same summary, e.g.:
      "7 passed, 2 failed, 1 error in 1.0s"
      "4 passed in 0.10s"
      "no tests ran in 0.01s"  -> (0, 0, 0)

    Returns None when no summary token is present at all (so the caller can fall
    back to verbose line counting). Returns (0, 0, 0) for an explicit empty run.
    """
    if "no tests ran" in output:
        return (0, 0, 0)

    passed_m = re.search(r"(\d+)\s+passed", output)
    failed_m = re.search(r"(\d+)\s+failed", output)
    error_m = re.search(r"(\d+)\s+error", output)  # matches "error" and "errors"

    if not (passed_m or failed_m or error_m):
        return None

    passed = int(passed_m.group(1)) if passed_m else 0
    failed = int(failed_m.group(1)) if failed_m else 0
    errors = int(error_m.group(1)) if error_m else 0
    return (passed, failed, errors)


def _parse_verbose_lines(output: str) -> tuple[int, int]:
    """Count individual PASSED/FAILED lines in verbose pytest output."""
    passed = 0
    total = 0
    for line in output.split("\n"):
        if " PASSED" in line:
            passed += 1
            total += 1
        elif " FAILED" in line:
            total += 1
    return passed, total


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
                    details="NOT RUNNABLE: SyntaxError — code did not compile",
                    test_output="",
                    tasks_passed=0,
                    tasks_total=0,
                    runnable=False,
                )

            # Step 2: Run the test command.
            test_output = self._run_tests(workdir, command)
            logger.info("test output (first 500 chars):\n%s", test_output[:500])

            # Step 3: Parse results.
            parsed = self._parse_pytest_output(test_output)

            # NOT RUNNABLE: the agent code never executed (import/collection
            # error, no tests ran, 0 executed). This is explicitly NOT a silent
            # score-0 failure — the caller must be able to tell "code didn't run"
            # apart from "ran but failed" (e.g. to exclude it from A/B means).
            if not parsed.runnable:
                detail = f"NOT RUNNABLE: {parsed.reason}" if parsed.reason else "NOT RUNNABLE: no tests executed"
                logger.warning("%s", detail)
                return EvalResult(
                    passed=False,
                    score=0.0,
                    details=detail,
                    test_output=test_output[:2000],
                    tasks_passed=0,
                    tasks_total=0,
                    runnable=False,
                )

            score = (parsed.passed / parsed.total) * 100
            result = EvalResult(
                passed=(score >= _pass_threshold()),
                score=score,
                details=f"{parsed.passed}/{parsed.total} tests passed ({score:.0f}%)",
                test_output=test_output[:2000],
                tasks_passed=parsed.passed,
                tasks_total=parsed.total,
                runnable=True,
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
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                cwd=workdir,
                timeout=_TEST_TIMEOUT_S,
                env={**os.environ, "PYTHONPATH": workdir},
            )
            return result.stdout + "\n" + result.stderr
        except subprocess.TimeoutExpired:
            logger.error("test command timed out")
            return f"ERROR: test command timed out after {_TEST_TIMEOUT_S}s"
        except Exception as e:
            logger.error("test command exception: %s", e)
            return f"ERROR: {e}"

    def _parse_pytest_output(self, output: str) -> _ParseResult:
        """Parse pytest output for both `-q` and `-v` formats.

        The pytest SUMMARY line ("N passed, M failed, K error[s]") is the source
        of truth — it is emitted identically for `-q` (dots) and `-v` (PASSED
        lines). Verbose PASSED/FAILED line counting is a fallback only when no
        summary line is present.

        Runnable vs not-runnable is distinguished explicitly:
          - import/collection errors, "no tests ran", or 0 executed => NOT
            runnable (the agent code never ran; 0 is not a real failure).
          - any executed test (pass or fail) => runnable.

        Returns a `_ParseResult`.
        """
        not_runnable_reason = _detect_not_runnable_reason(output)

        # Strategy 1 (source of truth): the pytest summary counts.
        summary = _parse_summary_counts(output)
        if summary is not None:
            passed, failed, errors = summary
            executed = passed + failed
            # A pure collection/import error (errors only, nothing executed)
            # means the agent code never ran — NOT a real score-0 failure.
            if executed == 0:
                return _ParseResult(
                    passed=0,
                    total=0,
                    runnable=False,
                    reason=not_runnable_reason or ("collection error" if errors else "no tests collected"),
                )
            return _ParseResult(passed=passed, total=executed + errors, runnable=True)

        # Strategy 2 (fallback): count verbose PASSED/FAILED lines.
        v_passed, v_total = _parse_verbose_lines(output)
        if v_total > 0:
            return _ParseResult(passed=v_passed, total=v_total, runnable=True)

        # Nothing executed — surface WHY, never a silent score-0.
        return _ParseResult(
            passed=0,
            total=0,
            runnable=False,
            reason=not_runnable_reason or "no tests found",
        )
