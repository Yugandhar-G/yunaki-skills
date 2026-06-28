"""Auth for the shared super-memory service. Stdlib only.

Two independent checks:

  - **Per-repo bearer tokens** gate `/recall` and `/webhook`. A token maps to exactly one
    `owner/repo`, so a token can only ever read or write that repo's slice of the store —
    partitioned and individually revocable. Tokens are loaded from a JSON file on the
    persistent volume (`YUNAKI_TOKENS_FILE`) or inline JSON (`YUNAKI_TOKENS`).
  - **GitHub webhook HMAC** (`X-Hub-Signature-256`) verifies that a webhook really came
    from GitHub, using the repo's configured webhook secret.

All comparisons are constant-time (`hmac.compare_digest`).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os

_TOKENS_FILE_ENV = "YUNAKI_TOKENS_FILE"
_TOKENS_INLINE_ENV = "YUNAKI_TOKENS"


def load_tokens(inline: str | None = None, path: str | None = None) -> dict[str, str]:
    """Return {token: "owner/repo"}. Reads inline JSON first, then a JSON file; both
    default to their env vars. Returns {} on anything malformed (fail closed: no token
    matches, so every request is rejected rather than silently granted)."""
    raw = inline if inline is not None else os.environ.get(_TOKENS_INLINE_ENV)
    if not raw:
        file_path = path if path is not None else os.environ.get(_TOKENS_FILE_ENV)
        if file_path and os.path.exists(file_path):
            try:
                with open(file_path, encoding="utf-8") as fh:
                    raw = fh.read()
            except OSError:
                return {}
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if k and v}


def repo_for_token(tokens: dict[str, str], presented: str | None) -> str | None:
    """Constant-time-ish lookup of the repo a presented token grants. None if no match."""
    if not presented:
        return None
    for token, repo in tokens.items():
        if hmac.compare_digest(token, presented):
            return repo
    return None


def bearer_token(authorization: str | None) -> str | None:
    """Extract the token from an `Authorization: Bearer <token>` header."""
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def verify_github_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Verify GitHub's `X-Hub-Signature-256: sha256=...` HMAC over the raw body."""
    if not secret or not signature_header:
        return False
    prefix = "sha256="
    if not signature_header.startswith(prefix):
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header[len(prefix) :])
