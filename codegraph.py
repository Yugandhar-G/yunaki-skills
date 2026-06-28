#!/usr/bin/env python3
"""Build a graph of the codebase from its own source. Deterministic, stdlib only, no LLM.

Nodes are modules; edges are the REAL import dependencies (extracted via `ast`). Each module
node carries the conventions the scan can prove from the code itself — stdlib-only (imports
checked against `sys.stdlib_module_names`), `from __future__ import annotations`, an
argparse + `main()` CLI shape, and a documented never-raises contract.

This is the structural half of the super memory: the code graph + a convention overlay. It
emits a graph (nodes + edges), not a flat list — `recall by locality` later means "touch a
file → its node → neighbours → their conventions".
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys

_STDLIB = set(getattr(sys, "stdlib_module_names", set())) | {"__future__"}
_SKIP_DIRS = {"self-evolution-v1", "demo", "tests", "__pycache__", "node_modules", "build"}


def _py_files(root: str) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(".py"):
                out.append(os.path.join(dirpath, fn))
    return out


def _module_id(path: str, root: str) -> str:
    rel = os.path.relpath(path, root)[:-3]  # drop .py
    return rel.replace(os.sep, ".")


def _top_imports(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def analyze(path: str) -> tuple[set[str], list[str], str]:
    """Return (top-level imports, provable conventions, raw source). Never raises."""
    try:
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        tree = ast.parse(src)
    except (OSError, SyntaxError, ValueError):
        return set(), [], ""
    imports = _top_imports(tree)
    has_future = any(
        isinstance(n, ast.ImportFrom) and n.module == "__future__" for n in ast.walk(tree)
    )
    has_main = any(isinstance(n, ast.FunctionDef) and n.name == "main" for n in ast.walk(tree))
    return imports, _conventions(imports, has_future, has_main, src), src


def _conventions(imports: set[str], has_future: bool, has_main: bool, src: str) -> list[str]:
    conv = []
    if has_future:
        conv.append("future-annotations")
    if "argparse" in imports and has_main:
        conv.append("argparse-cli")
    if "never raise" in src.lower() or "never raises" in src.lower():
        conv.append("never-raises")
    return conv


def build_graph(root: str = ".") -> dict:
    """Nodes = modules (+ conventions); edges = local import dependencies. Deterministic."""
    paths = _py_files(root)
    ids = {p: _module_id(p, root) for p in paths}
    local = set(ids.values())
    local_tops = {i.split(".")[0] for i in local}  # first segment, for `import facts` style

    nodes: list[dict] = []
    edges: list[dict] = []
    for path in sorted(paths):
        mid = ids[path]
        imports, conv, _ = analyze(path)
        third_party = imports - _STDLIB - local_tops
        if not third_party:
            conv = ["stdlib-only", *conv]
        nodes.append({"id": mid, "conventions": conv, "thirdparty": sorted(third_party)})
        for imp in sorted(imports):
            target = next((m for m in local if m == imp or m.split(".")[-1] == imp), None)
            if target and target != mid:
                edges.append({"src": mid, "dst": target, "kind": "imports"})
    return {"nodes": nodes, "edges": edges}


# Convention key -> (fact title, fact body). Only repo-wide conventions (held by many
# modules) become facts — high signal, not per-file noise.
_CONV_FACT = {
    "stdlib-only": (
        "This repo's core is stdlib-only",
        "Core modules import no third-party packages (verified by checking every import "
        "against the standard library). Keep new core code stdlib-only; isolate third-party "
        "deps like FastAPI to their own module.",
    ),
    "future-annotations": (
        "Modules open with `from __future__ import annotations`",
        "Every module starts with `from __future__ import annotations`. Add it to new modules.",
    ),
    "argparse-cli": (
        "CLIs use argparse + a `main(argv)` entrypoint",
        "Command-line tools parse args with argparse and expose `def main(argv=None) -> int`, "
        "run via `raise SystemExit(main())`.",
    ),
    "never-raises": (
        "Hot-path modules never raise",
        "recall.py / facts.py and the ingest/consolidate paths never raise to the caller — they "
        "return '' or a safe default on failure. Preserve that contract.",
    ),
}


def convention_facts(graph: dict) -> list[tuple[str, str]]:
    """Repo-wide conventions (held by a third+ of modules) as (title, body) facts."""
    held: dict[str, list[str]] = {}
    for node in graph["nodes"]:
        for conv in node["conventions"]:
            held.setdefault(conv, []).append(node["id"])
    threshold = max(2, len(graph["nodes"]) // 3)
    out = []
    for conv, mods in held.items():
        if conv in _CONV_FACT and len(mods) >= threshold:
            title, body = _CONV_FACT[conv]
            ev = ", ".join(mods[:6]) + ("…" if len(mods) > 6 else "")
            out.append((title, f"{body} (proven in {len(mods)} modules: {ev})"))
    return out


def render_text(graph: dict) -> str:
    lines = [f"codebase graph — {len(graph['nodes'])} modules, {len(graph['edges'])} import edges", ""]
    out_edges: dict[str, list[str]] = {}
    for e in graph["edges"]:
        out_edges.setdefault(e["src"], []).append(e["dst"])
    for n in graph["nodes"]:
        conv = ("  [" + ", ".join(n["conventions"]) + "]") if n["conventions"] else ""
        lines.append(f"{n['id']}{conv}")
        for dst in sorted(out_edges.get(n["id"], [])):
            lines.append(f"    └─imports─▶ {dst}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build a deterministic graph of a codebase (no LLM).")
    p.add_argument("--root", default=".", help="repo root to scan")
    p.add_argument("--json", action="store_true", help="emit graph as JSON")
    p.add_argument("--write", action="store_true", help="write proven conventions into a skill's memory")
    p.add_argument("--skill", default="python-patterns", help="skill to tag written facts with")
    args = p.parse_args(argv)
    graph = build_graph(args.root)
    if args.write:
        import facts  # local; keeps codegraph itself stdlib-only

        paths = [
            facts.write_fact([args.skill], title, body, source="codebase", ref="codegraph", topic="code-style")
            for title, body in convention_facts(graph)
        ]
        print(f"wrote {len(paths)} convention facts into skill '{args.skill}':")
        for pth in paths:
            print("  " + pth)
        return 0
    print(json.dumps(graph, indent=2) if args.json else render_text(graph))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
