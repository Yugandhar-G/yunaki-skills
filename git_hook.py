#!/usr/bin/env python3
"""Install the super-memory post-merge trigger into a repo's git hooks. Stdlib only.

Wires `hooks/post-merge-ingest.sh` into `<repo>/.git/hooks/post-merge` so that every
`git pull`/`git merge` re-ingests new PRs and curates the store (the self-evolution
loop). The edit is marker-scoped and idempotent: it appends our block to any existing
post-merge hook and `--uninstall` removes exactly that block, leaving the rest intact.

Usage:
    ./git_hook.py                 # install into the current repo
    ./git_hook.py --uninstall
    ./git_hook.py --repo-root /path/to/repo
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import stat
import subprocess

START = "# >>> yunaki super-memory >>>"
END = "# <<< yunaki super-memory <<<"
_DEFAULT_SCRIPT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "hooks", "post-merge-ingest.sh"
)
_BLOCK_RE = re.compile(rf"\n*{re.escape(START)}.*?{re.escape(END)}\n*", re.DOTALL)


def build_block(script_path: str) -> str:
    """The marker-scoped block that invokes our hook script (shell-quoted)."""
    return f"{START}\n{shlex.quote(script_path)} || true\n{END}\n"


def _strip_block(text: str) -> str:
    return _BLOCK_RE.sub("\n", text).strip("\n")


def resolve_hooks_dir(repo_root: str) -> str:
    """The repo's hooks dir (honors worktrees / core.hooksPath), falling back to
    <repo_root>/.git/hooks when git isn't available."""
    argv = ["git", "-C", repo_root, "rev-parse", "--git-path", "hooks"]
    try:
        # argv is a fixed literal list, no shell — the S603 injection risk can't occur.
        r = subprocess.run(argv, capture_output=True, text=True, timeout=15)  # noqa: S603
        if r.returncode == 0 and r.stdout.strip():
            path = r.stdout.strip()
            return path if os.path.isabs(path) else os.path.join(repo_root, path)
    except (OSError, subprocess.SubprocessError):
        pass
    return os.path.join(repo_root, ".git", "hooks")


def install(hooks_dir: str, script_path: str = _DEFAULT_SCRIPT) -> str:
    """Install/refresh the post-merge block. Returns the hook path. Idempotent."""
    os.makedirs(hooks_dir, exist_ok=True)
    hook = os.path.join(hooks_dir, "post-merge")
    existing = ""
    if os.path.exists(hook):
        with open(hook, encoding="utf-8") as fh:
            existing = fh.read()
    body = _strip_block(existing)
    if not body:
        body = "#!/usr/bin/env bash"
    content = body + "\n\n" + build_block(script_path)
    with open(hook, "w", encoding="utf-8") as fh:
        fh.write(content)
    mode = os.stat(hook).st_mode
    os.chmod(hook, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return hook


def uninstall(hooks_dir: str) -> bool:
    """Remove our block from the post-merge hook. Returns True if anything changed."""
    hook = os.path.join(hooks_dir, "post-merge")
    if not os.path.exists(hook):
        return False
    with open(hook, encoding="utf-8") as fh:
        original = fh.read()
    if START not in original:
        return False
    remaining = _strip_block(original)
    # If only the shebang is left, remove the now-empty hook entirely.
    if remaining.strip() in ("", "#!/usr/bin/env bash", "#!/bin/sh", "#!/bin/bash"):
        os.remove(hook)
        return True
    with open(hook, "w", encoding="utf-8") as fh:
        fh.write(remaining + "\n")
    return True


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Install the super-memory post-merge git hook.")
    p.add_argument("--repo-root", default=".", help="repo to install into (default: cwd)")
    p.add_argument("--script", default=_DEFAULT_SCRIPT, help="hook script to invoke")
    p.add_argument("--uninstall", action="store_true", help="remove the hook block")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    hooks_dir = resolve_hooks_dir(os.path.abspath(args.repo_root))
    try:
        if args.uninstall:
            changed = uninstall(hooks_dir)
            print("removed post-merge hook block" if changed else "no hook block to remove")
        else:
            path = install(hooks_dir, args.script)
            print(f"installed post-merge hook -> {path}")
    except OSError as e:
        print(f"git-hook install failed: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
