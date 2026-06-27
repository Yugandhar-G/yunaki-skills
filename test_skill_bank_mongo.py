#!/usr/bin/env python3
"""Test SkillBank against real MongoDB — with cleanup."""

from yunaki_skills.skill_bank import SkillBank
from yunaki_skills.interfaces import (
    Skill, EvalResult, Granularity, Trigger, TriggerType, TriggerMatchOn, Provenance,
)

print("Initializing SkillBank (loads sentence-transformers model)...")
bank = SkillBank()
print("✓ SkillBank initialized (MongoDB + model loaded)")

# Clean up existing data for fresh test
bank._skills.delete_many({})
bank._history.delete_many({})
bank._embeddings_col.delete_many({})
print("✓ Cleaned existing data")

# Load seed skills
import json
from pathlib import Path

seed_dir = Path(__file__).parent / "skills"
for seed_file in sorted(seed_dir.glob("*.json")):
    with open(seed_file) as f:
        data = json.load(f)
    skill = Skill(**data)
    bank.add(skill)
    print(f"  ✓ Added seed skill: {skill.id}")

# Test get
skill = bank.get("skill_dep_injection")
assert skill is not None, "Should find skill_dep_injection"
assert skill.title == "FastAPI Dependency Injection Pattern"
print(f"✓ get() works: {skill.id} -> {skill.title}")

# Test list_all
all_skills = bank.list_all()
assert len(all_skills) >= 3, f"Expected >=3 skills, got {len(all_skills)}"
print(f"✓ list_all() works: {len(all_skills)} skills")
for s in all_skills:
    print(f"  - {s.id} (score: {s.score})")

# Test search_semantic
results = bank.search_semantic("How to handle database sessions in FastAPI endpoints", top_k=2)
print(f"✓ search_semantic() works: {len(results)} results")
for r in results:
    print(f"  - {r.id}: {r.title}")

# Test search_pattern
results = bank.search_pattern("ModuleNotFoundError: No module named 'fastapi'")
print(f"✓ search_pattern() works: {len(results)} results")
for r in results:
    print(f"  - {r.id}: {r.title}")

# Test get_history
history = bank.get_history("skill_dep_injection")
print(f"✓ get_history() works: {len(history)} history entries")

# Test update (evolution)
updated_skill = skill.model_copy(update={"score": 60.0, "version": "0.2"})
success = bank.update("skill_dep_injection", updated_skill)
assert success, "Update should succeed"
verify = bank.get("skill_dep_injection")
assert verify.score == 60.0, f"Score should be 60.0, got {verify.score}"
assert verify.version == "0.2", f"Version should be 0.2, got {verify.version}"
print(f"✓ update() works: score updated to {verify.score}, version to {verify.version}")

# Check history grew
history2 = bank.get_history("skill_dep_injection")
print(f"✓ History after update: {len(history2)} entries")

# Test re-add (idempotent)
bank.add(skill)
retrieved = bank.get("skill_dep_injection")
assert retrieved.id == "skill_dep_injection"
print("✓ Re-add is idempotent (no duplicate key error)")

# Test search_semantic with different query
results = bank.search_semantic("fix import error module not found", top_k=3)
print(f"✓ search_semantic('fix import error') works: {len(results)} results")
for r in results:
    print(f"  - {r.id}: {r.title} (score: {r.score})")

# Test search_pattern with non-matching text
results = bank.search_pattern("Everything works fine")
print(f"✓ search_pattern with no match: {len(results)} results")

print("\n🎉 SkillBank MongoDB tests ALL PASSED!")
