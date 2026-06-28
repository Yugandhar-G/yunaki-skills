"""Tests for AuthStore — in-memory path (no real MongoDB)."""

from __future__ import annotations

import pytest

from yunaki_skills.api_models import Plan
from yunaki_skills.auth_store import AuthStore, generate_api_key, hash_key

# ─── helpers / keys ──────────────────────────────────────────────────────────


def test_generate_api_key_has_prefix():
    key = generate_api_key()
    assert key.startswith("yk_")


def test_generate_api_key_is_unique():
    keys = {generate_api_key() for _ in range(20)}
    assert len(keys) == 20


def test_hash_key_is_deterministic():
    assert hash_key("abc") == hash_key("abc")


def test_hash_key_differs_for_different_inputs():
    assert hash_key("abc") != hash_key("xyz")


# ─── AuthStore (always falls back to in-memory when Mongo is not reachable) ──


@pytest.fixture
def store(monkeypatch):
    """Patch MongoClient so AuthStore never talks to a real cluster."""
    import yunaki_skills.auth_store as mod

    monkeypatch.setattr(mod, "MongoClient", _raise_mongo)
    return AuthStore()


def _raise_mongo(*args, **kwargs):
    raise ConnectionError("test: no mongo")


# ── register_user ──────────────────────────────────────────────────────────


def test_register_user_returns_user_with_key(store):
    user = store.register_user("alice@example.com")
    assert user.email == "alice@example.com"
    assert user.api_key is not None
    assert user.api_key.startswith("yk_")


def test_register_user_plan_default_free(store):
    user = store.register_user("bob@example.com")
    assert user.plan == Plan.FREE


def test_register_user_plan_pro(store):
    user = store.register_user("pro@example.com", plan=Plan.PRO)
    assert user.plan == Plan.PRO


def test_register_user_normalises_email(store):
    user = store.register_user("  UPPER@Example.COM  ")
    assert user.email == "upper@example.com"


def test_register_duplicate_email_raises(store):
    store.register_user("dup@example.com")
    with pytest.raises(ValueError, match="already registered"):
        store.register_user("DUP@example.com")


def test_register_user_assigns_unique_ids(store):
    u1 = store.register_user("a@example.com")
    u2 = store.register_user("b@example.com")
    assert u1.id != u2.id


# ── verify_key ────────────────────────────────────────────────────────────


def test_verify_key_returns_user_for_valid_key(store):
    user = store.register_user("v@example.com")
    raw_key = user.api_key
    found = store.verify_key(raw_key)
    assert found is not None
    assert found.email == "v@example.com"
    # verify_key does NOT expose the raw api_key
    assert found.api_key is None


def test_verify_key_none_returns_none(store):
    assert store.verify_key(None) is None


def test_verify_key_empty_string_returns_none(store):
    assert store.verify_key("") is None


def test_verify_key_wrong_key_returns_none(store):
    store.register_user("w@example.com")
    assert store.verify_key("yk_notavalidkey") is None


# ── get_user ──────────────────────────────────────────────────────────────


def test_get_user_returns_user_by_id(store):
    user = store.register_user("g@example.com")
    found = store.get_user(user.id)
    assert found is not None
    assert found.id == user.id


def test_get_user_unknown_returns_none(store):
    assert store.get_user("user_nonexistent") is None


# ── repos ─────────────────────────────────────────────────────────────────


def test_create_repo_returns_repo(store):
    user = store.register_user("r@example.com")
    repo = store.create_repo(user.id, url="https://github.com/org/repo")
    assert repo.user_id == user.id
    assert repo.url == "https://github.com/org/repo"
    assert repo.branch == "main"


def test_create_repo_has_token_flag(store):
    user = store.register_user("t@example.com")
    repo_no = store.create_repo(user.id, url="https://github.com/org/a")
    repo_yes = store.create_repo(user.id, url="https://github.com/org/b", token="secret")
    assert repo_no.has_token is False
    assert repo_yes.has_token is True


def test_create_repo_infers_name_from_url(store):
    user = store.register_user("n@example.com")
    repo = store.create_repo(user.id, url="https://github.com/org/my-service.git")
    assert repo.name == "my-service"


def test_create_repo_custom_name(store):
    user = store.register_user("cn@example.com")
    repo = store.create_repo(user.id, url="https://github.com/org/x", name="custom")
    assert repo.name == "custom"


def test_list_repos_returns_user_repos(store):
    u1 = store.register_user("l1@example.com")
    u2 = store.register_user("l2@example.com")
    store.create_repo(u1.id, url="https://github.com/org/a")
    store.create_repo(u1.id, url="https://github.com/org/b")
    store.create_repo(u2.id, url="https://github.com/org/c")

    repos = store.list_repos(u1.id)
    assert len(repos) == 2
    assert all(r.user_id == u1.id for r in repos)


def test_list_repos_empty_for_new_user(store):
    user = store.register_user("empty@example.com")
    assert store.list_repos(user.id) == []


def test_get_repo_returns_repo(store):
    user = store.register_user("gr@example.com")
    repo = store.create_repo(user.id, url="https://github.com/org/z")
    found = store.get_repo(repo.id)
    assert found is not None
    assert found.id == repo.id


def test_get_repo_unknown_returns_none(store):
    assert store.get_repo("repo_nonexistent") is None


def test_delete_repo_succeeds_for_owner(store):
    user = store.register_user("del@example.com")
    repo = store.create_repo(user.id, url="https://github.com/org/del")
    deleted = store.delete_repo(user.id, repo.id)
    assert deleted is True
    assert store.get_repo(repo.id) is None


def test_delete_repo_fails_for_non_owner(store):
    u1 = store.register_user("own@example.com")
    u2 = store.register_user("other@example.com")
    repo = store.create_repo(u1.id, url="https://github.com/org/x")
    assert store.delete_repo(u2.id, repo.id) is False
    # Repo still exists
    assert store.get_repo(repo.id) is not None


def test_delete_repo_unknown_returns_false(store):
    assert store.delete_repo("user_xyz", "repo_nonexistent") is False
