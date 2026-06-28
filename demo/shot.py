#!/usr/bin/env python3
"""Render captured terminal output (with ANSI colour) to a PNG, faithfully.

Used to turn the real, verbatim output of the demo scripts into the screenshots on the
landing page — so what you see is exactly what the command printed, not hand-drawn HTML.

    ./demo/shot.py in.txt out.png --title "always-on: scanned from the code, no failure"

Reads ANSI SGR colour codes (the same ones the demo scripts emit) and draws them. Stdlib +
Pillow only. Deterministic.
"""

from __future__ import annotations

import argparse
import re
import sys

from PIL import Image, ImageDraw, ImageFont

# raw spec-sheet palette: near-black terminal, off-white text, restrained accents
BG = (11, 13, 16)
BAR = (22, 26, 31)
BASE = (214, 219, 224)
DIM = (122, 132, 144)
RED = (255, 107, 107)
GREEN = (93, 210, 138)
CYAN = (86, 182, 194)
YELLOW = (229, 192, 123)
PAD = 28
LINE_SPACING = 1.5

_FONTS = [
    "/System/Library/Fonts/SFNSMono.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/Library/Fonts/Courier New.ttf",
]
_ANSI = re.compile(r"\x1b\[([0-9;]*)m")


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONTS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _spans(line: str) -> list[tuple[str, tuple[int, int, int], bool]]:
    """Split a line into (text, colour, bold) runs by parsing ANSI SGR codes."""
    out: list[tuple[str, tuple[int, int, int], bool]] = []
    color, bold, pos = BASE, False, 0
    for m in _ANSI.finditer(line):
        if m.start() > pos:
            out.append((line[pos : m.start()], color, bold))
        for code in (m.group(1) or "0").split(";"):
            if code in ("", "0"):
                color, bold = BASE, False
            elif code == "1":
                bold = True
            elif code == "2":
                color = DIM
            elif code == "31":
                color = RED
            elif code == "32":
                color = GREEN
            elif code == "33":
                color = YELLOW
            elif code == "36":
                color = CYAN
        pos = m.end()
    if pos < len(line):
        out.append((line[pos:], color, bold))
    return out


def _brighten(c: tuple[int, int, int]) -> tuple[int, int, int]:
    return tuple(min(255, int(v * 1.25)) for v in c)  # type: ignore[return-value]


def render(text: str, out_path: str, title: str, size: int = 26) -> None:
    font = _load_font(size)
    bold_font = _load_font(size)
    raw_lines = text.replace("\t", "    ").split("\n")
    spans = [_spans(ln) for ln in raw_lines]
    plain = [_ANSI.sub("", ln) for ln in raw_lines]

    char_w = font.getlength("M") or size * 0.6
    line_h = int(size * LINE_SPACING)
    cols = max((len(p) for p in plain), default=10)
    width = int(cols * char_w) + PAD * 2
    bar_h = line_h + 12
    height = bar_h + len(raw_lines) * line_h + PAD

    img = Image.new("RGB", (max(width, 480), height), BG)
    draw = ImageDraw.Draw(img)

    # terminal title bar: three dots + a label
    draw.rectangle([0, 0, img.width, bar_h], fill=BAR)
    for i, dot in enumerate((RED, YELLOW, GREEN)):
        cx = PAD + i * 22
        draw.ellipse([cx, bar_h // 2 - 6, cx + 12, bar_h // 2 + 6], fill=dot)
    if title:
        draw.text((PAD + 90, bar_h // 2 - size // 2), title, font=font, fill=DIM)

    y = bar_h + PAD // 2
    for line_spans in spans:
        x = PAD
        for run_text, color, bold in line_spans:
            fnt = bold_font if bold else font
            draw.text((x, y), run_text, font=fnt, fill=_brighten(color) if bold else color)
            x += int(font.getlength(run_text))
        y += line_h

    img.save(out_path)
    print(f"wrote {out_path} ({img.width}x{img.height})")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Render terminal output (ANSI) to PNG.")
    p.add_argument("input", help="captured terminal text (UTF-8, may contain ANSI codes)")
    p.add_argument("output", help="PNG path to write")
    p.add_argument("--title", default="", help="label shown in the terminal title bar")
    p.add_argument("--size", type=int, default=26, help="font size in px")
    args = p.parse_args(argv)
    try:
        with open(args.input, encoding="utf-8") as fh:
            text = fh.read().rstrip("\n")
    except OSError as e:
        print(f"cannot read {args.input}: {e}", file=sys.stderr)
        return 1
    render(text, args.output, args.title, args.size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
