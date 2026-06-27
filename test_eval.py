"""Test EvalScorer against the target repo."""
import sys
import os
sys.path.insert(0, "/Users/yugandhargopu/yunaki-skills/src")

from yunaki_skills.eval_scorer import EvalScorer

repo_path = "/Users/yugandhargopu/yunaki-skills/target_repo"
scorer = EvalScorer()

print(f"Evaluating repo at: {repo_path}")
result = scorer.evaluate("Add missing endpoints", repo_path)
print(f"\nResult:")
print(f"  passed: {result.passed}")
print(f"  score: {result.score}")
print(f"  details: {result.details}")
print(f"  tasks_passed: {result.tasks_passed}")
print(f"  tasks_total: {result.tasks_total}")
print(f"  test_output (last 500 chars):")
print(result.test_output[-500:] if result.test_output else "(empty)")
