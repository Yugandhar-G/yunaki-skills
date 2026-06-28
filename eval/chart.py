#!/usr/bin/env python3
"""Render 3-arm eval results to a grouped bar chart (PNG). Deterministic — reads the JSON, no
agents — so the chart is reproducible without re-running the model.

  python3 eval/chart.py [eval/results/eval-latest.json] [-o eval/results/eval.png]
"""

from __future__ import annotations

import argparse
import json
import os

import matplotlib

matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt  # noqa: E402  (after backend selection)

ARMS_ORDER = ("baseline", "skill", "evolved")
METRICS = (("tests", "tests passed"), ("conventions", "conventions followed"))
COLORS = {"tests": "#0c0d0a", "conventions": "#ff3b00"}


def render(data: dict, out_path: str) -> None:
    arms = [a for a in ARMS_ORDER if a in data["arms"]]
    n = data["meta"]["n_per_arm"]
    model = data["meta"]["model"]
    x = list(range(len(arms)))
    width = 0.38

    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    for j, (key, label) in enumerate(METRICS):
        means = [data["arms"][a][key]["mean"] for a in arms]
        stds = [data["arms"][a][key]["std"] for a in arms]
        pos = [i + (j - 0.5) * width for i in x]
        bars = ax.bar(pos, means, width, yerr=stds, capsize=4, label=label, color=COLORS[key])
        ax.bar_label(bars, fmt="%.2f", padding=3, fontsize=8)  # label every bar

    ax.set_xticks(x)
    ax.set_xticklabels(arms, fontsize=11)
    ax.set_ylim(0, 1.22)  # headroom so the 1.00 labels clear the legend
    ax.set_ylabel("score (0–1)")
    ax.set_title(f"Skill evolution: baseline vs skill vs evolved  ·  {model}, N={n}/arm")
    ax.legend(frameon=False, loc="upper center", ncol=2)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"wrote {out_path}")


def main(argv: list[str] | None = None) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    p = argparse.ArgumentParser(description="Chart 3-arm eval results.")
    p.add_argument("results", nargs="?", default=os.path.join(here, "results", "eval-latest.json"))
    p.add_argument("-o", "--out", default=os.path.join(here, "results", "eval.png"))
    args = p.parse_args(argv)
    with open(args.results, encoding="utf-8") as fh:
        data = json.load(fh)
    render(data, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
