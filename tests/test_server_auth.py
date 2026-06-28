"""Offline tests for server/auth.py — token + GitHub HMAC verification."""

import hashlib
import hmac
import json

from server import auth


def test_load_tokens_inline():
    tokens = auth.load_tokens(inline=json.dumps({"t1": "o/a", "t2": "o/b"}))
    assert tokens == {"t1": "o/a", "t2": "o/b"}


def test_load_tokens_from_file(tmp_path):
    f = tmp_path / "tokens.json"
    f.write_text(json.dumps({"tok": "owner/repo"}))
    assert auth.load_tokens(path=str(f)) == {"tok": "owner/repo"}


def test_load_tokens_malformed_fails_closed():
    assert auth.load_tokens(inline="{not json") == {}  # no tokens => everything rejected
    assert auth.load_tokens(inline=json.dumps(["not", "a", "dict"])) == {}


def test_load_tokens_empty_sources():
    assert auth.load_tokens(inline="", path=None) == {}


def test_repo_for_token_matches():
    tokens = {"secret-token": "owner/repo"}
    assert auth.repo_for_token(tokens, "secret-token") == "owner/repo"


def test_repo_for_token_rejects_unknown_and_empty():
    tokens = {"secret-token": "owner/repo"}
    assert auth.repo_for_token(tokens, "wrong") is None
    assert auth.repo_for_token(tokens, None) is None
    assert auth.repo_for_token({}, "anything") is None


def test_bearer_token_parsing():
    assert auth.bearer_token("Bearer abc123") == "abc123"
    assert auth.bearer_token("bearer abc123") == "abc123"  # case-insensitive scheme
    assert auth.bearer_token("Token abc") is None
    assert auth.bearer_token(None) is None
    assert auth.bearer_token("Bearer ") is None


def test_verify_github_signature_valid():
    secret, body = "shh", b'{"action":"closed"}'
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert auth.verify_github_signature(secret, body, sig) is True


def test_verify_github_signature_rejects_tampered_body():
    secret, body = "shh", b'{"action":"closed"}'
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert auth.verify_github_signature(secret, b'{"action":"opened"}', sig) is False


def test_verify_github_signature_rejects_missing_or_wrong_format():
    assert auth.verify_github_signature("shh", b"x", None) is False
    assert auth.verify_github_signature("shh", b"x", "md5=deadbeef") is False
    assert auth.verify_github_signature("", b"x", "sha256=whatever") is False
