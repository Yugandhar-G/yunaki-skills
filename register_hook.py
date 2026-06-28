#!/usr/bin/env python3
"""Register the SessionStart re-bind hook in ~/.claude/settings.json. Stdlib only.

So skills installed after setup still get their recall block, Claude Code needs a
SessionStart hook that re-runs the binder each session. Editing settings.json by hand is
the one piece of setup that isn't obvious, so this does it idempotently and reversibly:
it adds exactly one entry pointing at hooks/session-start-bind.sh, leaves every other
setting untouched, and refuses to overwrite a settings file it can't parse (fail loud
rather than clobber a user's config).

Usage:
    ./register_hook.py                 # add the hook to ~/.claude/settings.json
    ./register_hook.py --uninstall
    ./register_hook.py --settings /path/to/settings.json
"""

from __future__ import annotations

import argparse
import json
import os

DEFAULT_SETTINGS = os.path.expanduser("~/.claude/settings.json")
_BIND_SCRIPT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "hooks", "session-start-bind.sh"
)


def hook_command(repo_root: str | None = None) -> str:
    """Absolute command Claude Code runs at SessionStart."""
    if repo_root:
        return os.path.join(os.path.abspath(repo_root), "hooks", "session-start-bind.sh")
    return _BIND_SCRIPT


def _load(settings_path: str) -> dict:
    """Load settings, or {} if absent. Raises ValueError on malformed JSON so we never
    overwrite a config we couldn't understand."""
    if not os.path.exists(settings_path):
        return {}
    with open(settings_path, encoding="utf-8") as fh:
        text = fh.read().strip()
    if not text:
        return {}
    data = json.loads(text)  # JSONDecodeError (a ValueError) propagates intentionally
    if not isinstance(data, dict):
        raise ValueError("settings.json is not a JSON object")
    return data


def _save(settings_path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(settings_path) or ".", exist_ok=True)
    with open(settings_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def _groups(data: dict) -> list:
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return []
    ss = hooks.get("SessionStart")
    return ss if isinstance(ss, list) else []


def _has_command(data: dict, command: str) -> bool:
    for group in _groups(data):
        if isinstance(group, dict):
            for h in group.get("hooks", []) or []:
                if isinstance(h, dict) and h.get("command") == command:
                    return True
    return False


def register(settings_path: str, command: str) -> bool:
    """Add the SessionStart hook if absent. Returns True if it changed anything."""
    data = _load(settings_path)
    if _has_command(data, command):
        return False
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks.get("SessionStart"), list):
        hooks["SessionStart"] = []
    hooks["SessionStart"].append({"hooks": [{"type": "command", "command": command}]})
    _save(settings_path, data)
    return True


def unregister(settings_path: str, command: str) -> bool:
    """Remove our SessionStart hook (and any group it leaves empty). Returns changed."""
    if not os.path.exists(settings_path):
        return False
    data = _load(settings_path)
    if not _has_command(data, command):
        return False
    kept = []
    for group in _groups(data):
        inner = [h for h in group.get("hooks", []) or [] if h.get("command") != command]
        if inner:
            kept.append({**group, "hooks": inner})
    data["hooks"]["SessionStart"] = kept
    _save(settings_path, data)
    return True


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Register the SessionStart re-bind hook.")
    p.add_argument("--settings", default=DEFAULT_SETTINGS, help="settings.json path")
    p.add_argument("--repo-root", default=None, help="repo root (default: this script's repo)")
    p.add_argument("--uninstall", action="store_true", help="remove the hook")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    command = hook_command(args.repo_root)
    try:
        if args.uninstall:
            changed = unregister(args.settings, command)
            print("removed SessionStart hook" if changed else "no SessionStart hook to remove")
        else:
            changed = register(args.settings, command)
            print(
                "registered SessionStart hook" if changed else "SessionStart hook already present"
            )
    except (OSError, ValueError) as e:
        print(f"could not update {args.settings}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
