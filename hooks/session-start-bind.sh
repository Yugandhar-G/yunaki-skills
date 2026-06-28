#!/usr/bin/env bash
# claude-mem skill binder — SessionStart hook.
#
# Re-binds every skill at session start so skills installed AFTER initial setup
# get their per-skill memory-recall hook automatically. Idempotent: binder only
# rewrites a SKILL.md when its recall block is missing or changed, so steady-state
# runs are all no-ops and cost nothing.
#
# Register in ~/.claude/settings.json (use the absolute path printed by `pwd`):
#   "hooks": { "SessionStart": [ { "hooks": [
#     { "type": "command", "command": "/ABSOLUTE/PATH/hooks/session-start-bind.sh" }
#   ] } ] }
#
# Emits no additionalContext; it only maintains bindings.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${YUNAKI_PYTHON:-python3}"
SKILLS_DIR="${YUNAKI_SKILLS_DIR:-$HOME/.claude/skills}"

"$PY" "$HERE/../binder.py" --all --skills-dir "$SKILLS_DIR" >/dev/null 2>&1 || true
exit 0
