"""Tests for TaskRunner — the full evolution loop with every component mocked."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

import yunaki_skills.task_runner as tr
from tests.conftest import make_task_skill
from yunaki_skills.interfaces import ABResult, SkillStatus


@pytest.fixture
def components():
    """Fresh MagicMock for each loop component."""
    return {
        "bank": MagicMock(name="bank"),
        "extractor": MagicMock(name="extractor"),
        "evolver": MagicMock(name="evolver"),
        "retriever": MagicMock(name="retriever"),
        "agent": MagicMock(name="agent"),
        "scorer": MagicMock(name="scorer"),
    }


def build_runner(monkeypatch, components):
    monkeypatch.delenv("YUNAKI_DEMO_HANDICAP_STAGED_WALKTHROUGH", raising=False)
    monkeypatch.setattr(tr, "SkillBank", lambda *a, **k: components["bank"])
    monkeypatch.setattr(tr, "SkillExtractor", lambda: components["extractor"])
    monkeypatch.setattr(tr, "SkillEvolver", lambda: components["evolver"])
    monkeypatch.setattr(tr, "SkillRetriever", lambda bank=None: components["retriever"])
    monkeypatch.setattr(tr, "EvalScorer", lambda: components["scorer"])
    # Agent is dependency-injected via the constructor seam.
    return tr.TaskRunner(agent=components["agent"])


def test_already_passing_short_circuits(monkeypatch, components, eval_pass):
    components["scorer"].evaluate.return_value = eval_pass
    runner = build_runner(monkeypatch, components)

    result = runner.run("task", max_iterations=3)

    assert result.iterations == 0
    assert result.score_before == 100.0
    assert result.score_after == 100.0
    assert result.skills_created == []
    components["agent"].run_task.assert_not_called()


def test_learn_on_success_when_passes_first_iter(monkeypatch, components, eval_fail, eval_pass):
    # baseline fails, control arm fails, then iteration 1 passes
    components["scorer"].evaluate.side_effect = [eval_fail, eval_fail, eval_pass]
    components["retriever"].retrieve_for_task.return_value = []
    components["retriever"].check_triggers.return_value = []
    components["agent"].run_task.return_value = "winning trace"

    learned = make_task_skill("skill_winning_approach")
    components["extractor"].extract.return_value = learned
    components["bank"].get.return_value = None  # not already in bank
    components["bank"].add.return_value = learned.id

    runner = build_runner(monkeypatch, components)
    result = runner.run("task", max_iterations=3)

    assert result.iterations == 1
    assert "skill_winning_approach" in result.skills_created
    components["bank"].add.assert_called_once()
    components["bank"].save_run.assert_called_once()


def test_extract_new_skill_on_failure_then_pass(monkeypatch, components, eval_fail, eval_pass):
    # baseline fail, control arm fail, iter1 fail -> extract, iter2 pass
    components["scorer"].evaluate.side_effect = [eval_fail, eval_fail, eval_fail, eval_pass]
    components["retriever"].retrieve_for_task.return_value = []
    components["retriever"].check_triggers.return_value = []
    components["agent"].run_task.return_value = "trace"

    new_skill = make_task_skill("skill_new")
    components["extractor"].extract.return_value = new_skill
    components["bank"].get.return_value = None  # not yet in bank
    components["bank"].add.return_value = "skill_new"

    runner = build_runner(monkeypatch, components)
    result = runner.run("task", max_iterations=3)

    assert "skill_new" in result.skills_created
    assert result.iterations == 2
    assert result.score_after == eval_pass.score


def test_evolve_skill_on_repeated_failure(monkeypatch, components, eval_fail):
    # baseline fail, control arm fail, iter1 fail -> extract, iter2 fail -> evolve
    components["scorer"].evaluate.side_effect = [eval_fail, eval_fail, eval_fail, eval_fail]
    components["retriever"].retrieve_for_task.return_value = []
    components["retriever"].check_triggers.return_value = []
    components["agent"].run_task.return_value = "trace"

    new_skill = make_task_skill("skill_new")
    components["extractor"].extract.return_value = new_skill
    # iter1: existing lookup -> None (add path). iter2: parent lookup -> the skill
    components["bank"].get.side_effect = [None, new_skill]
    components["bank"].add.return_value = "skill_new"

    evolved = new_skill.model_copy(update={"version": "0.2", "score": 65.0})
    components["evolver"].evolve.return_value = evolved

    runner = build_runner(monkeypatch, components)
    result = runner.run("task", max_iterations=2)

    assert "skill_new" in result.skills_created
    assert "skill_new" in result.skills_evolved
    components["evolver"].evolve.assert_called_once()
    components["bank"].update.assert_called_once()


def test_event_triggered_skills_rerun_agent(monkeypatch, components, eval_fail, eval_pass):
    # baseline fail, control arm fail, then iteration 1 passes
    components["scorer"].evaluate.side_effect = [eval_fail, eval_fail, eval_pass]
    components["retriever"].retrieve_for_task.return_value = []
    triggered = make_task_skill("skill_event")
    components["retriever"].check_triggers.return_value = [triggered]
    components["agent"].run_task.return_value = "trace with KeyError"
    components["extractor"].extract.return_value = None  # learn-on-success yields nothing
    components["bank"].get.return_value = None

    runner = build_runner(monkeypatch, components)
    result = runner.run("task", max_iterations=3)

    # Control arm runs once (no skills), then the iteration runs, then again
    # with triggered skills: 3 total agent invocations.
    assert components["agent"].run_task.call_count == 3
    assert "skill_event" in result.skills_used


def test_retrieved_skills_recorded_as_used(monkeypatch, components, eval_fail, eval_pass):
    retrieved = make_task_skill("skill_retrieved")
    # baseline fail, control arm fail, then iteration 1 passes
    components["scorer"].evaluate.side_effect = [eval_fail, eval_fail, eval_pass]
    components["retriever"].retrieve_for_task.return_value = [retrieved]
    components["retriever"].check_triggers.return_value = []
    components["agent"].run_task.return_value = "trace"
    components["extractor"].extract.return_value = None
    components["bank"].get.return_value = None

    runner = build_runner(monkeypatch, components)
    result = runner.run("task", max_iterations=3)
    assert "skill_retrieved" in result.skills_used


def test_agent_exception_does_not_crash_loop(monkeypatch, components, eval_fail):
    components["scorer"].evaluate.side_effect = [eval_fail, eval_fail]
    components["retriever"].retrieve_for_task.return_value = []
    components["retriever"].check_triggers.return_value = []
    components["agent"].run_task.side_effect = RuntimeError("model down")
    components["extractor"].extract.return_value = None

    runner = build_runner(monkeypatch, components)
    result = runner.run("task", max_iterations=1)
    # Loop survived the agent error and still produced a result.
    assert result.iterations == 1
    assert result.score_after == eval_fail.score


def test_no_demo_handicap_mechanism_exists():
    """The staged-walkthrough handicap was removed entirely. Guard against it
    ever returning: there must be no mechanism that degrades the agent to
    manufacture an improvement curve."""
    assert not hasattr(tr, "_demo_handicap_clause")


def test_learn_false_is_read_only(monkeypatch, components, eval_fail):
    """Eval mode (learn=False) must never mutate the bank, but still measure
    the control arm + skill_delta for held-out transfer."""
    components["scorer"].evaluate.side_effect = [eval_fail, eval_fail, eval_fail]
    components["retriever"].retrieve_for_task.return_value = [make_task_skill("skill_x")]
    components["retriever"].check_triggers.return_value = []
    components["agent"].run_task.return_value = "trace"

    runner = build_runner(monkeypatch, components)
    result = runner.run("task", max_iterations=1, learn=False)

    # No bank mutation of any kind.
    components["extractor"].extract.assert_not_called()
    components["evolver"].evolve.assert_not_called()
    components["bank"].add.assert_not_called()
    components["bank"].update.assert_not_called()
    components["bank"].increment_usage.assert_not_called()
    # But the honest measurement is still produced.
    assert result.score_control is not None
    assert result.skill_delta is not None


def test_run_repo_runs_in_a_copy(monkeypatch, components, eval_fail, eval_pass, tmp_path):
    """run_repo copies the repo into an ephemeral workspace and drives the loop
    there — never mutating the source repo."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("x = 1\n")
    (repo / "test_app.py").write_text("def test():\n    assert True\n")

    components["scorer"].evaluate.side_effect = [eval_fail, eval_fail, eval_pass]
    components["retriever"].retrieve_for_task.return_value = []
    components["retriever"].check_triggers.return_value = []
    components["extractor"].extract.return_value = None
    components["bank"].get.return_value = None

    seen: dict = {}

    def agent_run(task_description, skills, repo_path):
        seen["repo_path"] = repo_path
        seen["files"] = sorted(os.listdir(repo_path))
        return "trace"

    components["agent"].run_task.side_effect = agent_run

    runner = build_runner(monkeypatch, components)
    result = runner.run_repo("make tests pass", str(repo), test_command=["pytest"], max_iterations=1)

    # Agent ran inside a copy, not the original repo, and saw the full tree.
    assert seen["repo_path"] != str(repo)
    assert "app.py" in seen["files"]
    assert "test_app.py" in seen["files"]
    # Source repo is untouched.
    assert sorted(os.listdir(repo)) == ["app.py", "test_app.py"]
    assert result.score_before == eval_fail.score


def test_injected_agent_is_used_over_default(monkeypatch, components, eval_fail, eval_pass):
    """An agent passed via the DI seam must be used instead of the built default."""
    monkeypatch.setattr(tr, "SkillBank", lambda *a, **k: components["bank"])
    monkeypatch.setattr(tr, "SkillExtractor", lambda: components["extractor"])
    monkeypatch.setattr(tr, "SkillEvolver", lambda: components["evolver"])
    monkeypatch.setattr(tr, "SkillRetriever", lambda bank=None: components["retriever"])
    monkeypatch.setattr(tr, "EvalScorer", lambda: components["scorer"])
    # The default build path must NOT be invoked when an agent is injected.
    monkeypatch.setattr(
        tr, "build_agent", lambda: pytest.fail("build_agent should not be called when agent is injected")
    )

    components["scorer"].evaluate.side_effect = [eval_fail, eval_fail, eval_pass]
    components["retriever"].retrieve_for_task.return_value = []
    components["retriever"].check_triggers.return_value = []
    components["agent"].run_task.return_value = "trace"
    components["extractor"].extract.return_value = None
    components["bank"].get.return_value = None

    runner = tr.TaskRunner(agent=components["agent"])
    runner.run("task", max_iterations=3)

    assert components["agent"].run_task.called


def test_contrastive_extraction_used_when_rollouts_gt_1(monkeypatch, components, eval_fail):
    # baseline fail, control fail, iter1 fail -> contrastive extraction.
    components["scorer"].evaluate.side_effect = [eval_fail, eval_fail, eval_fail]
    components["retriever"].retrieve_for_task.return_value = []
    components["retriever"].check_triggers.return_value = []
    components["agent"].run_task.return_value = "trace"
    components["bank"].get.return_value = None
    components["bank"].add.return_value = "skill_contrast"

    contr = MagicMock()
    contr.run.return_value = make_task_skill("skill_contrast")
    monkeypatch.setattr(tr, "ContrastiveRunner", lambda *a, **k: contr)

    runner = build_runner(monkeypatch, components)
    result = runner.run("task", max_iterations=1, rollouts=2)

    contr.run.assert_called_once()
    components["extractor"].extract.assert_not_called()  # contrastive supplied the skill
    assert "skill_contrast" in result.skills_created


def test_control_arm_reset_restores_full_tree(monkeypatch, components, eval_fail, eval_pass):
    """The control arm may create/edit many files; the skilled run must start
    from the identical pre-control tree (multi-file snapshot/restore)."""
    components["scorer"].evaluate.side_effect = [eval_fail, eval_fail, eval_pass]
    skill = make_task_skill("skill_x")
    components["retriever"].retrieve_for_task.return_value = [skill]
    components["retriever"].check_triggers.return_value = []
    components["extractor"].extract.return_value = None
    components["bank"].get.return_value = None

    seen: dict[str, list[str]] = {}

    def agent_run(task_description, skills, repo_path):
        if not skills:
            # Control arm pollutes the workspace with an extra file.
            with open(os.path.join(repo_path, "garbage.py"), "w") as f:
                f.write("# junk\n")
        else:
            seen["skilled_files"] = sorted(os.listdir(repo_path))
        return "trace"

    components["agent"].run_task.side_effect = agent_run

    runner = build_runner(monkeypatch, components)
    runner.run("task", code_snapshot="print('hi')\n", max_iterations=1)

    # Skilled run must NOT see the control arm's garbage, and must see the
    # original materialized file restored.
    assert "garbage.py" not in seen["skilled_files"]
    assert tr._SNAPSHOT_FILENAME in seen["skilled_files"]


# ─── A/B control-arm tests ────────────────────────────────────────────────────


def _eval(score, runnable=True, passed=False):
    from yunaki_skills.interfaces import EvalResult

    return EvalResult(
        passed=passed,
        score=score,
        runnable=runnable,
        tasks_passed=int(score / 100 * 10),
        tasks_total=10,
    )


def test_run_ab_computes_lift(monkeypatch, components):
    # control: 3 rollouts @ 40, treatment: 3 rollouts @ 70 -> lift +30
    control = [_eval(40), _eval(40), _eval(40)]
    treatment = [_eval(70), _eval(70), _eval(70)]
    components["scorer"].evaluate.side_effect = control + treatment
    components["retriever"].retrieve_for_task.return_value = [make_task_skill("skill_x")]
    components["agent"].run_task.return_value = "trace"

    runner = build_runner(monkeypatch, components)
    result = runner.run_ab("task", n_rollouts=3)

    assert result.control_mean == 40.0
    assert result.treatment_mean == 70.0
    assert result.skill_lift == 30.0
    assert result.control_scores == [40.0, 40.0, 40.0]
    assert result.treatment_scores == [70.0, 70.0, 70.0]
    assert result.control_runnable_rate == 1.0
    assert result.treatment_runnable_rate == 1.0
    assert result.skills_used == ["skill_x"]


def test_run_ab_excludes_not_runnable_from_mean(monkeypatch, components):
    # control rollout 2 is NOT runnable (import error) -> excluded from mean.
    control = [_eval(50), _eval(0, runnable=False), _eval(50)]
    treatment = [_eval(80), _eval(80), _eval(80)]
    components["scorer"].evaluate.side_effect = control + treatment
    components["retriever"].retrieve_for_task.return_value = []
    components["agent"].run_task.return_value = "trace"

    runner = build_runner(monkeypatch, components)
    result = runner.run_ab("task", n_rollouts=3)

    # Mean over runnable only: (50+50)/2 = 50, NOT (50+0+50)/3.
    assert result.control_mean == 50.0
    assert result.control_scores == [50.0, 50.0]
    assert result.control_runnable_rate == round(2 / 3, 3)
    assert result.treatment_mean == 80.0


def test_run_ab_agent_crash_does_not_zero_arm(monkeypatch, components):
    # treatment rollout 1 crashes; remaining two still score.
    components["scorer"].evaluate.side_effect = [
        _eval(30),  # control 1
        _eval(30),  # control 2
        # treatment: rollout 1 crashes (no scorer call), 2 and 3 evaluate
        _eval(90),
        _eval(90),
    ]
    components["retriever"].retrieve_for_task.return_value = []

    calls = {"n": 0}

    def run_task(task_description, skills, repo_path):
        calls["n"] += 1
        # 3rd overall call (treatment rollout 1) crashes.
        if calls["n"] == 3:
            raise RuntimeError("model down")
        return "trace"

    components["agent"].run_task.side_effect = run_task

    runner = build_runner(monkeypatch, components)
    result = runner.run_ab("task", n_rollouts=2)

    assert result.control_mean == 30.0
    assert result.treatment_scores == [90.0]  # only the non-crashed rollout
    assert result.treatment_runnable_rate == 0.5


def test_run_ab_all_not_runnable_gives_none_mean(monkeypatch, components):
    components["scorer"].evaluate.side_effect = [
        _eval(0, runnable=False),
        _eval(0, runnable=False),
        _eval(50),
        _eval(50),
    ]
    components["retriever"].retrieve_for_task.return_value = []
    components["agent"].run_task.return_value = "trace"

    runner = build_runner(monkeypatch, components)
    result = runner.run_ab("task", n_rollouts=2)

    # Control arm had zero runnable rollouts -> None mean, None lift.
    assert result.control_mean is None
    assert result.skill_lift is None
    assert result.treatment_mean == 50.0
    assert result.control_runnable_rate == 0.0


def test_run_ab_rejects_zero_rollouts(monkeypatch, components):
    runner = build_runner(monkeypatch, components)
    with pytest.raises(ValueError):
        runner.run_ab("task", n_rollouts=0)


def test_run_ab_both_arms_start_from_same_baseline(monkeypatch, components):
    """Every rollout in both arms must see the original materialized file and
    none of a prior rollout's pollution."""
    components["scorer"].evaluate.side_effect = [_eval(50)] * 4
    components["retriever"].retrieve_for_task.return_value = []

    seen_files: list[list[str]] = []

    def run_task(task_description, skills, repo_path):
        seen_files.append(sorted(os.listdir(repo_path)))
        # Pollute so a missing reset would leak into the next rollout.
        with open(os.path.join(repo_path, "junk.py"), "w") as f:
            f.write("# junk\n")
        return "trace"

    components["agent"].run_task.side_effect = run_task

    runner = build_runner(monkeypatch, components)
    runner.run_ab("task", code_snapshot="print('hi')\n", n_rollouts=2)

    # 4 rollouts (2 control + 2 treatment); each starts clean.
    assert len(seen_files) == 4
    for files in seen_files:
        assert tr._SNAPSHOT_FILENAME in files
        assert "junk.py" not in files  # prior rollout's pollution was reset


def test_default_agent_built_via_factory(monkeypatch, components):
    """With no injected agent, TaskRunner obtains one from build_agent()."""
    monkeypatch.setattr(tr, "SkillBank", lambda *a, **k: components["bank"])
    monkeypatch.setattr(tr, "SkillExtractor", lambda: components["extractor"])
    monkeypatch.setattr(tr, "SkillEvolver", lambda: components["evolver"])
    monkeypatch.setattr(tr, "SkillRetriever", lambda bank=None: components["retriever"])
    monkeypatch.setattr(tr, "EvalScorer", lambda: components["scorer"])

    built = MagicMock(name="built_agent")
    factory = MagicMock(name="build_agent", return_value=built)
    monkeypatch.setattr(tr, "build_agent", factory)

    runner = tr.TaskRunner()

    factory.assert_called_once()
    assert runner._agent is built


# ─── verify() — the verification-gate orchestration ──────────────────────────


def test_verify_runs_ab_on_provenance_task_and_records(monkeypatch, components):
    skill = make_task_skill("skill_x")  # provenance.task = "Implement the GET /users endpoint"
    components["bank"].get.return_value = skill
    runner = build_runner(monkeypatch, components)

    ab = ABResult(
        task_description=skill.provenance.task,
        n_rollouts=3,
        control_mean=40.0,
        treatment_mean=70.0,
        skill_lift=30.0,
        control_scores=[40.0, 40.0, 40.0],
        treatment_scores=[70.0, 70.0, 70.0],
        control_runnable_rate=1.0,
        treatment_runnable_rate=1.0,
    )
    runner.run_ab = MagicMock(return_value=ab)

    rec = runner.verify("skill_x", n_rollouts=3)

    assert rec is not None and rec.recommendation == "promote"
    # A/B measured THIS skill, on its own task
    kwargs = runner.run_ab.call_args.kwargs
    assert kwargs["task_description"] == "Implement the GET /users endpoint"
    assert kwargs["skills"] == [skill]
    # measurement persisted, but status/score NOT changed (advisory only)
    components["bank"].update.assert_called_once()
    recorded = components["bank"].update.call_args.args[1]
    assert recorded.measured_lift == 30.0
    assert recorded.gate_recommendation == "promote"
    assert recorded.status == SkillStatus.ACTIVE  # unchanged
    assert recorded.verified is False  # unchanged
    components["bank"].set_status.assert_not_called()


def test_verify_missing_skill_returns_none(monkeypatch, components):
    components["bank"].get.return_value = None
    runner = build_runner(monkeypatch, components)

    assert runner.verify("nope") is None
    components["bank"].update.assert_not_called()
