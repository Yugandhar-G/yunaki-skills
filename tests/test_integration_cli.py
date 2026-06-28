"""Opt-in integration test against a REAL coding-agent CLI.

Skipped unless YUNAKI_IT=1 so CI stays hermetic. Run locally with a coding CLI
on PATH (claude by default):

    YUNAKI_IT=1 pytest tests/test_integration_cli.py -v

This is the only test that executes a real subprocess agent — it guards the
argv templates and stdout parsers that the unit tests can only mock.
"""

from __future__ import annotations

import json
import os
import shutil

import pytest

from yunaki_skills import cli_agent, skill_llm
from yunaki_skills.agent_specs import spec_by_name

pytestmark = pytest.mark.integration

_OPT_IN = os.getenv("YUNAKI_IT") in {"1", "true", "yes", "on"}
_BACKEND = os.getenv("YUNAKI_IT_BACKEND", "claude")

skip_reason = "set YUNAKI_IT=1 (and have the CLI installed/authed) to run real-CLI integration tests"


@pytest.mark.skipif(not _OPT_IN, reason=skip_reason)
def test_real_cli_returns_parseable_json():
    spec = spec_by_name(_BACKEND)
    assert spec is not None, f"unknown backend {_BACKEND}"
    if shutil.which(spec.binary) is None:
        pytest.skip(f"{spec.binary} not on PATH")

    # Short leash for the test.
    spec = spec.__class__(spec.name, spec.binary, spec.argv_template, spec.parser_kind, timeout_s=90)
    body, stderr, rc = cli_agent.run_cli(spec, 'Reply with ONLY this JSON: {"audit": "ok"}', ".")

    assert rc == 0, f"{spec.name} exited {rc}: {stderr[:300]}"
    assert json.loads(body) == {"audit": "ok"}


@pytest.mark.skipif(not _OPT_IN, reason=skip_reason)
def test_real_meta_op_returns_json(monkeypatch):
    monkeypatch.delenv("YUNAKI_SKILL_MODEL", raising=False)  # force host-CLI routing
    out = skill_llm.complete_json(
        "Extract a skill as JSON with keys id, title, instructions for the task "
        '"add a /health endpoint". Return ONLY the JSON object.'
    )
    data = json.loads(out)
    assert {"id", "title", "instructions"} <= set(data.keys())
