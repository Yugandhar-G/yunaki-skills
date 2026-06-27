"""User + repository storage with API-key auth.

MongoDB-backed (`users`, `repos` collections) with an in-memory fallback that
mirrors the rest of the app's graceful-degradation pattern, so the service runs
even when Mongo is unreachable.

API keys are generated once, returned once, and stored only as SHA-256 hashes.
Repo access tokens are stored but never returned (responses expose has_token).
"""

import hashlib
import logging
import secrets
from typing import Optional

from pymongo import ASCENDING, MongoClient

from yunaki_skills.api_models import Plan, Repo, User, utc_now_iso
from yunaki_skills.config import build_mongo_uri
from yunaki_skills.config import get as cfg

logger = logging.getLogger(__name__)

_API_KEY_PREFIX = "yk_"


def generate_api_key() -> str:
    """Generate a fresh opaque API key (shown to the user exactly once)."""
    return _API_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


class AuthStore:
    """Persistence + verification for users, API keys, and repos."""

    def __init__(self):
        self._mongo_ok = False
        self._users_col = None
        self._repos_col = None
        # In-memory fallbacks (keyed by id) used only when Mongo is down.
        self._users: dict[str, dict] = {}
        self._repos: dict[str, dict] = {}
        self._key_index: dict[str, str] = {}  # api_key_hash -> user_id

        try:
            uri = build_mongo_uri()
            client = MongoClient(uri, serverSelectionTimeoutMS=3000)
            client.admin.command("ping")
            db = client[cfg("MONGO_DB", "yunaki")]
            self._users_col = db["users"]
            self._repos_col = db["repos"]
            self._users_col.create_index([("email", ASCENDING)], unique=True)
            self._users_col.create_index([("api_key_hash", ASCENDING)], unique=True)
            self._repos_col.create_index([("user_id", ASCENDING)])
            self._mongo_ok = True
            logger.info("AuthStore connected to MongoDB")
        except Exception as e:
            logger.warning("AuthStore: MongoDB unavailable (%s) — using in-memory store", e)

    # ── serialization ────────────────────────────────────────────────────

    @staticmethod
    def _doc_to_user(doc: dict, api_key: Optional[str] = None) -> User:
        return User(
            id=doc["id"],
            email=doc["email"],
            api_key=api_key,
            created_at=doc["created_at"],
            plan=Plan(doc.get("plan", "free")),
        )

    @staticmethod
    def _doc_to_repo(doc: dict) -> Repo:
        return Repo(
            id=doc["id"],
            user_id=doc["user_id"],
            name=doc["name"],
            url=doc["url"],
            branch=doc.get("branch", "main"),
            has_token=bool(doc.get("token")),
            created_at=doc["created_at"],
        )

    # ── users ─────────────────────────────────────────────────────────────

    def _email_exists(self, email: str) -> bool:
        if self._mongo_ok:
            return self._users_col.count_documents({"email": email}, limit=1) > 0
        return any(u["email"] == email for u in self._users.values())

    def register_user(self, email: str, plan: Plan = Plan.FREE) -> User:
        """Create a user and return it WITH a freshly minted api_key.

        Raises ValueError if the email is already registered.
        """
        email = email.strip().lower()
        if self._email_exists(email):
            raise ValueError(f"email already registered: {email}")

        raw_key = generate_api_key()
        doc = {
            "id": "user_" + secrets.token_hex(8),
            "email": email,
            "api_key_hash": hash_key(raw_key),
            "created_at": utc_now_iso(),
            "plan": plan.value,
        }
        if self._mongo_ok:
            self._users_col.insert_one(dict(doc))
        else:
            self._users[doc["id"]] = doc
            self._key_index[doc["api_key_hash"]] = doc["id"]

        return self._doc_to_user(doc, api_key=raw_key)

    def verify_key(self, raw_key: Optional[str]) -> Optional[User]:
        """Return the owning user for a valid API key, else None."""
        if not raw_key:
            return None
        key_hash = hash_key(raw_key)
        if self._mongo_ok:
            doc = self._users_col.find_one({"api_key_hash": key_hash}, {"_id": 0})
            return self._doc_to_user(doc) if doc else None
        user_id = self._key_index.get(key_hash)
        if not user_id:
            return None
        doc = self._users.get(user_id)
        return self._doc_to_user(doc) if doc else None

    def get_user(self, user_id: str) -> Optional[User]:
        if self._mongo_ok:
            doc = self._users_col.find_one({"id": user_id}, {"_id": 0})
            return self._doc_to_user(doc) if doc else None
        doc = self._users.get(user_id)
        return self._doc_to_user(doc) if doc else None

    # ── repos ─────────────────────────────────────────────────────────────

    def create_repo(
        self,
        user_id: str,
        url: str,
        branch: str = "main",
        token: Optional[str] = None,
        name: Optional[str] = None,
    ) -> Repo:
        repo_name = name or url.rstrip("/").split("/")[-1].removesuffix(".git") or url
        doc = {
            "id": "repo_" + secrets.token_hex(8),
            "user_id": user_id,
            "name": repo_name,
            "url": url,
            "branch": branch,
            "token": token or "",
            "created_at": utc_now_iso(),
        }
        if self._mongo_ok:
            self._repos_col.insert_one(dict(doc))
        else:
            self._repos[doc["id"]] = doc
        return self._doc_to_repo(doc)

    def list_repos(self, user_id: str) -> list[Repo]:
        if self._mongo_ok:
            docs = self._repos_col.find({"user_id": user_id}, {"_id": 0})
            return [self._doc_to_repo(d) for d in docs]
        return [self._doc_to_repo(d) for d in self._repos.values() if d["user_id"] == user_id]

    def get_repo(self, repo_id: str) -> Optional[Repo]:
        if self._mongo_ok:
            doc = self._repos_col.find_one({"id": repo_id}, {"_id": 0})
            return self._doc_to_repo(doc) if doc else None
        doc = self._repos.get(repo_id)
        return self._doc_to_repo(doc) if doc else None

    def delete_repo(self, user_id: str, repo_id: str) -> bool:
        """Delete a repo owned by `user_id`. Returns False if not found/owned."""
        if self._mongo_ok:
            res = self._repos_col.delete_one({"id": repo_id, "user_id": user_id})
            return res.deleted_count > 0
        doc = self._repos.get(repo_id)
        if doc and doc["user_id"] == user_id:
            del self._repos[repo_id]
            return True
        return False
