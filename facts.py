#!/usr/bin/env python3
"""Local, deterministic skill-fact store (markdown). No LLM, stdlib only.

This is the memory source we control — recall.py reads it as the PRIMARY source and
treats claude-mem as a secondary/best-effort source. Each fact is a markdown file with
frontmatter:

    ---
    skills: [api-design, fastapi-patterns]
    title: EmailStr requires email-validator
    source: pr
    ref: "#42"
    topic: src/app/routes.py
    created: 2026-06-28
    updated: 2026-06-28
    ---
    FastAPI's EmailStr needs the email-validator package or imports 500 at startup.

Only `skills` and `title` are required; the rest are provenance fields used by the
self-evolution pass (consolidate.py) to dedup, supersede, and prune. They are optional
and default safely, so facts written before provenance existed still parse.

Facts are scoped per project (cwd basename) under YUNAKI_FACTS_DIR. A fact with an
empty `skills:` list is global (returned for every skill). Never raises to the caller.
"""

from __future__ import annotations

import dataclasses
import datetime
import glob
import os
import re
import zlib

DEFAULT_ROOT = os.path.expanduser(os.environ.get("YUNAKI_FACTS_DIR", "~/.claude/skill-memory"))
_SKILLS_RE = re.compile(r"^skills:\s*\[(.*?)\]\s*$", re.MULTILINE)
_TITLE_RE = re.compile(r"^title:\s*(.+?)\s*$", re.MULTILINE)
_SOURCE_RE = re.compile(r"^source:\s*(.+?)\s*$", re.MULTILINE)
_REF_RE = re.compile(r"^ref:\s*(.+?)\s*$", re.MULTILINE)
_TOPIC_RE = re.compile(r"^topic:\s*(.+?)\s*$", re.MULTILINE)
_CREATED_RE = re.compile(r"^created:\s*(.+?)\s*$", re.MULTILINE)
_UPDATED_RE = re.compile(r"^updated:\s*(.+?)\s*$", re.MULTILINE)
_MAX_LINE = 300
_DEFAULT_SOURCE = "manual"


@dataclasses.dataclass(frozen=True)
class Fact:
    """A parsed fact. `path` is set when loaded from disk (empty for parse-only)."""

    skills: list[str]
    title: str
    body: str
    source: str = _DEFAULT_SOURCE
    ref: str = ""
    topic: str = ""
    created: str = ""
    updated: str = ""
    path: str = ""


def _today() -> str:
    return datetime.date.today().isoformat()


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


def _field(pattern: re.Pattern[str], fm: str) -> str:
    m = pattern.search(fm)
    return m.group(1).strip().strip("\"'") if m else ""


def parse_fact(text: str) -> Fact:
    """Parse a fact file's text into a Fact. Missing provenance fields default safely."""
    fm, body = _split_frontmatter(text)
    skills: list[str] = []
    skills_match = _SKILLS_RE.search(fm)
    if skills_match:
        skills = [s.strip().strip("\"'") for s in skills_match.group(1).split(",") if s.strip()]
    return Fact(
        skills=skills,
        title=_field(_TITLE_RE, fm),
        body=body.strip(),
        source=_field(_SOURCE_RE, fm) or _DEFAULT_SOURCE,
        ref=_field(_REF_RE, fm),
        topic=_field(_TOPIC_RE, fm),
        created=_field(_CREATED_RE, fm),
        updated=_field(_UPDATED_RE, fm),
    )


def load_facts(directory: str) -> list[Fact]:
    """Load and parse every *.md fact in a directory. Skips unreadable files."""
    out: list[Fact] = []
    for path in sorted(glob.glob(os.path.join(directory, "*.md"))):
        try:
            with open(path, encoding="utf-8") as fh:
                out.append(dataclasses.replace(parse_fact(fh.read()), path=path))
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
    matches = [f for f in facts if _relevant(f.skills, skill)]
    if query:
        terms = [w.lower() for w in re.findall(r"\w+", query)]
        if terms:

            def score(item: Fact) -> int:
                hay = f"{item.title} {item.body}".lower()
                return sum(hay.count(term) for term in terms)

            matches.sort(key=score, reverse=True)
    lines = []
    for fact in matches[:limit]:
        first = fact.body.splitlines()[0] if fact.body else ""
        lines.append(f"- {(fact.title or first)[:_MAX_LINE]}")
    return "\n".join(lines)


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "fact"


def _fact_filename(source: str, ref: str, topic: str, title: str) -> str:
    """Stable filename. Sourced facts key on source/ref/topic/title with a deterministic
    hash suffix so re-ingesting the same fact overwrites (idempotent) while distinct facts
    never collide once the readable slug is truncated. Manual facts key on the title (their
    natural identity)."""
    if source != _DEFAULT_SOURCE and (ref or topic):
        key = f"{source}-{ref}-{topic}-{title}"
        digest = format(zlib.crc32(key.encode("utf-8")) & 0xFFFFFFFF, "08x")
        return f"{_slug(key)[:48]}-{digest}.md"
    return f"{_slug(title)}.md"


def write_fact(
    skills: list[str],
    title: str,
    body: str,
    project: str | None = None,
    root: str = DEFAULT_ROOT,
    source: str = _DEFAULT_SOURCE,
    ref: str = "",
    topic: str = "",
    created: str | None = None,
    updated: str = "",
) -> str:
    """Write a fact file and return its path. Creates the store dir if needed.

    `created` defaults to today when not supplied; provenance fields are only written
    when set, so manual facts stay minimal and old facts remain valid."""
    directory = facts_dir(project, root)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, _fact_filename(source, ref, topic, title))
    lines = [f"skills: [{', '.join(skills)}]", f"title: {title}", f"source: {source}"]
    if ref:
        lines.append(f"ref: {ref}")
    if topic:
        lines.append(f"topic: {topic}")
    lines.append(f"created: {created or _today()}")
    if updated:
        lines.append(f"updated: {updated}")
    content = "---\n" + "\n".join(lines) + "\n---\n" + body.strip() + "\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path
