#!/usr/bin/env python3
"""Bind skills to their memory: inject a per-skill recall hook into SKILL.md.

This realizes the "install creates a hook for every skill" directive. For each
SKILL.md it inserts, right after the YAML frontmatter, a marker-delimited block
that runs `recall.py --skill <name>` at skill-load time (a native `!`command``).
The block is the ONLY thing we touch: idempotent (re-binding replaces, never
duplicates), reversible (`--unbind` removes it), and it never edits skill content.

Pairs with a SessionStart hook (`hooks/session-start-bind.sh`) that re-runs
`bind --all` so skills installed after setup get bound automatically.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import shlex

START = "<!-- yunaki-memory:start -->"
END = "<!-- yunaki-memory:end -->"
_BLOCK_RE = re.compile(
    r"\n*" + re.escape(START) + r".*?" + re.escape(END) + r"\n*",
    re.DOTALL,
)
_NAME_RE = re.compile(r"""^name:\s*["']?([^"'\n]+?)["']?\s*$""", re.MULTILINE)
# Allowlist for skill names that may appear in the generated command, as defense in
# depth on top of shlex.quote. Anything else is sanitized to a safe slug.
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9 _.\-]")

_RECALL_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recall.py")
_SKILLS_DIR_DEFAULT = os.path.expanduser("~/.claude/skills")


# ── pure text transforms (no I/O) ────────────────────────────────────────────


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return (head, body) where head includes the closing `---` fence + newline.

    ("", text) when there is no well-formed YAML frontmatter."""
    if not text.startswith("---"):
        return "", text
    lines = text.splitlines(keepends=True)
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":  # .strip() tolerates CRLF and trailing spaces
            return "".join(lines[: i + 1]), "".join(lines[i + 1 :])
    return "", text


def derive_name(text: str, fallback: str) -> str:
    """Read `name:` from frontmatter; fall back to the skill's directory name."""
    head, _ = split_frontmatter(text)
    if head:
        match = _NAME_RE.search(head)
        if match:
            return match.group(1).strip()
    return fallback


def _safe_name(name: str) -> str:
    """Strip shell-dangerous characters from a skill name (allowlist)."""
    return _SAFE_NAME_RE.sub("", name).strip() or "skill"


def build_block(recall_path: str, name: str) -> str:
    """The marker-delimited recall block injected into a SKILL.md.

    The skill name is allowlist-sanitized AND shell-quoted, and the path is
    shell-quoted, so a crafted `name:` cannot inject a command into the `!`...``
    block (which the host executes at skill-load time)."""
    cmd = f"{shlex.quote(recall_path)} --skill {shlex.quote(_safe_name(name))}"
    return (
        f"{START}\n"
        f"!`{cmd}`\n"
        "> If you discover a repo-specific fact this skill needed, "
        "save it so future runs benefit.\n"
        f"{END}"
    )


def strip_block(text: str) -> str:
    """Remove any existing recall block and collapse the gap it leaves."""
    stripped = _BLOCK_RE.sub("\n\n", text)
    return re.sub(r"\n{3,}", "\n\n", stripped)


def bind_text(text: str, recall_path: str, name: str) -> str:
    """Return `text` with exactly one fresh recall block after the frontmatter."""
    base = strip_block(text)
    head, body = split_frontmatter(base)
    block = build_block(recall_path, name)
    if head:
        return f"{head}\n{block}\n\n{body.lstrip(chr(10))}"
    return f"{block}\n\n{body.lstrip(chr(10))}"


def unbind_text(text: str) -> str:
    """Return `text` with the recall block removed (a single trailing newline)."""
    return strip_block(text).rstrip() + "\n"


# ── file-level operations ────────────────────────────────────────────────────


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def bind_skill(path: str, recall_path: str = _RECALL_DEFAULT, name: str | None = None) -> bool:
    """Bind one SKILL.md. Returns True if the file changed."""
    text = _read(path)
    resolved = name or derive_name(text, os.path.basename(os.path.dirname(path)))
    new_text = bind_text(text, recall_path, resolved)
    if new_text != text:
        _write(path, new_text)
        return True
    return False


def unbind_skill(path: str) -> bool:
    """Remove the recall block from one SKILL.md. Returns True if it changed."""
    text = _read(path)
    new_text = unbind_text(text)
    if new_text != text:
        _write(path, new_text)
        return True
    return False


def bind_all(
    skills_dir: str = _SKILLS_DIR_DEFAULT,
    recall_path: str = _RECALL_DEFAULT,
    unbind: bool = False,
) -> dict[str, bool]:
    """(Un)bind every `<skills_dir>/*/SKILL.md`. Returns {path: changed}."""
    results: dict[str, bool] = {}
    for skill_md in sorted(glob.glob(os.path.join(skills_dir, "*", "SKILL.md"))):
        results[skill_md] = unbind_skill(skill_md) if unbind else bind_skill(skill_md, recall_path)
    return results


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Inject/remove the per-skill recall hook.")
    p.add_argument("--skills-dir", default=_SKILLS_DIR_DEFAULT)
    p.add_argument("--skill", default=None, help="path to a single SKILL.md")
    p.add_argument("--all", action="store_true", help="process every skill in --skills-dir")
    p.add_argument("--unbind", action="store_true", help="remove the block instead of adding")
    p.add_argument("--recall-path", default=_RECALL_DEFAULT)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.skill:
        changed = (
            unbind_skill(args.skill) if args.unbind else bind_skill(args.skill, args.recall_path)
        )
        verb = "unbound" if args.unbind else "bound"
        print(f"{verb} {args.skill}: {'changed' if changed else 'no-op'}")
        return 0
    if args.all:
        results = bind_all(args.skills_dir, args.recall_path, unbind=args.unbind)
        count = sum(1 for v in results.values() if v)
        verb = "unbound" if args.unbind else "bound"
        print(f"{verb} {count}/{len(results)} skills in {args.skills_dir}")
        return 0
    print("nothing to do: pass --skill <SKILL.md> or --all")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
