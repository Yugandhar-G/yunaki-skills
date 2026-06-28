#!/usr/bin/env bash
# One-command setup for skill evolution — works for any user, any machine.
#
# Wires the always-on pieces using YOUR clone's absolute paths:
#   1. binds every ~/.claude/skills/*/SKILL.md so it recalls repo context when invoked
#   2. registers a SessionStart hook so newly-installed skills get bound automatically
#   3. seeds the memory from this repo's code so an invoked skill recalls its conventions,
#      before anything is ever run, and without waiting for a failure
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

# Seed the memory from THIS repo's code so an invoked skill recalls its conventions,
# before anything is ever run, and without waiting for a failure.
echo "Scanning this repo's code for conventions ..."
( cd "$HERE" && "$PY" "$HERE/codegraph.py" --write ) || true

cat <<EOF

Done. When you invoke a skill it now recalls this machine's repo context (no failure
needed); new skills bind automatically each session; and this repo's conventions were
scanned into memory, so an invoked skill arrives already loaded.

Optional — turn on the self-evolving super memory inside any git repo you work in:
  cd /path/to/your/repo
  $HERE/ingest_pr.py                 # mine merged-PR knowledge (auto-detects the repo)
  $HERE/ingest_pr.py --install-git-hook   # re-ingest + curate on every pull/merge

Undo everything with:  $HERE/install.sh --uninstall
EOF
