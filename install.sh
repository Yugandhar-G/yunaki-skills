#!/usr/bin/env bash
# One-command setup for skill evolution — works for any user, any machine.
#
# Wires the two always-on pieces using YOUR clone's absolute paths:
#   1. binds every ~/.claude/skills/*/SKILL.md so it recalls repo context at load time
#   2. registers a SessionStart hook so newly-installed skills get bound automatically
#
# Idempotent and reversible (`./install.sh --uninstall`). Nothing is hardcoded to any
# user or repo: paths resolve from this script's location and ~/.claude, and the PR
# ingester auto-detects the repo from its git remote.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${YUNAKI_PYTHON:-python3}"

if [ "${1:-}" = "--uninstall" ]; then
  echo "Removing skill-evolution wiring..."
  "$PY" "$HERE/register_hook.py" --uninstall
  "$PY" "$HERE/binder.py" --all --unbind
  echo "Done. Skills are unbound and the SessionStart hook is removed."
  exit 0
fi

echo "Wiring skill evolution into ~/.claude ..."
"$PY" "$HERE/binder.py" --all
"$PY" "$HERE/register_hook.py"

cat <<EOF

Done. Every skill now recalls this machine's repo context at load time, and new
skills bind automatically each session.

Optional — turn on the self-evolving super memory inside any git repo you work in:
  cd /path/to/your/repo
  $HERE/ingest_pr.py                 # mine merged-PR knowledge (auto-detects the repo)
  $HERE/ingest_pr.py --install-git-hook   # re-ingest + curate on every pull/merge

Undo everything with:  $HERE/install.sh --uninstall
EOF
