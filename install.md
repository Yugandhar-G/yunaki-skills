# Install

Wire the two trigger points onto your skills. No build step, stdlib-only, markdown in/out.

## 1. Wire the invocation trigger into your skills

`binder.py` injects one marker-delimited `!command` block into each `SKILL.md` so that, at
skill-load time, `recall.py` inlines the skill's learned repo context above the method.
Idempotent (re-binding replaces), reversible (`--unbind`), and it never edits skill content.

```bash
./binder.py --all                                   # bind every ~/.claude/skills/*/SKILL.md
./binder.py --skill ~/.claude/skills/api-design/SKILL.md   # one skill
./binder.py --all --unbind                          # remove the blocks
```

Keep new skills wired automatically — register the SessionStart hook in
`~/.claude/settings.json` (use the absolute path from `pwd`):

```json
{ "hooks": { "SessionStart": [ { "hooks": [
  { "type": "command", "command": "/ABSOLUTE/PATH/hooks/session-start-bind.sh" }
] } ] } }
```

## 2. Give skills context (the failure trigger + manual)

```bash
# Learn automatically from a failing run (deterministic, no LLM):
pytest -ra ... 2>&1 | ./ingest.py --skill api-design

# Or record a fact by hand:
./remember.py --skill api-design --title "EmailStr needs email-validator" \
  "FastAPI EmailStr requires the email-validator package or imports 500 at startup."
```

## 3. Build the super memory from PRs (and let it self-evolve)

Seed the store from the repo's merged PRs (verbatim titles, review comments, commit
subjects via `gh` — deterministic, no LLM), then curate it:

```bash
./ingest_pr.py --repo owner/name --limit 30     # or just ./ingest_pr.py inside the repo
./consolidate.py --dry-run                       # preview dedup/supersede/prune
./consolidate.py                                 # apply
```

Wire the self-evolution so it keeps up automatically — a git `post-merge` hook re-ingests
new PRs and re-curates on every `git pull`/`git merge`:

```bash
./ingest_pr.py --install-git-hook                # idempotent; --uninstall-git-hook to remove
```

Ingest is incremental (a per-project watermark tracks the highest PR seen). `gh` must be
installed and authenticated; if it isn't, ingestion writes nothing rather than failing.
Tune curation with `YUNAKI_SUPERSEDE_KEEP` (facts kept per topic, default 2) and
`YUNAKI_FACT_TTL_DAYS` (age-prune, default off).

## 4. Verify

```bash
./recall.py --skill api-design --query "validation"   # prints the skill's context, or nothing
python3 -m pytest tests/ -v                            # offline suite
```

Context is stored as per-project markdown under `~/.claude/skill-memory/<project>/facts/`
(override with `YUNAKI_FACTS_DIR`). A skill with no facts recalls nothing, so a bound skill
behaves exactly like an unbound one until it has learned something.

## Optional: claude-mem as a second context source

Off by default. To also read [claude-mem](https://github.com/thedotmack/claude-mem)
observations as a secondary source, set `YUNAKI_USE_CLAUDE_MEM=1`. Note its search is only
project-scoped (not skill-scoped) and its compression is unreliable on the worker runtime;
the local store is the skill-scoped, deterministic primary.
