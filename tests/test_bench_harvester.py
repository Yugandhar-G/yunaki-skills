"""Tests for the git task harvester (real git, real pytest, hermetic tmp repo)."""

from __future__ import annotations

import subprocess
import sys

from yunaki_skills.bench.harvester import harvest
from yunaki_skills.bench.task_spec import TaskCorpus, materialize

# Use the running interpreter so the materialized repos' tests run under the
# same env that has pytest installed.
_CMD = [sys.executable, "-m", "pytest", "-q"]


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _make_repo(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")

    # commit A: a stub that returns the wrong answer (no test yet)
    (repo / "app.py").write_text("def mul(a, b):\n    return 0\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "A: stub mul")

    # commit B: the fix + a new test -> harvestable (fails on A, passes on B)
    (repo / "app.py").write_text("def mul(a, b):\n    return a * b\n")
    (repo / "test_app.py").write_text("from app import mul\n\n\ndef test_mul():\n    assert mul(2, 3) == 6\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "B: fix mul and add test")

    # commit C: a test that already passes -> no headroom -> must be skipped
    (repo / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "C: add already-passing test")
    return str(repo)


def test_harvest_keeps_fail_at_base_skips_passing(tmp_path):
    corpus = harvest(_make_repo(tmp_path), test_command=_CMD, max_tasks=10)
    # Only commit B yields a task: its test fails against the stub at base.
    # Commit C's test passes at base (no headroom) and is dropped.
    assert len(corpus.tasks) == 1
    task = corpus.tasks[0]
    assert task.test_paths == ["test_app.py"]
    assert task.base_commit.endswith("^")


def test_materialize_gives_base_source_plus_fix_tests(tmp_path):
    corpus = harvest(_make_repo(tmp_path), test_command=_CMD, max_tasks=10)
    dest = tmp_path / "ws"
    materialize(corpus.tasks[0], str(dest))
    # Source is the pre-fix STUB; the requirement (test) is overlaid from the fix.
    assert "return 0" in (dest / "app.py").read_text()
    assert (dest / "test_app.py").exists()


def test_corpus_json_roundtrip(tmp_path):
    corpus = harvest(_make_repo(tmp_path), test_command=_CMD, max_tasks=10)
    path = tmp_path / "corpus.json"
    corpus.save(str(path))
    loaded = TaskCorpus.load(str(path))
    assert [t.id for t in loaded.tasks] == [t.id for t in corpus.tasks]
    assert loaded.test_command == _CMD


def test_harvest_empty_when_no_test_commits(tmp_path):
    repo = tmp_path / "r2"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "app.py").write_text("x = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "no tests here")
    corpus = harvest(str(repo), test_command=_CMD, max_tasks=10)
    assert corpus.tasks == []
