"""Tests for APIKeyMiddleware — auth enforcement logic."""

from __future__ import annotations

import os

# Ensure stub mode before any import of main.
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:1/yunaki")
os.environ.pop("MONGODB_USER", None)
os.environ.pop("MONGODB_PASS", None)

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from yunaki_skills.auth_middleware import APIKeyMiddleware, _is_public  # noqa: E402
from yunaki_skills.auth_store import AuthStore  # noqa: E402

# ─── _is_public helper ────────────────────────────────────────────────────────


def test_is_public_health():
    assert _is_public("/health") is True


def test_is_public_root():
    assert _is_public("/") is True


def test_is_public_docs():
    assert _is_public("/docs") is True


def test_is_public_openapi():
    assert _is_public("/openapi.json") is True


def test_is_public_auth_prefix():
    assert _is_public("/api/auth/register") is True
    assert _is_public("/api/auth/verify") is True


def test_is_public_static_asset():
    assert _is_public("/static/app.js") is True


def test_is_not_public_api_skills():
    assert _is_public("/api/skills") is False


def test_is_not_public_api_run():
    assert _is_public("/api/run") is False


# ─── Middleware integration tests ────────────────────────────────────────────


def _make_auth_store_no_mongo(monkeypatch) -> AuthStore:
    """Return an in-memory AuthStore (no Mongo)."""
    import yunaki_skills.auth_store as mod

    monkeypatch.setattr(mod, "MongoClient", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("no mongo")))
    return AuthStore()


@pytest.fixture
def enabled_app(monkeypatch):
    """Minimal FastAPI app with auth middleware ENABLED and a protected route."""
    import yunaki_skills.auth_store as mod

    # Patch MongoClient so AuthStore falls back to in-memory.
    original_client = mod.MongoClient

    class _FailClient:
        def __init__(self, *a, **k):
            raise ConnectionError("no mongo")

    mod.MongoClient = _FailClient
    auth = AuthStore()
    mod.MongoClient = original_client  # restore

    inner = FastAPI()

    @inner.get("/api/protected")
    async def protected():
        return {"ok": True}

    @inner.get("/health")
    async def health_check():
        return {"status": "ok"}

    @inner.get("/api/auth/register")
    async def register():
        return {"registered": True}

    inner.add_middleware(APIKeyMiddleware, auth_store=auth, enabled=True)
    return inner, auth


@pytest.fixture
def disabled_app(monkeypatch):
    """Minimal FastAPI app with auth middleware DISABLED."""
    import yunaki_skills.auth_store as mod

    original_client = mod.MongoClient

    class _FailClient:
        def __init__(self, *a, **k):
            raise ConnectionError("no mongo")

    mod.MongoClient = _FailClient
    auth = AuthStore()
    mod.MongoClient = original_client

    inner = FastAPI()

    @inner.get("/api/protected")
    async def protected():
        return {"ok": True}

    inner.add_middleware(APIKeyMiddleware, auth_store=auth, enabled=False)
    return inner, auth


def test_protected_route_rejects_missing_key(enabled_app):
    app, _ = enabled_app
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/protected")
    assert resp.status_code == 401


def test_protected_route_rejects_bad_key(enabled_app):
    app, _ = enabled_app
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/protected", headers={"X-API-Key": "yk_badkey"})
    assert resp.status_code == 401


def test_protected_route_allows_valid_key(enabled_app):
    app, auth = enabled_app
    user = auth.register_user("middleware@example.com")
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/protected", headers={"X-API-Key": user.api_key})
    assert resp.status_code == 200


def test_health_endpoint_public_even_when_auth_enabled(enabled_app):
    app, _ = enabled_app
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/health")
    assert resp.status_code == 200


def test_auth_prefix_public_even_when_auth_enabled(enabled_app):
    app, _ = enabled_app
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/auth/register")
    assert resp.status_code == 200


def test_disabled_middleware_allows_all(disabled_app):
    app, _ = disabled_app
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/protected")
    assert resp.status_code == 200


def test_options_preflight_always_passes(enabled_app):
    """CORS preflight (OPTIONS) must never be blocked by auth."""
    app, _ = enabled_app
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.options("/api/protected")
    # 405 (method not allowed) means it reached the route — middleware let it through
    # 200 means there was an OPTIONS handler. Either way, not 401.
    assert resp.status_code != 401
