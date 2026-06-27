#!/usr/bin/env python3
"""Test imports and basic functionality of the Core Skill Engine."""

from yunaki_skills.interfaces import (
    Skill, SkillBank, SkillExtractor, SkillEvolver, SkillRetriever,
    EvalResult, Granularity, Trigger, TriggerType, TriggerMatchOn, Provenance,
)
print("✓ Interfaces import OK")

from yunaki_skills.skill_bank import SkillBank as SkillBankImpl
print("✓ SkillBank import OK")

from yunaki_skills.skill_extractor import SkillExtractor as SkillExtractorImpl
print("✓ SkillExtractor import OK")

from yunaki_skills.skill_evolver import SkillEvolver as SkillEvolverImpl
print("✓ SkillEvolver import OK")

from yunaki_skills.skill_retriever import SkillRetriever as SkillRetrieverImpl
print("✓ SkillRetriever import OK")

# Test interface conformance
assert issubclass(SkillBankImpl, SkillBank), "SkillBankImpl must subclass SkillBank"
assert issubclass(SkillExtractorImpl, SkillExtractor), "SkillExtractorImpl must subclass SkillExtractor"
assert issubclass(SkillEvolverImpl, SkillEvolver), "SkillEvolverImpl must subclass SkillEvolver"
assert issubclass(SkillRetrieverImpl, SkillRetriever), "SkillRetrieverImpl must subclass SkillRetriever"
print("✓ All classes implement correct interfaces")

# Test SkillRetriever.inject_skills (pure function, no MongoDB needed)
retriever = SkillRetrieverImpl.__new__(SkillRetrieverImpl)
retriever._bank = None  # We won't test DB methods here

test_skill = Skill(
    id="skill_test",
    title="Test Skill",
    granularity=Granularity.TASK_LEVEL,
    version="0.1",
    score=75.0,
    trigger=Trigger(
        type=TriggerType.SEMANTIC,
        patterns=[],
        query="test query",
        match_on=TriggerMatchOn.TASK_DESCRIPTION,
    ),
    when_to_apply="When testing the system",
    instructions=["Step 1: Do something", "Step 2: Do something else"],
    provenance=Provenance(),
)

result = retriever.inject_skills("You are a helpful assistant.", [test_skill])
assert "You are a helpful assistant." in result
assert "Test Skill" in result
assert "Step 1: Do something" in result
print("✓ SkillRetriever.inject_skills works correctly")

# Test inject with no skills
result_empty = retriever.inject_skills("You are a helpful assistant.", [])
assert result_empty == "You are a helpful assistant."
print("✓ SkillRetriever.inject_skills with empty list works")

print("\n🎉 All basic tests passed! Core Skill Engine modules are importable and functional.")
