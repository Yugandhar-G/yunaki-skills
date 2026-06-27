#!/usr/bin/env python3
"""Update DO App Platform env vars via the API using doctl's token."""
import os, json, subprocess

# Load .env
with open(os.path.expanduser("~/yunaki-skills/.env")) as f:
    env = {}
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k] = v

# Get DO token from doctl config
result = subprocess.run(["doctl", "auth", "get-access-token"], capture_output=True, text=True)
DO_TOKEN = result.stdout.strip()

APP_ID = "ed81b60d-7365-4449-a428-4793d89482d2"

# Build spec with secrets inline
spec = {
    "name": "yunaki-skills",
    "services": [{
        "name": "yunaki-app",
        "git": {
            "repo_clone_url": "https://github.com/Yugandhar-G/yunaki-skills.git",
            "branch": "main"
        },
        "dockerfile_path": "Dockerfile",
        "source_dir": "/",
        "run_command": "uvicorn yunaki_skills.main:app --host 0.0.0.0 --port 8000",
        "http_port": 8000,
        "instance_count": 1,
        "instance_size_slug": "basic-xxs",
        "envs": [
            {"key": "GEMINI_API_KEY", "scope": "RUN_TIME", "value": env.get("GEMINI_API_KEY", ""), "type": "SECRET"},
            {"key": "DO_MODEL_ACCESS_KEY", "scope": "RUN_TIME", "value": env.get("DO_MODEL_ACCESS_KEY", ""), "type": "SECRET"},
            {"key": "MONGODB_URI", "scope": "RUN_TIME", "value": env.get("MONGODB_URI", ""), "type": "SECRET"},
            {"key": "MONGO_DB", "scope": "RUN_TIME", "value": "yunaki"},
            {"key": "AUTH_ENABLED", "scope": "RUN_TIME", "value": "false"},
            {"key": "PYTHONPATH", "scope": "RUN_TIME", "value": "/app/src"}
        ],
        "health_check": {
            "http_path": "/health",
            "initial_delay_seconds": 30
        }
    }],
    "ingress": {
        "rules": [{
            "component": {"name": "yunaki-app"},
            "match": {"path": {"prefix": "/"}}
        }]
    }
}

# Write temp spec file
spec_path = "/tmp/do-app-spec.json"
with open(spec_path, "w") as f:
    json.dump(spec, f)

# Use doctl to update
result = subprocess.run(
    ["doctl", "apps", "update", APP_ID, "--spec", spec_path],
    capture_output=True, text=True
)
print(f"stdout: {result.stdout}")
print(f"stderr: {result.stderr}")
print(f"exit: {result.returncode}")

# Clean up
os.remove(spec_path)
