"""Tests for TaskRunner — the full evolution loop with every component mocked."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

import yunaki_skills.task_runner as tr
from tests.conftest import make_task_skill


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


def test_demo_handicap_clause_appends_constraint(monkeypatch):
    monkeypatch.setenv("YUNAKI_DEMO_HANDICAP_STAGED_WALKTHROUGH", "1")
    monkeypatch.setenv("YUNAKI_DEMO_HANDICAP", "1,2")
    clause1 = tr._demo_handicap_clause(1)
    clause3 = tr._demo_handicap_clause(3)
    assert "first 1 item" in clause1
    assert "NOT A REAL MEASUREMENT" in clause1  # Must be unmistakably labeled
    assert clause3 == ""  # past the schedule


def test_demo_handicap_disabled_by_default(monkeypatch):
    monkeypatch.delenv("YUNAKI_DEMO_HANDICAP_STAGED_WALKTHROUGH", raising=False)
    assert tr._demo_handicap_clause(1) == ""


def test_injected_agent_is_used_over_default(monkeypatch, components, eval_fail, eval_pass):
    """An agent passed via the DI seam must be used instead of the built default."""
    monkeypatch.delenv("YUNAKI_DEMO_HANDICAP_STAGED_WALKTHROUGH", raising=False)
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
