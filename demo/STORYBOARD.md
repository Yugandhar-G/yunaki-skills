# 3-minute demo — script & storyboard

Goal: show the **real product working** and its **real impact**. Lead with the point that
actually matters: a skill arrives carrying the repo's conventions the moment it's invoked,
scanned straight from the code — **no failure required**. Then show it keeps getting sharper
from failures and merged PRs, that it's measured, and that it's an **org-wide shared brain**.
No architecture diagrams.

## Before you hit record
```bash
# point the demo at your live service (the org's shared memory)
export SUPERMEM_URL=https://<your-supermem-host>.sslip.io
export SUPERMEM_TOKEN=<your-repo-token>   # never commit the real token
```
- Big terminal font (18pt+), wide window. Dark theme.
- Do one dry run with `DEMO_AUTO=1 ./demo/evolve.sh` so you know the beats.
- For the take, run `./demo/evolve.sh` — it **pauses on Enter between the 6 beats** so you
  narrate at your own pace.
- Have a browser tab open at **`https://161.35.239.198.sslip.io/`** — the live landing page
  with the padlock and real numbers (facts learned, repos, **0 LLM calls**). This is your
  "it's really deployed, team-wide" shot. (`/health` and `/stats` return JSON for raw proof.)

---

## Beat-by-beat (target 3:00)

### 0:00–0:18 · Hook (talk over a plain terminal or your face)
> "Coding agents keep breaking on conventions they can't guess — they don't know *your*
> repo. The usual fix is rewriting the skill's prompt. We measured that; it makes skills
> *worse*. So we did the opposite: the skill stays fixed, and we feed it **memory** — read
> straight from your code. Here it is."

### 0:18–0:35 · Beat 1 — a real skill, nothing learned yet  *(run ./demo/evolve.sh)*
SHOW: the bound `SKILL.md` (method + recall hook); `recall` is empty.
> "A real skill: a fixed method, plus a hook that recalls what it's learned about this repo.
> Right now it's learned nothing — recall is empty."

### 0:35–1:05 · Beat 2 — read the codebase into memory  ← **the point**
SHOW: `codegraph --write` writes four conventions. No test. No failure. No LLM.
> "We read the codebase. Pure extraction — every module, no model call. It just found this
> repo's house rules: stdlib-only, a fixed import style, how CLIs are written."

### 1:05–1:35 · Beat 3 — invoke the skill: it's already loaded
SHOW: `recall --skill repo-conventions` now prints the conventions; the facts are their own
files; the `SKILL.md` body is verified unchanged.
> "Now invoke the skill. Before it does *anything*, it already carries those conventions —
> inlined above its method. Nothing failed to teach it. And the skill file itself is
> byte-for-byte unchanged. The method is fixed; the memory is what arrived."

### 1:35–2:05 · Beat 4 — and it keeps getting sharper
SHOW: a task fails on a convention it couldn't guess; `ingest` adds one fact to the **same**
store (4 → 5). Still no LLM.
> "It doesn't stop at the scan. When the agent hits a rule it couldn't guess, the failed
> check teaches the same memory one more fact — no model call. Code, failures, and PRs all
> feed one store. The method never moves; the memory only grows."

### 2:05–2:30 · Beat 5 — the measured impact
SHOW: the A/B — 1/3 without context, 3/3 with it.
> "Real Claude agents, same task. The only difference is whether they had the recalled rule.
> Without it: one of three. With it: three of three. No LLM in the loop, no edits."

### 2:30–2:55 · Beat 6 — one shared brain, rebuilt on every merge  ← **team story**
SHOW: a merged-PR webhook hits the shared memory and it **rebuilds from the codebase** (the
store jumps from 0 to N conventions — `team.png`); then the live browser at
`https://161.35.239.198.sslip.io/` — padlock + "facts learned · 0 LLM calls".
> "And it's not one laptop. Every repo and teammate points at one shared memory. When *one*
> engineer merges a PR, GitHub fires a webhook and the shared memory **rebuilds itself from the
> merged code** — no rewrites, no model calls. Every teammate then recalls the refreshed rules
> on the next skill they invoke. One dev merges; the whole org's agents get sharper."

### 2:55–3:00 · Close
> "Read from your code, sharpened by every failure and PR, shared across the team — and every
> agent that invokes a skill evolves with it. That's skill evolution."

---

## Optional depth beat — one skill, many lessons
For an "it generalizes" moment, run **`./demo/skill-evolves.sh`**: it binds the real
`SKILL.md` and has it learn **three** repo conventions from three failing tasks — slugs use
underscores, validation returns 422, timestamps use a `Z` suffix — while its method stays
byte-for-byte unchanged. This is the `failures.png` receipt on the landing page.

## Screenshots on the landing page (real, re-runnable)
- `alwayson.png` — Beat 2–3: scanned from the code, skill invoked, already loaded. **No failure.**
- `failures.png` — Beat 4 / `skill-evolves.sh`: three conventions learned from failing tests.
- `ab.png` — Beat 5: same agent, 1/3 without context vs 3/3 with it.
- `team.png` — Beat 6: a merged-PR webhook rebuilds the shared memory (0 → N conventions),
  recalled over HTTPS. The team loop.
- `live.png` — Beat 6: the shared memory answering live over HTTPS, deployed.

Regenerate any shot from real output with `./demo/shot.py <capture.txt> <out.png>`.

## If the live box is down
`evolve.sh` degrades gracefully (prints a note instead of the curl). Beats 1–5 are fully
local and always work, so the demo never hard-fails on stage.

## One honest line you can include (judges love it)
> "Everything you saw is deterministic and runs offline — the only network call is the
> optional shared service. No LLM in the learning loop, nothing faked."
