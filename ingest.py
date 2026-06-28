#!/usr/bin/env python3
"""Deterministic fact extraction from failing test output. No LLM, stdlib only.

This is the automatic ingestion path: when a task's tests fail, we mine the output
for high-signal, repo-specific facts (missing dependencies, the exact expected vs
actual values, the failing test names) and write them to the local fact store via
facts.write_fact. Next time the skill is invoked, recall surfaces them — so the
skill improves from failure WITHOUT any LLM call or any change to SKILL.md.

Usage:
    pytest ... 2>&1 | ./ingest.py --skill api-design
    ./ingest.py --skill backend-patterns --from-file failure.txt
"""
from __future__ import annotations

import argparse
import re
import sys

import facts

_MISSING_MODULE_RE = re.compile(r"No module named ['\"]([\w.]+)['\"]")
_FAILED_TEST_RE = re.compile(r"^FAILED\s+\S+::(\w+)", re.MULTILINE)
_ASSERT_RE = re.compile(r"assert\s+(.+?)\s+==\s+(.+?)\s*$", re.MULTILINE)
_MAX_BODY = 280


def _humanize(test_name: str) -> str:
    """test_slugify_uses_underscores -> 'slugify uses underscores'."""
    return re.sub(r"^test_", "", test_name).replace("_", " ").strip()


def extract_facts(output: str) -> list[tuple[str, str]]:
    """Mine pytest/agent output into (title, body) facts. Deterministic; may be empty."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(title: str, body: str) -> None:
        key = title.lower()
        if key not in seen:
            seen.add(key)
            out.append((title[:120], body[:_MAX_BODY]))

    for module in dict.fromkeys(_MISSING_MODULE_RE.findall(output)):
        add(
            f"Missing dependency: {module}",
            f"Importing '{module}' failed in this environment. Install it / add it as a "
            f"dependency, or avoid the import.",
        )

    # Pair failed-test names with a concrete assertion diff. pytest prints the source
    # line ("assert f(x) == y") then the rewritten concrete line ("assert 'a' == 'b'");
    # the last match has the actual values, so prefer it.
    asserts = _ASSERT_RE.findall(output)
    got, expected = (asserts[-1] if asserts else (None, None))
    for test in dict.fromkeys(_FAILED_TEST_RE.findall(output)):
        human = _humanize(test)
        if got is not None and expected is not None:
            add(
                f"Convention: {human}",
                f"The test '{human}' expects {expected} (a run produced {got}). "
                f"Match the expected output exactly.",
            )
        else:
            add(f"Convention: {human}", f"The test '{human}' must pass. Honor that behavior.")

    # If there were assertions but no parsed FAILED lines, still capture the example.
    if not out and got is not None and expected is not None:
        add("Expected output", f"A test expected {expected} but a run produced {got}.")

    return out


def ingest(output: str, skills: list[str], project: str | None = None) -> list[str]:
    """Extract facts from output and write them to the store. Returns written paths."""
    paths = []
    for title, body in extract_facts(output):
        paths.append(facts.write_fact(skills, title, body, project=project))
    return paths


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Extract repo facts from failing test output (no LLM).")
    p.add_argument("--skill", action="append", default=[], help="skill to tag (repeatable)")
    p.add_argument("--project", default=None, help="project scope (default: cwd basename)")
    p.add_argument("--from-file", default=None, help="read output from file instead of stdin")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.from_file:
        with open(args.from_file, encoding="utf-8") as fh:
            output = fh.read()
    else:
        output = sys.stdin.read()
    paths = ingest(output, args.skill, project=args.project)
    if paths:
        print(f"learned {len(paths)} fact(s):")
        for p in paths:
            print(f"  {p}")
    else:
        print("no facts extracted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
