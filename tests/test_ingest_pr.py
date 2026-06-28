"""Offline tests for ingest_pr.py — deterministic PR knowledge extraction (no network)."""

import facts
import ingest_pr

PR = {
    "number": 8,
    "title": "fix(api): validate pagination params at the boundary",
    "body": "Pagination accepted negative offsets.\n\nThis clamps them.\n",
    "mergedAt": "2026-06-20T10:00:00Z",
    "files": [
        {"path": "src/app/routes.py", "additions": 40, "deletions": 5},
        {"path": "tests/test_routes.py", "additions": 10, "deletions": 0},
    ],
    "commits": [
        {"messageHeadline": "fix(api): clamp negative offset to zero"},
        {"messageHeadline": "Merge branch 'main' into fix/pagination"},
        {"messageHeadline": "test: cover offset boundary"},
    ],
    "review_comments": [
        {
            "path": "src/app/routes.py",
            "body": "Use 422 here, not 400, for validation errors.",
            "user": {"login": "reviewer"},
        },
        {"path": "src/app/routes.py", "body": "nit", "user": {"login": "reviewer"}},
        {
            "path": "src/app/routes.py",
            "body": "auto comment from a bot here now",
            "user": {"login": "dependabot[bot]"},
        },
    ],
    "reviews": [{"body": "Looks good once the 422 change lands."}],
}


# ── topic selection ────────────────────────────────────────────────────────────


def test_pr_topic_picks_most_changed_file():
    assert ingest_pr._pr_topic(PR["files"]) == "src/app/routes.py"


def test_pr_topic_single_file():
    assert ingest_pr._pr_topic([{"path": "a.py", "additions": 1, "deletions": 0}]) == "a.py"


def test_pr_topic_empty():
    assert ingest_pr._pr_topic([]) == ""


# ── extraction (pure, deterministic) ───────────────────────────────────────────


def test_extract_includes_title_fact():
    specs = ingest_pr.extract_facts_from_pr(PR)
    assert any("validate pagination params" in s["title"] for s in specs)


def test_extract_commit_subjects_skipping_merges():
    titles = [s["title"] for s in ingest_pr.extract_facts_from_pr(PR)]
    assert any("clamp negative offset" in t for t in titles)
    assert not any(t.lower().startswith("merge ") for t in titles)


def test_extract_review_comment_topic_is_file_path():
    specs = ingest_pr.extract_facts_from_pr(PR)
    c422 = [s for s in specs if "422" in s["body"]]
    assert c422 and c422[0]["topic"] == "src/app/routes.py"


def test_topic_only_on_file_anchored_facts():
    specs = ingest_pr.extract_facts_from_pr(PR)
    title_fact = next(s for s in specs if "validate pagination" in s["title"])
    assert title_fact["topic"] == "src/app/routes.py"  # headline keyed to its file
    commit_fact = next(s for s in specs if "clamp negative offset" in s["title"])
    assert commit_fact["topic"] == ""  # commit subject is a historical event, topic-less
    review = next(s for s in specs if "422" in s["body"])
    assert review["topic"] == "src/app/routes.py"  # review comment anchored to its file


def test_extract_filters_short_and_bot_comments():
    bodies = [s["body"] for s in ingest_pr.extract_facts_from_pr(PR)]
    assert not any(b == "nit" for b in bodies)
    assert not any("bot" in b.lower() for b in bodies)


def test_extract_is_deduped():
    specs = ingest_pr.extract_facts_from_pr(PR)
    keys = [(s["title"].lower(), s["topic"]) for s in specs]
    assert len(keys) == len(set(keys))


def test_extract_empty_pr_is_empty():
    assert ingest_pr.extract_facts_from_pr({"title": "", "files": []}) == []


def test_extract_survives_non_numeric_churn():
    # gh JSON is external; a non-numeric additions/deletions must not raise.
    pr = {
        "number": 9,
        "title": "fix something important in the codebase",
        "files": [
            {"path": "a.py", "additions": "NaN", "deletions": None},
            {"path": "b.py", "additions": 3, "deletions": 1},
        ],
    }
    specs = ingest_pr.extract_facts_from_pr(pr)
    assert specs and specs[0]["topic"] == "b.py"  # the numerically-rankable file wins


def test_extract_redacts_secrets():
    pr = {
        "number": 9,
        "title": "chore: rotate credentials and clean things up",
        "body": "old token was ghp_0123456789012345678901234567890123 fyi",
        "files": [{"path": "a.py", "additions": 1, "deletions": 0}],
        "review_comments": [
            {
                "path": "a.py",
                "body": "left AWS_SECRET=AKIAIOSFODNN7EXAMPLE in here, remove it",
                "user": {"login": "rev"},
            }
        ],
    }
    blob = " ".join(s["body"] for s in ingest_pr.extract_facts_from_pr(pr))
    assert "ghp_0123456789012345678901234567890123" not in blob
    assert "AKIAIOSFODNN7EXAMPLE" not in blob
    assert "[REDACTED]" in blob


def test_pr_topic_tie_is_deterministic():
    files = [
        {"path": "b.py", "additions": 5, "deletions": 0},
        {"path": "a.py", "additions": 5, "deletions": 0},
    ]
    assert ingest_pr._pr_topic(files) == "b.py"  # equal churn -> stable secondary key (path desc)
    assert ingest_pr._pr_topic(list(reversed(files))) == "b.py"  # order-independent


# ── skill tagging ──────────────────────────────────────────────────────────────


def test_tag_skills_default_global():
    assert ingest_pr.tag_skills(None) == []
    assert ingest_pr.tag_skills([]) == []


def test_tag_skills_override():
    assert ingest_pr.tag_skills(["code-review"]) == ["code-review"]


# ── watermark ──────────────────────────────────────────────────────────────────


def test_watermark_round_trip(tmp_path):
    root = str(tmp_path)
    assert ingest_pr.read_watermark("proj", root) == 0
    ingest_pr.write_watermark(8, "proj", root)
    assert ingest_pr.read_watermark("proj", root) == 8


def test_watermark_clamps_corrupt_value(tmp_path):
    root = str(tmp_path)
    ingest_pr.write_watermark(-5, "proj", root)
    assert ingest_pr.read_watermark("proj", root) == 0  # negative clamped, not re-ingest-all


# ── orchestration (gh boundary mocked) ─────────────────────────────────────────


def test_ingest_prs_writes_facts_and_advances_watermark(tmp_path, monkeypatch):
    root = str(tmp_path)
    monkeypatch.setattr(ingest_pr, "fetch_merged_prs", lambda repo, since_number, limit: [PR])
    report = ingest_pr.ingest_prs(repo="o/r", project="proj", root=root)
    assert report["prs"] == 1 and report["written"]
    assert report["watermark"] == 8

    loaded = facts.load_facts(facts.facts_dir("proj", root))
    assert loaded and all(f.source == "pr" and f.ref == "#8" for f in loaded)
    assert any(f.topic == "src/app/routes.py" for f in loaded)
    assert all(f.created == "2026-06-20" for f in loaded)


def test_ingest_prs_incremental_skips_seen(tmp_path, monkeypatch):
    root = str(tmp_path)
    ingest_pr.write_watermark(8, "proj", root)
    # fetch_merged_prs is responsible for honoring since_number; simulate it returning nothing.
    monkeypatch.setattr(ingest_pr, "fetch_merged_prs", lambda repo, since_number, limit: [])
    report = ingest_pr.ingest_prs(repo="o/r", project="proj", root=root)
    assert report["prs"] == 0 and report["written"] == []
    assert report["watermark"] == 8


def test_ingest_prs_no_repo_returns_error(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest_pr, "detect_repo", lambda: None)
    report = ingest_pr.ingest_prs(repo=None, project="proj", root=str(tmp_path))
    assert report["error"] == "no repo" and report["written"] == []


def test_ingest_prs_survives_a_malformed_pr(tmp_path, monkeypatch):
    root = str(tmp_path)
    bad = {"number": "not-an-int", "files": [{"path": "a.py", "additions": object()}]}
    monkeypatch.setattr(ingest_pr, "fetch_merged_prs", lambda repo, since_number, limit: [bad, PR])
    report = ingest_pr.ingest_prs(repo="o/r", project="proj", root=root)
    # the good PR still ingests; the bad one is skipped, not fatal
    assert report["written"] and report["watermark"] == 8


def test_fetch_merged_prs_filters_by_watermark(monkeypatch):
    listed = [
        {"number": 10, "title": "new", "body": "", "mergedAt": "", "files": []},
        {"number": 7, "title": "old", "body": "", "mergedAt": "", "files": []},
    ]

    def fake_gh_json(args, default):
        if args[:2] == ["pr", "list"]:
            return listed
        return default  # commits/reviews/comments empty

    monkeypatch.setattr(ingest_pr, "_gh_json", fake_gh_json)
    prs = ingest_pr.fetch_merged_prs("o/r", since_number=8, limit=30)
    nums = [p["number"] for p in prs]
    assert nums == [10]  # #7 is below the watermark


def test_detect_repo_parses_origin(monkeypatch):
    monkeypatch.setattr(
        ingest_pr, "_run", lambda args: "git@github.com:Yugandhar-G/yunaki-skills.git\n"
    )
    assert ingest_pr.detect_repo() == "Yugandhar-G/yunaki-skills"


def test_run_never_raises_on_missing_binary(monkeypatch):
    def boom(*a, **k):
        raise OSError("gh not found")

    monkeypatch.setattr(ingest_pr.subprocess, "run", boom)
    assert ingest_pr._run(["gh", "--version"]) is None


def test_extract_drops_low_signal_titles_and_commits():
    pr = {
        "title": "Feat/ide agnostic godlevel loop",  # branch-name style -> dropped
        "body": "",
        "files": [{"path": "x.py", "additions": 1, "deletions": 0}],
        "commits": [
            {"messageHeadline": "chore: bump deps to latest"},  # housekeeping -> dropped
            {"messageHeadline": "fix: clamp negative watermark offset"},  # substantive -> kept
        ],
        "review_comments": [],
        "reviews": [],
    }
    titles = [s["title"] for s in ingest_pr.extract_facts_from_pr(pr)]
    assert any("clamp negative watermark" in t for t in titles)
    assert not any("godlevel" in t for t in titles)
    assert not any("bump deps" in t for t in titles)


def test_extract_keeps_review_comments_even_if_chore_like():
    pr = {
        "title": "chore: x",
        "body": "",
        "files": [],
        "commits": [],
        "review_comments": [
            {
                "body": "always validate input at the boundary here",
                "path": "a.py",
                "user": {"login": "alice"},
            }
        ],
        "reviews": [],
    }
    titles = [s["title"] for s in ingest_pr.extract_facts_from_pr(pr)]
    assert any("validate input at the boundary" in t for t in titles)
