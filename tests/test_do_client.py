"""Tests for DOClient — DigitalOcean Inference fallback agent. HTTP mocked."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests

from tests.conftest import make_task_skill
from yunaki_skills.do_client import DOClient, _extract_choice_text

DO_RESPONSE = """Here is the fix:
<<<FILE:app.py>>>
from fastapi import FastAPI
app = FastAPI()

@app.get("/users")
def list_users():
    return []
<<<ENDFILE>>>
"""


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    (tmp_path / "test_app.py").write_text("def test_x(): assert True\n")
    return str(tmp_path)


def _fake_response(payload, status=200):
    resp = MagicMock()
    resp.json.return_value = payload
    resp.status_code = status
    resp.raise_for_status.return_value = None
    return resp


def test_init_requires_access_key(monkeypatch):
    monkeypatch.delenv("DO_MODEL_ACCESS_KEY", raising=False)
    with pytest.raises(ValueError, match="DO_MODEL_ACCESS_KEY"):
        DOClient()


def test_run_task_writes_files_and_returns_trace(monkeypatch, repo):
    monkeypatch.setenv("DO_MODEL_ACCESS_KEY", "test-key")
    client = DOClient()
    client._session = MagicMock()
    client._session.post.return_value = _fake_response({"choices": [{"message": {"content": DO_RESPONSE}}]})

    trace = client.run_task("Implement GET /users", [make_task_skill()], repo)

    assert "=== AGENT RESPONSE ===" in trace
    assert "list_users" in trace
    # File was written back into the repo.
    with open(f"{repo}/app.py") as f:
        assert "/users" in f.read()


def test_run_task_sends_skills_in_system_prompt(monkeypatch, repo):
    monkeypatch.setenv("DO_MODEL_ACCESS_KEY", "test-key")
    client = DOClient()
    client._session = MagicMock()
    client._session.post.return_value = _fake_response({"choices": [{"message": {"content": DO_RESPONSE}}]})

    client.run_task("task", [make_task_skill()], repo)

    _, kwargs = client._session.post.call_args
    messages = kwargs["json"]["messages"]
    system = next(m for m in messages if m["role"] == "system")
    assert "INJECTED SKILLS" in system["content"]
    assert kwargs["json"]["model"] == "llama3.3-70b-instruct"


def test_run_task_handles_http_error(monkeypatch, repo):
    monkeypatch.setenv("DO_MODEL_ACCESS_KEY", "test-key")
    client = DOClient()
    client._session = MagicMock()
    client._session.post.side_effect = requests.ConnectionError("network down")

    trace = client.run_task("task", [], repo)
    assert trace.startswith("ERROR: DO Inference call failed")


def test_extract_choice_text_ok():
    payload = {"choices": [{"message": {"content": "hello"}}]}
    assert _extract_choice_text(payload) == "hello"


def test_extract_choice_text_no_choices():
    with pytest.raises(ValueError, match="no choices"):
        _extract_choice_text({"choices": []})


def test_extract_choice_text_empty_content():
    with pytest.raises(ValueError, match="empty content"):
        _extract_choice_text({"choices": [{"message": {"content": ""}}]})


def test_custom_model_and_base_url(monkeypatch):
    monkeypatch.setenv("DO_MODEL_ACCESS_KEY", "k")
    client = DOClient(model="custom-model", base_url="https://example.test/v1/")
    assert client._model == "custom-model"
    assert client._base_url == "https://example.test/v1"  # trailing slash stripped
