"""Offline tests for git_hook.py — marker-scoped post-merge hook install/uninstall."""

import os
import stat

import git_hook


def test_install_creates_executable_hook(tmp_path):
    hooks = str(tmp_path / "hooks")
    path = git_hook.install(hooks, script_path="/abs/post-merge-ingest.sh")
    assert os.path.basename(path) == "post-merge"
    text = open(path).read()
    assert git_hook.START in text and git_hook.END in text
    assert "/abs/post-merge-ingest.sh" in text
    assert os.stat(path).st_mode & stat.S_IXUSR  # executable


def test_install_is_idempotent(tmp_path):
    hooks = str(tmp_path / "hooks")
    git_hook.install(hooks, script_path="/abs/s.sh")
    git_hook.install(hooks, script_path="/abs/s.sh")
    text = open(os.path.join(hooks, "post-merge")).read()
    assert text.count(git_hook.START) == 1  # no duplicate block


def test_install_preserves_existing_hook_body(tmp_path):
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "post-merge").write_text("#!/usr/bin/env bash\necho existing-user-hook\n")
    git_hook.install(str(hooks), script_path="/abs/s.sh")
    text = (hooks / "post-merge").read_text()
    assert "echo existing-user-hook" in text  # user's hook kept
    assert git_hook.START in text  # our block appended


def test_uninstall_removes_only_our_block(tmp_path):
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "post-merge").write_text("#!/usr/bin/env bash\necho keep-me\n")
    git_hook.install(str(hooks), script_path="/abs/s.sh")
    assert git_hook.uninstall(str(hooks)) is True
    text = (hooks / "post-merge").read_text()
    assert "echo keep-me" in text
    assert git_hook.START not in text


def test_uninstall_removes_empty_hook_file(tmp_path):
    hooks = str(tmp_path / "hooks")
    git_hook.install(hooks, script_path="/abs/s.sh")  # creates a shebang-only + our block
    assert git_hook.uninstall(hooks) is True
    assert not os.path.exists(os.path.join(hooks, "post-merge"))  # nothing left -> removed


def test_uninstall_noop_when_absent(tmp_path):
    assert git_hook.uninstall(str(tmp_path / "hooks")) is False


def test_build_block_shell_quotes_path():
    block = git_hook.build_block("/path with spaces/s.sh")
    assert "'/path with spaces/s.sh'" in block


def test_resolve_hooks_dir_fallback_without_git(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise OSError("no git")

    monkeypatch.setattr(git_hook.subprocess, "run", boom)
    assert git_hook.resolve_hooks_dir(str(tmp_path)) == os.path.join(str(tmp_path), ".git", "hooks")


def test_cli_install_then_uninstall(tmp_path, capsys):
    repo = tmp_path
    (repo / ".git" / "hooks").mkdir(parents=True)
    rc = git_hook.main(["--repo-root", str(repo), "--script", "/abs/s.sh"])
    assert rc == 0 and "installed" in capsys.readouterr().out
    rc = git_hook.main(["--repo-root", str(repo), "--uninstall"])
    assert rc == 0 and "removed" in capsys.readouterr().out
