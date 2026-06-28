"""Tests for config — env loading and Mongo URI construction."""

from __future__ import annotations

from yunaki_skills import config


def test_get_returns_env_value(monkeypatch):
    monkeypatch.setenv("YUNAKI_TEST_KEY", "value123")
    assert config.get("YUNAKI_TEST_KEY") == "value123"


def test_get_returns_default(monkeypatch):
    monkeypatch.delenv("YUNAKI_MISSING", raising=False)
    assert config.get("YUNAKI_MISSING", "fallback") == "fallback"


def test_build_mongo_uri_prefers_plain_uri(monkeypatch):
    monkeypatch.setenv("MONGODB_URI", "mongodb://db.example:27017/yunaki")
    monkeypatch.delenv("MONGODB_USER", raising=False)
    monkeypatch.delenv("MONGODB_PASS", raising=False)
    assert config.build_mongo_uri() == "mongodb://db.example:27017/yunaki"


def test_build_mongo_uri_rebuilds_when_redacted(monkeypatch):
    monkeypatch.setenv("MONGODB_URI", "mongodb+srv://user:***@cluster.net/yunaki")
    monkeypatch.setenv("MONGODB_USER", "alice")
    monkeypatch.setenv("MONGODB_PASS", "s3cret")
    monkeypatch.setenv("MONGODB_CLUSTER", "cluster.mongodb.net")

    uri = config.build_mongo_uri()
    assert "alice:s3cret@cluster.mongodb.net" in uri
    assert "***" not in uri


def test_build_mongo_uri_localhost_fallback(monkeypatch):
    for key in ("MONGODB_URI", "MONGODB_USER", "MONGODB_PASS"):
        monkeypatch.delenv(key, raising=False)
    assert config.build_mongo_uri() == "mongodb://localhost:27017"
