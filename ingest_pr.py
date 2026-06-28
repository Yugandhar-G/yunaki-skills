#!/usr/bin/env python3
"""Deterministic PR ingester — the repo-knowledge source for the super memory. No LLM.

Merged PRs carry knowledge a human already wrote down: the PR title/body (what changed
and why), the commit subjects (intent, conventional-commit-tagged), and inline review
comments (gotchas anchored to a file). This miner pulls those verbatim via `gh` and
writes them as provenance-tagged facts (source=pr, ref=#N, topic=<file>) into the same
markdown store recall.py reads. No LLM, no rewriting — the human's words, scoped.

Ingestion is incremental: a per-project watermark records the highest PR number seen, so
re-runs only pull newer PRs. Like recall/facts, this never raises to the caller — a
missing or unauthenticated `gh` yields no facts rather than an error.

Usage:
    ./ingest_pr.py                                  # auto-detect repo from git remote
    ./ingest_pr.py --repo owner/name --limit 30
    ./ingest_pr.py --repo owner/name --skill code-review   # tag to a skill (default global)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess

import facts

_MIN_LEN = 12  # ignore one-word/"LGTM"/"nit" fragments
_MAX_BODY = 280
_MAX_TITLE = 120
_MAX_COMMITS_PER_PR = 10
_DEFAULT_LIMIT = 30
_GH_TIMEOUT = 30
_MERGE_RE = re.compile(r"^(Merge (pull request|branch|remote-tracking)|Merge\b)", re.IGNORECASE)
_BOT_RE = re.compile(r"(\[bot\]|-bot$|^dependabot|^github-actions)", re.IGNORECASE)
_REMOTE_RE = re.compile(r"github\.com[:/]+([^/]+/[^/.]+)")
# Redact obvious secrets before they're persisted (recall.py also scrubs on read; this is
# defense-in-depth so a leaked token in a PR body never lands on disk). Mirrors recall._SECRET_RE.
_SECRET_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|"
    r"AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}|"
    r"(?:password|secret|token|api[_-]?key)\s*[=:]\s*\S{6,})"
)


# ── gh boundary (the only side-effecting part; never raises) ───────────────────


def _run(args: list[str]) -> str | None:
    """Run a command, return stdout or None on any failure. Never raises."""
    # args is always a fixed list of literals (gh/git + flags); no shell=True, so the
    # untrusted-input execution S603 guards against cannot occur here. Kept active
    # repo-wide; silenced only on this reviewed call.
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=_GH_TIMEOUT)  # noqa: S603
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _gh_json(args: list[str], default):
    out = _run(["gh", *args])
    if not out:
        return default
    try:
        return json.loads(out)
    except (json.JSONDecodeError, ValueError):
        return default


def detect_repo() -> str | None:
    """owner/name from the git origin remote (no network), falling back to `gh`."""
    out = _run(["git", "remote", "get-url", "origin"])
    if out:
        m = _REMOTE_RE.search(out.strip())
        if m:
            return m.group(1)
    data = _gh_json(["repo", "view", "--json", "nameWithOwner"], {})
    return data.get("nameWithOwner") if isinstance(data, dict) else None


def fetch_merged_prs(repo: str, since_number: int = 0, limit: int = _DEFAULT_LIMIT) -> list[dict]:
    """Return merged PRs newer than `since_number`, enriched with commits + review
    comments. Each dict: {number, title, body, mergedAt, files, commits, review_comments,
    reviews}. Never raises; returns [] when `gh` is unavailable."""
    listed = _gh_json(
        [
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "merged",
            "--json",
            "number,title,body,mergedAt,files",
            "--limit",
            str(limit),
        ],
        [],
    )
    if not isinstance(listed, list):
        return []
    prs = []
    for pr in listed:
        num = pr.get("number")
        if not isinstance(num, int) or num <= since_number:
            continue
        view = _gh_json(["pr", "view", str(num), "--repo", repo, "--json", "commits,reviews"], {})
        pr["commits"] = view.get("commits", []) if isinstance(view, dict) else []
        pr["reviews"] = view.get("reviews", []) if isinstance(view, dict) else []
        rc = _gh_json(["api", f"repos/{repo}/pulls/{num}/comments"], [])
        pr["review_comments"] = rc if isinstance(rc, list) else []
        prs.append(pr)
    return prs


# ── pure extraction (no network; fully unit-testable) ──────────────────────────


def _clean(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", (text or "").strip())
    return _SECRET_RE.sub("[REDACTED]", collapsed)


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def _safe_int(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _pr_topic(files: list[dict]) -> str:
    """The single most-changed file — a specific supersession key. '' if none."""
    dicts = [f for f in files if isinstance(f, dict) and f.get("path")]
    if not dicts:
        return ""
    if len(dicts) == 1:
        return dicts[0]["path"]

    def churn(f: dict) -> int:
        return _safe_int(f.get("additions")) + _safe_int(f.get("deletions"))

    # Secondary key (path) so equal-churn files pick the same topic across re-runs — topic
    # is the supersession key, so a non-deterministic pick would break re-ingest idempotency.
    ranked = sorted(dicts, key=lambda f: (churn(f), f.get("path", "")), reverse=True)
    return ranked[0]["path"]


def extract_facts_from_pr(pr: dict) -> list[dict]:
    """Deterministic [{title, body, topic}] specs from a PR dict. No network, no LLM."""
    specs: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(title: str, body: str, topic: str) -> None:
        title, body = _clean(title), _clean(body)
        if len(title) < _MIN_LEN:
            return
        key = (title.lower(), topic)
        if key in seen:
            return
        seen.add(key)
        specs.append(
            {"title": title[:_MAX_TITLE], "body": (body or title)[:_MAX_BODY], "topic": topic}
        )

    topic = _pr_topic(pr.get("files") or [])

    # Topic is the supersession key, so it's reserved for file-state guidance: the PR's
    # headline change (one per PR -> newest-K-per-file across PRs keeps it current) and
    # inline review comments (anchored to their file). Commit subjects and review summaries
    # are historical events, not current guidance, so they're topic-less (dedup + TTL only).

    # 1) PR title/body — the change summary, keyed to the most-changed file.
    add(pr.get("title", ""), _first_line(pr.get("body", "")) or pr.get("title", ""), topic)

    # 2) commit subjects — intent, conventional-commit-tagged (skip merge commits).
    commits = 0
    for c in pr.get("commits") or []:
        if commits >= _MAX_COMMITS_PER_PR:
            break
        msg = c.get("messageHeadline") or c.get("message") or ""
        if not msg or _MERGE_RE.match(msg.strip()):
            continue
        add(msg, msg, "")
        commits += 1

    # 3) inline review comments — gotchas anchored to a file (topic = that file).
    for rc in pr.get("review_comments") or []:
        if not isinstance(rc, dict):
            continue
        body = rc.get("body") or ""
        user = (rc.get("user") or {}).get("login", "") if isinstance(rc.get("user"), dict) else ""
        if _BOT_RE.search(user) or len(body.strip()) < _MIN_LEN:
            continue
        add(_first_line(body), body, rc.get("path") or "")

    # 4) review summary bodies — overall verdict, not file-specific.
    for rv in pr.get("reviews") or []:
        if not isinstance(rv, dict):
            continue
        body = rv.get("body") or ""
        if len(body.strip()) < _MIN_LEN:
            continue
        add(_first_line(body), body, "")

    return specs


def tag_skills(skills: list[str] | None) -> list[str]:
    """Skills to tag PR facts with. Default global (empty) — recall ranks by query so
    repo-wide knowledge stays available to every skill without brittle auto-mapping."""
    return list(skills) if skills else []


# ── watermark (incremental ingest state; plain text, stdlib) ───────────────────


def _watermark_path(project: str | None, root: str) -> str:
    return os.path.join(os.path.dirname(facts.facts_dir(project, root)), ".watermark")


def read_watermark(project: str | None = None, root: str = facts.DEFAULT_ROOT) -> int:
    try:
        with open(_watermark_path(project, root), encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("last_pr="):
                    n = int(line.split("=", 1)[1].strip() or 0)
                    return n if n >= 0 else 0  # clamp a corrupt/negative watermark
    except (OSError, ValueError):
        return 0
    return 0


def write_watermark(n: int, project: str | None = None, root: str = facts.DEFAULT_ROOT) -> None:
    path = _watermark_path(project, root)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"last_pr={n}\n")
    except OSError:
        return


# ── orchestration ─────────────────────────────────────────────────────────────


def ingest_prs(
    repo: str | None = None,
    skills: list[str] | None = None,
    project: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    root: str = facts.DEFAULT_ROOT,
) -> dict:
    """Pull merged PRs newer than the watermark, write their facts, advance the
    watermark. Returns a report dict. Never raises."""
    repo = repo or detect_repo()
    if not repo:
        return {"repo": None, "prs": 0, "written": [], "watermark": 0, "error": "no repo"}
    since = read_watermark(project, root)
    prs = fetch_merged_prs(repo, since_number=since, limit=limit)
    tags = tag_skills(skills)
    written: list[str] = []
    highest = since
    for pr in prs:
        # One malformed PR must not abort the whole run (keeps the never-raise contract).
        try:
            num = pr.get("number", 0)
            created = (pr.get("mergedAt") or "")[:10]
            ref = f"#{num}"
            for spec in extract_facts_from_pr(pr):
                written.append(
                    facts.write_fact(
                        tags,
                        spec["title"],
                        spec["body"],
                        project=project,
                        root=root,
                        source="pr",
                        ref=ref,
                        topic=spec["topic"],
                        created=created or None,
                    )
                )
            highest = max(highest, num)
        except (OSError, ValueError, TypeError, KeyError):
            continue
    if highest > since:
        write_watermark(highest, project, root)
    return {"repo": repo, "prs": len(prs), "written": written, "watermark": highest}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Ingest merged-PR knowledge into the fact store (no LLM)."
    )
    p.add_argument("--repo", default=None, help="owner/name (default: detect from git remote)")
    p.add_argument(
        "--skill", action="append", default=[], help="skill to tag (repeatable; default global)"
    )
    p.add_argument("--project", default=None, help="project scope (default: cwd basename)")
    p.add_argument("--limit", type=int, default=_DEFAULT_LIMIT, help="max PRs to scan")
    p.add_argument(
        "--install-git-hook",
        action="store_true",
        help="wire the post-merge trigger into this repo and exit",
    )
    p.add_argument(
        "--uninstall-git-hook", action="store_true", help="remove the post-merge trigger and exit"
    )
    return p.parse_args(argv)


def _handle_git_hook(uninstall: bool) -> int:
    """Delegate to git_hook for the documented `ingest_pr.py --install-git-hook` UX."""
    import git_hook

    hooks_dir = git_hook.resolve_hooks_dir(os.path.abspath("."))
    if uninstall:
        changed = git_hook.uninstall(hooks_dir)
        print("removed post-merge hook block" if changed else "no hook block to remove")
    else:
        print(f"installed post-merge hook -> {git_hook.install(hooks_dir)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.install_git_hook or args.uninstall_git_hook:
        return _handle_git_hook(args.uninstall_git_hook)
    report = ingest_prs(args.repo, skills=args.skill, project=args.project, limit=args.limit)
    if report.get("error") or not report.get("repo"):
        print("no repo detected (set --repo owner/name)")
        return 0
    n = len(report["written"])
    print(f"ingested {report['prs']} PR(s) from {report['repo']}, wrote {n} fact(s)")
    print(f"watermark -> PR #{report['watermark']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
