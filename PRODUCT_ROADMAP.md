# Yunaki Skills — Roadmap

Status legend: ✅ shipped · 🟡 partial · ⬜ planned

## Shipped
- ✅ Evolution loop with an honest **control arm** + `skill_delta` (no fabricated scores)
- ✅ MongoDB skill bank with semantic search (hash-embedding fallback when offline)
- ✅ IDE-agnostic execution — drives the host coding CLI (claude/codex/cursor/gemini/aider),
  no Gemini key required (Gemini SDK is the fallback)
- ✅ Skill model meta-ops routed through one seam (`skill_llm`), backend-agnostic
- ✅ Contrastive extraction (learn from a passing-vs-failing pair)
- ✅ Composite reward (pytest × LLM-judge align/quality; advisory, never flips the gate)
- ✅ Score-weighted retrieval (opt-in) + skill consolidation (merge near-dupes, drop dead weight)
- ✅ Skill governance (status lifecycle, approve/reject, auto-approve toggle)
- ✅ Skill versioning + history (archive-on-update)
- ✅ REST + WebSocket API with per-user API-key auth; multi-repo namespacing
- ✅ Dockerized stack (docker-compose: app + mongo + redis)

## In progress
- 🟡 Dashboard — basic UI + live run streaming exist; richer charts/diff viewer are rough
- 🟡 Skill marketplace — `publish` + `search_marketplace` exist; no rating/sharing UX
- 🟡 Multi-repo — namespacing works; per-repo management UX is thin
- 🟡 Distributable SDK — installable from source (`pip install -e .`); not yet published to PyPI

## Planned
- ⬜ Other backends (codex/cursor/gemini/aider) verified end-to-end (only `claude` is today)
- ⬜ Skill rollback UI
- ⬜ Skill graph + before/after diff visualization
- ⬜ Skill rating (upvote/downvote) and cross-user sharing
- ⬜ Webhook integrations (GitHub/GitLab)
- ⬜ Scheduled background consolidation
