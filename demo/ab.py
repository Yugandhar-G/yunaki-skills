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
# human-readable names so the output reads without dev jargon
LABEL = {"slug": "url format", "status": "error code", "time": "date format"}


def _load(path: str):
    spec = importlib.util.spec_from_file_location("m", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    print("Real Claude agents wrote the same function each time. The ONLY difference:")
    print("did they have the codebase's house rule, or not?\n")
    print(f"{'house rule':12} {'AI had rule?':13} {'it wrote':22} {'codebase wants':22} ok")
    print("-" * 76)
    score = {"control": 0, "context": 0}
    for task, (call, expected) in TASKS.items():
        for arm, fname in (("control", f"ctl_{task}.py"), ("context", f"trt_{task}.py")):
            try:
                got = call(_load(os.path.join(HERE, "ab", fname)))
                ok = got == expected
            except Exception as e:  # noqa: BLE001 — report any failure as a fail
                got, ok = f"ERROR {e}", False
            score[arm] += ok
            had = "no" if arm == "control" else "yes"
            print(f"{LABEL[task]:12} {had:13} {str(got)[:22]:22} {str(expected)[:22]:22} {'pass' if ok else 'FAIL'}")
    print("-" * 76)
    print(f"AI WITHOUT the codebase's rules : {score['control']}/3 correct")
    print(f"AI WITH the learned rules       : {score['context']}/3 correct")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
