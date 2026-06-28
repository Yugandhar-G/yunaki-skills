# Yunaki Skills — API Reference

REST + WebSocket API for the self-evolving skill system. The server is a FastAPI
app (`yunaki_skills.main:app`). Yunaki is headless — there is no bundled
dashboard; this API (and the `yunaki` CLI) is the interface.

```bash
uvicorn yunaki_skills.main:app --port 8000 --reload
```

- **Base URL (local):** `http://localhost:8000`
- **WebSocket base:** `ws://localhost:8000`
- **Content type:** `application/json` for all request/response bodies.

---

## Conventions

### Response envelope

Newer endpoints (auth, repos) return a consistent envelope:

```json
{ "success": true, "data": { }, "error": null, "pagination": null }
```

```json
{ "success": false, "data": null, "error": "message", "pagination": null }
```

Legacy dashboard endpoints (`/api/skills`, `/api/runs`, `/api/stats`, `/api/run`)
return their raw shape (arrays/objects) for backward compatibility — these are
called out per-endpoint below.

### Errors

Failures use standard HTTP status codes with a FastAPI error body:

```json
{ "detail": "Skill 'skill_x' not found" }
```

| Status | Meaning |
|--------|---------|
| `400` | Invalid request body (schema validation failed) |
| `401` | Missing or invalid `X-API-Key` |
| `404` | Resource not found |
| `409` | Conflict (e.g. duplicate email on register) |
| `500` | Server-side error |

---

## Authentication

Auth is **API-key based** via the `X-API-Key` header.

- Global enforcement is gated by the `AUTH_ENABLED` env var (`false` by default
  for local dev). When enabled, the `APIKeyMiddleware` rejects unauthenticated
  requests.
- **Repo endpoints always require a valid key**, regardless of `AUTH_ENABLED`,
  because each repo needs an owner.
- The raw API key is returned **exactly once** at registration. Only its
  SHA-256 hash is stored — store the key somewhere safe.

```
X-API-Key: <your-api-key>
```

### `POST /api/auth/register`

Create a user and receive a one-time API key.

**Request body**

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `email` | string | yes | — | Light validation; lowercased. Must be unique. |
| `plan` | enum | no | `free` | `free` or `pro`. |

**Response** — envelope wrapping the created `User`. `api_key` is present only here.

```json
{
  "success": true,
  "data": {
    "id": "usr_a1b2c3",
    "email": "dev@example.com",
    "api_key": "yk_live_9f8e7d6c5b4a...",
    "created_at": "2026-06-27T12:00:00+00:00",
    "plan": "free"
  },
  "error": null,
  "pagination": null
}
```

**Errors:** `409` duplicate email, `400` invalid email.

```bash
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "dev@example.com", "plan": "free"}'
```

### `POST /api/auth/verify`

Validate the `X-API-Key` header and report the owning user.

**Request:** no body — the key is read from the header.

**Response** — envelope wrapping a `VerifyResponse`.

```json
{
  "success": true,
  "data": { "valid": true, "user_id": "usr_a1b2c3", "plan": "free" },
  "error": null,
  "pagination": null
}
```

When the key is missing or invalid, `valid` is `false` and the other fields are
`null` (the request itself still returns `200`).

```bash
curl -X POST http://localhost:8000/api/auth/verify \
  -H "X-API-Key: yk_live_9f8e7d6c5b4a..."
```

---

## Skills

The skill bank. Skills follow the canonical `Skill` schema (see
`interfaces.py`): `id`, `title`, `granularity`, `version`, `score`, `trigger`,
`when_to_apply`, `instructions[]`, `provenance`, `status`, `repo_id`.

### `GET /api/skills`

List every skill in the bank. Returns a **raw array** of `Skill` objects (each
normalized to include a `status`, defaulting to `active`).

```json
[
  {
    "id": "skill_dep_injection",
    "title": "Use FastAPI dependency injection for shared state",
    "granularity": "task-level",
    "version": "0.3",
    "score": 78.5,
    "trigger": {
      "type": "semantic",
      "patterns": [],
      "query": "fastapi shared state dependency",
      "match_on": "task_description"
    },
    "when_to_apply": "When an endpoint needs request-scoped shared resources",
    "instructions": [
      "Define a dependency callable returning the resource",
      "Inject it with Depends() in the path operation"
    ],
    "provenance": { "created_from": "trace_42", "iteration": 2 },
    "status": "active",
    "repo_id": null
  }
]
```

```bash
curl http://localhost:8000/api/skills
```

### `GET /api/skills/{skill_id}`

Fetch a single skill by ID. Returns a raw `Skill` object.

**Errors:** `404` if the skill does not exist.

```bash
curl http://localhost:8000/api/skills/skill_dep_injection
```

### `GET /api/skills/{skill_id}/history`

Return the version/evolution history of a skill as a **raw array** of `Skill`
snapshots, sorted by `version` ascending. Empty array if no history.

```bash
curl http://localhost:8000/api/skills/skill_dep_injection/history
```

---

## Skill Governance

Skills move through a lifecycle: `draft → pending_review → approved → active`,
with `rejected` terminal. Only `approved` and `active` skills are retrieved for
injection.

### `POST /api/skills/{skill_id}/approve`

Promote a skill to `active`.

```json
{ "id": "skill_dep_injection", "status": "active" }
```

**Errors:** `404` if not found.

```bash
curl -X POST http://localhost:8000/api/skills/skill_dep_injection/approve
```

### `POST /api/skills/{skill_id}/reject`

Mark a skill `rejected` so it stops being injected.

```json
{ "id": "skill_dep_injection", "status": "rejected" }
```

**Errors:** `404` if not found.

```bash
curl -X POST http://localhost:8000/api/skills/skill_dep_injection/reject
```

---

## Runs

A "run" executes a task through the evolution loop: baseline run → skill
extraction/injection → re-run, measuring score before vs after.

### `POST /api/run`

Trigger a synchronous run and return the full result. Blocks until the loop
completes. Returns a **raw** `TaskResult`-shaped object plus `timestamp` and
`status`.

**Request body**

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `task_description` | string | yes | — | The coding task to attempt. |
| `max_iterations` | int | no | `3` | Loop iterations. |
| `repo_id` | string \| null | no | `null` | Namespace to evolve against. `null` = global bank. |

**Response**

```json
{
  "task_description": "Implement the DELETE /users/{id} endpoint",
  "score_before": 22.0,
  "score_after": 71.5,
  "skills_used": ["skill_dep_injection", "skill_pytest_fixtures"],
  "skills_created": ["skill_delete_endpoint"],
  "skills_evolved": ["skill_dep_injection"],
  "iterations": 3,
  "trace": "Iteration 1/3: score=22 ...",
  "timestamp": "2026-06-27T12:05:00",
  "status": "completed"
}
```

> If the real `TaskRunner` (Gemini + pytest) is unavailable, the endpoint falls
> back to a simulated run so the dashboard still works without API cost.

```bash
curl -X POST http://localhost:8000/api/run \
  -H "Content-Type: application/json" \
  -d '{"task_description": "Implement the DELETE /users/{id} endpoint", "max_iterations": 3}'
```

### `POST /api/run/start`

Kick off a run **in the background** and immediately return a `run_id`. Open the
WebSocket stream (below) to follow progress live.

**Request body:** same shape as `/api/run` (`task_description`,
`max_iterations`, `repo_id`).

**Response**

```json
{ "run_id": "a1b2c3d4e5f6", "status": "started" }
```

> Set `YUNAKI_FORCE_STUB_RUN=true` to force the simulated loop (live demo without
> API cost).

```bash
curl -X POST http://localhost:8000/api/run/start \
  -H "Content-Type: application/json" \
  -d '{"task_description": "Add pagination to GET /users", "max_iterations": 3}'
```

### `GET /api/runs`

List all past runs as a **raw array**, most recent first.

```bash
curl http://localhost:8000/api/runs
```

### `GET /api/stats`

Aggregate dashboard stats. Returns a raw object.

```json
{
  "total_skills": 12,
  "avg_score": 64.3,
  "total_runs": 48,
  "avg_improvement": 43.0
}
```

```bash
curl http://localhost:8000/api/stats
```

---

## Repositories

Each repo is an **isolated skill-bank namespace**. All repo endpoints require a
valid `X-API-Key` (even when `AUTH_ENABLED=false`).

The access `token` is **write-only**: accepted on create, never echoed back.
Responses expose `has_token` instead.

### `POST /api/repos`

Register a repository.

**Headers:** `X-API-Key: <key>` (required)

**Request body**

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `url` | string | yes | — | Must start with `http(s)://` or `git@`. |
| `branch` | string | no | `main` | |
| `token` | string \| null | no | `null` | Access token; stored, never returned. |
| `name` | string \| null | no | `null` | Display name. |

**Response** — envelope wrapping a `Repo`.

```json
{
  "success": true,
  "data": {
    "id": "repo_7h8i9j",
    "user_id": "usr_a1b2c3",
    "name": "user-service",
    "url": "https://github.com/acme/user-service",
    "branch": "main",
    "has_token": true,
    "created_at": "2026-06-27T12:10:00+00:00"
  },
  "error": null,
  "pagination": null
}
```

```bash
curl -X POST http://localhost:8000/api/repos \
  -H "Content-Type: application/json" \
  -H "X-API-Key: yk_live_9f8e7d6c5b4a..." \
  -d '{"url": "https://github.com/acme/user-service", "branch": "main", "name": "user-service"}'
```

### `GET /api/repos`

List repositories owned by the calling user. Envelope wrapping an array of
`Repo`.

```bash
curl http://localhost:8000/api/repos \
  -H "X-API-Key: yk_live_9f8e7d6c5b4a..."
```

### `DELETE /api/repos/{repo_id}`

Remove a repository owned by the calling user.

**Response**

```json
{ "success": true, "data": { "id": "repo_7h8i9j", "deleted": true }, "error": null, "pagination": null }
```

**Errors:** `404` if the repo does not exist or isn't owned by the caller.

```bash
curl -X DELETE http://localhost:8000/api/repos/repo_7h8i9j \
  -H "X-API-Key: yk_live_9f8e7d6c5b4a..."
```

---

## WebSocket — Live Runs

### `WS /ws/runs/{run_id}`

Stream live progress for a run started via `POST /api/run/start`. The stream:

1. **Replays history** — any events already emitted are sent first, so
   reconnecting or late-joining clients catch up.
2. **Forwards live events** until a stream-done sentinel arrives.

If the run already finished before you subscribed, the full history is replayed
followed immediately by the done sentinel.

**Event shape** (JSON per message). The terminal event carries the done
`type`; intermediate events carry progress such as iteration scores, skills
used/created/evolved.

```json
{ "type": "iteration", "run_id": "a1b2c3d4e5f6", "iteration": 1, "score": 22.0 }
{ "type": "skill_created", "run_id": "a1b2c3d4e5f6", "skill_id": "skill_delete_endpoint" }
{ "type": "stream_done", "run_id": "a1b2c3d4e5f6" }
```

**Browser client**

```javascript
const ws = new WebSocket(`ws://localhost:8000/ws/runs/${runId}`);
ws.onmessage = (msg) => {
  const event = JSON.parse(msg.data);
  console.log(event.type, event);
  if (event.type === "stream_done") ws.close();
};
```

**CLI client** (`websocat`)

```bash
websocat ws://localhost:8000/ws/runs/a1b2c3d4e5f6
```

**Typical flow**

```bash
# 1. Start a background run
RUN_ID=$(curl -s -X POST http://localhost:8000/api/run/start \
  -H "Content-Type: application/json" \
  -d '{"task_description":"Add pagination to GET /users"}' | jq -r .run_id)

# 2. Stream it
websocat "ws://localhost:8000/ws/runs/$RUN_ID"
```

---

## Health

### `GET /health`

Liveness/readiness probe (used by the Docker healthcheck). Always returns `200`;
dependency status is in the body for observability.

```json
{ "status": "ok", "mongo": true, "auth_enabled": false }
```

```bash
curl http://localhost:8000/health
```

---

## Endpoint summary

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/auth/register` | no | Create user, return one-time API key |
| `POST` | `/api/auth/verify` | header | Validate API key |
| `GET` | `/api/skills` | gated | List all skills |
| `GET` | `/api/skills/{id}` | gated | Get one skill |
| `GET` | `/api/skills/{id}/history` | gated | Skill version history |
| `POST` | `/api/skills/{id}/approve` | gated | Promote skill to active |
| `POST` | `/api/skills/{id}/reject` | gated | Reject skill |
| `POST` | `/api/run` | gated | Synchronous evolution run |
| `POST` | `/api/run/start` | gated | Background run, returns `run_id` |
| `GET` | `/api/runs` | gated | List past runs |
| `GET` | `/api/stats` | gated | Aggregate dashboard stats |
| `POST` | `/api/repos` | **yes** | Register a repo namespace |
| `GET` | `/api/repos` | **yes** | List owned repos |
| `DELETE` | `/api/repos/{id}` | **yes** | Delete a repo |
| `WS` | `/ws/runs/{run_id}` | — | Live run event stream |
| `GET` | `/health` | no | Health probe |

> **Auth column:** `no` = open; `header` = reads `X-API-Key` but doesn't reject;
> `gated` = enforced only when `AUTH_ENABLED=true`; `yes` = always enforced.
