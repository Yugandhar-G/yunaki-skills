"""Tests for EmbeddingCache — graceful-degradation Redis wrapper.

Redis is never actually contacted. We test the no-op path (Redis unavailable /
not installed) and the happy path via a mock redis client.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from yunaki_skills.redis_cache import _KEY_PREFIX, EmbeddingCache

# ─── _key helper ─────────────────────────────────────────────────────────────


def test_key_is_prefixed():
    key = EmbeddingCache._key("hello")
    assert key.startswith(_KEY_PREFIX)


def test_key_is_deterministic():
    assert EmbeddingCache._key("abc") == EmbeddingCache._key("abc")


def test_key_differs_for_different_text():
    assert EmbeddingCache._key("abc") != EmbeddingCache._key("xyz")


# ─── Degradation path (Redis unavailable) ────────────────────────────────────


@pytest.fixture
def disabled_cache():
    """EmbeddingCache with Redis forced disabled via ImportError."""
    cache = EmbeddingCache(url="redis://localhost:1/0")  # unreachable port
    # Simulate redis not installed
    cache._disabled = True
    return cache


def test_get_returns_none_when_disabled(disabled_cache):
    result = disabled_cache.get("some text")
    assert result is None


def test_set_is_noop_when_disabled(disabled_cache):
    # Should not raise
    disabled_cache.set("some text", [0.1, 0.2, 0.3])


def test_available_false_when_disabled(disabled_cache):
    assert disabled_cache.available is False


# ─── _get_client with no redis package ───────────────────────────────────────


def test_get_client_disables_on_import_error():
    cache = EmbeddingCache(url="redis://localhost")
    with patch.dict("sys.modules", {"redis": None}):
        client = cache._get_client()
    assert client is None
    assert cache._disabled is True


def test_get_client_disables_on_connection_error():
    cache = EmbeddingCache(url="redis://localhost:1/0")  # nothing listening there

    mock_redis = MagicMock()
    mock_redis.Redis.from_url.return_value.ping.side_effect = ConnectionError("refused")

    with patch.dict("sys.modules", {"redis": mock_redis}):
        client = cache._get_client()

    assert client is None
    assert cache._disabled is True


# ─── Happy path via mock redis client ────────────────────────────────────────


def _make_mock_redis(stored: dict | None = None):
    """Return a MagicMock redis module whose from_url returns a usable client."""
    if stored is None:
        stored = {}
    mock_client = MagicMock()
    mock_client.ping.return_value = True

    def _get(key):
        return stored.get(key)

    def _setex(key, ttl, value):
        stored[key] = value

    mock_client.get.side_effect = _get
    mock_client.setex.side_effect = _setex

    mock_redis_mod = MagicMock()
    mock_redis_mod.Redis.from_url.return_value = mock_client
    return mock_redis_mod, mock_client, stored


def test_get_returns_none_on_cache_miss():
    mock_redis_mod, _, _ = _make_mock_redis()
    cache = EmbeddingCache(url="redis://localhost")

    with patch.dict("sys.modules", {"redis": mock_redis_mod}):
        result = cache.get("missing text")

    assert result is None


def test_set_and_get_round_trip():
    import json

    stored: dict = {}
    mock_redis_mod, mock_client, stored = _make_mock_redis(stored)

    cache = EmbeddingCache(url="redis://localhost")
    embedding = [0.1, 0.2, 0.3]

    with patch.dict("sys.modules", {"redis": mock_redis_mod}):
        cache.set("hello", embedding)
        key = EmbeddingCache._key("hello")
        # Manually decode what was stored
        raw = stored.get(key)
        assert raw is not None
        assert json.loads(raw) == embedding


def test_get_returns_cached_embedding():
    import json

    embedding = [0.4, 0.5, 0.6]
    key = EmbeddingCache._key("test text")
    stored = {key: json.dumps(embedding)}
    mock_redis_mod, _, _ = _make_mock_redis(stored)

    cache = EmbeddingCache(url="redis://localhost")

    with patch.dict("sys.modules", {"redis": mock_redis_mod}):
        result = cache.get("test text")

    assert result == embedding


def test_available_true_when_connected():
    mock_redis_mod, _, _ = _make_mock_redis()
    cache = EmbeddingCache(url="redis://localhost")

    with patch.dict("sys.modules", {"redis": mock_redis_mod}):
        available = cache.available

    assert available is True


def test_get_swallows_exception_returns_none():
    """get() must not propagate exceptions from redis."""
    mock_redis_mod, mock_client, _ = _make_mock_redis()
    mock_client.get.side_effect = Exception("network glitch")

    cache = EmbeddingCache(url="redis://localhost")

    with patch.dict("sys.modules", {"redis": mock_redis_mod}):
        result = cache.get("some text")

    assert result is None


def test_set_swallows_exception():
    """set() must not propagate exceptions from redis."""
    mock_redis_mod, mock_client, _ = _make_mock_redis()
    mock_client.setex.side_effect = Exception("write fail")

    cache = EmbeddingCache(url="redis://localhost")

    with patch.dict("sys.modules", {"redis": mock_redis_mod}):
        cache.set("some text", [0.1])  # must not raise


def test_get_client_cached_after_first_call():
    """Subsequent calls to _get_client must reuse the same connection."""
    mock_redis_mod, mock_client, _ = _make_mock_redis()
    cache = EmbeddingCache(url="redis://localhost")

    with patch.dict("sys.modules", {"redis": mock_redis_mod}):
        c1 = cache._get_client()
        c2 = cache._get_client()

    assert c1 is c2
    # ping called exactly once (on first connect, not second)
    mock_client.ping.assert_called_once()
