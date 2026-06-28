"""Tests for the target repo"""
import pytest
from httpx import AsyncClient, ASGITransport
from app import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_root():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/")
    assert r.status_code == 200


@pytest.mark.anyio
async def test_create_user():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/users", json={"name": "Alice", "email": "alice@example.com"})
    assert r.status_code == 200
    assert r.json()["name"] == "Alice"


@pytest.mark.anyio
async def test_list_users():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/users")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ─── These will FAIL initially (agent must implement them) ──────────────

@pytest.mark.anyio
async def test_get_user_by_id():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/users", json={"name": "Bob", "email": "bob@example.com"})
        user_id = r.json()["id"]
        r = await ac.get(f"/users/{user_id}")
    assert r.status_code == 200
    assert r.json()["name"] == "Bob"


@pytest.mark.anyio
async def test_get_user_not_found():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/users/9999")
    assert r.status_code == 404


@pytest.mark.anyio
async def test_delete_user():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/users", json={"name": "Charlie", "email": "charlie@example.com"})
        user_id = r.json()["id"]
        r = await ac.delete(f"/users/{user_id}")
    assert r.status_code == 204


@pytest.mark.anyio
async def test_health_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert "status" in data
    assert "user_count" in data
