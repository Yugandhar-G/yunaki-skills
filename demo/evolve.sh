#!/usr/bin/env bash
# Live demo: a skill that learns a repo convention from one failure — no LLM, and the
# skill file is never edited. Deterministic and reproducible, so it records cleanly.
#
#   ./demo/evolve.sh                 # paced for recording (press Enter between beats)
#   DEMO_AUTO=1 ./demo/evolve.sh     # run straight through (for a dry run)
#
# Live shared-service shot at the end needs:
#   export SUPERMEM_URL=https://<ip>.sslip.io  SUPERMEM_TOKEN=<your token>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL="demo-slug"
export YUNAKI_FACTS_DIR="$ROOT/demo/.facts"   # isolated store, so your real one is untouched
rm -rf "$YUNAKI_FACTS_DIR"

b() { printf '\n\033[1;36m%s\033[0m\n' "$*"; }      # cyan header
dim() { printf '\033[2m%s\033[0m\n' "$*"; }
pause() { [ "${DEMO_AUTO:-0}" = 1 ] || read -rp $'\033[2m   … press Enter …\033[0m'; }

clear 2>/dev/null || true
b "1 │ The skill knows its METHOD — but nothing about THIS repo yet."
dim "What the skill recalls right now:"
python3 "$ROOT/recall.py" --skill "$SKILL" --project demo --query "slugify convention" || true
echo "   (empty — it has learned nothing)"
pause

b "2 │ An agent does the task. It writes the obvious slug… and fails our convention."
( cd "$ROOT/demo/task" && python3 -m pytest -q test_slugify.py 2>&1 \
    | grep -E "assert |FAILED|failed in" | head -4 )
pause

b "3 │ Feed that failure in. Pure extraction — NO LLM."
( cd "$ROOT/demo/task" && python3 -m pytest -q test_slugify.py 2>&1 \
    | python3 "$ROOT/ingest.py" --skill "$SKILL" --project demo )
pause

b "4 │ The skill just got smarter — and we never touched the skill file."
dim "What it recalls now:"
python3 "$ROOT/recall.py" --skill "$SKILL" --project demo --query "slugify convention"
echo
dim "The learned fact lives in its OWN file, not in the skill:"
ls "$YUNAKI_FACTS_DIR"/demo/facts/*.md 2>/dev/null | sed "s#$ROOT/##"
echo "   → SKILL.md is byte-for-byte unchanged. The context evolved, not the method."
pause

b "5 │ Measured on real Claude agents + real pytest (convention-decisive task):"
echo "      SKILL.md alone ............ 0 / 3 passed"
echo "      after one auto-learned fact 3 / 3 passed     (no LLM, no edits to the skill)"
pause

b "6 │ Not just local — deployed, shared across the team, self-evolving."
if [ -n "${SUPERMEM_URL:-}" ] && [ -n "${SUPERMEM_TOKEN:-}" ]; then
  dim "GET $SUPERMEM_URL/recall  (real PR knowledge, over HTTPS, per-repo token):"
  curl -sS --max-time 8 -H "Authorization: Bearer $SUPERMEM_TOKEN" \
    "$SUPERMEM_URL/recall?skill=code-review&query=ci%20required%20checks&limit=4"
  echo
  echo "   → fed automatically by merged PRs via a GitHub webhook. This is live."
else
  dim "set SUPERMEM_URL and SUPERMEM_TOKEN to show the live deployed service here."
fi
echo
b "Same skill. We never rewrote it. It learned — locally and at team scale."
