#!/usr/bin/env python3
"""Score the live A/B. Six functions in demo/ab/ were written by real Claude agents — the
same task each time, the ONLY difference being whether the recalled repo convention was in
the prompt (ctl_* = no context, trt_* = with the learned fact). This just runs the hidden
convention tests against what they wrote. Deterministic; re-run it any time.
"""

from __future__ import annotations

import datetime
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
UTC = datetime.timezone.utc

TASKS = {
    "slug": (lambda m: m.slugify("My Cool Title"), "my_cool_title"),
    "status": (lambda m: m.validation_error_status(), 422),
    "time": (lambda m: m.iso_utc(datetime.datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC)), "2026-06-28T12:00:00Z"),
}
LABEL = {"slug": "slug", "status": "status", "time": "timestamp"}


def _load(path: str):
    spec = importlib.util.spec_from_file_location("m", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    print("6 implementations written by real Claude agents (haiku) — same task each time,")
    print("the only difference is whether the recalled repo convention was in the prompt.\n")
    print(f"{'task':10} {'arm':8} {'produced':22} {'expected':22} ok")
    print("-" * 70)
    score = {"control": 0, "context": 0}
    for task, (call, expected) in TASKS.items():
        for arm, fname in (("control", f"ctl_{task}.py"), ("context", f"trt_{task}.py")):
            try:
                got = call(_load(os.path.join(HERE, "ab", fname)))
                ok = got == expected
            except Exception as e:  # noqa: BLE001 — report any failure as a fail
                got, ok = f"ERROR {e}", False
            score[arm] += ok
            print(f"{LABEL[task]:10} {arm:8} {str(got)[:22]:22} {str(expected)[:22]:22} {'pass' if ok else 'FAIL'}")
    print("-" * 70)
    print(f"control (no learned context): {score['control']}/3 passed")
    print(f"context (recalled context)  : {score['context']}/3 passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
