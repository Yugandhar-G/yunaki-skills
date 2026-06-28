#!/usr/bin/env python3
"""Self-evolution pass for the super memory. Deterministic, no LLM, stdlib only.

The store grows as PRs land; without curation it accumulates duplicates and stale
guidance, and skills start recalling advice that no longer matches the repo. This pass
keeps it current in three deterministic steps:

  1. dedup     — collapse facts with identical content, keeping the newest.
  2. supersede — within a (source, topic), keep only the newest K facts; a newer PR's
                 guidance about a file replaces the older guidance about that file.
  3. prune     — drop facts whose topic file no longer exists, and (when a TTL is set)
                 the aged tail that isn't the newest on its topic.

Manual facts (source=manual) are never superseded or pruned — a human put them there.
Like the rest of the system this never raises: on any failure it curates nothing.

Usage:
    ./consolidate.py --dry-run                 # show what it would do
    ./consolidate.py                           # apply
    ./consolidate.py --ttl-days 180 --repo-root .
"""

from __future__ import annotations

import argparse
import datetime
import os
import re

import facts

_DEFAULT_KEEP_PER_TOPIC = int(os.environ.get("YUNAKI_SUPERSEDE_KEEP", "2") or 2)
_DEFAULT_TTL_DAYS = int(os.environ.get("YUNAKI_FACT_TTL_DAYS", "0") or 0)  # 0 = disabled
_REF_NUM_RE = re.compile(r"(\d+)")


def _today() -> str:
    return datetime.date.today().isoformat()


def _date(f: facts.Fact) -> str:
    """Effective recency date (ISO string; '' sorts oldest)."""
    return f.updated or f.created or ""


def _ref_num(ref: str) -> int:
    m = _REF_NUM_RE.search(ref or "")
    return int(m.group(1)) if m else 0


def _recency_key(f: facts.Fact) -> tuple[str, int, str]:
    """Newest last. ISO date, then PR number, then path as a stable tiebreaker."""
    return (_date(f), _ref_num(f.ref), f.path)


def _is_sourced(f: facts.Fact) -> bool:
    """Auto-ingested (PR/commit/test/codebase) — eligible for supersede/prune.
    Manual facts are owned by a human and left alone."""
    return f.source not in ("", "manual")


def _looks_like_path(topic: str) -> bool:
    return bool(topic) and " " not in topic and ("/" in topic or "." in topic)


def dedup(items: list[facts.Fact]) -> tuple[list[facts.Fact], list[facts.Fact]]:
    """Collapse identical content, keeping the newest per group. Topic is part of the key:
    two facts with the same words but anchored to different files are distinct guidance."""
    groups: dict[tuple[str, str, str], list[facts.Fact]] = {}
    for f in items:
        key = (f.title.strip().lower(), f.body.strip().lower(), f.topic)
        groups.setdefault(key, []).append(f)
    kept, dropped = [], []
    for group in groups.values():
        ordered = sorted(group, key=_recency_key)
        kept.append(ordered[-1])
        dropped.extend(ordered[:-1])
    return kept, dropped


def supersede(
    items: list[facts.Fact], keep_per_topic: int = _DEFAULT_KEEP_PER_TOPIC
) -> tuple[list[facts.Fact], list[facts.Fact]]:
    """Within each (source, topic) of sourced facts, keep the newest `keep_per_topic`."""
    groups: dict[tuple[str, str], list[facts.Fact]] = {}
    kept, dropped = [], []
    for f in items:
        if _is_sourced(f) and f.topic:
            groups.setdefault((f.source, f.topic), []).append(f)
        else:
            kept.append(f)  # manual or topic-less facts are exempt
    for group in groups.values():
        ordered = sorted(group, key=_recency_key, reverse=True)  # newest first
        kept.extend(ordered[:keep_per_topic])
        dropped.extend(ordered[keep_per_topic:])
    return kept, dropped


def prune(
    items: list[facts.Fact],
    ttl_days: int = _DEFAULT_TTL_DAYS,
    today: str | None = None,
    repo_root: str | None = None,
) -> tuple[list[facts.Fact], list[facts.Fact]]:
    """Drop facts whose topic file is gone (when repo_root is given) and, if ttl_days>0,
    the aged tail that isn't the newest on its topic."""
    today = today or _today()
    cutoff = ""
    if ttl_days > 0:
        cutoff = (
            datetime.date.fromisoformat(today) - datetime.timedelta(days=ttl_days)
        ).isoformat()

    newest_by_topic: dict[str, facts.Fact] = {}
    for f in items:
        if f.topic:
            cur = newest_by_topic.get(f.topic)
            if cur is None or _recency_key(f) > _recency_key(cur):
                newest_by_topic[f.topic] = f

    kept, dropped = [], []
    for f in items:
        gone = (
            repo_root is not None
            and _is_sourced(f)
            and _looks_like_path(f.topic)
            and not os.path.exists(os.path.join(repo_root, f.topic))
        )
        aged = (
            cutoff
            and _is_sourced(f)
            and _date(f)
            and _date(f) < cutoff
            and newest_by_topic.get(f.topic) is not f
        )
        if gone or aged:
            dropped.append(f)
        else:
            kept.append(f)
    return kept, dropped


def plan_consolidation(
    items: list[facts.Fact],
    keep_per_topic: int = _DEFAULT_KEEP_PER_TOPIC,
    ttl_days: int = _DEFAULT_TTL_DAYS,
    today: str | None = None,
    repo_root: str | None = None,
) -> dict:
    """Run dedup -> supersede -> prune on the survivors. Returns Fact lists per stage."""
    survivors, deduped = dedup(items)
    survivors, superseded = supersede(survivors, keep_per_topic)
    survivors, pruned = prune(survivors, ttl_days, today, repo_root)
    return {"deduped": deduped, "superseded": superseded, "pruned": pruned, "kept": survivors}


def consolidate(
    project: str | None = None,
    root: str = facts.DEFAULT_ROOT,
    dry_run: bool = False,
    keep_per_topic: int = _DEFAULT_KEEP_PER_TOPIC,
    ttl_days: int = _DEFAULT_TTL_DAYS,
    today: str | None = None,
    repo_root: str | None = None,
) -> dict:
    """Curate the project's fact store in place. Returns a report. Never raises."""
    try:
        items = facts.load_facts(facts.facts_dir(project, root))
    except OSError:
        return {"deduped": [], "superseded": [], "pruned": [], "kept": 0, "dry_run": dry_run}
    plan = plan_consolidation(items, keep_per_topic, ttl_days, today, repo_root)
    removed = [*plan["deduped"], *plan["superseded"], *plan["pruned"]]
    if not dry_run:
        for f in removed:
            try:
                if f.path:
                    os.remove(f.path)
            except OSError:
                continue
    return {
        "deduped": [f.path for f in plan["deduped"]],
        "superseded": [f.path for f in plan["superseded"]],
        "pruned": [f.path for f in plan["pruned"]],
        "kept": len(plan["kept"]),
        "dry_run": dry_run,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Curate the fact store: dedup, supersede, prune (no LLM)."
    )
    p.add_argument("--project", default=None, help="project scope (default: cwd basename)")
    p.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    p.add_argument(
        "--keep-per-topic",
        type=int,
        default=_DEFAULT_KEEP_PER_TOPIC,
        help="newest facts kept per topic",
    )
    p.add_argument(
        "--ttl-days", type=int, default=_DEFAULT_TTL_DAYS, help="prune aged facts (0=off)"
    )
    p.add_argument(
        "--repo-root", default=None, help="prune facts whose topic file is gone under here"
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = consolidate(
        project=args.project,
        dry_run=args.dry_run,
        keep_per_topic=args.keep_per_topic,
        ttl_days=args.ttl_days,
        repo_root=args.repo_root,
    )
    verb = "would remove" if report["dry_run"] else "removed"
    print(
        f"{verb}: {len(report['deduped'])} dup, {len(report['superseded'])} superseded, "
        f"{len(report['pruned'])} pruned | kept {report['kept']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
