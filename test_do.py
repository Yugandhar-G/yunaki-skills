"""Quick DigitalOcean inference smoke check.

Reads the access key from the environment (DO_MODEL_ACCESS_KEY) — never hardcode
secrets. Run: `DO_MODEL_ACCESS_KEY=... python test_do.py`.
"""
import os
import sys

import requests

key = os.environ.get("DO_MODEL_ACCESS_KEY")
if not key:
    sys.exit("DO_MODEL_ACCESS_KEY not set in environment")

url = "https://inference.do-ai.run/v1/chat/completions"
headers = {
    "Authorization": f"Bearer {key}",
    "Content-Type": "application/json",
}
payload = {
    "model": "llama3.3-70b-instruct",
    "messages": [{"role": "user", "content": "Say YUNAKI SKILLS is ready in exactly 5 words"}],
    "max_completion_tokens": 50,
}

resp = requests.post(url, headers=headers, json=payload, timeout=30)
print(f"Status: {resp.status_code}")
print(f"Response: {resp.json()['choices'][0]['message']['content']}")
print("DigitalOcean inference working ✅")
