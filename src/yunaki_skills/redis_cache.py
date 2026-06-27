"""Optional Redis cache for skill embeddings.

Embeddings are deterministic for a given text + encoder, so caching them keyed
by a content hash avoids recomputing MiniLM vectors on every retrieval. Redis
is strictly optional: if the package is missing or the server is unreachable,
every method degrades to a no-op and callers compute embeddings normally.
"""

import hashlib
import json
import logging
from typing import Optional

from yunaki_skills.config import get as cfg

logger = logging.getLogger(__name__)

# Embeddings rarely change; a long TTL keeps the cache warm without growing
# unbounded. 7 days in seconds.
_DEFAULT_TTL = 7 * 24 * 3600
_KEY_PREFIX = "yunaki:embed:"


class EmbeddingCache:
    """Thin wrapper over redis with graceful degradation to no-op."""

    def __init__(self, url: Optional[str] = None, ttl: int = _DEFAULT_TTL):
        self._ttl = ttl
        self._client = None
        self._disabled = False
        self._url = url or cfg("REDIS_URL", "redis://localhost:6379/0")

    # ── connection (lazy) ────────────────────────────────────────────────

    def _get_client(self):
        if self._client is not None or self._disabled:
            return self._client
        try:
            import redis  # imported lazily so redis stays an optional dep

            client = redis.Redis.from_url(self._url, socket_connect_timeout=2, socket_timeout=2)
            client.ping()
            self._client = client
            logger.info("Embedding cache connected to Redis at %s", self._url)
        except Exception as e:
            self._disabled = True
            logger.warning("Redis unavailable (%s) — embedding cache disabled", e)
        return self._client

    # ── helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _key(text: str) -> str:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return f"{_KEY_PREFIX}{digest}"

    # ── public API ───────────────────────────────────────────────────────

    def get(self, text: str) -> Optional[list[float]]:
        """Return a cached embedding for `text`, or None on miss/unavailable."""
        client = self._get_client()
        if client is None:
            return None
        try:
            raw = client.get(self._key(text))
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as e:
            logger.warning("Embedding cache get failed (%s) — ignoring", e)
            return None

    def set(self, text: str, embedding: list[float]) -> None:
        """Store an embedding for `text`. Failures are swallowed."""
        client = self._get_client()
        if client is None:
            return
        try:
            client.setex(self._key(text), self._ttl, json.dumps(embedding))
        except Exception as e:
            logger.warning("Embedding cache set failed (%s) — ignoring", e)

    @property
    def available(self) -> bool:
        return self._get_client() is not None
