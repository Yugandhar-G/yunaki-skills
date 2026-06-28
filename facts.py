#!/usr/bin/env python3
"""Local, deterministic skill-fact store (markdown). No LLM, stdlib only.

This is the memory source we control — recall.py reads it as the PRIMARY source and
treats claude-mem as a secondary/best-effort source. Each fact is a markdown file with
frontmatter:

    ---
    skills: [api-design, fastapi-patterns]
    title: EmailStr requires email-validator
    ---
    FastAPI's EmailStr needs the email-validator package or imports 500 at startup.

Facts are scoped per project (cwd basename) under YUNAKI_FACTS_DIR. A fact with an
empty `skills:` list is global (returned for every skill). Never raises to the caller.
"""

from __future__ import annotations

import glob
import os
import re

DEFAULT_ROOT = os.path.expanduser(os.environ.get("YUNAKI_FACTS_DIR", "~/.claude/skill-memory"))
_SKILLS_RE = re.compile(r"^skills:\s*\[(.*?)\]\s*$", re.MULTILINE)
_TITLE_RE = re.compile(r"^title:\s*(.+?)\s*$", re.MULTILINE)
_MAX_LINE = 300


def facts_dir(project: str | None = None, root: str = DEFAULT_ROOT) -> str:
    """Per-project facts directory: <root>/<project>/facts (project=cwd basename)."""
    proj = project or os.path.basename(os.getcwd()) or "_global"
    return os.path.join(root, proj, "facts")


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter, body); ("", text) when there's no well-formed frontmatter."""
    if not text.startswith("---"):
        return "", text
    lines = text.splitlines(keepends=True)
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "".join(lines[1:i]), "".join(lines[i + 1 :])
    return "", text


def parse_fact(text: str) -> tuple[list[str], str, str]:
    """Parse a fact file into (skills, title, body)."""
    fm, body = _split_frontmatter(text)
    skills: list[str] = []
    skills_match = _SKILLS_RE.search(fm)
    if skills_match:
        skills = [s.strip().strip("\"'") for s in skills_match.group(1).split(",") if s.strip()]
    title_match = _TITLE_RE.search(fm)
    title = title_match.group(1).strip() if title_match else ""
    return skills, title, body.strip()


def load_facts(directory: str) -> list[tuple[list[str], str, str]]:
    """Load and parse every *.md fact in a directory. Skips unreadable files."""
    out: list[tuple[list[str], str, str]] = []
    for path in sorted(glob.glob(os.path.join(directory, "*.md"))):
        try:
            with open(path, encoding="utf-8") as fh:
                out.append(parse_fact(fh.read()))
        except OSError:
            continue
    return out


def _relevant(skills: list[str], skill: str) -> bool:
    """A fact is relevant if it's tagged for this skill or is global (no tags)."""
    return (not skills) or (skill in skills)


def fetch(
    skill: str,
    query: str | None = None,
    project: str | None = None,
    limit: int = 8,
    root: str = DEFAULT_ROOT,
) -> str:
    """Return a markdown bullet body of facts for `skill` (or ""). Never raises.

    When `query` is given, facts are ranked by keyword overlap with the query."""
    try:
        facts = load_facts(facts_dir(project, root))
    except OSError:
        return ""
    matches = [(t, b) for (sk, t, b) in facts if _relevant(sk, skill)]
    if query:
        terms = [w.lower() for w in re.findall(r"\w+", query)]
        if terms:

            def score(item: tuple[str, str]) -> int:
                hay = f"{item[0]} {item[1]}".lower()
                return sum(hay.count(term) for term in terms)

            matches.sort(key=score, reverse=True)
    lines = []
    for title, body in matches[:limit]:
        first = body.splitlines()[0] if body else ""
        lines.append(f"- {(title or first)[:_MAX_LINE]}")
    return "\n".join(lines)


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "fact"


def write_fact(
    skills: list[str],
    title: str,
    body: str,
    project: str | None = None,
    root: str = DEFAULT_ROOT,
) -> str:
    """Write a fact file and return its path. Creates the store dir if needed."""
    directory = facts_dir(project, root)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{_slug(title)}.md")
    tags = ", ".join(skills)
    content = f"---\nskills: [{tags}]\ntitle: {title}\n---\n{body.strip()}\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path
