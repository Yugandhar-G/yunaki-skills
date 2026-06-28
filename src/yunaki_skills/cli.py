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
    result = runner.run(args.task, max_iterations=args.max_iterations, rollouts=args.rollouts)

    if args.json:
        print(json.dumps(result.model_dump(), indent=2))
    else:
        print(f"\n{result.score_before:.0f}% -> {result.score_after:.0f}% in {result.iterations} iteration(s)")
        # The honest measure is skill_delta (vs the no-skills control arm), NOT
        # score_after - score_before, which conflates "the agent can code" with
        # "the skills helped."
        if result.score_control is not None:
            print(f"  control (no skills): {result.score_control:.0f}%")
        if result.skill_delta is not None:
            print(f"  skill_delta:         {result.skill_delta:+.0f}%  (effect of skills vs control)")
        else:
            print("  skill_delta:         n/a (control arm did not run)")
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

    The agent runs inside an ephemeral copy of the target repo so a file-editing
    CLI backend never mutates the real working tree.
    """
    import shutil
    import tempfile

    from yunaki_skills.agent_factory import build_agent
    from yunaki_skills.eval_scorer import EvalScorer
    from yunaki_skills.skill_bank import SkillBank
    from yunaki_skills.skill_evolver import SkillEvolver

    bank = SkillBank()
    skill = bank.get(args.skill_id)
    if skill is None:
        print(f"error: skill '{args.skill_id}' not found", file=sys.stderr)
        return 1

    task = skill.provenance.task or skill.when_to_apply
    src_repo = os.environ.get(
        "TARGET_REPO",
        os.path.join(os.path.dirname(__file__), "..", "..", "target_repo"),
    )

    workspace = tempfile.mkdtemp(prefix="yunaki_evolve_")
    try:
        if os.path.isdir(src_repo):
            shutil.copytree(src_repo, workspace, dirs_exist_ok=True)

        print(f"Gathering fresh evidence for '{skill.id}' on task: {task!r}")
        trace = build_agent().run_task(task, [skill], workspace)
        eval_result = EvalScorer().evaluate(task, workspace=workspace)
        print(f"  fresh eval: {eval_result.score:.0f}% ({eval_result.details})")

        evolved = SkillEvolver().evolve(skill, trace, eval_result)
        ok = bank.update(skill.id, evolved)
        if not ok:
            print(f"error: failed to persist evolved skill '{skill.id}'", file=sys.stderr)
            return 1
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    print(
        f"Evolved {skill.id}: v{skill.version} -> v{evolved.version} (score {skill.score:.0f} -> {evolved.score:.0f})"
    )
    return 0


def _cmd_skills_consolidate(args: argparse.Namespace) -> int:
    """Merge near-duplicate skills and drop ineffective ones.

    Dry-run by default; pass --apply to actually mutate the bank.
    """
    from yunaki_skills.skill_consolidator import SkillConsolidator

    report = SkillConsolidator().consolidate(dry_run=not args.apply)

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    mode = "APPLIED" if args.apply else "DRY-RUN (use --apply to execute)"
    print(f"Consolidation [{mode}]")
    print(f"  merges: {len(report['merges'])}")
    for m in report["merges"]:
        print(f"    {m['sources']} -> {m['merged_id']}")
    print(f"  drops: {len(report['drops'])}")
    for d in report["drops"]:
        print(f"    {d['id']}: {d['reason']}")
    return 0


def _cmd_bench_harvest(args: argparse.Namespace) -> int:
    """Harvest coding tasks from a repo's git fix-commits into a corpus JSON."""
    from yunaki_skills.bench.harvester import harvest

    test_cmd = args.test_cmd.split()
    corpus = harvest(
        args.repo_path,
        test_command=test_cmd,
        max_tasks=args.max_tasks,
        since=args.since,
    )
    corpus.save(args.out)

    if args.json:
        print(json.dumps({"tasks": len(corpus.tasks), "out": args.out}, indent=2))
        return 0
    print(f"Harvested {len(corpus.tasks)} verified task(s) (fail-at-base) -> {args.out}")
    for t in corpus.tasks:
        print(f"  {t.id}: {t.prompt[:70]}")
    if not corpus.tasks:
        print("  (none — try --max-tasks higher, a different repo, or check the test command)")
    return 0


def _cmd_bench_run(args: argparse.Namespace) -> int:
    """Train a skill bank on a split, then report honest held-out transfer."""
    from yunaki_skills.bench.runner import run_benchmark
    from yunaki_skills.bench.task_spec import TaskCorpus

    corpus = TaskCorpus.load(args.corpus)
    if not corpus.tasks:
        print("error: corpus has no tasks", file=sys.stderr)
        return 1

    report = run_benchmark(corpus, train_frac=args.train_frac, max_iterations=args.max_iterations)
    report.save(args.out)

    if args.json:
        print(report.model_dump_json(indent=2))
        return 0

    delta = report.mean_held_out_skill_delta
    print(f"\nBenchmark [{report.org_id}] -> {args.out}")
    print(f"  train tasks: {report.n_train}   held-out tasks: {report.n_eval}")
    print(f"  bank size after training: {report.bank_size_after_train}")
    print(f"  control pass rate: {report.control_pass_rate:.0%}   skilled pass rate: {report.skilled_pass_rate:.0%}")
    if delta is None:
        print("  mean held-out skill_delta: n/a (no comparable held-out tasks)")
    else:
        verdict = "skills HELPED" if delta > 0 else ("no effect" if delta == 0 else "skills HURT")
        print(f"  mean held-out skill_delta: {delta:+.1f}%  ({verdict})")
    print(f"  note: {report.note}")
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    """Report which coding-agent backend would be used (no clients constructed)."""
    from yunaki_skills.agent_factory import selection_summary

    summary = selection_summary()
    if args.json:
        print(json.dumps(summary, indent=2))
        return 0

    print("Coding-agent backend detection")
    print(f"  override (YUNAKI_AGENT_BACKEND): {summary['override'] or '(none)'}")
    print(f"  available on PATH: {', '.join(summary['available']) or '(none — will use Gemini SDK)'}")
    print(f"  selected: {summary['selected']}")
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
    p_run.add_argument(
        "--rollouts",
        type=int,
        default=None,
        help="Rollouts per failure for contrastive extraction (default 1 / env YUNAKI_CONTRASTIVE_ROLLOUTS)",
    )
    p_run.set_defaults(func=_cmd_run)

    p_skills = sub.add_parser("skills", help="Manage the skill bank")
    skills_sub = p_skills.add_subparsers(dest="skills_command", required=True)

    p_list = skills_sub.add_parser("list", help="List all skills")
    p_list.set_defaults(func=_cmd_skills_list)

    p_evolve = skills_sub.add_parser("evolve", help="Evolve a skill by id")
    p_evolve.add_argument("skill_id", help="ID of the skill to evolve")
    p_evolve.set_defaults(func=_cmd_skills_evolve)

    p_consolidate = skills_sub.add_parser("consolidate", help="Merge near-duplicate skills and drop ineffective ones")
    p_consolidate.add_argument("--apply", action="store_true", help="Actually mutate the bank (default: dry-run)")
    p_consolidate.set_defaults(func=_cmd_skills_consolidate)

    p_doctor = sub.add_parser("doctor", help="Show which coding-agent backend is detected")
    p_doctor.set_defaults(func=_cmd_doctor)

    p_bench = sub.add_parser("bench", help="Self-evolution benchmark (harvest real tasks, prove transfer)")
    bench_sub = p_bench.add_subparsers(dest="bench_command", required=True)

    p_harvest = bench_sub.add_parser("harvest", help="Harvest tasks from a repo's git fix-commits")
    p_harvest.add_argument("repo_path", help="Path to the git repo to harvest from")
    p_harvest.add_argument("--out", default="corpus.json", help="Output corpus JSON path")
    p_harvest.add_argument("--max-tasks", type=int, default=20, help="Max tasks to harvest")
    p_harvest.add_argument("--since", default=None, help="Only scan commits after this rev (e.g. a tag)")
    p_harvest.add_argument("--test-cmd", default="python3 -m pytest -q", help="Test command (quoted string)")
    p_harvest.set_defaults(func=_cmd_bench_harvest)

    p_bench_run = bench_sub.add_parser("run", help="Train on a split, measure held-out transfer")
    p_bench_run.add_argument("--corpus", required=True, help="Task corpus JSON from `bench harvest`")
    p_bench_run.add_argument("--train-frac", type=float, default=0.7, help="Fraction of tasks for training")
    p_bench_run.add_argument("--max-iterations", type=int, default=_DEFAULT_MAX_ITERATIONS)
    p_bench_run.add_argument("--out", default="bench_report.json", help="Output report JSON path")
    p_bench_run.set_defaults(func=_cmd_bench_run)

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
