# Yunaki Skills — Project Context

## What This Is
Self-evolving skills for coding agents. Hackathon project for AI Engineer World's Fair 2026.

## Architecture
```
Task → Agent (Gemini) → Eval Scorer →
  if failed → Skill Extractor → Skill Bank →
  Skill Retriever → inject skills into next Agent call →
  run again → measurable improvement
```

## Key Files
- `src/yunaki_skills/interfaces.py` — Pydantic models + interface signatures (THE CONTRACT)
- `src/yunaki_skills/config.py` — env var loader
- `src/yunaki_skills/skill_bank.py` — MongoDB-backed skill storage
- `src/yunaki_skills/skill_extractor.py` — Gemini-powered skill extraction from traces
- `src/yunaki_skills/skill_evolver.py` — Gemini-powered skill evolution
- `src/yunaki_skills/skill_retriever.py` — semantic + pattern skill retrieval + injection
- `src/yunaki_skills/antigravity_client.py` — Gemini agent that executes coding tasks
- `src/yunaki_skills/eval_scorer.py` — pytest-based evaluation
- `src/yunaki_skills/task_runner.py` — orchestrates the full evolution loop
- `src/yunaki_skills/main.py` — FastAPI backend + dashboard API

## Credentials
All in .env — GEMINI_API_KEY, MONGODB_URI, DO_MODEL_ACCESS_KEY, etc.
NEVER commit .env

## MongoDB
Database: yunaki
Collections: skills, skills_history, skill_embeddings, runs

## Target Repo
`target_repo/` — simple FastAPI User Service with tests.
Some tests pass, some fail — the agent must implement failing endpoints.

## Commands
```bash
# Install
pip install -r requirements.txt

# Run tests on target repo
cd target_repo && python -m pytest test_app.py -v

# Start dashboard
uvicorn yunaki_skills.main:app --port 8000 --reload
```

## Conventions
- Follow interfaces.py method signatures exactly
- All classes must work with no-arg constructors (load config internally)
- Use yunaki_skills.config.get() for env vars
- Skills are JSON objects matching the Skill Pydantic model
