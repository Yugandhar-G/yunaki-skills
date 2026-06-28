"""MongoDB-backed skill storage with semantic search and pattern matching."""

import hashlib
import logging
import math
import re
from datetime import datetime, timezone
from typing import Optional

from pymongo import MongoClient

from yunaki_skills import governance
from yunaki_skills.config import build_mongo_uri, get
from yunaki_skills.interfaces import (
    Granularity,
    Skill,
    SkillBank,
    SkillStatus,
    TriggerType,
)
from yunaki_skills.redis_cache import EmbeddingCache

logger = logging.getLogger(__name__)


def _env_float(key: str, default: float) -> float:
    """Read a float-valued env var, falling back to default on missing/invalid."""
    raw = get(key, "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid float for %s=%r; using default %s", key, raw, default)
        return default


# Embedding dimensionality. Matches all-MiniLM-L6-v2 so stored vectors stay
# comparable whether they came from the model or the deterministic fallback.
_EMBED_DIM = 384


class SkillBank(SkillBank):
    """MongoDB-backed skill storage. Implements the SkillBank interface."""

    def __init__(self, org_id: Optional[str] = None):
        uri = build_mongo_uri()
        self._client = MongoClient(uri)
        self._db = self._client["yunaki"]
        self._skills = self._db["skills"]
        self._history = self._db["skills_history"]
        self._embeddings_col = self._db["skill_embeddings"]
        self._runs = self._db["runs"]

        # Namespace isolation: each org gets its own logical skill bank. None
        # is the personal/global namespace. All reads and writes are scoped to
        # it. Skills are universal — namespacing is by org, never by repo.
        self._org_id = org_id

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
        # set, so a skill cannot leak across orgs via a stale org_id field.
        doc["org_id"] = self._org_id
        # Drop any legacy repo_id so old documents don't carry the dead field.
        doc.pop("repo_id", None)
        return doc

    def _doc_to_skill(self, doc: dict) -> Optional[Skill]:
        if doc is None:
            return None
        doc.pop("_id", None)
        return Skill(**doc)

    def _namespace_filter(self) -> dict:
        """Mongo filter restricting to this bank's namespace.

        `{"org_id": None}` matches both explicit nulls and legacy/seed docs that
        predate the org_id field, keeping the personal/global namespace backward
        compatible.
        """
        return {"org_id": self._org_id}

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

        # Upsert keyed by (id, org_id) so the same skill id can exist
        # independently in different org namespaces.
        self._skills.update_one(
            {"id": skill.id, "org_id": self._org_id},
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
            {"skill_id": skill.id, "org_id": self._org_id},
            {"$set": {"skill_id": skill.id, "org_id": self._org_id, "embedding": embedding}},
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
            {"skill_id": skill.id, "org_id": self._org_id},
            {"$set": {"skill_id": skill.id, "org_id": self._org_id, "embedding": embedding}},
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

    def increment_usage(self, skill_id: str, success: bool) -> bool:
        """Record an application of a skill.

        Increments usage_count, and success_count when the application led to a
        passing result. This is the self-evolution signal: a skill's hit rate
        (success_count / usage_count) reflects how well it actually performs as
        it is reused, independent of its model-assigned score.
        """
        scope = {"id": skill_id, **self._namespace_filter()}
        inc = {"usage_count": 1}
        if success:
            inc["success_count"] = 1
        result = self._skills.update_one(scope, {"$inc": inc})
        return result.matched_count > 0

    def drop(self, skill_id: str, reason: str = "") -> bool:
        """Soft-delete a skill: archive to history, then remove from the live bank.

        Recoverable via ``skills_history``. Also removes the stored embedding.
        Returns False if the skill is not found in this namespace.
        """
        scope = {"id": skill_id, **self._namespace_filter()}
        old_doc = self._skills.find_one(scope)
        if old_doc is None:
            return False

        archive_doc = dict(old_doc)
        archive_doc.pop("_id", None)
        archive_doc["_archived_at"] = self._now_iso()
        archive_doc["_dropped"] = True
        if reason:
            archive_doc["_drop_reason"] = reason
        self._history.insert_one(archive_doc)

        self._skills.delete_one(scope)
        self._embeddings_col.delete_one({"skill_id": skill_id, "org_id": self._org_id})
        return True

    def merge(self, source_ids: list[str], merged: Skill) -> Optional[str]:
        """Consolidate several skills into one.

        Archives and drops the sources, sums their usage/success counts into the
        merged skill (so learning signal is preserved, not reset), and records
        ``provenance.merged_from``. The merged skill may reuse one source's id
        (kept and updated) or introduce a new id (added). Returns the merged
        skill id, or None if none of the sources exist in this namespace.
        """
        sources = [s for s in (self.get(sid) for sid in source_ids) if s is not None]
        if not sources:
            return None

        total_usage = merged.usage_count + sum(s.usage_count for s in sources)
        total_success = merged.success_count + sum(s.success_count for s in sources)
        merged = merged.model_copy(
            update={
                "usage_count": total_usage,
                "success_count": total_success,
                "provenance": merged.provenance.model_copy(update={"merged_from": [s.id for s in sources]}),
            }
        )

        if self.get(merged.id) is not None:
            self.update(merged.id, merged)
        else:
            self.add(merged)

        for s in sources:
            if s.id != merged.id:
                self.drop(s.id, reason=f"merged into {merged.id}")

        return merged.id

    def publish_skill(self, skill_id: str) -> bool:
        """Publish a skill to the marketplace (visibility -> 'public')."""
        scope = {"id": skill_id, **self._namespace_filter()}
        result = self._skills.update_one(scope, {"$set": {"visibility": "public"}})
        return result.matched_count > 0

    def search_marketplace(self, query: str, top_k: int = 5) -> list[Skill]:
        """Semantic search across PUBLIC skills only, ignoring org namespace.

        The marketplace is global: any user can discover any published skill,
        regardless of which org created it. Only retrievable (approved/active)
        public skills are returned.
        """
        query_vec = self._compute_embedding(query)
        statuses = governance.retrievable_statuses()
        docs = list(
            self._skills.find(
                {
                    "visibility": "public",
                    "$or": [
                        {"status": {"$in": statuses}},
                        {"status": {"$exists": False}},
                    ],
                }
            )
        )
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
            scored.append((self._rank_value(sim, skill), skill))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [skill for _, skill in scored[:top_k]]

    @staticmethod
    def _rank_value(sim: float, skill: Skill) -> float:
        """Combine similarity with skill quality for retrieval ranking.

        rank = w_sim*sim + w_score*(score/100) + w_rate*success_rate

        Off by default: w_score and w_rate are 0.0, so ranking is pure cosine
        similarity (today's behavior). Set YUNAKI_RANK_W_SCORE / _W_RATE > 0 to
        let proven, higher-scoring skills win ties. Unproven skills (0 usage) get
        a neutral 0.5 success prior so they are not starved once weighting is on.
        """
        w_sim = _env_float("YUNAKI_RANK_W_SIM", 1.0)
        w_score = _env_float("YUNAKI_RANK_W_SCORE", 0.0)
        w_rate = _env_float("YUNAKI_RANK_W_RATE", 0.0)

        score_norm = max(0.0, min(skill.score / 100.0, 1.0))
        if skill.usage_count > 0:
            success_rate = skill.success_count / skill.usage_count
        else:
            success_rate = 0.5  # neutral prior for unproven skills
        return w_sim * sim + w_score * score_norm + w_rate * success_rate

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
