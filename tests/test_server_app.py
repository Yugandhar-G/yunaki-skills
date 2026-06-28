"""Offline tests for server/app.py — FastAPI service over the shared store.

Skipped automatically where fastapi isn't installed (the core suite is stdlib-only);
the server CI job installs server/requirements.txt and runs these.
"""

import hashlib
import hmac
import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import facts  # noqa: E402
import ingest_pr  # noqa: E402
from server.app import app  # noqa: E402

TOKEN_A = "tok-a"  # noqa: S105 — fake token, test fixture
TOKEN_B = "tok-b"  # noqa: S105 — fake token, test fixture
REPO_A = "owner/alpha"
REPO_B = "owner/beta"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("YUNAKI_FACTS_DIR", str(tmp_path))
    monkeypatch.setenv("YUNAKI_TOKENS", json.dumps({TOKEN_A: REPO_A, TOKEN_B: REPO_B}))
    monkeypatch.setenv("YUNAKI_WEBHOOK_SECRET", "hooksecret")
    # a tiny local checkout so the on-merge codebase rebuild scans real files, never the
    # network (YUNAKI_REPO_PATH short-circuits the shallow git clone in _repo_source).
    src = tmp_path / "src"
    src.mkdir()
    for name in ("alpha", "beta", "gamma"):
        (src / f"{name}.py").write_text(
            "from __future__ import annotations\n"
            "import os\n\n\n"
            "def go() -> str:\n"
            "    return os.getcwd()\n"
        )
    monkeypatch.setenv("YUNAKI_REPO_PATH", str(src))
    return tmp_path


@pytest.fixture
def client():
    return TestClient(app)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_home_page_renders_html(env, client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Skills that" in r.text  # the landing hero, not raw JSON


def test_stats_endpoint_counts_facts(env, client):
    facts.write_fact([], "a fact", "body", project=REPO_A, root=str(env))
    body = client.get("/stats").json()
    assert body["facts"] >= 1 and body["repos"] >= 1


def test_recall_requires_token(env, client):
    assert client.get("/recall", params={"skill": "x"}).status_code == 401


def test_recall_returns_repo_facts(env, client):
    facts.write_fact([], "use 422 for validation", "body", project=REPO_A, root=str(env))
    r = client.get("/recall", params={"skill": "api-design"}, headers=_auth(TOKEN_A))
    assert r.status_code == 200
    assert "use 422 for validation" in r.text


def test_recall_is_scoped_per_repo(env, client):
    # a fact written for REPO_A must never surface for REPO_B's token
    facts.write_fact([], "alpha-only secret guidance", "body", project=REPO_A, root=str(env))
    r = client.get("/recall", params={"skill": "x"}, headers=_auth(TOKEN_B))
    assert r.status_code == 200
    assert "alpha-only" not in r.text


def test_webhook_rejects_bad_signature(env, client):
    r = client.post("/webhook", content=b"{}", headers={"X-Hub-Signature-256": "sha256=bad"})
    assert r.status_code == 401


def test_webhook_ingests_merged_pr(env, client, monkeypatch):
    canned = {
        "number": 5,
        "title": "fix: clamp negative offset at the boundary",
        "body": "",
        "mergedAt": "2026-06-20T00:00:00Z",
        "files": [{"path": "app.py", "additions": 3, "deletions": 1}],
        "commits": [],
        "review_comments": [],
        "reviews": [],
    }
    monkeypatch.setattr(ingest_pr, "fetch_merged_prs", lambda repo, since_number, limit: [canned])

    payload = {
        "action": "closed",
        "pull_request": {"merged": True},
        "repository": {"full_name": REPO_A},
    }
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(b"hooksecret", body, hashlib.sha256).hexdigest()
    r = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": sig})
    assert r.status_code == 200 and r.json()["status"] == "scheduled"

    # background task ran: the merged PR's knowledge is now in REPO_A's slice
    loaded = facts.load_facts(facts.facts_dir(REPO_A, str(env)))
    assert any("clamp negative offset" in f.title for f in loaded)


def test_webhook_rebuilds_codebase_conventions(env, client, monkeypatch):
    # even with no new PRs, a merge rebuilds the repo's codebase conventions from source
    monkeypatch.setattr(ingest_pr, "fetch_merged_prs", lambda repo, since_number, limit: [])
    payload = {
        "action": "closed",
        "pull_request": {"merged": True},
        "repository": {"full_name": REPO_A},
    }
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(b"hooksecret", body, hashlib.sha256).hexdigest()
    r = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": sig})
    assert r.json()["status"] == "scheduled"

    loaded = facts.load_facts(facts.facts_dir(REPO_A, str(env)))
    assert any(f.source == "codebase" for f in loaded), "merge must rebuild codebase conventions"
    assert any("from __future__" in f.body or "stdlib-only" in f.title.lower() for f in loaded)


def test_repo_source_prefers_local_checkout(env):
    # with YUNAKI_REPO_PATH set, the rebuild scans it directly — never a network clone
    from server.app import _repo_source

    path, is_temp = _repo_source(REPO_A)
    assert is_temp is False
    assert path.endswith("src")


def test_webhook_ignores_unmerged(env, client):
    payload = {
        "action": "closed",
        "pull_request": {"merged": False},
        "repository": {"full_name": REPO_A},
    }
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(b"hooksecret", body, hashlib.sha256).hexdigest()
    r = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": sig})
    assert r.json()["status"] == "ignored"


def test_webhook_ignores_traversal_repo(env, client):
    payload = {
        "action": "closed",
        "pull_request": {"merged": True},
        "repository": {"full_name": "../../etc/passwd"},
    }
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(b"hooksecret", body, hashlib.sha256).hexdigest()
    r = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": sig})
    assert r.json()["status"] == "ignored"  # rejected before it becomes a path


def test_ingest_endpoint_requires_token(env, client):
    assert client.post("/ingest").status_code == 401
