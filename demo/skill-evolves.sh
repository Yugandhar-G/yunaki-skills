#!/usr/bin/env bash
# One real skill, three lessons. Watch a skill accumulate repo conventions from failing
# tests — deterministically, no LLM — while its SKILL.md body never changes. This is the
# "skills keep evolving, agents evolve with them" story across multiple task shapes.
#
#   ./demo/skill-evolves.sh              # paced for recording
#   DEMO_AUTO=1 ./demo/skill-evolves.sh  # straight through
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL="repo-conventions"
export YUNAKI_FACTS_DIR="$ROOT/demo/.facts"
rm -rf "$YUNAKI_FACTS_DIR"
SKDIR="$YUNAKI_FACTS_DIR/_skills"        # throwaway copy so the repo's SKILL.md stays unbound
mkdir -p "$SKDIR"; cp -r "$ROOT/demo/skills/$SKILL" "$SKDIR/"
MD="$SKDIR/$SKILL/SKILL.md"

b() { printf '\n\033[1;36m%s\033[0m\n' "$*"; }
dim() { printf '\033[2m%s\033[0m\n' "$*"; }
pause() { [ "${DEMO_AUTO:-0}" = 1 ] || read -rp $'\033[2m   … press Enter …\033[0m'; }

clear 2>/dev/null || true
b "1 │ A real skill — static method + a recall hook. (binding it now)"
python3 "$ROOT/binder.py" --skill "$MD" >/dev/null 2>&1
sed -n '1,12p' "$MD"
dim "↑ the hook recalls learned context; below it, the human-written method. Both fixed."
pause

b "2 │ What this skill knows about the repo right now:"
python3 "$ROOT/recall.py" --skill "$SKILL" --project demo --query "conventions" || true
echo "   (nothing yet)"
pause

b "3 │ Three tasks. Each one fails on a convention the agent can't guess — and teaches it."
for t in slug status timestamps; do
  printf '\n\033[2m── task: %s ──\033[0m\n' "$t"
  ( cd "$ROOT/demo/tasks/$t" && python3 -m pytest -q 2>&1 | grep -E "assert |failed in" | head -2 )
  ( cd "$ROOT/demo/tasks/$t" && python3 -m pytest -q 2>&1 \
      | python3 "$ROOT/ingest.py" --skill "$SKILL" --project demo )
done
pause

b "4 │ The skill has EVOLVED — it now carries all three conventions:"
python3 "$ROOT/recall.py" --skill "$SKILL" --project demo --query "convention status timestamp slug"
pause

b "5 │ The skill's METHOD never changed — only its memory did."
# Compute these, don't claim them: count real fact files + verify the repo's SKILL.md
# is byte-for-byte unchanged (the demo binds a throwaway copy, never the original).
FACTS=$(find "$YUNAKI_FACTS_DIR/demo/facts" -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
if git -C "$ROOT" diff --quiet -- "demo/skills/$SKILL/SKILL.md" 2>/dev/null; then BODY="unchanged"; else BODY="CHANGED"; fi
printf '   SKILL.md body : %s   (verified: git diff --quiet demo/skills/%s/SKILL.md)\n' "$BODY" "$SKILL"
printf '   facts learned : %s   (counted in the store)   ·   LLM calls : none, by design\n' "$FACTS"
echo
b "One skill. Three lessons. Body never rewritten — it keeps evolving, and the agents using it evolve with it."
