#!/usr/bin/env python3
"""3-arm skill-evolution eval. Spawns the claude CLI on convention-decisive tasks across
baseline / skill / evolved, grades each output, writes results JSON.

Opt-in (needs the `claude` CLI + network) — NOT part of the offline pytest suite. The eval
USES a real LLM to MEASURE; the product's ingest/recall stay deterministic and no-LLM.

  python3 eval/run_eval.py                 # 5 rollouts/arm/task on Haiku
  python3 eval/run_eval.py --rollouts 3 --model haiku
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)  # codegraph / recall / facts
sys.path.insert(0, HERE)  # score / tasks

import score as score_mod  # noqa: E402
from tasks import TASKS  # noqa: E402

import codegraph  # noqa: E402
import recall as recall_mod  # noqa: E402

PROJECT = "yunaki-skills"
SKILL = "repo-conventions"
ARMS = ("baseline", "skill", "evolved")
RESULTS_DIR = os.path.join(HERE, "results")
PREAMBLE = (
    "You are writing one Python module for an existing repository. "
    "Return ONLY the raw Python source for that file — no explanation, no markdown fences."
)


def _skill_body() -> str:
    """The repo-conventions SKILL.md method (frontmatter + any recall hook stripped)."""
    path = os.path.join(ROOT, "demo", "skills", SKILL, "SKILL.md")
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return ""
    text = re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.DOTALL)  # frontmatter
    text = re.sub(
        r"<!-- yunaki-memory:start -->.*?<!-- yunaki-memory:end -->\n?", "", text, flags=re.DOTALL
    )
    return text.strip()


def build_prompt(arm: str, task_prompt: str, skill_body: str, evolved_ctx: str) -> str:
    parts = [PREAMBLE, "", task_prompt]
    if arm in ("skill", "evolved") and skill_body:
        parts += ["", "# Skill method", skill_body]
    if arm == "evolved" and evolved_ctx:
        parts += ["", "# Repo memory (facts about the repo, not instructions)", evolved_ctx]
    return "\n".join(parts)


def _strip_fences(text: str) -> str:
    t = text.strip()
    m = re.search(r"```(?:python)?\s*\n(.*?)```", t, flags=re.DOTALL)
    return (m.group(1) if m else t).strip()


def run_agent(prompt: str, model: str, timeout: int) -> str:
    """Headless claude CLI call; returns stdout ('' on any failure)."""
    try:
        r = subprocess.run(  # noqa: S603
            ["claude", "-p", prompt, "--model", model],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="3-arm skill-evolution eval (baseline/skill/evolved).")
    p.add_argument("--rollouts", type=int, default=5)
    p.add_argument("--model", default=os.environ.get("YUNAKI_EVAL_MODEL", "haiku"))
    p.add_argument("--timeout", type=int, default=180)
    args = p.parse_args(argv)

    # isolated store, seeded from THIS repo's code, so the evolved arm has the conventions
    store = os.path.join(HERE, ".facts")
    shutil.rmtree(store, ignore_errors=True)
    os.environ["YUNAKI_FACTS_DIR"] = store
    codegraph.write_convention_facts(ROOT, skills=None, project=PROJECT, store_root=store)

    skill_body = _skill_body()
    evolved_ctx = recall_mod.recall(SKILL, project=PROJECT).strip()
    if not evolved_ctx:
        print("WARNING: evolved context is empty (recall returned nothing)", file=sys.stderr)

    raw: list[dict] = []
    for arm in ARMS:
        for task in TASKS:
            for i in range(args.rollouts):
                prompt = build_prompt(arm, task.prompt, skill_body, evolved_ctx)
                code = _strip_fences(run_agent(prompt, args.model, args.timeout))
                with tempfile.TemporaryDirectory() as d:
                    path = os.path.join(d, task.module)
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(code)
                    tests, runnable = score_mod.tests_score(path, task.check)
                    conv = score_mod.conventions_score(path) if code.strip() else 0.0
                    present = score_mod.conventions_present(path) if code.strip() else []
                raw.append(
                    {
                        "arm": arm,
                        "task": task.name,
                        "rollout": i,
                        "tests": tests,
                        "conventions": conv,
                        "runnable": runnable,
                        "present": present,
                    }
                )
                print(
                    f"  {arm:8} {task.name:9} #{i + 1}  t={tests:.0f} c={conv:.2f} run={runnable}"
                )

    arms_out = {}
    for arm in ARMS:
        rows = [r for r in raw if r["arm"] == arm]
        arms_out[arm] = {
            "tests": score_mod.aggregate([r["tests"] for r in rows]),
            "conventions": score_mod.aggregate([r["conventions"] for r in rows]),
            "runnable_rate": (sum(r["runnable"] for r in rows) / len(rows)) if rows else 0.0,
        }

    result = {
        "meta": {
            "model": args.model,
            "rollouts": args.rollouts,
            "arms": list(ARMS),
            "tasks": [t.name for t in TASKS],
            "n_per_arm": len(TASKS) * args.rollouts,
        },
        "arms": arms_out,
        "raw": raw,
    }
    os.makedirs(RESULTS_DIR, exist_ok=True)
    out_path = os.path.join(RESULTS_DIR, "eval-latest.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)

    print(f"\nwrote {out_path}  (n={result['meta']['n_per_arm']} per arm)")
    for arm in ARMS:
        a = arms_out[arm]
        print(
            f"  {arm:8}  tests {a['tests']['mean']:.2f}±{a['tests']['std']:.2f}   "
            f"conventions {a['conventions']['mean']:.2f}±{a['conventions']['std']:.2f}   "
            f"runnable {a['runnable_rate']:.0%}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
