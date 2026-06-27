"""Pydantic models + response envelope for the HTTP/WS API.

Covers auth (users, API keys), multi-repo registration, and the standard
response envelope used by the newer endpoints. Existing skill/run/stats
endpoints keep their legacy raw shape for dashboard compatibility.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

# ─── Response Envelope ───────────────────────────────────────────────────────


class Envelope(BaseModel):
    """Consistent API response envelope: {success, data, error, pagination}."""

    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    pagination: Optional[dict] = None


def ok(data: Any = None, pagination: Optional[dict] = None) -> dict:
    return Envelope(success=True, data=data, pagination=pagination).model_dump()


def err(message: str) -> dict:
    return Envelope(success=False, error=message).model_dump()


# ─── Users / Auth ────────────────────────────────────────────────────────────


class Plan(str, Enum):
    FREE = "free"
    PRO = "pro"


class User(BaseModel):
    """A registered user. `api_key` is only populated on registration response;
    it is never stored in plaintext and never returned on subsequent reads."""

    id: str
    email: str
    api_key: Optional[str] = None
    created_at: str
    plan: Plan = Plan.FREE


class RegisterRequest(BaseModel):
    email: str
    plan: Plan = Plan.FREE

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        v = v.strip().lower()
        # Deliberately light validation — we only need a sane, unique handle,
        # not RFC-5322 compliance.
        if "@" not in v or "." not in v.split("@")[-1] or len(v) < 5:
            raise ValueError("invalid email address")
        return v


class VerifyResponse(BaseModel):
    valid: bool
    user_id: Optional[str] = None
    plan: Optional[Plan] = None


# ─── Repositories ────────────────────────────────────────────────────────────


class Repo(BaseModel):
    """A user-registered repository. Doubles as a skill-bank namespace.

    The access token is write-only: it is accepted on create and stored, but is
    never echoed back. Responses expose `has_token` instead.
    """

    id: str
    user_id: str
    name: str
    url: str
    branch: str = "main"
    has_token: bool = False
    created_at: str


class RepoCreateRequest(BaseModel):
    url: str
    branch: str = "main"
    token: Optional[str] = None
    name: Optional[str] = None

    @field_validator("url")
    @classmethod
    def _valid_url(cls, v: str) -> str:
        v = v.strip()
        if not (v.startswith("http://") or v.startswith("https://") or v.startswith("git@")):
            raise ValueError("repo url must start with http(s):// or git@")
        return v


# ─── Run requests ────────────────────────────────────────────────────────────


class RunRequest(BaseModel):
    task_description: str
    max_iterations: int = Field(default=3, ge=1, le=10)
    org_id: Optional[str] = None  # org namespace to run against (None = global)
    run_id: Optional[str] = None  # client-supplied id so it can pre-subscribe to /ws
    wait: bool = True  # True = block + return result; False = run in background


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
