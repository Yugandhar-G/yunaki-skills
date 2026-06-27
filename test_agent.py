"""Test AntigravityClient with Gemini API."""
import sys
import os
sys.path.insert(0, "/Users/yugandhargopu/yunaki-skills/src")

# Load env
from dotenv import load_dotenv
load_dotenv("/Users/yugandhargopu/yunaki-skills/.env")

from yunaki_skills.antigravity_client import AntigravityClient, FallbackClient

repo_path = "/Users/yugandhargopu/yunaki-skills/target_repo"

# Test FallbackClient (simpler, direct API)
print("Testing FallbackClient...")
try:
    client = FallbackClient()
    print("  Client created OK")
    
    trace = client.run_task(
        task_description="Add a GET /users/{user_id} endpoint that returns a single user by ID, or 404 if not found",
        skills=[],
        repo_path=repo_path,
    )
    print(f"  Trace length: {len(trace)} chars")
    print(f"  Trace preview (last 500 chars):\n{trace[-500:]}")
    
    # Check what app.py looks like now
    with open(os.path.join(repo_path, "app.py")) as f:
        content = f.read()
    print(f"\n  app.py now has {len(content)} chars, {content.count('def ')} function(s)")
    print(f"  Has /users/{{user_id}}: {'{user_id}' in content}")
    
except Exception as e:
    print(f"  ERROR: {e}")
    import traceback
    traceback.print_exc()
