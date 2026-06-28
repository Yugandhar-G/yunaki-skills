"""Offline tests for ingest.py — deterministic fact extraction from failure output."""

import ingest

PYTEST_FAIL = """\
=================================== FAILURES ===================================
___________________ test_slugify_uses_underscores_not_hyphens __________________
    def test_slugify_uses_underscores_not_hyphens():
>       assert slugify('My Cool Title') == 'my_cool_title'
E       assert 'my-cool-title' == 'my_cool_title'
=========================== short test summary info ============================
FAILED test_solution.py::test_slugify_uses_underscores_not_hyphens - AssertionError
"""

IMPORT_FAIL = """\
ImportError while importing test module 'test_app.py'.
E   ModuleNotFoundError: No module named 'email_validator'
"""


def test_extract_missing_module():
    facts = ingest.extract_facts(IMPORT_FAIL)
    titles = [t for t, _ in facts]
    assert any("email_validator" in t for t in titles)
    body = next(b for t, b in facts if "email_validator" in t)
    assert "dependency" in body.lower() or "install" in body.lower()


def test_extract_failed_test_with_assertion_example():
    facts = ingest.extract_facts(PYTEST_FAIL)
    assert facts
    title, body = facts[0]
    assert "slugify uses underscores not hyphens" in title.lower()
    assert "'my_cool_title'" in body  # the expected value is captured
    assert "'my-cool-title'" in body  # the actual value is captured


def test_extract_assertion_only_when_no_failed_line():
    out = "E       assert 'got' == 'want'\n"
    facts = ingest.extract_facts(out)
    assert facts and "'want'" in facts[0][1]


def test_extract_empty_output_is_empty():
    assert ingest.extract_facts("everything passed, all green") == []


def test_humanize():
    assert ingest._humanize("test_slugify_uses_underscores") == "slugify uses underscores"


def test_ingest_writes_each_fact(monkeypatch):
    written = []

    def fake_write(skills, title, body, project=None, **kw):
        written.append((skills, title, kw.get("source")))
        return f"/store/{title}.md"

    monkeypatch.setattr(ingest.facts, "write_fact", fake_write)
    paths = ingest.ingest(PYTEST_FAIL, ["python-patterns"], project="proj")
    assert len(paths) == 1
    assert written[0][0] == ["python-patterns"]
    assert written[0][2] == "test"  # test-failure facts are tagged source=test


def test_main_from_file(tmp_path, monkeypatch, capsys):
    f = tmp_path / "fail.txt"
    f.write_text(IMPORT_FAIL)
    monkeypatch.setattr(ingest.facts, "write_fact", lambda *a, **k: "/store/x.md")
    rc = ingest.main(["--skill", "api-design", "--from-file", str(f)])
    assert rc == 0
    assert "learned" in capsys.readouterr().out
