#!/usr/bin/env bash
# Live wiring demo — take a BLANK skill and watch it get loaded from the codebase
# alone. No failure, no LLM. The skill's method is never rewritten; only its memory
# arrives. This is the "nothing up my sleeve" version: the skill starts empty.
#
#   ./demo/wire.sh                 # paced for stage (press Enter between beats)
#   DEMO_AUTO=1 ./demo/wire.sh     # run straight through (dry run / rehearsal)
#
# Optional live shared-service shot at the end needs:
#   export SUPERMEM_URL=https://<ip>.sslip.io  SUPERMEM_TOKEN=<token>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"                                          # project scope = repo basename, consistently
SKILL="yugandhar"
export YUNAKI_FACTS_DIR="$ROOT/demo/.facts-live"    # fresh, isolated store → starts empty, re-runnable
rm -rf "$YUNAKI_FACTS_DIR"
WORK="$YUNAKI_FACTS_DIR/_skills/$SKILL"             # throwaway copy, so the source skill stays pristine
mkdir -p "$WORK"; cp "$ROOT/demo/skills/$SKILL.md" "$WORK/$SKILL.md"
MD="$WORK/$SKILL.md"

b()   { printf '\n\033[1;36m%s\033[0m\n' "$*"; }    # cyan header
dim() { printf '\033[2m%s\033[0m\n' "$*"; }
ok()  { printf '\033[32m%s\033[0m\n' "$*"; }
hash() { python3 -c "import hashlib,sys;print(hashlib.md5(open(sys.argv[1],'rb').read()).hexdigest())" "$1"; }
pause() { [ "${DEMO_AUTO:-0}" = 1 ] || read -rp $'\033[2m   … press Enter …\033[0m'; }

clear 2>/dev/null || true

b "1 │ A real, generic skill: 'add a Python module.' Solid method — but it knows nothing about THIS repo."
cat "$MD"
dim "↑ A complete human-written method. No recall hook yet, and zero repo-specific knowledge."
pause

b "2 │ Wire it: inject the recall hook. This is the ONLY edit we ever make to a skill."
python3 "$ROOT/binder.py" --skill "$MD" >/dev/null 2>&1
sed -n '/yunaki-memory:start/,/yunaki-memory:end/p' "$MD"
dim "↑ a native \`!\`command\`\` that runs recall.py at skill-load time. The method below it is untouched."
echo
dim "What it recalls right now:  recall.py --skill $SKILL"
python3 "$ROOT/recall.py" --skill "$SKILL" || true
echo "   (empty — it still knows nothing about this repo)"
HASH_BEFORE="$(hash "$MD")"
pause

b "3 │ Read the CODEBASE into memory. No test, no failure, no LLM — just the source."
python3 "$ROOT/codegraph.py" --write | sed "s#$ROOT/##"
dim "Pure extraction: conventions proven by reading every module. Stored as GLOBAL facts."
pause

b "4 │ Invoke the same generic skill. It now arrives carrying THIS repo's rules.  ← the point"
dim "exactly what runs on invocation:  recall.py --skill $SKILL"
python3 "$ROOT/recall.py" --skill "$SKILL"
pause

b "5 │ Proof: the scan never touched the skill. Memory lives in its OWN files."
HASH_AFTER="$(hash "$MD")"
if [ "$HASH_BEFORE" = "$HASH_AFTER" ]; then
  ok "   yugandhar.md: byte-for-byte unchanged by the scan ($HASH_AFTER)"
else
  echo "   yugandhar.md: CHANGED — investigate"
fi
ls "$YUNAKI_FACTS_DIR"/*/facts/codebase-*.md 2>/dev/null | sed "s#$YUNAKI_FACTS_DIR/##" | head -4
dim "The method is fixed. The memory is what arrived — read from your code, in its own files."
pause

b "6 │ Not just local — one shared brain, fed by merged PRs, recalled team-wide over HTTPS."
if [ -n "${SUPERMEM_URL:-}" ] && [ -n "${SUPERMEM_TOKEN:-}" ]; then
  dim "GET $SUPERMEM_URL/recall  (real PR knowledge, per-repo token):"
  curl -sS --max-time 8 -H "Authorization: Bearer $SUPERMEM_TOKEN" \
    "$SUPERMEM_URL/recall?skill=code-review&query=ci%20required%20checks&limit=4" || true
  echo; echo "   → fed automatically by merged PRs via a GitHub webhook. This is live."
else
  dim "set SUPERMEM_URL and SUPERMEM_TOKEN to show the live deployed service here."
fi
echo
b "A generic skill, now repo-aware — loaded from your code. The method never moved; only the memory arrived. That's skill evolution."
