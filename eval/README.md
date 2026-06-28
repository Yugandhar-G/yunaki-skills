# Skill-evolution eval (3-arm)

Measures whether an evolved skill actually helps, with a number — not a vibe. Real agents run
convention-decisive tasks across three arms; each output is graded; the result is charted.

```
baseline   task prompt only
skill      task prompt + the repo-conventions SKILL.md method
evolved    task prompt + SKILL.md + the recalled repo context  (the always-on product)
```

Two metrics per arm, averaged over rollouts (mean ± std):

- **tests passed** — did the module do the task (each task's behavioral `check`).
- **conventions followed** — did it match the repo's house rules, graded by `codegraph`
  (stdlib-only / future-annotations / argparse+main / never-raises), 0..1.

## Run

```bash
# offline: the grading logic only (CI-safe, no agents)
python3 -m pytest tests/test_eval_scoring.py -v

# live: spawns the claude CLI (needs it installed + auth). ~45 runs (3 arms x 3 tasks x 5).
python3 eval/run_eval.py                 # writes eval/results/eval-latest.json
python3 eval/chart.py                     # renders eval/results/eval.png from that JSON

# knobs
python3 eval/run_eval.py --rollouts 3 --model haiku
```

The chart re-renders from the saved JSON with **no agents**, so it's reproducible for free.

## Honest caveats

- **Small N.** Default 5 rollouts/arm/task. The chart shows N and error bars; don't overclaim.
- **The eval uses a real LLM to MEASURE.** That is not the product loop — the product's
  ingest and recall stay deterministic and no-LLM. Only the thing being measured (the coding
  agent) is an LLM.
- **Opt-in, not in the offline suite.** It needs the `claude` CLI + network, so it lives here,
  not in `tests/`. Results are committed as a receipt (`eval/results/*.json` + `eval.png`).
- **Grader limits.** `never-raises` is text-detected (weak); the conventions favor CLI-shaped
  modules — hence the three CLI tasks. Tasks are convention-*neutral* in their prompts, so the
  conventions can only come from an arm's context.
- **Expectation, not a guarantee.** `evolved ≥ skill ≥ baseline` on conventions-followed is the
  hypothesis (only the evolved arm is told the conventions). Whatever the run shows is the
  honest result.
