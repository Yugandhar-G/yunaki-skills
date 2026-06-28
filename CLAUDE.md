# Yunaki Skills — Project Context

## What This Is
Self-evolving skills for coding agents: run a task, score it with tests, extract
reusable skills from the trace, inject them into future runs, and measure the
improvement honestly via a no-skills control arm.

## Architecture
```
Task → Coding agent (detected host CLI; Gemini SDK fallback) → Eval Scorer (pytest [+ judge]) →
  if failed → Skill Extractor (single-trace or contrastive) → Skill Bank →
  Skill Retriever (semantic, optionally score-weighted) → inject into next agent run →
  run again → measure skill_delta (vs control arm)
       ↘ periodic consolidation: merge duplicates, drop dead weight
```

## Key Files
- `interfaces.py` — Pydantic models + interface signatures (THE CONTRACT)
- `config.py` — env var loader
- `agent_specs.py` — declarative registry of coding-agent CLI backends (data, not code)
- `cli_agent.py` — generic adapter that drives a backend CLI + parses its output
- `agent_factory.py` — `build_agent()`: backend override → auto-detect → Gemini SDK fallback
- `antigravity_client.py` — Gemini SDK agent (the fallback backend)
- `skill_llm.py` — single LLM seam for meta-ops (extract/evolve/judge/ingest); host CLI by default
- `skill_extractor.py` — extract a skill from a trace (`extract` + `extract_contrastive`)
- `skill_evolver.py` — refine an existing skill from new evidence
- `skill_retriever.py` — semantic + pattern retrieval + injection
- `skill_bank.py` — MongoDB-backed storage; ranking, merge/drop, history
- `skill_consolidator.py` — merge near-duplicates, drop ineffective skills
- `reward.py` — composite pytest×judge reward (advisory, opt-in)
- `contrastive_runner.py` — N-rollout contrastive extraction
- `governance.py` — skill status lifecycle / auto-approve policy
- `eval_scorer.py` — pytest-based evaluation
- `llm_judge.py` — LLM-as-judge code-quality scoring
- `task_runner.py` — orchestrates the full evolution loop (control arm + iterations)
- `main.py` — FastAPI backend + dashboard API

## Credentials
In `.env`. `GEMINI_API_KEY` is now **optional** — only needed when no coding-agent
CLI is detected or when `YUNAKI_SKILL_MODEL` pins a Gemini model. Backend selection:
`YUNAKI_AGENT_BACKEND`. Other vars: `MONGODB_URI`, `DO_MODEL_ACCESS_KEY`, `AUTH_ENABLED`.
NEVER commit `.env`.

## MongoDB
Database: `yunaki`. Collections: `skills`, `skills_history`, `skill_embeddings`,
`runs`, `evaluations`, plus auth (`users`, `repos`) when `AUTH_ENABLED`.

## Target Repo
`target_repo/` — a small FastAPI service with passing and failing tests, used as a
demo/eval fixture; the agent implements the failing endpoints.

## Commands
```bash
pip install -e .                                   # installs the `yunaki` / `yunaki-server` CLIs
yunaki doctor                                      # show the detected coding-agent backend
cd target_repo && python -m pytest test_app.py -v  # run the fixture's tests
yunaki-server                                      # start the dashboard + API on :8000
pytest                                             # run the suite (YUNAKI_IT=1 to include real-CLI tests)
```

## Conventions
- Follow `interfaces.py` method signatures exactly
- All classes must work with no-arg constructors (load config internally)
- Use `yunaki_skills.config.get()` for env vars
- Route all skill-model LLM calls through `skill_llm.complete_json` (never import `genai` directly)
- Skills are JSON objects matching the `Skill` Pydantic model
- Never report `score_after − score_before` as the result — `skill_delta` (vs control) is the honest metric
