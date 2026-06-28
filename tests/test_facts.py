"""Offline tests for facts.py (local fact store) and remember.py (writer)."""
import facts
import remember

FACT = """\
---
skills: [api-design, fastapi-patterns]
title: EmailStr needs email-validator
---
FastAPI EmailStr requires email-validator or imports 500 at startup.
"""

PAGINATION = """\
---
skills: [api-design]
title: Pagination uses limit and offset
---
Use limit/offset query params.
"""

GLOBAL_FACT = """\
---
skills: []
title: Always validate input at boundaries
---
Validate external input before use.
"""


# ── parsing ──────────────────────────────────────────────────────────────────


def test_parse_fact():
    skills, title, body = facts.parse_fact(FACT)
    assert skills == ["api-design", "fastapi-patterns"]
    assert title == "EmailStr needs email-validator"
    assert "email-validator" in body


def test_parse_fact_no_frontmatter():
    skills, title, body = facts.parse_fact("just body text")
    assert skills == [] and title == "" and body == "just body text"


# ── fetch (scoped, ranked) ───────────────────────────────────────────────────


def _seed(tmp_path, name, text):
    d = tmp_path / "proj" / "facts"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text)
    return str(tmp_path)


def test_fetch_returns_facts_for_skill(tmp_path):
    root = _seed(tmp_path, "a.md", FACT)
    assert "EmailStr needs email-validator" in facts.fetch("api-design", project="proj", root=root)


def test_fetch_excludes_other_skills(tmp_path):
    root = _seed(tmp_path, "a.md", FACT)
    assert facts.fetch("unrelated-skill", project="proj", root=root) == ""


def test_fetch_includes_global_facts(tmp_path):
    root = _seed(tmp_path, "g.md", GLOBAL_FACT)
    assert "Always validate input" in facts.fetch("anything", project="proj", root=root)


def test_fetch_ranks_by_query(tmp_path):
    root = _seed(tmp_path, "a.md", FACT)
    _seed(tmp_path, "b.md", PAGINATION)
    out = facts.fetch("api-design", query="pagination", project="proj", root=root)
    assert out.splitlines()[0].endswith("limit and offset")  # most query-relevant first


def test_fetch_missing_dir_is_empty(tmp_path):
    assert facts.fetch("x", project="nope", root=str(tmp_path)) == ""


# ── write round trip ─────────────────────────────────────────────────────────


def test_write_then_fetch_round_trip(tmp_path):
    root = str(tmp_path)
    path = facts.write_fact(
        ["api-design"], "Use 422 for validation errors", "Return 422 with field errors.",
        project="proj", root=root,
    )
    assert path.endswith(".md")
    assert "Use 422 for validation errors" in facts.fetch("api-design", project="proj", root=root)


def test_write_global_fact_returned_for_any_skill(tmp_path):
    root = str(tmp_path)
    facts.write_fact([], "Global rule", "body", project="proj", root=root)
    assert "Global rule" in facts.fetch("any-skill", project="proj", root=root)


# ── remember CLI ─────────────────────────────────────────────────────────────


def test_remember_cli_delegates_to_write_fact(monkeypatch, capsys):
    seen = {}

    def fake_write(skills, title, body, project=None):
        seen.update(skills=skills, title=title, body=body, project=project)
        return "fact.md"

    monkeypatch.setattr(remember.facts, "write_fact", fake_write)
    rc = remember.main(["--skill", "api-design", "--title", "T", "the body"])
    assert rc == 0
    assert seen == {"skills": ["api-design"], "title": "T", "body": "the body", "project": None}
    assert "saved fact" in capsys.readouterr().out
