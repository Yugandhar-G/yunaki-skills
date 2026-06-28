"""Task corpus model + workspace materialization for the self-evolution benchmark.

A task is a SWE-bench-style construction harvested from a real fix-commit C:
the workspace is the parent tree (C^) with C's *test* files overlaid, so the
tests express a requirement the old source does not yet satisfy. The agent must
edit the source to make them pass — C itself proves a solution exists.
"""

from __future__ import annotations

import io
import os
import subprocess
import tarfile

from pydantic import BaseModel


class TaskSpec(BaseModel):
    """A single harvested task, materializable on demand from the source repo."""

    id: str
    repo_path: str  # source repo (needs its .git) used to materialize the workspace
    base_commit: str  # C^ — the agent starts from this tree
    fix_commit: str  # C — supplies the test files and proves the task is solvable
    test_paths: list[str]  # test files overlaid from C onto the base tree
    test_command: list[str]
    prompt: str


class TaskCorpus(BaseModel):
    """A JSON-serializable collection of harvested tasks."""

    repo_path: str
    test_command: list[str]
    tasks: list[TaskSpec]

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            f.write(self.model_dump_json(indent=2))

    @classmethod
    def load(cls, path: str) -> TaskCorpus:
        with open(path) as f:
            return cls.model_validate_json(f.read())


def materialize(spec: TaskSpec, dest: str) -> None:
    """Reconstruct the task workspace at `dest`.

    1. Export the base tree (C^) via `git archive`.
    2. Overlay C's versions of the test files, so the requirement is present
       while the source is still at its pre-fix state.
    """
    os.makedirs(dest, exist_ok=True)

    archive = subprocess.run(
        ["git", "-C", spec.repo_path, "archive", "--format=tar", spec.base_commit],
        capture_output=True,
        check=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(dest)  # noqa: S202 - trusted local git archive

    for test_path in spec.test_paths:
        content = subprocess.run(
            ["git", "-C", spec.repo_path, "show", f"{spec.fix_commit}:{test_path}"],
            capture_output=True,
            check=True,
        ).stdout
        out = os.path.join(dest, test_path)
        os.makedirs(os.path.dirname(out) or dest, exist_ok=True)
        with open(out, "wb") as f:
            f.write(content)
