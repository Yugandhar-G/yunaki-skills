"""
yunaki — command-line interface.

Commands:
  yunaki run <task> [--max-iterations N]   Run a task through the evolution loop
  yunaki skills list                       List all skills in the bank
  yunaki skills evolve <skill_id>          Re-evolve a skill against fresh evidence

Console entry point is `yunaki` (see pyproject [project.scripts]).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

logger = logging.getLogger(__name__)

_DEFAULT_MAX_ITERATIONS = 3


def _cmd_run(args: argparse.Namespace) -> int:
    """Run a task through the full evolution loop."""
    from yunaki_skills.task_runner import TaskRunner

    runner = TaskRunner()
    result = runner.run(args.task, max_iterations=args.max_iterations)

    if args.json:
        print(json.dumps(result.model_dump(), indent=2))
    else:
        delta = result.score_after - result.score_before
        print(
            f"\n{result.score_before:.0f}% -> {result.score_after:.0f}% "
            f"(Δ{delta:+.0f}) in {result.iterations} iteration(s)"
        )
        print(f"  used:    {result.skills_used}")
        print(f"  created: {result.skills_created}")
        print(f"  evolved: {result.skills_evolved}")
    return 0


def _cmd_skills_list(args: argparse.Namespace) -> int:
    """List all skills in the bank."""
    from yunaki_skills.skill_bank import SkillBank

    skills = SkillBank().list_all()
    if args.json:
        print(json.dumps([s.model_dump() for s in skills], indent=2))
        return 0

    if not skills:
        print("No skills in bank.")
        return 0

    for s in skills:
        print(f"{s.id:<32} v{s.version:<5} score={s.score:>5.1f}  [{s.granularity.value}]  {s.title}")
    return 0


def _cmd_skills_evolve(args: argparse.Namespace) -> int:
    """Evolve a skill against fresh evidence from its originating task.

    Runs the agent on the skill's recorded task, scores it, and feeds that new
    trace + eval into the evolver, then persists the evolved version.
    """
    from yunaki_skills.antigravity_client import AntigravityClient
    from yunaki_skills.eval_scorer import EvalScorer
    from yunaki_skills.skill_bank import SkillBank
    from yunaki_skills.skill_evolver import SkillEvolver

    bank = SkillBank()
    skill = bank.get(args.skill_id)
    if skill is None:
        print(f"error: skill '{args.skill_id}' not found", file=sys.stderr)
        return 1

    task = skill.provenance.task or skill.when_to_apply
    repo_path = os.environ.get(
        "TARGET_REPO",
        os.path.join(os.path.dirname(__file__), "..", "..", "target_repo"),
    )

    print(f"Gathering fresh evidence for '{skill.id}' on task: {task!r}")
    trace = AntigravityClient().run_task(task, [skill], repo_path)
    eval_result = EvalScorer().evaluate(task, repo_path)
    print(f"  fresh eval: {eval_result.score:.0f}% ({eval_result.details})")

    evolved = SkillEvolver().evolve(skill, trace, eval_result)
    ok = bank.update(skill.id, evolved)
    if not ok:
        print(f"error: failed to persist evolved skill '{skill.id}'", file=sys.stderr)
        return 1

    print(
        f"Evolved {skill.id}: v{skill.version} -> v{evolved.version} (score {skill.score:.0f} -> {evolved.score:.0f})"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yunaki", description="Yunaki self-evolving skills CLI")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Run a task through the evolution loop")
    p_run.add_argument("task", help="Task description")
    p_run.add_argument(
        "--max-iterations",
        type=int,
        default=_DEFAULT_MAX_ITERATIONS,
        help=f"Max evolution iterations (default {_DEFAULT_MAX_ITERATIONS})",
    )
    p_run.set_defaults(func=_cmd_run)

    p_skills = sub.add_parser("skills", help="Manage the skill bank")
    skills_sub = p_skills.add_subparsers(dest="skills_command", required=True)

    p_list = skills_sub.add_parser("list", help="List all skills")
    p_list.set_defaults(func=_cmd_skills_list)

    p_evolve = skills_sub.add_parser("evolve", help="Evolve a skill by id")
    p_evolve.add_argument("skill_id", help="ID of the skill to evolve")
    p_evolve.set_defaults(func=_cmd_skills_evolve)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=os.environ.get("YUNAKI_LOG_LEVEL", "WARNING"))
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
