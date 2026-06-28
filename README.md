# Yunaki Skills

Self-evolving skills for coding agents. An agent writes code, fails, extracts patterns into JSON skills, evolves them, and measurably improves.



## Architecture

```
Task → Coding Agent (host CLI or Gemini) → Eval Scorer (pytest [+ judge]) →
  if failed → Skill Extractor (single-trace or contrastive) → Skill Bank →
  Skill Retriever (score-weighted) → inject skills into next Agent call →
  run again → measurable improvement
                              ↘ periodic consolidation: merge dupes, drop dead weight
```

## Bring your own coding agent

The coding agent is whatever CLI is installed on your machine. yunaki detects it,
drives it in headless mode, and reuses its existing auth — so you do **not** need
a `GEMINI_API_KEY` for the common case.

```bash
yunaki doctor   # shows detected backends and which one will be used
```

Supported backends (detection-preference order): `claude`, `codex`,
`cursor-agent`, `gemini` (CLI), `aider`. Override with
`YUNAKI_AGENT_BACKEND=<name>`, or force the in-process Gemini SDK with
`YUNAKI_AGENT_BACKEND=gemini-sdk`. Skill meta-ops (extract/evolve/judge) route
through the same backend by default; pin them to a Gemini model with
`YUNAKI_SKILL_MODEL=gemini-2.5-flash`.

### Backend verification status

| Backend | Binary | Invocation | Parser | Status |
|---------|--------|-----------|--------|--------|
| `claude` | `claude` | `claude -p "<prompt>" --output-format json` | `claude_json` — extracts `.result` from single JSON object | **Verified end-to-end** (CI + real CLI) |
| `cursor-agent` | `cursor-agent` | `cursor-agent -p "<prompt>" --output-format json --force` | `cursor_json` — extracts `.result` from single JSON object (`{"type":"result","result":"<text>",...}`) | **Schema verified** against real binary; end-to-end smoke blocked by missing auth |
| `codex` | `codex` | `codex exec "<prompt>" --json` | `codex_jsonl` — harvests only `item.completed` events where `item.type == "agent_message"`, extracting `item.text`; reasoning/tool events skipped | **Best-effort** — schema verified against openai/codex source; no binary available in this env |
| `gemini` | `gemini` | `gemini -p "<prompt>" --output-format json` | `gemini_json` — extracts `.response` from single JSON object (`{"response":"<text>","stats":{...},"error":null,...}`) | **Best-effort** — schema verified against google-gemini/gemini-cli source; no binary available in this env |
| `aider` | `aider` | `aider --message "<prompt>" --yes-always` | `text` — strips startup banner lines (`Aider v`, `Model:`, `Git repo:`, etc.) before the response reaches the trace | **Best-effort** — schema verified against aider docs; no binary available in this env |

"Schema verified" means the parser was confirmed correct against the real CLI output format from official source code and documentation, with realistic fixture tests covering the full event/field structure. "Verified end-to-end" means the parser was additionally exercised against the actual running binary.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # most keys are optional now — see comments in the file
yunaki doctor          # confirm your coding-agent CLI is detected
python -m yunaki_skills.main
```

## Quick Start

```python
from yunaki_skills.task_runner import TaskRunner

runner = TaskRunner()
result = runner.run("Add a /health endpoint to the FastAPI app")
# skill_delta = score_after − score_control isolates the skill effect from
# "the agent can already code." It is the only honest measure of value.
print(f"{result.score_before} → {result.score_after}  (skill_delta={result.skill_delta})")
```

## CLI

```bash
yunaki run "<task>" [--max-iterations N] [--rollouts N]   # --rollouts>1 = contrastive
yunaki doctor                                             # show detected backend
yunaki skills list
yunaki skills evolve <skill_id>
yunaki skills consolidate [--apply]                       # dry-run unless --apply
```

## God-level loop (all opt-in, default = baseline behavior)

- **Contrastive extraction** — `--rollouts N` (or `YUNAKI_CONTRASTIVE_ROLLOUTS`)
  runs N rollouts and learns from the best-passing vs worst-failing pair.
- **Composite reward** — `YUNAKI_COMPOSITE_REWARD=1` layers an LLM-judge
  alignment+quality signal on top of pytest. Signal only: it never flips the
  deterministic pytest pass/fail gate.
- **Score-weighted retrieval** — proven, higher-scoring skills win ties; unproven
  (0-usage) skills keep a neutral prior so they aren't starved.
- **Merge + Drop** — `yunaki skills consolidate` fuses near-duplicate skills and
  drops ineffective ones (never 0-usage). Dry-run by default.

See `.env.example` for every tunable knob.
