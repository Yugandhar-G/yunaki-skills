"""Shared super-memory service (FastAPI). A thin HTTP layer over the local logic.

The whole point is reuse: the store is the SAME per-project markdown fact store, just on a
persistent volume (`YUNAKI_FACTS_DIR`, e.g. /data), and the endpoints call the SAME tested
functions the CLI uses — `ingest_pr.ingest_prs`, `consolidate.consolidate`, `facts.fetch`.
No new storage backend, no LLM.

  - GET  /health   liveness.
  - GET  /recall   bearer-token-scoped; returns a repo's markdown context for a skill.
  - POST /webhook  GitHub `pull_request: merged` (HMAC-verified) -> ingest + consolidate
                   that repo in the background.
  - POST /ingest   bearer-token-scoped manual seed/refresh of the token's repo.

Each per-repo token only ever touches its own repo's slice (`project=<repo>`), so the store
is partitioned and individually revocable.
"""

from __future__ import annotations

import os
import re

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, Response

import consolidate
import facts
import ingest_pr
from server import auth

app = FastAPI(title="yunaki super-memory", version="1.0")

# repo becomes a directory segment (<root>/<owner>/<repo>/facts), so constrain it to a
# real owner/repo shape — no traversal, no absolute paths.
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _data_dir() -> str:
    """Persistent store root (read per request so tests/redeploys can point elsewhere)."""
    return os.environ.get("YUNAKI_FACTS_DIR", "/data")


def _valid_repo(repo: object) -> bool:
    return isinstance(repo, str) and ".." not in repo and bool(_REPO_RE.match(repo))


def _require_repo(authorization: str | None) -> str:
    """Resolve the bearer token to its repo or reject. Fails closed."""
    repo = auth.repo_for_token(auth.load_tokens(), auth.bearer_token(authorization))
    if not repo or not _valid_repo(repo):
        raise HTTPException(status_code=401, detail="invalid or missing token")
    return repo


def _ingest_repo(repo: str, root: str) -> None:
    """Incremental ingest + curate for one repo. Never raises (mirrors the CLI contract)."""
    try:
        ingest_pr.ingest_prs(repo=repo, project=repo, root=root)
        consolidate.consolidate(project=repo, root=root)
    except Exception:  # noqa: BLE001 — background task; a failure must not crash the worker
        return


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/recall")
def recall(
    skill: str,
    query: str | None = None,
    limit: int = 8,
    authorization: str | None = Header(default=None),
) -> Response:
    repo = _require_repo(authorization)
    body = facts.fetch(skill, query=query, project=repo, limit=limit, root=_data_dir())
    return Response(content=body, media_type="text/markdown")


@app.post("/ingest")
def ingest(
    background: BackgroundTasks,
    authorization: str | None = Header(default=None),
) -> dict:
    repo = _require_repo(authorization)
    background.add_task(_ingest_repo, repo, _data_dir())
    return {"status": "scheduled", "repo": repo}


@app.post("/webhook")
async def webhook(request: Request, background: BackgroundTasks) -> dict:
    raw = await request.body()
    secret = os.environ.get("YUNAKI_WEBHOOK_SECRET", "")
    sig = request.headers.get("X-Hub-Signature-256")
    if not auth.verify_github_signature(secret, raw, sig):
        raise HTTPException(status_code=401, detail="bad signature")
    try:
        payload = await request.json()
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="invalid payload") from None
    pr = payload.get("pull_request") or {}
    merged = payload.get("action") == "closed" and bool(pr.get("merged"))
    repo = (payload.get("repository") or {}).get("full_name")
    if not (merged and isinstance(repo, str) and _valid_repo(repo)):
        return {"status": "ignored"}  # not a merged-PR event for a valid repo
    background.add_task(_ingest_repo, repo, _data_dir())
    return {"status": "scheduled", "repo": repo}
