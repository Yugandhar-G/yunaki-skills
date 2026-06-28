"""Harvest coding tasks from a repo's git history.

A candidate is any recent commit that changes test files. For each, we build a
TaskSpec (parent tree + that commit's test files) and KEEP it only if the tests
genuinely FAIL on the parent tree — guaranteeing the control arm has real
headroom and that a solution exists (the commit itself). Tasks that already pass
at the base, or collect no tests, are discarded.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile

from yunaki_skills.bench.task_spec import TaskCorpus, TaskSpec, materialize
from yunaki_skills.eval_scorer import EvalScorer

logger = logging.getLogger(__name__)

_DEFAULT_TEST_COMMAND = ["python3", "-m", "pytest", "-q"]
_TEST_PATH_RE = re.compile(r"(^|/)(tests?/|test_[^/]*\.py$|[^/]*_test\.py$)")


def _git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True).stdout.strip()


def _is_test_path(path: str) -> bool:
    return bool(_TEST_PATH_RE.search(path)) and path.endswith(".py")


def _candidate_commits(repo: str, since: str | None, scan_limit: int) -> list[str]:
    """Recent commits (newest first) that touch at least one test file."""
    rev = f"{since}..HEAD" if since else "HEAD"
    out = _git(repo, "log", rev, f"-n{scan_limit}", "--format=%H")
    return [line for line in out.splitlines() if line.strip()]


def _test_files_added_or_modified(repo: str, commit: str) -> list[str]:
    """Test files added/modified (not deleted) by `commit`."""
    out = _git(repo, "show", "--name-status", "--format=", commit)
    paths: list[str] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status, path = parts[0], parts[-1]
        if status.startswith("D"):  # deleted — can't overlay from this commit
            continue
        if _is_test_path(path):
            paths.append(path)
    return paths


def _has_parent(repo: str, commit: str) -> bool:
    try:
        _git(repo, "rev-parse", f"{commit}^")
        return True
    except subprocess.CalledProcessError:
        return False  # root commit


def _prompt_for(repo: str, commit: str) -> str:
    subject = _git(repo, "log", "-1", "--format=%s", commit)
    return (
        "Some tests in this repository are failing. Edit the source code so all "
        f"tests pass. Do not modify the test files. Context: {subject}"
    )


def _fails_at_base(spec: TaskSpec, scorer: EvalScorer) -> bool:
    """True if the task's tests fail on the base tree (real headroom)."""
    workspace = tempfile.mkdtemp(prefix="yunaki_harvest_")
    try:
        materialize(spec, workspace)
        ev = scorer.evaluate(spec.prompt, test_command=spec.test_command, workspace=workspace)
        # Need real, collectible tests AND at least one failing — otherwise no task.
        return ev.tasks_total > 0 and ev.tasks_passed < ev.tasks_total
    except Exception as e:
        logger.warning("Harvest verification failed for %s: %s", spec.id, e)
        return False
    finally:
        import shutil

        shutil.rmtree(workspace, ignore_errors=True)


def harvest(
    repo_path: str,
    test_command: list[str] | None = None,
    max_tasks: int = 20,
    since: str | None = None,
    scan_limit: int = 200,
    verify: bool = True,
) -> TaskCorpus:
    """Build a task corpus from `repo_path`'s git history.

    Scans up to `scan_limit` recent commits, keeping verified fail-at-base tasks
    until `max_tasks` is reached. `verify=False` skips the (slow) per-task test
    run — only use it when you trust the construction.
    """
    repo_path = os.path.abspath(repo_path)
    test_command = test_command or _DEFAULT_TEST_COMMAND
    scorer = EvalScorer()

    tasks: list[TaskSpec] = []
    for commit in _candidate_commits(repo_path, since, scan_limit):
        if len(tasks) >= max_tasks:
            break
        if not _has_parent(repo_path, commit):
            continue
        test_paths = _test_files_added_or_modified(repo_path, commit)
        if not test_paths:
            continue
        spec = TaskSpec(
            id=f"task_{commit[:10]}",
            repo_path=repo_path,
            base_commit=f"{commit}^",
            fix_commit=commit,
            test_paths=test_paths,
            test_command=test_command,
            prompt=_prompt_for(repo_path, commit),
        )
        if verify and not _fails_at_base(spec, scorer):
            logger.info("Skipping %s — tests do not fail at base (no headroom)", spec.id)
            continue
        tasks.append(spec)
        logger.info("Harvested %s (%d test file(s))", spec.id, len(test_paths))

    return TaskCorpus(repo_path=repo_path, test_command=test_command, tasks=tasks)
