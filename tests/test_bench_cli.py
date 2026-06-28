"""Tests for the `yunaki bench` CLI group (harvest + run), with the heavy lifting mocked."""

from __future__ import annotations

from yunaki_skills import cli
from yunaki_skills.bench import harvester as harvester_mod
from yunaki_skills.bench import runner as runner_mod
from yunaki_skills.bench.runner import BenchReport
from yunaki_skills.bench.task_spec import TaskCorpus, TaskSpec


def _spec(i):
    return TaskSpec(
        id=f"t{i}",
        repo_path="/x",
        base_commit="abc^",
        fix_commit="abc",
        test_paths=["test_x.py"],
        test_command=["pytest"],
        prompt=f"make tests pass {i}",
    )


def test_bench_harvest_saves_corpus(monkeypatch, tmp_path, capsys):
    corpus = TaskCorpus(repo_path="/x", test_command=["pytest"], tasks=[_spec(0), _spec(1)])
    monkeypatch.setattr(harvester_mod, "harvest", lambda *a, **k: corpus)

    out = tmp_path / "corpus.json"
    rc = cli.main(["bench", "harvest", "/some/repo", "--out", str(out), "--max-tasks", "5"])

    assert rc == 0
    assert out.exists()
    loaded = TaskCorpus.load(str(out))
    assert len(loaded.tasks) == 2
    assert "Harvested 2" in capsys.readouterr().out


def test_bench_run_reports_skill_delta(monkeypatch, tmp_path, capsys):
    corpus_path = tmp_path / "corpus.json"
    TaskCorpus(repo_path="/x", test_command=["pytest"], tasks=[_spec(0), _spec(1), _spec(2)]).save(str(corpus_path))

    report = BenchReport(
        org_id="bench_test",
        n_train=2,
        n_eval=1,
        bank_size_after_train=3,
        mean_held_out_skill_delta=12.5,
        control_pass_rate=0.0,
        skilled_pass_rate=1.0,
        outcomes=[],
        note="x",
    )
    monkeypatch.setattr(runner_mod, "run_benchmark", lambda *a, **k: report)

    out = tmp_path / "report.json"
    rc = cli.main(["bench", "run", "--corpus", str(corpus_path), "--out", str(out)])

    assert rc == 0
    assert out.exists()
    printed = capsys.readouterr().out
    assert "skill_delta: +12.5%" in printed
    assert "skills HELPED" in printed


def test_bench_run_handles_negative_delta(monkeypatch, tmp_path, capsys):
    corpus_path = tmp_path / "corpus.json"
    TaskCorpus(repo_path="/x", test_command=["pytest"], tasks=[_spec(0)]).save(str(corpus_path))
    report = BenchReport(
        org_id="b",
        n_train=0,
        n_eval=1,
        bank_size_after_train=0,
        mean_held_out_skill_delta=-5.0,
        control_pass_rate=1.0,
        skilled_pass_rate=0.0,
        outcomes=[],
        note="x",
    )
    monkeypatch.setattr(runner_mod, "run_benchmark", lambda *a, **k: report)

    cli.main(["bench", "run", "--corpus", str(corpus_path), "--out", str(tmp_path / "r.json")])
    # Honest: a negative transfer is reported as "skills HURT", not hidden.
    assert "skills HURT" in capsys.readouterr().out


def test_bench_run_empty_corpus_errors(monkeypatch, tmp_path, capsys):
    corpus_path = tmp_path / "empty.json"
    TaskCorpus(repo_path="/x", test_command=["pytest"], tasks=[]).save(str(corpus_path))
    rc = cli.main(["bench", "run", "--corpus", str(corpus_path)])
    assert rc == 1
    assert "no tasks" in capsys.readouterr().err
