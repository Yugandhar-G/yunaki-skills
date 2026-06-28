"""Offline tests for register_hook.py — idempotent SessionStart hook registration."""

import json

import pytest

import register_hook

CMD = "/abs/repo/hooks/session-start-bind.sh"


def _read(path):
    with open(path) as fh:
        return json.load(fh)


def test_register_creates_settings(tmp_path):
    s = str(tmp_path / "settings.json")
    assert register_hook.register(s, CMD) is True
    data = _read(s)
    assert register_hook._has_command(data, CMD)


def test_register_is_idempotent(tmp_path):
    s = str(tmp_path / "settings.json")
    register_hook.register(s, CMD)
    assert register_hook.register(s, CMD) is False  # second time changes nothing
    groups = _read(s)["hooks"]["SessionStart"]
    cmds = [h["command"] for g in groups for h in g["hooks"]]
    assert cmds.count(CMD) == 1  # exactly one


def test_register_preserves_existing_settings(tmp_path):
    s = tmp_path / "settings.json"
    s.write_text(
        json.dumps(
            {
                "model": "opus",
                "hooks": {
                    "SessionStart": [{"hooks": [{"type": "command", "command": "other.sh"}]}],
                    "PostToolUse": [{"matcher": "Write", "hooks": []}],
                },
            }
        )
    )
    register_hook.register(str(s), CMD)
    data = _read(str(s))
    assert data["model"] == "opus"  # unrelated settings intact
    assert "PostToolUse" in data["hooks"]  # other hook kinds intact
    cmds = [h["command"] for g in data["hooks"]["SessionStart"] for h in g["hooks"]]
    assert "other.sh" in cmds and CMD in cmds  # existing SessionStart hook kept


def test_unregister_removes_only_our_hook(tmp_path):
    s = tmp_path / "settings.json"
    s.write_text(
        json.dumps(
            {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "other.sh"}]}]}}
        )
    )
    register_hook.register(str(s), CMD)
    assert register_hook.unregister(str(s), CMD) is True
    cmds = [h["command"] for g in _read(str(s))["hooks"]["SessionStart"] for h in g["hooks"]]
    assert cmds == ["other.sh"]  # ours gone, user's kept


def test_unregister_noop_when_absent(tmp_path):
    s = tmp_path / "settings.json"
    s.write_text("{}")
    assert register_hook.unregister(str(s), CMD) is False


def test_malformed_settings_is_not_clobbered(tmp_path):
    s = tmp_path / "settings.json"
    s.write_text("{ this is not json ")
    with pytest.raises(ValueError):
        register_hook.register(str(s), CMD)
    assert s.read_text() == "{ this is not json "  # left exactly as-is


def test_empty_file_treated_as_empty_settings(tmp_path):
    s = tmp_path / "settings.json"
    s.write_text("   \n")
    assert register_hook.register(str(s), CMD) is True


def test_hook_command_uses_repo_root():
    assert register_hook.hook_command("/x/y") == "/x/y/hooks/session-start-bind.sh"


def test_cli_install_and_uninstall(tmp_path, capsys):
    s = str(tmp_path / "settings.json")
    rc = register_hook.main(["--settings", s, "--repo-root", "/abs/repo"])
    assert rc == 0 and "registered" in capsys.readouterr().out
    rc = register_hook.main(["--settings", s, "--repo-root", "/abs/repo", "--uninstall"])
    assert rc == 0 and "removed" in capsys.readouterr().out


def test_cli_reports_malformed_without_crashing(tmp_path, capsys):
    s = tmp_path / "settings.json"
    s.write_text("not json")
    rc = register_hook.main(["--settings", str(s)])
    assert rc == 1 and "could not update" in capsys.readouterr().out
