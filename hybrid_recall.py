#!/usr/bin/env python3
"""Buildable spec: hybrid recall over a heterogeneous memory (code graph + PRs + conversations).

One unified node set, three retrievers that each see what the others miss, fused with
Reciprocal Rank Fusion, deduped by (topic, source), and budgeted:

    graph   — retrieval by CONNECTION (start at the files you touch, walk edges).
              Wording-independent: finds the PR/conversation attached to a file even
              when the text shares no terms with the query.
    bm25    — retrieval by EXACT TERM (error codes, symbol names, file paths).
    dense   — retrieval by MEANING (PRs/conversations, synonyms). PLUGGABLE and the
              ONLY non-deterministic/optional piece: inject an embed fn (local model or
              API). Omit it and recall stays fully deterministic + offline.

Edges are a join over provenance you already capture (same file / same topic / explicit
links), so no new storage shape is required. Vectors are computed at WRITE time; the only
per-call embed is the query. Everything here is stdlib-only and importable.
"""

from __future__ import annotations

import dataclasses
import math
import re
from collections import defaultdict
from collections.abc import Sequence
from typing import Protocol


@dataclasses.dataclass(frozen=True)
class MemoryNode:
    """One retrievable memory item, whatever its source."""

    id: str
    title: str
    text: str
    source: str = "codebase"  # codebase | pr | conversation | test | manual
    ref: str = ""  # PR #, sha, thread id
    topic: str = ""  # what it's about (often a file or convention) — a graph key
    file: str = ""  # code entity it attaches to — a graph anchor
    created: str = ""
    vector: tuple[float, ...] = ()  # dense embedding, set at WRITE time (optional)
    edges: tuple[str, ...] = ()  # explicit links to other node ids


class EmbeddingFn(Protocol):
    def __call__(self, text: str) -> Sequence[float]: ...


def _tokens(s: str) -> list[str]:
    return re.findall(r"\w+", s.lower())


# ---- retriever 1: graph (by connection) -------------------------------------------------
def _adjacency(nodes: list[MemoryNode]) -> dict[str, set[str]]:
    """Neighbours = nodes sharing a file or topic, plus explicit edges. (Provenance join.)"""
    by_key: dict[str, set[str]] = defaultdict(set)
    for n in nodes:
        for key in (n.file, n.topic):
            if key:
                by_key[key].add(n.id)
    adj: dict[str, set[str]] = defaultdict(set)
    for ids in by_key.values():
        for a in ids:
            adj[a] |= ids - {a}
    for n in nodes:
        for e in n.edges:
            adj[n.id].add(e)
            adj[e].add(n.id)
    return adj


def graph_retrieve(nodes: list[MemoryNode], seed_files: set[str], hops: int = 2) -> list[str]:
    """BFS from the working-set files; returns node ids closest-first."""
    adj = _adjacency(nodes)
    seeds = {n.id for n in nodes if (n.file in seed_files or n.topic in seed_files)}
    dist: dict[str, int] = {s: 0 for s in seeds}
    frontier, d = set(seeds), 0
    while frontier and d < hops:
        nxt: set[str] = set()
        for nid in frontier:
            for m in adj.get(nid, ()):
                if m not in dist:
                    dist[m] = d + 1
                    nxt.add(m)
        frontier, d = nxt, d + 1
    return sorted(dist, key=lambda i: dist[i])


# ---- retriever 2: BM25 (by exact term) --------------------------------------------------
def bm25_retrieve(
    nodes: list[MemoryNode], query: str, k1: float = 1.5, b: float = 0.75
) -> list[str]:
    terms = _tokens(query)
    if not terms or not nodes:
        return []
    docs = [(n.id, _tokens(f"{n.title} {n.title} {n.text}")) for n in nodes]  # title weighted x2
    n_docs = len(docs)
    avgdl = (sum(len(d) for _, d in docs) / n_docs) or 1.0
    df: dict[str, int] = defaultdict(int)
    for _, d in docs:
        for t in set(d):
            df[t] += 1
    uniq = set(terms)
    scored: list[tuple[str, float]] = []
    for nid, d in docs:
        dl = len(d) or 1
        s = 0.0
        for t in uniq:
            tf = d.count(t)
            if not tf:
                continue
            idf = math.log(1 + (n_docs - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))
        if s > 0:
            scored.append((nid, s))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [i for i, _ in scored]


# ---- retriever 3: dense (by meaning) — pluggable, optional ------------------------------
def _cos(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def dense_retrieve(nodes: list[MemoryNode], query: str, embed: EmbeddingFn | None) -> list[str]:
    if embed is None:
        return []  # deterministic/offline mode: dense path disabled
    q = embed(query)
    scored = [(n.id, _cos(q, n.vector)) for n in nodes if n.vector]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [i for i, _ in scored]


# ---- fusion: Reciprocal Rank Fusion (no score calibration needed) -----------------------
def rrf_fuse(rankings: list[tuple[list[str], float]], k: int = 60) -> list[str]:
    score: dict[str, float] = defaultdict(float)
    for ranking, weight in rankings:
        for rank, nid in enumerate(ranking):
            score[nid] += weight / (k + rank + 1)
    return sorted(score, key=lambda i: score[i], reverse=True)


def recall_hybrid(
    nodes: list[MemoryNode],
    *,
    working_files: Sequence[str] = (),
    lens: str = "",
    terms: str = "",
    embed: EmbeddingFn | None = None,
    hops: int = 2,
    budget: int = 8,
) -> list[MemoryNode]:
    """Retrieve the right slice for a skill at invocation. Graph is weighted slightly above
    the text retrievers because locality is the strongest signal for 'what am I touching'."""
    idx = {n.id: n for n in nodes}
    q = f"{lens} {terms}".strip()
    candidates = [
        (graph_retrieve(nodes, set(working_files), hops), 1.2),
        (dense_retrieve(nodes, q, embed), 1.0),
        (bm25_retrieve(nodes, q), 1.0),
    ]
    fused = rrf_fuse([(r, w) for r, w in candidates if r])
    out: list[MemoryNode] = []
    seen: set[tuple[str, str]] = set()  # dedup key (topic, source): diverse sources, no repeats
    for nid in fused:
        n = idx[nid]
        key = (n.topic or n.id, n.source)
        if key in seen:
            continue
        seen.add(key)
        out.append(n)
        if len(out) >= budget:
            break
    return out


if __name__ == "__main__":
    demo = [
        MemoryNode(
            "c1",
            "validation errors return 422",
            "bad body returns 422 not 400",
            "codebase",
            topic="routes.py",
            file="routes.py",
        ),
        MemoryNode(
            "pr42",
            "decide 422 for invalid bodies",
            "we return 422 for unprocessable input",
            "pr",
            ref="#42",
            topic="routes.py",
            file="routes.py",
        ),
        MemoryNode(
            "cv9",
            "why not 400 for bad input",
            "thread: REST semantics, unprocessable entity, keep the client fix small",
            "conversation",
            ref="thread-9",
            topic="routes.py",
            file="routes.py",
        ),
        MemoryNode(
            "c2",
            "tokens compared in constant time",
            "auth compares tokens constant-time",
            "codebase",
            topic="auth.py",
            file="auth.py",
        ),
        MemoryNode(
            "c3",
            "cache ttl is 60s",
            "redis entries expire after 60s",
            "codebase",
            topic="cache.py",
            file="cache.py",
        ),
        MemoryNode(
            "c5",
            "general validation notes",
            "validation validation general guidance",
            "codebase",
            topic="util.py",
            file="util.py",
        ),
    ]
    lens = "how should the API handle invalid request bodies"
    print(f"query: editing routes.py · lens={lens!r} · terms='422'\n")
    print("graph :", graph_retrieve(demo, {"routes.py"}))
    print("bm25  :", bm25_retrieve(demo, f"{lens} 422"))
    print("dense : []  (no embed fn — deterministic/offline mode)\n")
    got = recall_hybrid(demo, working_files=["routes.py"], lens=lens, terms="422")
    print("hybrid (cv9 = a conversation with no query-term overlap, pulled in by the graph):")
    for n in got:
        print(f"  [{n.source:12}] {n.title}")
