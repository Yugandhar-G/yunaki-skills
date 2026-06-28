#!/usr/bin/env bash
# Live demo — ALWAYS-ON first. A skill arrives carrying the repo's conventions the moment
# it is invoked, scanned straight from the code: no test, no failure, no LLM. THEN it keeps
# getting sharper from failures and merged PRs. The SKILL.md method is never rewritten.
#
#   ./demo/evolve.sh                 # paced for recording (press Enter between beats)
#   DEMO_AUTO=1 ./demo/evolve.sh     # run straight through (for a dry run)
#
# Live shared-service shot at the end needs:
#   export SUPERMEM_URL=https://<ip>.sslip.io  SUPERMEM_TOKEN=<your token>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL="repo-conventions"
export YUNAKI_FACTS_DIR="$ROOT/demo/.facts"   # isolated store, so your real one is untouched
rm -rf "$YUNAKI_FACTS_DIR"
SKDIR="$YUNAKI_FACTS_DIR/_skills"             # throwaway copy, so the repo's SKILL.md stays unbound
mkdir -p "$SKDIR"; cp -r "$ROOT/demo/skills/$SKILL" "$SKDIR/"
MD="$SKDIR/$SKILL/SKILL.md"

b() { printf '\n\033[1;36m%s\033[0m\n' "$*"; }      # cyan header
dim() { printf '\033[2m%s\033[0m\n' "$*"; }
ok() { printf '\033[32m%s\033[0m\n' "$*"; }
pause() { [ "${DEMO_AUTO:-0}" = 1 ] || read -rp $'\033[2m   … press Enter …\033[0m'; }

clear 2>/dev/null || true
b "1 │ A real skill: a fixed METHOD + a recall hook. Nothing learned yet."
python3 "$ROOT/binder.py" --skill "$MD" >/dev/null 2>&1
sed -n '1,11p' "$MD"
dim "↑ the hook recalls repo memory; below it, the human-written method. Both fixed."
echo
dim "What it recalls right now:"
python3 "$ROOT/recall.py" --skill "$SKILL" || true
echo "   (empty — it knows nothing about THIS repo yet)"
pause

b "2 │ Read the CODEBASE into memory. No test, no failure, no LLM — just the code."
python3 "$ROOT/codegraph.py" --write | sed "s#$ROOT/##"
dim "Pure extraction from your source: conventions proven by reading every module."
pause

b "3 │ Invoke the skill. BEFORE it does anything, it already carries them.  ← the point"
dim "exactly what runs on invocation:  recall.py --skill $SKILL"
python3 "$ROOT/recall.py" --skill "$SKILL"
echo
dim "That memory lives in its OWN files, not in the skill:"
ls "$YUNAKI_FACTS_DIR"/*/facts/codebase-*.md 2>/dev/null | sed "s#$YUNAKI_FACTS_DIR/##" | head -4
if git -C "$ROOT" diff --quiet -- "demo/skills/$SKILL/SKILL.md" 2>/dev/null; then
  ok "   repo SKILL.md: unchanged — no failure happened; it loaded from the code alone."
else
  echo "   repo SKILL.md: CHANGED"
fi
pause

b "4 │ And it keeps getting sharper — every failure and every merged PR feeds the SAME memory."
printf '\033[2m── a task fails on a convention the agent could not guess ──\033[0m\n'
( cd "$ROOT/demo/tasks/slug" && python3 -m pytest -q test_slugify.py 2>&1 ) \
    | grep -E "assert |failed in" | head -2
# ingest runs in the OUTER shell (same project as the scan), so the fact joins the same store
( cd "$ROOT/demo/tasks/slug" && python3 -m pytest -q test_slugify.py 2>&1 ) \
    | python3 "$ROOT/ingest.py" --skill "$SKILL"
echo
dim "the SAME memory now carries it too — was 4 facts, now 5:"
python3 "$ROOT/recall.py" --skill "$SKILL" --query "slug url underscore convention"
dim "no LLM — extracted from the failure. The method never moved; only the memory grew."
pause

b "5 │ Measured: real Claude agents, same task, only difference is the recalled context."
python3 "$ROOT/demo/ab.py"
pause

b "6 │ Not just local — deployed, shared across the team, self-evolving from merged PRs."
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
b "The skill is never rewritten. It arrives loaded from your code, and keeps evolving from every failure and PR — every agent that invokes it evolves with it."
