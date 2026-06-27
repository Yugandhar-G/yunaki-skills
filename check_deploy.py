#!/usr/bin/env python3
"""Get DO App Platform build logs."""
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

# Get deployment details
resp = requests.get(
    f"https://api.digitalocean.com/v2/apps/{APP_ID}/deployments/{DEPLOY_ID}",
    headers={"Authorization": f"Bearer {DO_TOKEN}"}
)
data = resp.json()
deployment = data.get("deployment", {})
print(f"Phase: {deployment.get('phase')}")
print(f"Progress: {deployment.get('progress', {}).get('success_steps', 0)}/{deployment.get('progress', {}).get('total_steps', 0)}")

for step in deployment.get("progress", {}).get("steps", []):
    print(f"\nStep: {step.get('name')} - Status: {step.get('status')}")
    if step.get("message_base"):
        print(f"  Message: {step['message_base']}")
    for cause in step.get("causes", []):
        print(f"  Cause: {cause.get('message', cause)}")

# Try to get build logs
for component in deployment.get("components", []):
    cname = component.get("name", "")
    if cname == "yunaki-app":
        print(f"\nComponent: {cname}")
        print(f"  Phase: {component.get('phase')}")
