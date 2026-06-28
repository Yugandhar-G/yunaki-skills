# Skill Evolution — Project Context

## What This Is
Skills that improve over time **without being rewritten**. A skill = its `SKILL.md` (the
static, human-written method) + the **context it has learned** about this repo. We never
edit the skill body — we evolve its context. Rewriting skills with an LLM was measured to
degrade them (see `self-evolution-v1/`, the archived prior approach), so this project
moves the evolution into the context, triggered by hooks.

## Trigger points (the only moving parts)
- **Invocation trigger**: every `SKILL.md` carries a `!command` (native Claude Code dynamic
  context) that runs `recall.py` at skill-load time and inlines the skill's current repo
  context above the method. Fires on explicit and auto-invoked skills (confirmed empirically).
- **Failure trigger**: `ingest.py` mines failing test output for repo facts (deterministic,
  no LLM) and writes them to the skill's context. Next invocation is smarter.

## Key files (all at repo root, stdlib-only, never raise to the caller)
- `recall.py` — invocation trigger. Reads the local context store (primary, skill-scoped);
  claude-mem is an OPT-IN secondary source (`YUNAKI_USE_CLAUDE_MEM=1`, default off). Prints a
  markdown block or nothing. Auto-detects claude-mem's port from `~/.claude-mem/worker.pid`.
- `ingest.py` — failure trigger. `pytest ... | ./ingest.py --skill X` extracts facts
  (missing deps, failed-test conventions, expected-vs-actual examples). No LLM.
- `facts.py` — the context store: per-project markdown facts with `skills:` frontmatter tags.
- `remember.py` — record a fact by hand (`--skill X --title ... "body"`).
- `binder.py` — injects/removes the per-skill `!command` block in `SKILL.md`. Idempotent,
  marker-scoped, reversible; **never edits skill content**. `bind_all` walks `~/.claude/skills`.
  Shell-injection-safe (shlex-quoted + name allowlist).
- `hooks/session-start-bind.sh` — SessionStart hook to re-bind newly installed skills.
- `tests/` — offline only (no network/LLM). `conftest.py` puts repo root on `sys.path`.
- `self-evolution-v1/` — archived prior project (rewrote skills + md→json). Do not modify.

## No conversion / no rewriting
Skills stay markdown. Nothing is converted to JSON. The binder's hook line is the only edit
to a `SKILL.md`, and context lives in separate markdown facts.

## Conventions
- Stdlib-only; `recall.py`/`facts.py` must never raise — recall returns "" on any failure so
  a bound skill behaves exactly as unbound.
- No LLM in recall or ingest. Recall is deterministic; ingest is regex over test output.
- Tests are offline.

## Measured result
Real Claude agents + real pytest on a convention-decisive task: `SKILL.md` only = 0/3 passed;
after one failure auto-learned the convention (no LLM), `SKILL.md` + evolved context = 3/3.
The skill evolved without editing `SKILL.md`. (N=3/arm; convention-decisive task.)

## Commands
```bash
python3 -m pytest tests/ -v                       # offline suite (71 tests)
python3 -m ruff check *.py tests/                 # lint
./binder.py --all                                 # wire the invocation trigger onto all skills
./recall.py --skill <name> --query "..."          # what a skill recalls
pytest ... | ./ingest.py --skill <name>           # learn from a failure
```
