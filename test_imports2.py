"""Quick import check - just our 3 modules."""
import sys
sys.path.insert(0, "/Users/yugandhargopu/yunaki-skills/src")

print("Testing antigravity_client...")
from yunaki_skills.antigravity_client import AntigravityClient, FallbackClient
print("  AntigravityClient: OK")
print("  FallbackClient: OK")

print("\nTesting eval_scorer...")
from yunaki_skills.eval_scorer import EvalScorer
print("  EvalScorer: OK")

print("\nDone - our 3 modules import fine.")
