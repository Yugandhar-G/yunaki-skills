"""Offline tests for recall.py — no network, no LLM, no running worker."""
import json
import sqlite3

import pytest

import recall


@pytest.fixture(autouse=True)
def _recall_isolation(monkeypatch):
    """Isolate recall tests: neutralize the local store and exercise the claude-mem path."""
    monkeypatch.setattr(recall.facts, "fetch", lambda *a, **k: "")
    monkeypatch.setenv("YUNAKI_USE_CLAUDE_MEM", "1")


# ── env parsing (never raises at import) ─────────────────────────────────────


def test_env_float_valid_and_invalid(monkeypatch):
    monkeypatch.setenv("YUNAKI_X", "3.5")
    assert recall._env_float("YUNAKI_X", 1.0) == 3.5
    monkeypatch.setenv("YUNAKI_X", "not-a-float")
    assert recall._env_float("YUNAKI_X", 1.0) == 1.0
    monkeypatch.delenv("YUNAKI_X", raising=False)
    assert recall._env_float("YUNAKI_X", 1.0) == 1.0


# ── scrub (secret redaction) ─────────────────────────────────────────────────


def test_scrub_redacts_secrets():
    assert "[REDACTED]" in recall._scrub("here is sk-ABCDEFGHIJKLMNOPQRSTUV012345")
    assert "[REDACTED]" in recall._scrub("token: abcdefghijklmnop")
    assert recall._scrub("a normal harmless line") == "a normal harmless line"


# ── render ───────────────────────────────────────────────────────────────────


def test_render_empty_is_blank():
    assert recall.render("api-design", "") == ""
    assert recall.render("api-design", "   ") == ""


def test_render_wraps_body_with_trust_boundary():
    out = recall.render("api-design", "- EmailStr needs email-validator")
    assert "## Repo memory for `api-design`" in out
    assert "untrusted DATA" in out  # trust-boundary marker
    assert "BEGIN repo memory" in out and "END repo memory" in out
    assert "- EmailStr needs email-validator" in out


# ── search payload parsing ───────────────────────────────────────────────────


def test_parse_mcp_content_returns_text():
    data = {"content": [{"type": "text", "text": "fact one\nfact two"}]}
    assert recall.parse_search_payload(data) == "fact one\nfact two"


def test_parse_mcp_no_results_sentinel_is_empty():
    data = {"content": [{"type": "text", "text": 'No observations found matching "x"'}]}
    assert recall.parse_search_payload(data) == ""


def test_parse_mcp_scrubs_secrets():
    data = {"content": [{"type": "text", "text": "leaked token: abcdef123456"}]}
    assert "[REDACTED]" in recall.parse_search_payload(data)


def test_parse_structured_items_bullets():
    data = {"items": [{"title": "fact one"}, {"summary": "fact two"}, {"id": 9}]}
    assert recall.parse_search_payload(data) == "- fact one\n- fact two"


def test_parse_list_payload_bullets():
    assert recall.parse_search_payload([{"text": "x"}]) == "- x"


def test_parse_garbage_is_empty():
    assert recall.parse_search_payload({"nope": 1}) == ""
    assert recall.parse_search_payload("string") == ""


def test_extract_line_prefers_title_then_truncates():
    assert recall._extract_line({"title": "T", "summary": "S"}) == "T"
    assert recall._extract_line({"title": "first\nsecond"}) == "first"
    assert len(recall._extract_line({"text": "x" * 500})) == recall._MAX_LINE
    assert recall._extract_line({"id": 1}) == ""


def test_fetch_http_uses_search_endpoint(monkeypatch):
    seen = {}

    def fake_get(url, timeout):
        seen["url"] = url
        return {"content": [{"type": "text", "text": "from http"}]}

    monkeypatch.setattr(recall, "_http_get_json", fake_get)
    out = recall.fetch_http("pagination", 5, 37701, project="yunaki-skills")
    assert out == "from http"
    assert "/api/search/observations?" in seen["url"]
    assert "query=pagination" in seen["url"]
    assert "project=yunaki-skills" in seen["url"]


# ── health ───────────────────────────────────────────────────────────────────


def test_worker_healthy_true_and_false(monkeypatch):
    monkeypatch.setattr(recall, "_http_get_json", lambda url, timeout: {"status": "ok"})
    assert recall.worker_healthy(37701) is True

    def boom(url, timeout):
        raise OSError("connection refused")

    monkeypatch.setattr(recall, "_http_get_json", boom)
    assert recall.worker_healthy(37701) is False


# ── port detection ───────────────────────────────────────────────────────────


def test_detect_port_env_wins(monkeypatch):
    monkeypatch.setenv("CLAUDE_MEM_PORT", "40000")
    assert recall.detect_port() == 40000


def test_detect_port_rejects_out_of_range_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_MEM_PORT", "80")  # privileged, invalid
    monkeypatch.setattr(recall, "PIDFILE", str(tmp_path / "missing.pid"))
    monkeypatch.setattr(recall.os, "getuid", lambda: 501, raising=False)
    assert recall.detect_port() == 37701  # falls through to formula, not 80


def test_detect_port_reads_pidfile(monkeypatch, tmp_path):
    monkeypatch.delenv("CLAUDE_MEM_PORT", raising=False)
    pid = tmp_path / "worker.pid"
    pid.write_text(json.dumps({"pid": 1, "port": 37705}))
    monkeypatch.setattr(recall, "PIDFILE", str(pid))
    assert recall.detect_port() == 37705


def test_detect_port_rejects_bad_pidfile_port(monkeypatch, tmp_path):
    monkeypatch.delenv("CLAUDE_MEM_PORT", raising=False)
    pid = tmp_path / "worker.pid"
    pid.write_text(json.dumps({"port": 22}))  # out of range
    monkeypatch.setattr(recall, "PIDFILE", str(pid))
    monkeypatch.setattr(recall.os, "getuid", lambda: 501, raising=False)
    assert recall.detect_port() == 37701  # formula, not 22


def test_detect_port_falls_back_to_formula(monkeypatch, tmp_path):
    monkeypatch.delenv("CLAUDE_MEM_PORT", raising=False)
    monkeypatch.setattr(recall, "PIDFILE", str(tmp_path / "missing.pid"))
    monkeypatch.setattr(recall.os, "getuid", lambda: 501, raising=False)
    assert recall.detect_port() == 37701


# ── sqlite fallback (real sqlite, temp db) ──────────────────────────────────


def _make_db(tmp_path, rows):
    db = tmp_path / "claude-mem.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE observations (id INTEGER PRIMARY KEY, title TEXT)")
    con.executemany("INSERT INTO observations (title) VALUES (?)", [(r,) for r in rows])
    con.commit()
    con.close()
    return str(db)


def test_fetch_sqlite_like_matches(tmp_path):
    db = _make_db(tmp_path, ["fastapi pagination uses limit/offset", "unrelated note"])
    assert recall.fetch_sqlite("pagination", 5, db) == "- fastapi pagination uses limit/offset"


def test_fetch_sqlite_escapes_like_wildcards(tmp_path):
    db = _make_db(tmp_path, ["match a%b here", "decoy axxb here"])
    out = recall.fetch_sqlite("a%b", 5, db)
    assert "match a%b here" in out
    assert "decoy" not in out  # % is treated literally, not as a wildcard


def test_fetch_sqlite_missing_db_is_empty(tmp_path):
    assert recall.fetch_sqlite("q", 5, str(tmp_path / "nope.db")) == ""


def test_quote_id_escapes_quotes():
    assert recall._quote_id('a"b') == '"a""b"'


# ── recall orchestration ────────────────────────────────────────────────────


def test_recall_uses_http_when_worker_healthy(monkeypatch):
    monkeypatch.setattr(recall, "detect_port", lambda: 37701)
    monkeypatch.setattr(recall, "worker_healthy", lambda port, timeout=0: True)
    monkeypatch.setattr(recall, "fetch_http", lambda q, limit, port, project=None: "from http")
    out = recall.recall("backend-patterns", project="")
    assert "from http" in out and "backend-patterns" in out


def test_recall_falls_back_to_sqlite_when_worker_down(monkeypatch):
    monkeypatch.setattr(recall, "detect_port", lambda: 37701)
    monkeypatch.setattr(recall, "worker_healthy", lambda port, timeout=0: False)
    monkeypatch.setattr(recall, "fetch_sqlite", lambda q, limit, db_path="": "- from sqlite")
    assert "from sqlite" in recall.recall("backend-patterns", project="")


def test_recall_broadens_when_scoped_query_empty(monkeypatch):
    calls = []

    def fake_http(q, limit, port, project=None):
        calls.append(project)
        return "" if project else "broadened hit"

    monkeypatch.setattr(recall, "detect_port", lambda: 37701)
    monkeypatch.setattr(recall, "worker_healthy", lambda port, timeout=0: True)
    monkeypatch.setattr(recall, "fetch_http", fake_http)
    out = recall.recall("api-design", project="some-repo")
    assert "broadened hit" in out
    assert calls == ["some-repo", None]  # scoped first, then broadened


def test_recall_http_error_falls_through(monkeypatch):
    monkeypatch.setattr(recall, "detect_port", lambda: 37701)
    monkeypatch.setattr(recall, "worker_healthy", lambda port, timeout=0: True)

    def boom(q, limit, port, project=None):
        raise OSError("boom")

    monkeypatch.setattr(recall, "fetch_http", boom)
    monkeypatch.setattr(recall, "fetch_sqlite", lambda q, limit, db_path="": "- recovered")
    assert "recovered" in recall.recall("api-design", project="")


def test_claude_mem_enabled_reads_env(monkeypatch):
    monkeypatch.delenv("YUNAKI_USE_CLAUDE_MEM", raising=False)
    assert recall._claude_mem_enabled() is False
    monkeypatch.setenv("YUNAKI_USE_CLAUDE_MEM", "1")
    assert recall._claude_mem_enabled() is True


def test_recall_off_by_default_uses_local_only(monkeypatch):
    monkeypatch.delenv("YUNAKI_USE_CLAUDE_MEM", raising=False)
    monkeypatch.setattr(recall.facts, "fetch", lambda *a, **k: "- local only")

    def fail(*a, **k):
        raise AssertionError("worker must not be consulted when claude-mem disabled")

    monkeypatch.setattr(recall, "worker_healthy", fail)
    out = recall.recall("api-design", project="")
    assert "local only" in out and "from cm" not in out


def test_recall_includes_local_facts_first(monkeypatch):
    monkeypatch.setattr(recall, "detect_port", lambda: 37701)
    monkeypatch.setattr(recall, "worker_healthy", lambda port, timeout=0: True)
    monkeypatch.setattr(recall, "fetch_http", lambda q, limit, port, project=None: "- from cm")
    monkeypatch.setattr(recall.facts, "fetch", lambda *a, **k: "- local fact")
    out = recall.recall("api-design", project="")
    assert "- local fact" in out and "- from cm" in out
    assert out.index("local fact") < out.index("from cm")  # local source first


def test_recall_empty_query_is_blank():
    assert recall.recall("", project="") == ""


def test_recall_returns_blank_when_nothing_found(monkeypatch):
    monkeypatch.setattr(recall, "detect_port", lambda: 37701)
    monkeypatch.setattr(recall, "worker_healthy", lambda port, timeout=0: True)
    monkeypatch.setattr(recall, "fetch_http", lambda q, limit, port, project=None: "")
    monkeypatch.setattr(recall, "fetch_sqlite", lambda q, limit, db_path="": "")
    assert recall.recall("api-design", project="") == ""


# ── CLI main ─────────────────────────────────────────────────────────────────


def test_main_prints_block_and_passes_all_projects(monkeypatch, capsys):
    seen = {}

    def fake_recall(skill, query=None, limit=0, port=None, db_path="", project=None):
        seen["project"] = project
        return "## Repo memory for `x`\n\n- hi\n"

    monkeypatch.setattr(recall, "recall", fake_recall)
    rc = recall.main(["--skill", "x", "--all-projects"])
    assert rc == 0
    assert seen["project"] == ""  # --all-projects disables scoping
    assert "Repo memory" in capsys.readouterr().out


def test_main_prints_nothing_when_empty(monkeypatch, capsys):
    monkeypatch.setattr(recall, "recall", lambda *a, **k: "")
    assert recall.main(["--skill", "x"]) == 0
    assert capsys.readouterr().out == ""
