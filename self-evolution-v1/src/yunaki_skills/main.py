"""
Yunaki Skills — FastAPI Backend + Dashboard Server
Serves the web UI and provides /api/ endpoints for skill registry, evolution, and runs.
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from yunaki_skills.api_models import (
    RegisterRequest,
    VerifyResponse,
    ok,
)
from yunaki_skills.auth_middleware import APIKeyMiddleware
from yunaki_skills.auth_store import AuthStore
from yunaki_skills.config import build_mongo_uri

# ─── Config ────────────────────────────────────────────────────────────────
from yunaki_skills.config import get as cfg
from yunaki_skills.live_runs import STREAM_DONE, broker
from yunaki_skills.run_orchestrator import _SIMULATED_STATUS, execute_run
from yunaki_skills.skill_bank import SkillBank

logger = logging.getLogger(__name__)

MONGO_URI = build_mongo_uri()
DB_NAME = cfg("MONGO_DB", "yunaki")
AUTH_ENABLED = str(cfg("AUTH_ENABLED", "false")).strip().lower() in {"1", "true", "yes", "on"}

# Shared user/auth store (MongoDB-backed with in-memory fallback).
_auth_store = AuthStore()

# ─── Try importing real modules (subagents may build in parallel) ──────────
try:
    from yunaki_skills.interfaces import (
        Skill,
        TaskResult,
    )

    _real_interfaces = True
except ImportError:
    _real_interfaces = False
    Skill = None
    TaskResult = None
    print("[WARN] yunaki_skills.interfaces not importable — running with stubs")

# Import the CONCRETE TaskRunner implementation (not the interface stub).
# The interface's run() returns Ellipsis, which would silently force the
# /api/run endpoint into the simulated stub path. The concrete runner is
# imported lazily-friendly here; it is only instantiated per request.
try:
    from yunaki_skills.task_runner import TaskRunner

    _real_task_runner = True
except Exception as e:  # genai / pymongo / model load issues
    TaskRunner = None
    _real_task_runner = False
    print(f"[WARN] Concrete TaskRunner unavailable ({e}) — /api/run will use stub")

# ─── MongoDB ──────────────────────────────────────────────────────────────
try:
    from pymongo import MongoClient

    _mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    _db = _mongo_client[DB_NAME]
    _skills_col = _db["skills"]
    _history_col = _db["skills_history"]
    _runs_col = _db["runs"]
    # Quick ping
    _mongo_client.admin.command("ping")
    _mongo_ok = True
    print("[INFO] MongoDB connected successfully")
except Exception as e:
    _mongo_ok = False
    _skills_col = None
    _history_col = None
    _runs_col = None
    _stub_skills: dict = {}
    _stub_history: dict = {}
    _stub_runs: list = []
    print(f"[WARN] MongoDB not available ({e}) — running with in-memory stubs")

# ─── Seed Skills ──────────────────────────────────────────────────────────
SEEDS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"


def _load_seed_skills_to_stubs():
    """Load seed JSON files into in-memory stubs (fallback when no MongoDB).

    No-op when MongoDB is available — the stub containers only exist on the
    Mongo-failure path, and seeding to Mongo is handled by _seed_mongodb().
    """
    if _mongo_ok:
        return
    global _stub_skills, _stub_history
    if not SEEDS_DIR.is_dir():
        return
    for fpath in sorted(SEEDS_DIR.glob("*.json")):
        try:
            data = json.loads(fpath.read_text())
            sid = data.get("id", fpath.stem)
            _stub_skills[sid] = data
            _stub_history.setdefault(sid, []).append(data.copy())
        except Exception as e:
            print(f"[WARN] Failed to load seed {fpath}: {e}")


def _seed_mongodb():
    """Insert seed skills into MongoDB if they don't already exist."""
    if not _mongo_ok or not SEEDS_DIR.is_dir():
        return
    for fpath in sorted(SEEDS_DIR.glob("*.json")):
        try:
            data = json.loads(fpath.read_text())
            sid = data.get("id", fpath.stem)
            if _skills_col.count_documents({"id": sid}) == 0:
                _skills_col.insert_one(data)
                _history_col.insert_one({**data, "_history_note": "seed"})
                print(f"[INFO] Seeded skill: {sid}")
        except Exception as e:
            print(f"[WARN] Failed to seed {fpath}: {e}")


# ─── Data access layer (MongoDB or in-memory) ────────────────────────────


def _normalize_status(skill: Optional[dict]) -> Optional[dict]:
    """Ensure every skill exposes governance + sharing fields for the dashboard.

    Legacy/seed docs predate `status` and `visibility`; we default a missing
    status to 'active' and a missing visibility to 'private'. Returns a new dict
    — never mutates input.
    """
    if skill is None:
        return None
    patch = {}
    if not skill.get("status"):
        patch["status"] = "active"
    if not skill.get("visibility"):
        patch["visibility"] = "private"
    if not patch:
        return skill
    return {**skill, **patch}


def _list_skills() -> list[dict]:
    if _mongo_ok:
        raw = list(_skills_col.find({}, {"_id": 0}))
    else:
        raw = list(_stub_skills.values())
    return [_normalize_status(s) for s in raw]


def _get_skill(skill_id: str) -> Optional[dict]:
    if _mongo_ok:
        return _normalize_status(_skills_col.find_one({"id": skill_id}, {"_id": 0}))
    return _normalize_status(_stub_skills.get(skill_id))


def _set_skill_status(skill_id: str, status: str) -> Optional[dict]:
    """Persist a governance status change. Returns the updated skill or None."""
    if _mongo_ok:
        res = _skills_col.find_one_and_update(
            {"id": skill_id},
            {"$set": {"status": status}},
            projection={"_id": 0},
            return_document=True,
        )
        return _normalize_status(res)
    existing = _stub_skills.get(skill_id)
    if existing is None:
        return None
    updated = {**existing, "status": status}
    _stub_skills[skill_id] = updated
    return updated


def _set_skill_visibility(skill_id: str, visibility: str) -> Optional[dict]:
    """Persist a visibility change (e.g. publish to marketplace). Returns the
    updated skill or None if it does not exist."""
    if _mongo_ok:
        res = _skills_col.find_one_and_update(
            {"id": skill_id},
            {"$set": {"visibility": visibility}},
            projection={"_id": 0},
            return_document=True,
        )
        return _normalize_status(res)
    existing = _stub_skills.get(skill_id)
    if existing is None:
        return None
    updated = {**existing, "visibility": visibility}
    _stub_skills[skill_id] = updated
    return updated


def _persist_skill(skill: dict) -> dict:
    """Upsert a skill into the store (Mongo or stub) and archive in history.

    Used by the ingest endpoint. Returns the normalized stored skill.
    """
    sid = skill["id"]
    if _mongo_ok:
        _skills_col.replace_one({"id": sid}, skill, upsert=True)
        _history_col.insert_one({**skill, "_history_note": "ingest"})
    else:
        _stub_skills[sid] = skill
        _stub_history.setdefault(sid, []).append(skill.copy())
    return _normalize_status(skill)


def _get_skill_history(skill_id: str) -> list[dict]:
    if _mongo_ok:
        return list(_history_col.find({"id": skill_id}, {"_id": 0}).sort("version", 1))
    return _stub_history.get(skill_id, [])


def _list_runs() -> list[dict]:
    if _mongo_ok:
        return list(_runs_col.find({}, {"_id": 0}).sort("timestamp", -1))
    return _stub_runs


def _add_run(run_data: dict):
    if _mongo_ok:
        _runs_col.insert_one(run_data.copy())
    else:
        _stub_runs.append(run_data)


# ─── App Setup ────────────────────────────────────────────────────────────

app = FastAPI(title="Yunaki Skills", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API-key enforcement. Added AFTER CORS so CORS remains the outermost layer and
# preflight requests are answered before auth runs. Gated by AUTH_ENABLED so
# local/dev and the existing dashboard keep working without keys; the Docker
# stack turns it on.
app.add_middleware(APIKeyMiddleware, auth_store=_auth_store, enabled=AUTH_ENABLED)


# Initialize seed data eagerly (also works when TestClient skips startup events)
_load_seed_skills_to_stubs()
_seed_mongodb()


@app.on_event("startup")
async def startup():
    # Ensure seeds are loaded even if the eager init didn't run (e.g. race with MongoDB)
    _load_seed_skills_to_stubs()
    _seed_mongodb()


# ─── API Routes ────────────────────────────────────────────────────────────


@app.get("/api/skills")
async def api_list_skills():
    """List all skills from the skill bank."""
    skills = _list_skills()
    return skills


@app.get("/api/skills/{skill_id}")
async def api_get_skill(skill_id: str):
    """Get a single skill by ID."""
    skill = _get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
    return skill


@app.get("/api/skills/{skill_id}/history")
async def api_skill_history(skill_id: str):
    """Get the evolution history of a skill."""
    history = _get_skill_history(skill_id)
    return history


class RunRequest(BaseModel):
    task_description: str
    max_iterations: int = 3
    org_id: Optional[str] = None  # org namespace to evolve against (None = global bank)
    code_snapshot: str = ""  # inline code context the agent edits


@app.post("/api/run")
async def api_trigger_run(req: RunRequest):
    """Trigger a task run through the evolution loop."""
    # Try the real TaskRunner first
    if _real_task_runner:
        try:
            runner = TaskRunner(org_id=req.org_id)
            result = runner.run(
                req.task_description,
                code_snapshot=req.code_snapshot,
                max_iterations=req.max_iterations,
            )
            # TaskRunner already persists the run to the `runs` collection,
            # so we do not call _add_run here (avoids double-counting).
            run_data = result.model_dump()
            run_data["timestamp"] = datetime.utcnow().isoformat()
            run_data["status"] = "completed"
            # Expose skill_delta — the only number that proves the thesis
            run_data["skill_delta"] = result.skill_delta
            return run_data
        except Exception as e:
            # FAIL LOUD: Do NOT silently fall through to a fabricated stub.
            # The old code used to emit random.uniform scores here — that
            # was disqualifiable dishonesty.  Now we surface the error.
            logger.exception("TaskRunner failed — refusing to fabricate scores")
            raise HTTPException(
                status_code=503,
                detail=(
                    f"TaskRunner failed: {e}. "
                    "No simulated fallback — scores must come from real runs. "
                    "Check that GEMINI_API_KEY and MONGODB_URI are set."
                ),
            )

    # No real TaskRunner available at all — fail explicitly
    raise HTTPException(
        status_code=503,
        detail=(
            "No TaskRunner available. Self-evolving skills require a real "
            "LLM backend (Gemini/Antigravity) and MongoDB. Set GEMINI_API_KEY "
            "and MONGODB_URI to enable live runs. The simulated path that "
            "previously fabricated scores has been removed — honest failure "
            "is better than fake success."
        ),
    )


@app.get("/api/runs")
async def api_list_runs():
    """List all past task runs."""
    runs = _list_runs()
    return runs


@app.get("/api/stats")
async def api_stats():
    """Return aggregate stats for the dashboard."""
    skills = _list_skills()
    runs = _list_runs()

    total_skills = len(skills)
    avg_score = sum(s.get("score", 0) for s in skills) / total_skills if total_skills else 0
    total_runs = len(runs)

    # total improvement conflates the agent and the skills: it measures
    # (after - before) against the no-agent baseline.
    improvements = []
    # skill contribution isolates what the skills actually added: (after - control),
    # where control is the agent running WITHOUT skills. Only this delta proves
    # the skills helped. Runs without a control arm are excluded.
    skill_deltas = []
    for r in runs:
        before = r.get("score_before", 0)
        after = r.get("score_after", 0)
        control = r.get("score_control")
        if before > 0:
            improvements.append((after - before) / before * 100)
        if control is not None:
            skill_deltas.append(after - control)

    avg_improvement = sum(improvements) / len(improvements) if improvements else 0
    avg_skill_delta = sum(skill_deltas) / len(skill_deltas) if skill_deltas else None

    return {
        "total_skills": total_skills,
        "avg_score": round(avg_score, 1),
        "total_runs": total_runs,
        # total improvement (vs no-agent baseline) — conflated metric, kept for context
        "avg_improvement": round(avg_improvement, 1),
        # skill contribution (vs agent without skills) — the honest, defensible metric
        "avg_skill_delta": round(avg_skill_delta, 1) if avg_skill_delta is not None else None,
    }


# ─── Skill Governance ──────────────────────────────────────────────────────


@app.post("/api/skills/{skill_id}/approve")
async def api_approve_skill(skill_id: str):
    """Approve a pending skill — promotes it to active."""
    updated = _set_skill_status(skill_id, "active")
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
    return {"id": skill_id, "status": "active"}


@app.post("/api/skills/{skill_id}/reject")
async def api_reject_skill(skill_id: str):
    """Reject a pending skill — marks it rejected so it stops being injected."""
    updated = _set_skill_status(skill_id, "rejected")
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
    return {"id": skill_id, "status": "rejected"}


# ─── Auth ───────────────────────────────────────────────────────────────────


@app.post("/api/auth/register")
async def api_register(req: RegisterRequest):
    """Create a user and return a one-time API key.

    The raw key is shown exactly once here; only its SHA-256 hash is stored.
    """
    try:
        user = _auth_store.register_user(req.email, req.plan)
    except ValueError as e:
        # Duplicate email — client error, surfaced cleanly.
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.exception("register failed")
        raise HTTPException(status_code=500, detail=f"registration failed: {e}")
    return ok(user.model_dump())


@app.post("/api/auth/verify")
async def api_verify(request: Request):
    """Validate the X-API-Key header and report the owning user."""
    api_key = request.headers.get("X-API-Key")
    user = _auth_store.verify_key(api_key) if api_key else None
    if user is None:
        return ok(VerifyResponse(valid=False).model_dump())
    return ok(VerifyResponse(valid=True, user_id=user.id, plan=user.plan).model_dump())


# ─── Multi-repo registry ─────────────────────────────────────────────────────

# ─── Marketplace + Ingest + Apply ──────────────────────────────────────────


class IngestRequest(BaseModel):
    content: str
    filename: str = "skill.txt"
    org_id: Optional[str] = None


@app.post("/api/skills/ingest")
async def api_ingest_skill(req: IngestRequest):
    """Ingest any skill format (.md, .json, .yaml, .txt) and normalize to Yunaki Skill."""
    try:
        from yunaki_skills.skill_ingestor import SkillIngestor

        ingestor = SkillIngestor()
        result = ingestor.ingest(req.content, filename=req.filename, org_id=req.org_id)
        bank = SkillBank()
        bank.add(result.skill)
        return ok(
            {
                "skill": result.skill.model_dump(),
                "format_detected": result.format_detected,
                "warnings": result.warnings,
            }
        )
    except Exception as e:
        logger.exception("skill ingest failed")
        raise HTTPException(status_code=500, detail=f"Ingest failed: {e}")


@app.post("/api/skills/ingest-file")
async def api_ingest_skill_file(file: UploadFile = File(...), org_id: Optional[str] = Form(None)):
    """Upload a skill file (.md, .json, .yaml, .txt) and ingest it."""
    try:
        from yunaki_skills.skill_ingestor import SkillIngestor

        content = (await file.read()).decode("utf-8")
        ingestor = SkillIngestor()
        result = ingestor.ingest(content, filename=file.filename or "skill.txt", org_id=org_id)
        bank = SkillBank()
        bank.add(result.skill)
        return ok(
            {
                "skill": result.skill.model_dump(),
                "format_detected": result.format_detected,
                "warnings": result.warnings,
            }
        )
    except Exception as e:
        logger.exception("skill file ingest failed")
        raise HTTPException(status_code=500, detail=f"Ingest failed: {e}")


@app.get("/api/marketplace")
async def api_marketplace(q: str = "", top_k: int = 10):
    """Search the public skill marketplace."""
    try:
        bank = SkillBank()
        if q:
            skills = bank.search_marketplace(q, top_k=top_k)
        else:
            # Return all public skills
            all_skills = bank.list_all()
            skills = [s for s in all_skills if s.visibility == "public"][:top_k]
        return ok([s.model_dump() for s in skills])
    except Exception as e:
        logger.exception("marketplace search failed")
        raise HTTPException(status_code=500, detail=f"Marketplace search failed: {e}")


@app.post("/api/skills/{skill_id}/publish")
async def api_publish_skill(skill_id: str):
    """Publish a skill to the public marketplace."""
    try:
        bank = SkillBank()
        success = bank.publish_skill(skill_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
        return ok({"skill_id": skill_id, "visibility": "public"})
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("publish skill failed")
        raise HTTPException(status_code=500, detail=f"Publish failed: {e}")


@app.get("/api/org/{org_id}/skills")
async def api_org_skills(org_id: str):
    """List skills for an organization."""
    try:
        bank = SkillBank(org_id=org_id)
        skills = bank.list_all()
        return ok([s.model_dump() for s in skills])
    except Exception as e:
        logger.exception("org skills list failed")
        raise HTTPException(status_code=500, detail=f"Failed: {e}")


# ─── Live Runs (streaming) ─────────────────────────────────────────────────


@app.post("/api/run/start")
async def api_run_start(req: RunRequest):
    """Kick off a run in the background and return a run_id to stream against.

    The dashboard opens ws://<host>/ws/runs/{run_id} immediately after this
    returns to receive live progress events.
    """
    run_id = uuid4().hex[:12]

    # YUNAKI_ALLOW_SIMULATED is the ONLY way to get simulated/demo runs. It is
    # opt-in, never the default. Every simulated record is loudly labelled
    # (status="SIMULATED", simulated=True) and logged as a WARNING. Without it,
    # an unavailable real runner is a loud failure (run_failed event), not a
    # silent fabricated curve.
    allow_simulated = str(cfg("YUNAKI_ALLOW_SIMULATED", "false")).strip().lower() in {"1", "true", "yes", "on"}
    use_runner = TaskRunner if _real_task_runner else None

    if use_runner is None and not allow_simulated:
        # Fail loud at the boundary instead of starting a run that can only fake.
        logger.error(
            "Refusing /api/run/start: no real TaskRunner and YUNAKI_ALLOW_SIMULATED unset"
        )
        raise HTTPException(
            status_code=503,
            detail=(
                "No real TaskRunner available. Set GEMINI_API_KEY + MONGODB_URI "
                "for live runs, or YUNAKI_ALLOW_SIMULATED=1 for an explicitly "
                "labelled SIMULATED demo. No silent fabricated fallback."
            ),
        )

    async def _runner():
        try:
            await execute_run(
                run_id,
                req.task_description,
                req.max_iterations,
                broker=broker,
                list_skills=_list_skills,
                add_run=_add_run,
                task_runner_cls=use_runner,
                org_id=req.org_id,
                allow_simulated=allow_simulated,
            )
        except Exception as e:  # already published as run_failed; log loudly
            logger.exception("background run %s errored", run_id)

    asyncio.create_task(_runner())
    status = _SIMULATED_STATUS if use_runner is None else "started"
    return {"run_id": run_id, "status": status, "simulated": use_runner is None}


@app.websocket("/ws/runs/{run_id}")
async def ws_run(websocket: WebSocket, run_id: str):
    """Stream live run events. Replays history first so reconnecting or
    late-joining clients catch up, then forwards live events until the run
    finishes."""
    await websocket.accept()
    # Subscribe BEFORE snapshotting history (both sync, no await between) so
    # no event can slip through the gap: events before this instant are in the
    # history snapshot, events after are delivered to the queue.
    queue = broker.subscribe(run_id)
    finished_before_subscribe = broker.is_finished(run_id)
    try:
        # Replay any events that already happened (reconnect / late join).
        for event in broker.history(run_id):
            await websocket.send_json(event)
        if finished_before_subscribe:
            # Run was already done when we subscribed — history is complete and
            # the queue will never receive the sentinel. Close cleanly.
            await websocket.send_json(STREAM_DONE)
            return
        # Forward live events (including any that arrived during replay) until
        # the stream-done sentinel.
        while True:
            event = await queue.get()
            await websocket.send_json(event)
            if event.get("type") == STREAM_DONE["type"]:
                break
    except WebSocketDisconnect:
        pass
    finally:
        broker.unsubscribe(run_id, queue)
        broker.cleanup(run_id)


# ─── Health ─────────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    """Liveness/readiness probe (used by the Docker healthcheck).

    Always returns 200 so the container is considered up; dependency status is
    reported in the body for observability without flapping the healthcheck.
    """
    return {
        "status": "ok",
        "mongo": _mongo_ok,
        "auth_enabled": AUTH_ENABLED,
    }


# ─── Root ───────────────────────────────────────────────────────────────────


@app.get("/")
async def root():
    """API info at root. Yunaki is headless: drive it from the `yunaki` CLI or
    this JSON API. There is no bundled dashboard."""
    return {
        "name": "Yunaki Skills API",
        "status": "ok",
        "docs": "/docs",
        "health": "/health",
    }


def run():
    """Console entry point (`yunaki-server`) — launches the uvicorn server.

    Host/port/reload are read from the environment so the same entry point
    works for local dev and the Docker image.
    """
    import uvicorn

    host = cfg("HOST", "0.0.0.0")  # noqa: S104 — container binds all interfaces
    port = int(cfg("PORT", "8000"))
    reload = cfg("RELOAD", "").strip().lower() in {"1", "true", "yes", "on"}
    uvicorn.run("yunaki_skills.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    run()
