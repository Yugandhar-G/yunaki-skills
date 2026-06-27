"""MongoDB-backed skill storage with semantic search and pattern matching."""

import hashlib
import logging
import math
import re
from datetime import datetime, timezone
from typing import Optional

from pymongo import MongoClient

from yunaki_skills import governance
from yunaki_skills.config import build_mongo_uri
from yunaki_skills.interfaces import (
    Granularity,
    Skill,
    SkillBank,
    SkillStatus,
    TriggerType,
)
from yunaki_skills.redis_cache import EmbeddingCache

logger = logging.getLogger(__name__)

# Embedding dimensionality. Matches all-MiniLM-L6-v2 so stored vectors stay
# comparable whether they came from the model or the deterministic fallback.
_EMBED_DIM = 384


class SkillBank(SkillBank):
    """MongoDB-backed skill storage. Implements the SkillBank interface."""

    def __init__(self, repo_id: Optional[str] = None):
        uri = build_mongo_uri()
        self._client = MongoClient(uri)
        self._db = self._client["yunaki"]
        self._skills = self._db["skills"]
        self._history = self._db["skills_history"]
        self._embeddings_col = self._db["skill_embeddings"]
        self._runs = self._db["runs"]

        # Namespace isolation: each repo gets its own logical skill bank. None
        # is the shared/global namespace. All reads and writes are scoped to it.
        self._repo_id = repo_id

        # Encoder is loaded lazily on first use. If sentence-transformers (or
        # its torch/torchvision stack) can't load, we fall back to a
        # deterministic token-hash embedding so retrieval still works.
        self._encoder = None
        self._encoder_failed = False

        # Optional Redis embedding cache (no-op if Redis is unavailable).
        self._embed_cache = EmbeddingCache()

    # ── encoder (lazy, with deterministic fallback) ──────────────────────

    def _get_encoder(self):
        """Lazily load the SentenceTransformer encoder.

        Returns the model, or None if it cannot be loaded (in which case the
        caller uses the hash-based fallback). The failure is logged once.
        """
        if self._encoder is not None or self._encoder_failed:
            return self._encoder
        try:
            from sentence_transformers import SentenceTransformer

            self._encoder = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("Loaded sentence-transformers encoder")
        except Exception as e:
            self._encoder_failed = True
            logger.warning(
                "sentence-transformers unavailable (%s) — using deterministic "
                "token-hash embeddings for skill retrieval",
                e,
            )
        return self._encoder

    def _hash_embedding(self, text: str) -> list[float]:
        """Deterministic bag-of-tokens embedding hashed into _EMBED_DIM buckets.

        Cheap, dependency-free, and good enough for token-overlap similarity
        across a small skill bank. Normalized so cosine similarity is stable.
        """
        vec = [0.0] * _EMBED_DIM
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        for tok in tokens:
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            vec[h % _EMBED_DIM] += 1.0
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec

    # ── helpers ──────────────────────────────────────────────────────────

    def _skill_to_doc(self, skill: Skill) -> dict:
        doc = skill.model_dump()
        # Pin the skill to this bank's namespace regardless of what the caller
        # set, so a skill cannot leak across repos via a stale repo_id field.
        doc["repo_id"] = self._repo_id
        return doc

    def _doc_to_skill(self, doc: dict) -> Optional[Skill]:
        if doc is None:
            return None
        doc.pop("_id", None)
        return Skill(**doc)

    def _namespace_filter(self) -> dict:
        """Mongo filter restricting to this bank's namespace.

        `{"repo_id": None}` matches both explicit nulls and legacy docs that
        predate the repo_id field, keeping the global namespace backward
        compatible.
        """
        return {"repo_id": self._repo_id}

    def _retrieval_filter(self) -> dict:
        """Namespace filter + governance gate for injectable skills.

        Only APPROVED/ACTIVE skills are retrievable. A missing status (legacy
        docs) is treated as retrievable for backward compatibility.
        """
        statuses = governance.retrievable_statuses()
        return {
            **self._namespace_filter(),
            "$or": [
                {"status": {"$in": statuses}},
                {"status": {"$exists": False}},
            ],
        }

    def _compute_embedding(self, text: str) -> list[float]:
        cached = self._embed_cache.get(text)
        if cached is not None:
            return cached
        embedding = self._compute_embedding_uncached(text)
        self._embed_cache.set(text, embedding)
        return embedding

    def _compute_embedding_uncached(self, text: str) -> list[float]:
        encoder = self._get_encoder()
        if encoder is None:
            return self._hash_embedding(text)
        try:
            vec = encoder.encode(text, normalize_embeddings=True)
            return vec.tolist()
        except Exception as e:
            logger.warning("Encoder.encode failed (%s) — using hash embedding", e)
            return self._hash_embedding(text)

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        return dot / (norm_a * norm_b + 1e-10)

    # ── public API ───────────────────────────────────────────────────────

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def add(self, skill: Skill) -> str:
        """Add a new skill. Returns the skill ID."""
        doc = self._skill_to_doc(skill)

        # Upsert keyed by (id, repo_id) so the same skill id can exist
        # independently in different repo namespaces.
        self._skills.update_one(
            {"id": skill.id, "repo_id": self._repo_id},
            {"$setOnInsert": doc},
            upsert=True,
        )

        # Archive in history for version tracking (strip _id to avoid duplicate key)
        history_doc = {**doc, "_archived_at": self._now_iso()}
        history_doc.pop("_id", None)
        self._history.insert_one(history_doc)

        # Compute and store embedding for semantic search
        embed_text = f"{skill.title} {skill.when_to_apply} {skill.trigger.query}"
        embedding = self._compute_embedding(embed_text)
        self._embeddings_col.update_one(
            {"skill_id": skill.id, "repo_id": self._repo_id},
            {"$set": {"skill_id": skill.id, "repo_id": self._repo_id, "embedding": embedding}},
            upsert=True,
        )

        return skill.id

    def get(self, skill_id: str) -> Optional[Skill]:
        """Get a skill by ID within this namespace."""
        doc = self._skills.find_one({"id": skill_id, **self._namespace_filter()})
        return self._doc_to_skill(doc)

    def update(self, skill_id: str, skill: Skill) -> bool:
        """Update an existing skill (evolution). Returns success."""
        scope = {"id": skill_id, **self._namespace_filter()}
        old_doc = self._skills.find_one(scope)
        if old_doc is None:
            return False

        # Archive the old version in history (strip _id to avoid duplicate key)
        archive_doc = dict(old_doc)
        archive_doc.pop("_id", None)
        archive_doc["_archived_at"] = self._now_iso()
        self._history.insert_one(archive_doc)

        # Replace with new version (namespace pinned by _skill_to_doc)
        new_doc = self._skill_to_doc(skill)
        result = self._skills.replace_one(scope, new_doc)

        # Update embedding
        embed_text = f"{skill.title} {skill.when_to_apply} {skill.trigger.query}"
        embedding = self._compute_embedding(embed_text)
        self._embeddings_col.update_one(
            {"skill_id": skill.id, "repo_id": self._repo_id},
            {"$set": {"skill_id": skill.id, "repo_id": self._repo_id, "embedding": embedding}},
            upsert=True,
        )

        return result.acknowledged

    def set_status(self, skill_id: str, status: SkillStatus) -> bool:
        """Transition a skill's governance status (approve/reject/activate).

        Archives the pre-change document to history so the governance trail is
        auditable. Returns False if the skill is not found in this namespace.
        """
        scope = {"id": skill_id, **self._namespace_filter()}
        old_doc = self._skills.find_one(scope)
        if old_doc is None:
            return False

        archive_doc = dict(old_doc)
        archive_doc.pop("_id", None)
        archive_doc["_archived_at"] = self._now_iso()
        archive_doc["_status_change"] = f"{old_doc.get('status', 'unknown')} -> {status.value}"
        self._history.insert_one(archive_doc)

        result = self._skills.update_one(scope, {"$set": {"status": status.value}})
        return result.modified_count > 0 or result.matched_count > 0

    def search_semantic(self, query: str, top_k: int = 3) -> list[Skill]:
        """Semantic search for task-level skills.

        Embeddings are computed on the fly from the live skill docs with the
        currently-active embedding function. This guarantees the query and the
        corpus live in the same vector space — critical because the encoder may
        be the MiniLM model or the deterministic hash fallback depending on the
        environment, and the two spaces are not comparable.
        """
        query_vec = self._compute_embedding(query)

        # Only retrievable (approved/active) skills in this namespace.
        docs = list(self._skills.find(self._retrieval_filter()))
        if not docs:
            return []

        scored = []
        for doc in docs:
            skill = self._doc_to_skill(doc)
            embed_text = f"{skill.title} {skill.when_to_apply} {skill.trigger.query}"
            corpus_vec = self._compute_embedding(embed_text)
            sim = self._cosine_similarity(query_vec, corpus_vec)
            scored.append((sim, skill))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [skill for _, skill in scored[:top_k]]

    def search_pattern(self, text: str) -> list[Skill]:
        """Pattern match for event-driven skills. Regex on text."""
        # Retrievable event-driven skills in this namespace.
        event_skills = self._skills.find({"granularity": Granularity.EVENT_DRIVEN, **self._retrieval_filter()})
        matched = []
        for doc in event_skills:
            skill = self._doc_to_skill(doc)
            if skill.trigger.type == TriggerType.PATTERN and skill.trigger.patterns:
                for pattern in skill.trigger.patterns:
                    try:
                        if re.search(pattern, text):
                            matched.append(skill)
                            break
                    except re.error:
                        # Skip invalid regex patterns
                        continue
        return matched

    def list_all(self) -> list[Skill]:
        """List all skills in this namespace (any status), score descending.

        Unlike retrieval, this exposes every status so the governance dashboard
        can show drafts and pending-review skills awaiting approval.
        """
        docs = self._skills.find(self._namespace_filter()).sort("score", -1)
        return [self._doc_to_skill(doc) for doc in docs]

    def get_history(self, skill_id: str) -> list[Skill]:
        """Get version history of a skill (for evolution timeline)."""
        docs = self._history.find({"id": skill_id, **self._namespace_filter()}).sort("_archived_at", 1)
        return [self._doc_to_skill(doc) for doc in docs]

    def save_run(self, run_data: dict) -> None:
        """Persist a completed evolution run to the `runs` collection.

        Accepts a plain dict (typically TaskResult.model_dump()). The caller
        owns the schema; we only ensure a stored copy so dashboard stats and
        CLI-triggered runs share the same source of truth.
        """
        self._runs.insert_one(dict(run_data))
