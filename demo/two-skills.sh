#!/usr/bin/env bash
# Two skills, two domains — watch each load ONLY its own conventions at invocation.
#   A) a backend skill ("add a Python module") invoked in THIS Python repo
#   B) a frontend skill (react-patterns) invoked in a React repo
# Deterministic, offline, no LLM. Re-runnable.
#
#   ./demo/two-skills.sh
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
unset YUNAKI_SUPERMEM_URL YUNAKI_USE_CLAUDE_MEM 2>/dev/null || true  # purely local

b()   { printf '\n\033[1;36m%s\033[0m\n' "$*"; }
dim() { printf '\033[2m%s\033[0m\n' "$*"; }

# ───────────────────────── A · backend skill, this Python repo ─────────────────────────
b "A │ Backend skill — 'add a Python module' (demo/skills/yugandhar.md) — invoked in THIS repo"
export YUNAKI_FACTS_DIR="$ROOT/demo/.facts-be"; rm -rf "$YUNAKI_FACTS_DIR"
dim "scan the codebase into memory — no test, no failure, no LLM:"
python3 codegraph.py --write | sed "s#$ROOT/##" | head -1
dim "now invoke the skill   →   recall.py --skill yugandhar"
python3 recall.py --skill yugandhar

# ───────────────────────── B · frontend skill, a React repo ─────────────────────────
b "B │ Frontend skill — react-patterns — invoked in a React repo"
export YUNAKI_FACTS_DIR="$ROOT/demo/.facts-fe"; rm -rf "$YUNAKI_FACTS_DIR"
dim "seed what a React repo's code + PRs teach (representative facts):"
python3 - <<'PY'
import facts, os
R = os.environ["YUNAKI_FACTS_DIR"]
for t, b in [
    ("Server Components by default; server state via TanStack Query, not Zustand",
     "React Server Components render on the server; use TanStack Query for server data in client components"),
    ("forms use React 19 useActionState, not manual onSubmit",
     "React 19 form actions with useActionState instead of onSubmit/useState handlers"),
    ("wrap React component state updates in await waitFor in tests",
     "React Testing Library: await waitFor around state changes to avoid act() warnings"),
]:
    facts.write_fact([], t, b, project="webapp", root=R)  # GLOBAL — the lens does the routing
print("  seeded 3 react facts")
PY
dim "now invoke the skill   →   recall.py --skill react-patterns --project webapp"
python3 recall.py --skill react-patterns --project webapp

b "Same engine, two skills: backend got the repo's Python rules, frontend got the React rules."
