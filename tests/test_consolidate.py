"""Offline tests for consolidate.py — deterministic self-evolution (dedup/supersede/prune)."""

import consolidate
import facts
from facts import Fact


def _f(title, body="b", source="pr", ref="#1", topic="", created="2026-06-01", path="p"):
    return Fact(
        skills=[],
        title=title,
        body=body,
        source=source,
        ref=ref,
        topic=topic,
        created=created,
        path=path,
    )


# ── dedup ───────────────────────────────────────────────────────────────────────


def test_dedup_collapses_identical_content_keeping_newest():
    a = _f("same", body="x", ref="#1", created="2026-01-01", path="a.md")
    b = _f("same", body="x", ref="#5", created="2026-06-01", path="b.md")
    kept, dropped = consolidate.dedup([a, b])
    assert [k.path for k in kept] == ["b.md"]  # newer wins
    assert [d.path for d in dropped] == ["a.md"]


def test_dedup_keeps_distinct_content():
    kept, dropped = consolidate.dedup([_f("one", path="a.md"), _f("two", path="b.md")])
    assert len(kept) == 2 and dropped == []


def test_dedup_keeps_same_content_on_different_topics():
    # "add a docstring" left on two different files is two distinct pieces of guidance.
    a = _f("add a docstring", body="add a docstring", topic="a.py", path="a.md")
    b = _f("add a docstring", body="add a docstring", topic="b.py", path="b.md")
    kept, dropped = consolidate.dedup([a, b])
    assert len(kept) == 2 and dropped == []


# ── supersede ─────────────────────────────────────────────────────────────────


def test_supersede_keeps_newest_k_per_topic():
    facts_in = [
        _f("c1", topic="routes.py", ref="#1", created="2026-01-01", path="1.md"),
        _f("c2", topic="routes.py", ref="#2", created="2026-02-01", path="2.md"),
        _f("c3", topic="routes.py", ref="#3", created="2026-03-01", path="3.md"),
    ]
    kept, dropped = consolidate.supersede(facts_in, keep_per_topic=2)
    assert {k.path for k in kept} == {"2.md", "3.md"}  # two newest
    assert [d.path for d in dropped] == ["1.md"]  # oldest superseded


def test_supersede_exempts_manual_and_topicless():
    manual = _f("m", source="manual", topic="routes.py", path="m.md")
    topicless = _f("t", source="pr", topic="", path="t.md")
    kept, dropped = consolidate.supersede([manual, topicless], keep_per_topic=1)
    assert {k.path for k in kept} == {"m.md", "t.md"} and dropped == []


def test_supersede_groups_by_source_and_topic():
    a = _f("a", source="pr", topic="x.py", path="a.md", created="2026-01-01")
    b = _f("b", source="commit", topic="x.py", path="b.md", created="2026-01-02")
    kept, dropped = consolidate.supersede([a, b], keep_per_topic=1)
    # different sources => different groups => both kept
    assert len(kept) == 2 and dropped == []


# ── prune ─────────────────────────────────────────────────────────────────────


def test_prune_disabled_by_default_keeps_all():
    old = _f("old", topic="a.py", created="2000-01-01", path="o.md")
    kept, dropped = consolidate.prune([old], ttl_days=0, today="2026-06-28")
    assert kept and dropped == []


def test_prune_ttl_drops_aged_non_newest():
    old = _f("old", topic="a.py", ref="#1", created="2024-01-01", path="o.md")
    new = _f("new", topic="a.py", ref="#2", created="2026-06-01", path="n.md")
    kept, dropped = consolidate.prune([old, new], ttl_days=180, today="2026-06-28")
    assert [d.path for d in dropped] == ["o.md"]  # aged + not newest-on-topic
    assert [k.path for k in kept] == ["n.md"]


def test_prune_ttl_keeps_aged_when_newest_on_topic():
    only = _f("only", topic="a.py", created="2000-01-01", path="o.md")
    kept, dropped = consolidate.prune([only], ttl_days=180, today="2026-06-28")
    assert kept and dropped == []  # never delete the sole/newest guidance on a topic


def test_prune_drops_facts_whose_topic_file_is_gone(tmp_path):
    (tmp_path / "exists.py").write_text("x")
    here = _f("here", topic="exists.py", path="h.md")
    gone = _f("gone", topic="deleted.py", path="g.md")
    kept, dropped = consolidate.prune([here, gone], repo_root=str(tmp_path))
    assert [k.path for k in kept] == ["h.md"]
    assert [d.path for d in dropped] == ["g.md"]


def test_prune_file_check_skips_manual():
    manual = _f("m", source="manual", topic="deleted.py", path="m.md")
    kept, dropped = consolidate.prune([manual], repo_root="/nonexistent")
    assert kept and dropped == []


# ── end-to-end consolidate over a real store dir ────────────────────────────────


def test_consolidate_applies_and_reports(tmp_path):
    root = str(tmp_path)
    # three facts on one topic (supersede keeps 2) + one duplicate of the newest
    facts.write_fact(
        [],
        "g1",
        "b",
        project="proj",
        root=root,
        source="pr",
        ref="#1",
        topic="x.py",
        created="2026-01-01",
    )
    facts.write_fact(
        [],
        "g2",
        "b2",
        project="proj",
        root=root,
        source="pr",
        ref="#2",
        topic="x.py",
        created="2026-02-01",
    )
    facts.write_fact(
        [],
        "g3",
        "b3",
        project="proj",
        root=root,
        source="pr",
        ref="#3",
        topic="x.py",
        created="2026-03-01",
    )

    report = consolidate.consolidate(project="proj", root=root, keep_per_topic=2)
    assert report["dry_run"] is False
    assert len(report["superseded"]) == 1  # oldest of the three dropped
    remaining = facts.load_facts(facts.facts_dir("proj", root))
    assert len(remaining) == 2


def test_consolidate_dry_run_writes_nothing(tmp_path):
    root = str(tmp_path)
    facts.write_fact(
        [],
        "g1",
        "b",
        project="proj",
        root=root,
        source="pr",
        ref="#1",
        topic="x.py",
        created="2026-01-01",
    )
    facts.write_fact(
        [],
        "g2",
        "b2",
        project="proj",
        root=root,
        source="pr",
        ref="#2",
        topic="x.py",
        created="2026-02-01",
    )
    facts.write_fact(
        [],
        "g3",
        "b3",
        project="proj",
        root=root,
        source="pr",
        ref="#3",
        topic="x.py",
        created="2026-03-01",
    )

    before = len(facts.load_facts(facts.facts_dir("proj", root)))
    report = consolidate.consolidate(project="proj", root=root, keep_per_topic=2, dry_run=True)
    after = len(facts.load_facts(facts.facts_dir("proj", root)))
    assert report["dry_run"] is True
    assert after == before  # nothing deleted
    assert len(report["superseded"]) == 1  # but it reports what it WOULD remove


def test_consolidate_missing_store_is_safe(tmp_path):
    report = consolidate.consolidate(project="nope", root=str(tmp_path))
    assert report["kept"] == 0 and report["superseded"] == []
