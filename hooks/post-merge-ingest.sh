#!/usr/bin/env bash
# Super-memory post-merge trigger.
#
# Installed as a repo's git `post-merge` hook (see ../git_hook.py), this fires after
# every `git pull` / `git merge` and keeps the super memory current: it re-scans the code
# for conventions (codegraph), incrementally ingests any newly-merged PRs (from the
# watermark), then curates the store (dedup / supersede / prune). That is the
# self-evolution loop — the memory tracks the repo as it changes.
#
# It runs detached so a merge/pull never blocks on the network, and every step is
# non-fatal: a missing or unauthenticated `gh` simply ingests nothing.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${YUNAKI_PYTHON:-python3}"

(
  "$PY" "$HERE/../codegraph.py" --write >/dev/null 2>&1 || true   # re-scan code → refresh conventions
  "$PY" "$HERE/../ingest_pr.py" >/dev/null 2>&1 || true
  "$PY" "$HERE/../consolidate.py" >/dev/null 2>&1 || true
) &

exit 0
