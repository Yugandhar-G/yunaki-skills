#!/usr/bin/env python3
"""Convention-decisive CLI tasks for the 3-arm eval.

Each task is convention-NEUTRAL on purpose: the prompt states only what to build (a function
with a fixed signature + a command-line entry point), never how to style it. The repo's
conventions (stdlib-only, future-annotations, argparse+main, never-raise) come ONLY from the
arm's context (skill / evolved), so they're what the eval measures.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Task:
    name: str
    module: str  # filename the agent writes (e.g. "mdcount.py")
    prompt: str  # convention-neutral task description
    check: Callable[[object], bool]  # behavioral grader against the written module


def _mdcount_check(mod: object) -> bool:
    with tempfile.TemporaryDirectory() as d:
        for n in ("a.md", "b.md", "c.md", "x.txt"):
            open(os.path.join(d, n), "w").close()
        sub = os.path.join(d, "sub")
        os.mkdir(sub)
        open(os.path.join(sub, "e.md"), "w").close()
        return mod.count_md(d) == 4  # a,b,c + sub/e ; x.txt excluded


def _linecount_check(mod: object) -> bool:
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "f1"), "w") as fh:
            fh.write("one\ntwo\nthree\n")
        with open(os.path.join(d, "f2"), "w") as fh:
            fh.write("a\nb\n")
        return mod.count_lines(d) == 5  # non-recursive total


def _wordfreq_check(mod: object) -> bool:
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "doc.txt")
        with open(p, "w") as fh:
            fh.write("the cat sat on the mat the")
        return mod.top_word(p) == "the"


TASKS: list[Task] = [
    Task(
        name="mdcount",
        module="mdcount.py",
        prompt=(
            "Write a Python module `mdcount.py` for this repository. Expose a function "
            "`count_md(path: str) -> int` that returns the number of Markdown (.md) files under "
            "`path`, searching subdirectories recursively. Also provide a command-line entry "
            "point that prints the count for a directory argument."
        ),
        check=_mdcount_check,
    ),
    Task(
        name="linecount",
        module="linecount.py",
        prompt=(
            "Write a Python module `linecount.py` for this repository. Expose a function "
            "`count_lines(path: str) -> int` that returns the total number of lines across the "
            "regular files directly inside `path` (non-recursive). Also provide a command-line "
            "entry point that prints the total for a directory argument."
        ),
        check=_linecount_check,
    ),
    Task(
        name="wordfreq",
        module="wordfreq.py",
        prompt=(
            "Write a Python module `wordfreq.py` for this repository. Expose a function "
            "`top_word(path: str) -> str` that returns the most frequent whitespace-separated "
            "word (lowercased) in the text file at `path`. Also provide a command-line entry "
            "point that prints it for a file argument."
        ),
        check=_wordfreq_check,
    ),
]
