"""Smoke + behavior tests for the FastAPI app (main.py).

main.py opens a MongoDB connection at import time. To keep this test hermetic
and avoid touching any real cluster, we force the connection to an unreachable
host BEFORE importing the app, which drops main into its in-memory stub mode.
"""

from __future__ import annotations

import os

# Force stub mode — must run before `yunaki_skills.main` is imported.
os.environ["MONGODB_URI"] = "mongodb://127.0.0.1:1/yunaki"
os.environ.pop("MONGODB_USER", None)
os.environ.pop("MONGODB_PASS", None)
os.environ["AUTH_ENABLED"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from yunaki_skills import main as main_mod  # noqa: E402
from yunaki_skills.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def stub_runner(monkeypatch):
    """Force the deterministic simulated-run path (no real agent / Gemini).

    The real TaskRunner is importable in this environment, which would make
    /api/run execute a live evolution loop. For API-contract tests we want the
    fast, side-effect-local stub path instead.
    """
    monkeypatch.setattr(main_mod, "_real_task_runner", False)


def test_list_skills_returns_list(client):
    resp = client.get("/api/skills")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_missing_skill_404(client):
    resp = client.get("/api/skills/definitely_not_a_skill")
    assert resp.status_code == 404


def test_runs_endpoint(client):
    resp = client.get("/api/runs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_stats_shape(client):
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    body = resp.json()
    for key in ("total_skills", "avg_score", "total_runs", "avg_improvement"):
        assert key in body


def test_trigger_run_returns_scores(client, stub_runner):
    """Without a real TaskRunner (no GEMINI_API_KEY), the API must fail
    honestly with 503 — NOT fabricate scores."""
    resp = client.post("/api/run", json={"task_description": "do a thing", "max_iterations": 2})
    assert resp.status_code == 503
    body = resp.json()
    assert "detail" in body
    assert "No TaskRunner available" in body["detail"] or "TaskRunner failed" in body["detail"]


def test_run_is_recorded(client, stub_runner):
    """Run endpoint correctly rejects when no real runner is available.
    (The old stub path that fabricated scores has been removed.)"""
    before = len(client.get("/api/runs").json())
    resp = client.post("/api/run", json={"task_description": "another task"})
    assert resp.status_code == 503
    after = len(client.get("/api/runs").json())
    assert after == before  # no fabricated run added


def test_root_serves_something(client):
    resp = client.get("/")
    assert resp.status_code == 200
