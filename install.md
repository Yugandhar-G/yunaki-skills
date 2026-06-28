# Install

No build step, stdlib-only, markdown in/out. Works for anyone — nothing is hardcoded to a
particular user or repo: paths resolve from your clone and `~/.claude`, and the PR ingester
auto-detects the repo from its git remote. Requires Python 3.11+ (and `gh`, authenticated,
only if you use the PR source).

## 1. One-command setup

```bash
git clone <this-repo> && cd <this-repo>
./install.sh
```

That binds every `~/.claude/skills/*/SKILL.md` (so each skill recalls repo context at load
time) and registers a SessionStart hook (so newly-installed skills bind automatically). It's
idempotent and reversible:

```bash
./install.sh --uninstall      # unbind skills + remove the hook
```

Prefer to do it by hand? The installer just runs these:

```bash
./binder.py --all             # bind every skill (idempotent; --unbind to reverse)
./register_hook.py            # add the SessionStart re-bind hook to ~/.claude/settings.json
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

Run these from inside any git repo you work in — the repo is auto-detected from its git
remote. They mine the repo's merged PRs (verbatim titles, review comments, commit subjects
via `gh` — deterministic, no LLM), then curate the store:

```bash
cd /path/to/your/repo
/path/to/this/ingest_pr.py                       # auto-detects the repo (--repo owner/name to override)
/path/to/this/consolidate.py --dry-run           # preview dedup/supersede/prune
/path/to/this/consolidate.py                      # apply
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
