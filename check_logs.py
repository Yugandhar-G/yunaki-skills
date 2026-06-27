#!/usr/bin/env python3
"""Get DO App Platform build logs via API."""
import os, json, requests

with open(os.path.expanduser("~/yunaki-skills/.env")) as f:
    env = {}
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k] = v

DO_TOKEN = env.get("DO_MODEL_ACCESS_KEY", "")
APP_ID = "ed81b60d-7365-4449-a428-4793d89482d2"
DEPLOY_ID = "3bc27f0a-328f-4ec2-ad43-f67771f9414e"

# List deployments with full details
resp = requests.get(
    f"https://api.digitalocean.com/v2/apps/{APP_ID}/deployments",
    headers={"Authorization": f"Bearer {DO_TOKEN}"}
)
for dep in resp.json().get("deployments", []):
    print(f"Deployment: {dep['id']} Phase: {dep['phase']} Cause: {dep.get('cause', '?')}")
    for step in dep.get("progress", {}).get("steps", []):
        causes = step.get("causes", [])
        cause_msgs = [c.get("message", str(c)) for c in causes]
        if step.get("status") in ("ERROR",) or cause_msgs:
            print(f"  {step['name']}: {step['status']} causes={cause_msgs}")

# Try build logs
print(f"\nFetching build logs...")
resp2 = requests.get(
    f"https://api.digitalocean.com/v2/apps/{APP_ID}/deployments/{DEPLOY_ID}/logs",
    params={"type": "BUILD", "component_name": "yunaki-app", "follow": "false", "tail_lines": 50},
    headers={"Authorization": f"Bearer {DO_TOKEN}"}
)
print(f"Status: {resp2.status_code}")
if resp2.status_code == 200:
    data = resp2.json()
    for url in data.get("live_urls", data.get("historical_urls", [])):
        print(f"  Log URL: {url}")
    # Try to fetch log URLs
    for key in ["live_urls", "historical_urls"]:
        for url in data.get(key, []):
            r = requests.get(url)
            for line in r.text.splitlines()[-20:]:
                print(f"  {line}")
else:
    print(f"Error: {resp2.text[:500]}")
