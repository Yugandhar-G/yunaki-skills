"""Tests for antigravity_client helpers and the FallbackClient (Gemini mocked)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests.conftest import make_task_skill
from yunaki_skills import antigravity_client as ac
from yunaki_skills.antigravity_client import (
    FallbackClient,
    _build_prompts,
    _extract_text,
    _format_skills_block,
    _parse_and_write_files,
    _read_repo_files,
)


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "app.py").write_text("APP = 1\n")
    (tmp_path / "tasks.py").write_text("TASKS = 2\n")
    (tmp_path / "test_app.py").write_text("def test(): pass\n")
    return str(tmp_path)


def test_read_repo_files_skips_tests(repo):
    files = _read_repo_files(repo)
    assert "app.py" in files
    assert "tasks.py" in files
    assert "test_app.py" not in files


def test_format_skills_block_empty():
    assert _format_skills_block([]) == ""


def test_format_skills_block_includes_instructions():
    block = _format_skills_block([make_task_skill()])
    assert "INJECTED SKILLS" in block
    assert "Define a dependency" in block


def test_build_prompts_contains_task_and_files(repo):
    files = _read_repo_files(repo)
    system, user = _build_prompts("Do the thing", files, [make_task_skill()])
    assert "coding agent" in system
    assert "INJECTED SKILLS" in system
    assert "Do the thing" in user
    assert "APP = 1" in user


def test_parse_and_write_primary_format(tmp_path):
    output = "<<<FILE:new.py>>>\nX = 42\n<<<ENDFILE>>>"
    written = _parse_and_write_files(output, str(tmp_path))
    assert written == ["new.py"]
    assert (tmp_path / "new.py").read_text().strip() == "X = 42"


def test_parse_and_write_skips_test_files(tmp_path):
    output = "<<<FILE:test_thing.py>>>\nX = 1\n<<<ENDFILE>>>"
    written = _parse_and_write_files(output, str(tmp_path))
    assert written == []


def test_parse_and_write_fallback_format(tmp_path):
    output = "### File: helper.py\n```python\nY = 7\n```"
    written = _parse_and_write_files(output, str(tmp_path))
    assert written == ["helper.py"]
    assert (tmp_path / "helper.py").read_text().strip() == "Y = 7"


def test_parse_and_write_no_blocks(tmp_path):
    assert _parse_and_write_files("no code here", str(tmp_path)) == []


def test_extract_text_from_text_attr():
    assert _extract_text(SimpleNamespace(text="hello")) == "hello"


def test_extract_text_from_candidates():
    part = SimpleNamespace(text="piece")
    content = SimpleNamespace(parts=[part])
    candidate = SimpleNamespace(content=content)
    resp = SimpleNamespace(text=None, candidates=[candidate])
    assert _extract_text(resp) == "piece"


def test_fallback_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        FallbackClient()


def test_fallback_client_run_task(monkeypatch, repo):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = SimpleNamespace(
        text="<<<FILE:app.py>>>\nAPP = 99\n<<<ENDFILE>>>", candidates=[]
    )
    monkeypatch.setattr(ac.genai, "Client", lambda *a, **k: fake_client)

    client = FallbackClient()
    trace = client.run_task("task", [make_task_skill()], repo)

    assert "=== AGENT RESPONSE ===" in trace
    with open(f"{repo}/app.py") as f:
        assert "APP = 99" in f.read()


def test_fallback_client_handles_api_error(monkeypatch, repo):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fake_client = MagicMock()
    fake_client.models.generate_content.side_effect = RuntimeError("boom")
    monkeypatch.setattr(ac.genai, "Client", lambda *a, **k: fake_client)

    trace = FallbackClient().run_task("task", [], repo)
    assert "ERROR: Gemini API call failed" in trace
