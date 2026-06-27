# Yunaki Skills — Product Roadmap

## Hackathon Demo (NOW)
✅ Skill evolution loop: 57% → 100%
✅ MongoDB skill bank with semantic search
✅ Gemini-powered agent + skill extraction
✅ Basic dashboard

## Product Build (THIS SESSION)
### P0 — Core Product
- [ ] Dockerized deployment (docker-compose: app + mongo + redis)
- [ ] Proper API with auth (API key per user)
- [ ] WebSocket for live evolution progress
- [ ] Multi-repo support (not just target_repo)
- [ ] Skill versioning + rollback
- [ ] Skill governance (approve/reject/merge skills)
- [ ] LLM-as-Judge eval (DO Inference) as alternative to pytest
- [ ] Real Antigravity integration (sandboxed code execution)
- [ ] SDK: `pip install yunaki-skills` — use in any Python project

### P1 — Dashboard
- [ ] Real-time evolution progress (WebSocket)
- [ ] Skill graph visualization (D3.js)
- [ ] Improvement curve charts (Chart.js)
- [ ] Skill diff viewer (before/after evolution)
- [ ] Run history with drill-down

### P2 — Platform
- [ ] Skill marketplace (share skills across users)
- [ ] Skill rating system (upvote/downvote)
- [ ] Multi-model support (not just Gemini — DO Inference Router)
- [ ] Webhook integrations (GitHub, GitLab)
- [ ] Governance UI (approve/reject skill changes)
