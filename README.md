# Skill Evolution

Skills that get better over time — **without rewriting them.**

A skill is its `SKILL.md` (the human-written method) plus the **context it has learned**
about this repo. The method never changes; the context evolves. That is the evolution.

We measured the obvious alternative — having an LLM rewrite the skill — and it *degrades*
it (−4.2pp here; SkillsBench reports the same: curated skills +16.2pp, self-generated
−1.3pp). So we never touch the skill body. We evolve what it knows.

## Trigger points

Two hooks drive the loop — they are the only moving parts:

1. **On invocation** — every `SKILL.md` carries a `!command` that runs `recall.py` at
   skill-load time, inlining the skill's current repo context *above* the method. This is
   native Claude Code dynamic context; it fires on both explicit (`/skill`) and
   auto-invoked skills. (Confirmed empirically.)
2. **On failure** — `ingest.py` mines failing test output for repo-specific facts
   (deterministic, **no LLM**) and writes them to the skill's context. The next invocation
   is smarter.

```
skill invoked ──▶ recall.py inlines learned context ──▶ agent runs
                                                            │
                                              tests fail ◀──┘
                                                   │
                                   ingest.py learns the fact (no LLM)
                                                   │
                                   next invocation: skill is better
```

## Measured

Real Claude agents, real pytest, a task whose answer is a repo convention the agent
cannot guess (so the learned context is the decisive variable):

| | result |
|---|---|
| `SKILL.md` only (no context) | **0/3** passed |
| after one failure → auto-learned context | **3/3** passed |

The skill evolved from 0/3 to 3/3 — and `SKILL.md` was never edited. (N=3/arm; the task
is convention-decisive to isolate the variable. More rollouts and task shapes would
harden the headline number.)

## Parts

| File | Role |
|------|------|
| `recall.py` | **invocation trigger** — skill-scoped context, inlined at load. Stdlib-only, never raises. |
| `ingest.py` | **failure trigger** — learns repo facts from test output, deterministic, no LLM. |
| `remember.py` | record a fact by hand. |
| `binder.py` | wire the invocation trigger into every `SKILL.md` (idempotent, reversible). |
| `facts.py` | the context store (markdown, per-skill, per-project). |

## No conversion, no rewriting

Skills stay markdown. Nothing is parsed into JSON or rewritten — `binder.py` injects one
marker-delimited hook line and reads `name:` from frontmatter; that's the only edit, and
`--unbind` removes it cleanly. Context lives in separate markdown facts, never in the skill.

## Optional: claude-mem as a second context source

`recall.py` can also read [claude-mem](https://github.com/thedotmack/claude-mem) as a
secondary source (`YUNAKI_USE_CLAUDE_MEM=1`, **off by default**). It's off because its
search is project-scoped, not skill-scoped, and its compression is unreliable on the
worker runtime. The local store is the skill-scoped, deterministic primary.

## The previous approach

`self-evolution-v1/` is the archived prior project — it *rewrote* skills with an LLM (and
converted md→json to do so). We measured that it degrades skills, which is why this
project evolves context instead. Left intact for reference; don't modify it.

## Develop

```bash
python3 -m pytest tests/ -v     # offline; no network, no LLM
```
See [install.md](install.md) to wire the triggers onto your skills.
