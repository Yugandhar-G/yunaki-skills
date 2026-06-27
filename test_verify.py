"""Verify all 3 modules import correctly."""
import sys
sys.path.insert(0, "/Users/yugandhargopu/yunaki-skills/src")

print("1. Testing antigravity_client...")
from yunaki_skills.antigravity_client import AntigravityClient, FallbackClient
print("   AntigravityClient: OK")
print("   FallbackClient: OK")

# Verify they implement the interface
from yunaki_skills.interfaces import AgentClient
assert issubclass(AntigravityClient, AgentClient), "AntigravityClient must implement AgentClient"
assert issubclass(FallbackClient, AgentClient), "FallbackClient must implement AgentClient"
print("   Interface compliance: OK")

print("\n2. Testing eval_scorer...")
from yunaki_skills.eval_scorer import EvalScorer
print("   EvalScorer: OK")
from yunaki_skills.interfaces import EvalScorer as IEvalScorer
assert issubclass(EvalScorer, IEvalScorer), "EvalScorer must implement interface"
print("   Interface compliance: OK")

# Test EvalScorer against target repo
repo_path = "/Users/yugandhargopu/yunaki-skills/target_repo"
scorer = EvalScorer()
result = scorer.evaluate("Add missing endpoints", repo_path)
print(f"   Live test: score={result.score:.1f}, passed={result.tasks_passed}/{result.tasks_total}")

print("\n3. Testing task_runner...")
# Can't fully test TaskRunner (needs MongoDB + Gemini), but verify import and class structure
from yunaki_skills.task_runner import TaskRunner as TR
from yunaki_skills.interfaces import TaskRunner as ITR
assert issubclass(TR, ITR), "TaskRunner must implement interface"
print("   TaskRunner: OK")
print("   Interface compliance: OK")

# Check method signature
import inspect
sig = inspect.signature(TR.run)
print(f"   .run signature: {sig}")

print("\n✅ All 3 modules verified!")
