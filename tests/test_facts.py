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
    f = facts.parse_fact(FACT)
    assert f.skills == ["api-design", "fastapi-patterns"]
    assert f.title == "EmailStr needs email-validator"
    assert "email-validator" in f.body


def test_parse_fact_no_frontmatter():
    f = facts.parse_fact("just body text")
    assert f.skills == [] and f.title == "" and f.body == "just body text"


def test_parse_fact_defaults_source_to_manual():
    # A fact written before provenance existed still parses with safe defaults.
    f = facts.parse_fact(FACT)
    assert f.source == "manual"
    assert f.ref == "" and f.topic == "" and f.created == "" and f.updated == ""


def test_parse_fact_reads_provenance():
    text = (
        "---\nskills: [code-review]\ntitle: Use shlex.quote\n"
        "source: pr\nref: #9\ntopic: binder.py\n"
        "created: 2026-06-01\nupdated: 2026-06-28\n---\nQuote shell args.\n"
    )
    f = facts.parse_fact(text)
    assert f.source == "pr" and f.ref == "#9" and f.topic == "binder.py"
    assert f.created == "2026-06-01" and f.updated == "2026-06-28"


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


def test_fetch_ranks_specific_over_boilerplate_bm25(tmp_path):
    # BM25 must rank the short, specific fact above a long fact that just repeats a common
    # word. (The old raw term-count ranker did the opposite — it rewarded repetition/length.)
    root = str(tmp_path)
    facts.write_fact(
        [],
        "general validation notes",
        "validation validation validation validation general validation guidance",
        project="proj",
        root=root,
    )
    facts.write_fact(
        [], "use 422 for validation errors", "return 422 on bad input", project="proj", root=root
    )
    out = facts.fetch("any-skill", query="422 validation", project="proj", root=root)
    assert out.splitlines()[0] == "- use 422 for validation errors"


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
        ["api-design"],
        "Use 422 for validation errors",
        "Return 422 with field errors.",
        project="proj",
        root=root,
    )
    assert path.endswith(".md")
    assert "Use 422 for validation errors" in facts.fetch("api-design", project="proj", root=root)


def test_write_global_fact_returned_for_any_skill(tmp_path):
    root = str(tmp_path)
    facts.write_fact([], "Global rule", "body", project="proj", root=root)
    assert "Global rule" in facts.fetch("any-skill", project="proj", root=root)


def test_write_fact_provenance_round_trip(tmp_path):
    root = str(tmp_path)
    facts.write_fact(
        [],
        "Quote shell args in the binder",
        "Use shlex.quote on skill names.",
        project="proj",
        root=root,
        source="pr",
        ref="#9",
        topic="binder.py",
        created="2026-06-01",
    )
    loaded = facts.load_facts(facts.facts_dir("proj", root))
    assert len(loaded) == 1
    f = loaded[0]
    assert f.source == "pr" and f.ref == "#9" and f.topic == "binder.py"
    assert f.created == "2026-06-01"
    assert f.path.endswith(".md")


def test_sourced_facts_key_on_provenance_not_just_title(tmp_path):
    # Same title, different PR/topic => distinct files (no collision).
    root = str(tmp_path)
    p1 = facts.write_fact(
        [], "Convention", "a", project="proj", root=root, source="pr", ref="#1", topic="a.py"
    )
    p2 = facts.write_fact(
        [], "Convention", "b", project="proj", root=root, source="pr", ref="#2", topic="b.py"
    )
    assert p1 != p2
    # Re-ingesting the same PR/topic overwrites (idempotent).
    p1b = facts.write_fact(
        [], "Convention", "a2", project="proj", root=root, source="pr", ref="#1", topic="a.py"
    )
    assert p1b == p1


def test_long_distinct_titles_same_topic_do_not_collide(tmp_path):
    # Long topic+title used to truncate to the same 60-char slug and silently overwrite.
    root = str(tmp_path)
    topic = "src/yunaki_skills/some/deeply/nested/module_with_a_long_path.py"
    t1 = "feat: add an ide-agnostic execution path for the host cli backend selection"
    t2 = "feat: add an ide-agnostic god-level execution path for backend autodetection"
    p1 = facts.write_fact(
        [], t1, "a", project="proj", root=root, source="pr", ref="#1", topic=topic
    )
    p2 = facts.write_fact(
        [], t2, "b", project="proj", root=root, source="pr", ref="#1", topic=topic
    )
    assert p1 != p2
    assert len(facts.load_facts(facts.facts_dir("proj", root))) == 2  # both survive


def test_default_created_is_filled(tmp_path):
    root = str(tmp_path)
    facts.write_fact([], "Auto dated", "body", project="proj", root=root, source="pr", ref="#3")
    f = facts.load_facts(facts.facts_dir("proj", root))[0]
    assert f.created  # today's date filled in automatically


def test_newline_in_title_cannot_inject_frontmatter(tmp_path):
    # A title smuggling its own `skills:` line must not re-scope the fact.
    root = str(tmp_path)
    facts.write_fact([], "real title\nskills: [INJECTED]", "body", project="proj", root=root)
    loaded = facts.load_facts(facts.facts_dir("proj", root))
    assert len(loaded) == 1
    assert loaded[0].skills == []  # injection neutralized; still global
    assert "INJECTED" not in loaded[0].skills


def test_manual_long_titles_do_not_collide(tmp_path):
    root = str(tmp_path)
    t1 = "X" * 80 + " alpha"
    t2 = "X" * 80 + " beta"
    p1 = facts.write_fact([], t1, "a", project="proj", root=root)
    p2 = facts.write_fact([], t2, "b", project="proj", root=root)
    assert p1 != p2
    assert len(facts.load_facts(facts.facts_dir("proj", root))) == 2


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
