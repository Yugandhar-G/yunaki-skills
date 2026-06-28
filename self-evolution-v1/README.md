# Yunaki Skills

Coding agents repeat the same *systematic mistakes* across runs. Yunaki gives them
a memory: it watches an agent attempt a task, scores the result with real tests,
and turns its recurring failure mode into a small reusable **skill**. That skill is
injected into future attempts so the agent stops making the same class of mistake,
and — crucially — the fix carries over to *different* tasks that share the failure mode.

This is not "the model gets smarter." It is narrower and more honest: **Yunaki learns
an agent's repeated blind spot and encodes the fix.** The measured gains are
reliability-driven (the agent stops shipping broken code), not emergent reasoning.
See [Evidence](#evidence) for exactly what we measured and where it does and doesn't help.

## How it works

```
Task → Coding agent (your installed CLI) → score with pytest →
  if it failed → extract a skill from the trace (or evolve an existing one)
  if it passed → capture the winning approach
       ↓
  store in the skill bank → retrieve relevant skills → inject into the next run
       ↓
  periodically consolidate: merge duplicates, drop dead weight
```

Each run does this:

1. **Control arm** — run the task once with *no* skills. This is the honest baseline.
2. Retrieve relevant skills, inject them, and run again.
3. Score with pytest. Learn a skill on failure; capture the approach on success.
4. Report **`skill_delta` = score-with-skills − score-of-control-arm**. This is the
   only number that proves the skills helped, as opposed to "the agent could
   already do it." Yunaki deliberately does not headline the flattering
   before/after delta.

## Evidence

All numbers below come from the real loop (Claude as the skill-manager, a frozen
Gemini agent as the coding policy), scored by real pytest. Scoring separates "code
didn't even run" from "ran but failed," so a single import error can't silently
zero a run. **Raw lift** counts broken code as 0%; that is the honest number.

| Experiment | Result | Reliability (runnable rate) |
|---|---|---|
| Self-extracted skill on a REST users API | **+40pp raw**, replicated at +39pp | 42% → 100% |
| **Pure cross-task transfer** (skill learned on users, *frozen*, applied to a products API it never saw) | **+24pp raw** | 38% → 88% |
| Clean algorithmic task (stats lib) | **no measurable lift** | agent already at 100% |

**What this shows:** an automatically-extracted skill genuinely helps, and it
*transfers* to a different task without re-tuning. The gains come from fixing a
systematic failure mode (the agent shipping non-importable FastAPI code), which is
why the win transfers across tasks that share that failure mode — and why the clean
algorithmic task shows nothing (the agent has no blind spot there).

**What this does not yet show (honest limitations):**
- This is *near* transfer (same domain, shared failure mode), not far transfer.
- Gains are reliability-driven; correctness of already-working code barely moves.
- n=8 per arm, few seeds. Directional with a clear mechanism — statistical hardening
  (more seeds, more task families, error bars) is the roadmap, not a finished claim.

## Install

```bash
pip install -e .
cp .env.example .env     # most keys are optional — see the comments in the file
yunaki doctor            # checks which coding agent Yunaki will drive
```

## Bring your own coding agent (no Gemini key needed)

Yunaki doesn't ship its own model. It drives whatever coding-agent CLI you already
have installed and reuses that tool's existing login, so you usually need **no**
`GEMINI_API_KEY`.

- **Supported backends:** `claude`, `codex`, `cursor-agent`, `gemini` (CLI), `aider`.
- **Override detection:** `YUNAKI_AGENT_BACKEND=<name>`. Force the in-process
  Gemini SDK (needs a key) with `YUNAKI_AGENT_BACKEND=gemini-sdk`.
- The skill model (extract / evolve / judge) routes through the same backend by
  default; pin it to a specific Gemini model with `YUNAKI_SKILL_MODEL=gemini-2.5-flash`.

### Backend verification status

| Backend | Invocation | Parser | Status |
|---------|-----------|--------|--------|
| `claude` | `claude -p "<prompt>" --output-format json` | `claude_json` — `.result` from a single JSON object | **Verified end-to-end** (CI + real CLI) |
| `cursor-agent` | `cursor-agent -p "<prompt>" --output-format json --force` | `cursor_json` — `.result` from `{"type":"result","result":"…"}` | **Schema verified** against the real binary; e2e smoke blocked by missing auth |
| `codex` | `codex exec "<prompt>" --json` | `codex_jsonl` — only `item.completed` `agent_message` events (`.item.text`); reasoning/tool events skipped | **Best-effort** — schema verified vs openai/codex source; binary not installed here |
| `gemini` | `gemini -p "<prompt>" --output-format json` | `gemini_json` — `.response` from `{"response":"…","error":null}` | **Best-effort** — schema verified vs google-gemini/gemini-cli source; binary not installed here |
| `aider` | `aider --message "<prompt>" --yes-always` | `text` — strips the startup banner before the response | **Best-effort** — schema verified vs aider docs; binary not installed here |

"Schema verified" = the parser was confirmed against the real CLI output format (from
official source/docs) with realistic fixture tests. "Verified end-to-end" = additionally
exercised against the actual running binary.

## Use it

```bash
yunaki run "Add a /health endpoint to the FastAPI app"
yunaki run "<task>" --max-iterations 5 --rollouts 3   # see "Tuning" below
yunaki skills list
yunaki skills evolve <skill_id>
yunaki skills consolidate            # dry-run; add --apply to actually change the bank
```

Or from Python:

```python
from yunaki_skills.task_runner import TaskRunner

result = TaskRunner().run("Add a /health endpoint to the FastAPI app")
print(f"{result.score_before}% → {result.score_after}%  (skill_delta={result.skill_delta})")
```

## Tuning (all opt-in; defaults reproduce baseline behavior)

- **Contrastive extraction** (`--rollouts N` / `YUNAKI_CONTRASTIVE_ROLLOUTS`) — run a
  task N times and learn the skill from the difference between the best passing and
  worst failing attempt. Higher signal than a single trace.
- **Composite reward** (`YUNAKI_COMPOSITE_REWARD=1`) — layer an LLM-as-judge
  alignment + quality score on top of pytest. Advisory only: it never flips the
  deterministic pytest pass/fail gate.
- **Score-weighted retrieval** (`YUNAKI_RANK_W_SCORE` / `YUNAKI_RANK_W_RATE`, both
  `0` by default = pure similarity) — let proven, higher-scoring skills win close
  matches. Unproven (0-usage) skills keep a neutral prior so they aren't starved.
- **Consolidation** (`yunaki skills consolidate`) — merge near-duplicate skills and
  drop ones that have proven ineffective (never drops a skill with zero usage).

Every knob is documented in [.env.example](.env.example).

## API

Yunaki is headless. Drive it from the `yunaki` CLI or the REST + WebSocket API;
there is no bundled dashboard. `yunaki-server` runs a FastAPI app (run a task,
stream progress, manage and govern skills, multi-repo namespacing). Full
reference in [docs/API.md](docs/API.md).

```bash
yunaki-server   # API on http://localhost:8000  (interactive docs at /docs)
```

## Troubleshooting

- **`yunaki doctor` shows no backends** — install and log into a coding-agent CLI
  (e.g. `claude`), or set `GEMINI_API_KEY` and `YUNAKI_AGENT_BACKEND=gemini-sdk`.
- **A backend is detected but tasks produce no skills** — that backend may not be
  returning clean JSON for the meta-ops; check the warning logs, or pin
  `YUNAKI_SKILL_MODEL=gemini-2.5-flash`.
- **MongoDB unavailable** — Yunaki falls back to in-memory storage; skills won't
  persist across restarts. Set `MONGODB_URI` to persist.
```
