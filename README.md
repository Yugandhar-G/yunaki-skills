# Yunaki Skills

Self-evolving skills for coding agents. An agent writes code, fails, extracts patterns into JSON skills, evolves them, and measurably improves.



## Architecture

```
Task → Agent (Antigravity/Gemini) → Eval Scorer →
  if failed → Skill Extractor → Skill Bank →
  Skill Retriever → inject skills into next Agent call →
  run again → measurable improvement
```

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env  # fill in your keys
python -m yunaki_skills.main
```

## Quick Start

```python
from yunaki_skills.task_runner import TaskRunner

runner = TaskRunner()
result = runner.run("Add a /health endpoint to the FastAPI app")
print(f"Score: {result.score_before} → {result.score_after}")
```
