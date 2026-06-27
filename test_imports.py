"""Quick import check for all yunaki_skills modules."""
import sys
sys.path.insert(0, "/Users/yugandhargopu/yunaki-skills/src")

# Test our 3 modules
print("Testing antigravity_client...")
from yunaki_skills.antigravity_client import AntigravityClient, FallbackClient
print("  AntigravityClient: OK")
print("  FallbackClient: OK")

print("\nTesting eval_scorer...")
from yunaki_skills.eval_scorer import EvalScorer
print("  EvalScorer: OK")

# Check if skill_bank etc. are empty or have implementations
print("\nChecking dependencies for task_runner...")
try:
    from yunaki_skills.skill_bank import SkillBank
    print(f"  SkillBank: {SkillBank}")
    # Check if it has method stubs
    has_add = hasattr(SkillBank, 'add')
    print(f"    has .add: {has_add}")
except ImportError as e:
    print(f"  SkillBank: IMPORT ERROR - {e}")

try:
    from yunaki_skills.skill_extractor import SkillExtractor
    print(f"  SkillExtractor: {SkillExtractor}")
    has_extract = hasattr(SkillExtractor, 'extract')
    print(f"    has .extract: {has_extract}")
except ImportError as e:
    print(f"  SkillExtractor: IMPORT ERROR - {e}")

try:
    from yunaki_skills.skill_evolver import SkillEvolver
    print(f"  SkillEvolver: {SkillEvolver}")
    has_evolve = hasattr(SkillEvolver, 'evolve')
    print(f"    has .evolve: {has_evolve}")
except ImportError as e:
    print(f"  SkillEvolver: IMPORT ERROR - {e}")

try:
    from yunaki_skills.skill_retriever import SkillRetriever
    print(f"  SkillRetriever: {SkillRetriever}")
    has_retrieve = hasattr(SkillRetriever, 'retrieve_for_task')
    print(f"    has .retrieve_for_task: {has_retrieve}")
except ImportError as e:
    print(f"  SkillRetriever: IMPORT ERROR - {e}")

print("\nTesting task_runner import...")
try:
    from yunaki_skills.task_runner import TaskRunner
    print("  TaskRunner: OK")
except ImportError as e:
    print(f"  TaskRunner: IMPORT ERROR - {e}")

print("\nAll checks complete!")
