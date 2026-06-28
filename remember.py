#!/usr/bin/env python3
"""Write a skill-bound fact into the local store. Deterministic, no LLM.

This is the ingestion path we control: a human (or the coding agent, using its own
tokens during a task) records a repo-specific fact that future skill invocations will
recall. Example:

    ./remember.py --skill api-design --skill fastapi-patterns \\
        --title "EmailStr requires email-validator" \\
        "FastAPI EmailStr needs the email-validator package or imports 500 at startup."
"""
from __future__ import annotations

import argparse

import facts


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Record a skill-bound repo fact (no LLM).")
    p.add_argument("--skill", action="append", default=[], help="skill to tag (repeatable)")
    p.add_argument("--title", required=True, help="one-line fact title")
    p.add_argument("--project", default=None, help="project scope (default: cwd basename)")
    p.add_argument("body", help="the fact body")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    path = facts.write_fact(args.skill, args.title, args.body, project=args.project)
    print(f"saved fact -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
