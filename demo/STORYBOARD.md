# 3-minute demo — script & storyboard

Goal: show the **real product working** and its **real impact** — a skill that goes from
failing to passing because it *learned*, with the skill file never edited — then prove it's
deployed and team-scale. No architecture diagrams.

## Before you hit record
```bash
# point the demo at your live service
export SUPERMEM_URL=https://161.35.239.198.sslip.io
export SUPERMEM_TOKEN=ZWIcgn7Am-ei7GPmQssJdUEqvXE9vf9BYBwKxr9Lm00
```
- Big terminal font (18pt+), wide window. Dark theme.
- Do one dry run with `DEMO_AUTO=1 ./demo/evolve.sh` so you know the beats.
- For the take, run `./demo/evolve.sh` — it **pauses on Enter between the 6 beats** so you
  narrate at your own pace.
- Have a browser tab open at **`https://161.35.239.198.sslip.io/`** — the live landing page
  with the padlock and real numbers (facts learned, repos, **0 LLM calls**). This is your
  "it's really deployed" shot. (`/health` and `/stats` return JSON if you want raw proof.)

---

## Beat-by-beat (target 3:00)

### 0:00–0:18 · Hook (talk over a plain terminal or your face)
> "Coding agents keep making the same mistakes — they don't know *your* repo's
> conventions. The usual fix is rewriting the skill's prompt. We measured that, and it
> actually makes skills *worse*. So we did the opposite: the skill stays fixed, and its
> **memory** evolves. Here it is."

### 0:18–0:35 · Beat 1 — the skill knows nothing yet  *(run ./demo/evolve.sh)*
SHOW: `recall` returns empty.
> "This skill has its method, but it's learned nothing about this repo yet — recall is
> empty."

### 0:35–1:05 · Beat 2 — the agent fails a convention it can't guess
SHOW: pytest fails: `assert 'my-cool-title' == 'my_cool_title'`.
> "An agent does a task and writes the obvious slug — hyphens. But this repo's convention
> is underscores. It can't guess that, so it fails."

### 1:05–1:25 · Beat 3 — it learns from the failure, no LLM
SHOW: `learned 1 fact(s)`.
> "We feed that failure straight in. Pure extraction — no LLM, no model call. It just
> learned our convention."

### 1:25–1:55 · Beat 4 — the skill is smarter, and we never touched it  ← **the point**
SHOW: `recall` now prints the convention; the fact is its own file; SKILL.md unchanged.
> "Now the skill recalls the convention — and look: that knowledge lives in its own file.
> The skill itself is byte-for-byte unchanged. The method didn't change. The memory did."

### 1:55–2:20 · Beat 5 — the measured impact
SHOW: the 0/3 → 3/3 lines.
> "On a convention-decisive task with real Claude agents and real tests: zero out of three
> passed with the skill alone — three out of three after one auto-learned fact. No LLM, no
> edits."

### 2:20–2:50 · Beat 6 — it's deployed, shared, self-evolving
SHOW: the live `curl` returning real PR knowledge over HTTPS. (Cut to the browser at
`https://161.35.239.198.sslip.io/` — padlock + "40 facts learned · 0 LLM calls".)
> "And it's not just on my laptop. This is live on DigitalOcean: a shared memory for the
> whole team, real HTTPS, per-repo tokens — and it feeds itself from every merged PR via a
> GitHub webhook. These facts came from this repo's actual pull requests."

### 2:50–3:00 · Close
> "We never rewrote the skill — it keeps evolving, and every agent that uses it evolves with
> it. Every PR, every test makes them sharper. That's skill evolution."

---

## If the live box is down
`evolve.sh` degrades gracefully (prints a note instead of the curl). Beats 1–5 are fully
local and always work, so the demo never hard-fails on stage.

## One honest line you can include (judges love it)
> "Everything you saw is deterministic and runs offline — the only network call is the
> optional shared service. No LLM in the learning loop, nothing faked."
