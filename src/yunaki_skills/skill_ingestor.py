"""Universal skill ingestion.

Accepts a skill in ANY format (.md, .json, .yaml, .txt, or already-canonical
Yunaki JSON) and normalizes it into the canonical Skill schema. The contract:
no matter how malformed the input, `ingest` always returns a valid Skill — any
information that could not be mapped is reported via `warnings`.

Format-specific strategies:
  - json  : flexible key mapping onto the Skill schema (handles aliases)
  - yaml  : parse then map like json
  - md    : H1/H2 headers -> title, bullet points -> instructions, first
            paragraph -> when_to_apply
  - txt   : Gemini extracts structure from freeform text; a deterministic
            heuristic is used when Gemini is unavailable

The semantic trigger query is derived from the content with the same
bag-of-tokens approach the SkillBank uses for hash embeddings, so an ingested
skill is immediately retrievable by semantic search.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections import Counter
from typing import Any, Optional

from yunaki_skills import skill_llm
from yunaki_skills.interfaces import (
    Granularity,
    Provenance,
    Skill,
    SkillIngestor,
    SkillIngestResult,
    Trigger,
    TriggerMatchOn,
    TriggerType,
)

logger = logging.getLogger(__name__)

# Tokens with no retrieval signal — dropped when deriving a semantic query.
_STOPWORDS = frozenset(
    """
    a an and are as at be by for from has have how if in into is it its of on or
    that the their then there these this to use using when where which with you
    your should always never must can will do does step steps skill apply
    """.split()
)

_MAX_QUERY_TOKENS = 12
_MIN_INSTRUCTIONS = 1

# Flexible key aliases for structured (json/yaml) ingestion.
_TITLE_KEYS = ("title", "name", "skill", "heading")
_WHEN_KEYS = ("when_to_apply", "when", "applies_to", "context", "description", "summary")
_INSTRUCTION_KEYS = ("instructions", "steps", "rules", "guidelines", "actions", "checklist")
_QUERY_KEYS = ("query", "trigger_query", "intent", "topic")


class SkillIngestor(SkillIngestor):
    """Normalizes arbitrary skill files into canonical Skill objects."""

    # ── format detection ─────────────────────────────────────────────────

    def detect_format(self, content: str, filename: str) -> str:
        """Detect the source format from the filename, then the content."""
        ext = (filename or "").lower().rsplit(".", 1)[-1] if "." in (filename or "") else ""
        if ext in {"md", "markdown"}:
            return "md"
        if ext == "json":
            return "json"
        if ext in {"yaml", "yml"}:
            return "yaml"
        if ext in {"txt", "text"}:
            return "txt"

        # No decisive extension — sniff the content.
        stripped = (content or "").strip()
        if not stripped:
            return "txt"
        if stripped[0] in "{[":
            try:
                json.loads(stripped)
                return "json"
            except (json.JSONDecodeError, ValueError):
                pass
        if stripped.startswith("#") or re.search(r"^#{1,6}\s", stripped, re.MULTILINE):
            return "md"
        if re.search(r"^[A-Za-z0-9_-]+:\s", stripped, re.MULTILINE):
            return "yaml"
        return "txt"

    # ── public entry point ───────────────────────────────────────────────

    def ingest(self, content: str, filename: str, org_id: Optional[str] = None) -> SkillIngestResult:
        """Ingest arbitrary content and normalize it into a Skill."""
        content = content or ""
        fmt = self.detect_format(content, filename)
        warnings: list[str] = []

        try:
            if fmt == "json":
                skill = self._from_json(content, warnings)
            elif fmt == "yaml":
                skill = self._from_yaml(content, warnings)
            elif fmt == "md":
                skill = self._from_markdown(content, warnings)
            else:  # txt
                skill = self._from_text(content, warnings)
        except Exception as e:  # never let ingestion hard-fail
            logger.warning("Ingestion of %s (%s) failed: %s — using raw fallback", filename, fmt, e)
            warnings.append(f"parser error: {e}")
            skill = self._raw_fallback(content)

        # Stamp universal metadata that the parsers don't own.
        skill = skill.model_copy(
            update={
                "org_id": org_id,
                "source_format": fmt,
                "source_uri": filename or None,
            }
        )
        return SkillIngestResult(skill=skill, format_detected=fmt, warnings=warnings)

    # ── JSON / YAML ──────────────────────────────────────────────────────

    def _from_json(self, content: str, warnings: list[str]) -> Skill:
        data = json.loads(content)
        if not isinstance(data, dict):
            warnings.append("json root was not an object — wrapped as freeform")
            return self._from_text(content, warnings)
        return self._skill_from_mapping(data, content, warnings)

    def _from_yaml(self, content: str, warnings: list[str]) -> Skill:
        try:
            import yaml
        except ImportError:
            warnings.append("PyYAML unavailable — treating YAML as freeform text")
            return self._from_text(content, warnings)
        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            warnings.append("yaml root was not a mapping — wrapped as freeform")
            return self._from_text(content, warnings)
        return self._skill_from_mapping(data, content, warnings)

    def _skill_from_mapping(self, data: dict[str, Any], raw: str, warnings: list[str]) -> Skill:
        """Map a parsed dict onto the Skill schema, tolerant of key naming.

        If the dict already looks like a canonical Yunaki skill (has a Trigger
        sub-object and instructions), it is constructed directly.
        """
        # Fast path: already a canonical Yunaki skill document.
        if isinstance(data.get("trigger"), dict) and data.get("instructions") is not None:
            try:
                data.setdefault("id", self._gen_id(data.get("title", "")))
                return Skill(**data)
            except Exception as e:
                warnings.append(f"canonical parse failed ({e}) — remapping fields")

        title = _first_str(data, _TITLE_KEYS) or "Imported Skill"
        when = _first_str(data, _WHEN_KEYS) or f"When working on: {title}"
        instructions = _coerce_instructions(_first_present(data, _INSTRUCTION_KEYS))
        if not instructions:
            warnings.append("no instructions found — derived from content")
            instructions = self._derive_instructions(raw)
        query = _first_str(data, _QUERY_KEYS) or self._semantic_query(f"{title} {when} {raw}")

        return self._build_skill(
            skill_id=str(data.get("id") or self._gen_id(title)),
            title=title,
            when_to_apply=when,
            instructions=instructions,
            query=query,
            version=str(data.get("version", "0.1")),
            score=_coerce_float(data.get("score"), 50.0),
        )

    # ── Markdown ─────────────────────────────────────────────────────────

    def _from_markdown(self, content: str, warnings: list[str]) -> Skill:
        lines = content.splitlines()

        title = ""
        for line in lines:
            m = re.match(r"^#{1,6}\s+(.*)", line.strip())
            if m:
                title = m.group(1).strip()
                break
        if not title:
            warnings.append("no markdown header found — using first non-empty line as title")
            title = next((ln.strip() for ln in lines if ln.strip()), "Imported Skill")

        # Bullet points (-, *, +, or "1.") become instructions.
        instructions: list[str] = []
        for line in lines:
            m = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)", line)
            if m and m.group(1).strip():
                instructions.append(m.group(1).strip())
        if not instructions:
            warnings.append("no bullet points found — derived instructions from prose")
            instructions = self._derive_instructions(content)

        # First non-header, non-bullet paragraph -> when_to_apply.
        when = ""
        for line in lines:
            s = line.strip()
            if not s or s.startswith("#") or re.match(r"^\s*(?:[-*+]|\d+[.)])\s+", line):
                continue
            when = s
            break
        if not when:
            when = f"When working on: {title}"

        return self._build_skill(
            skill_id=self._gen_id(title),
            title=title,
            when_to_apply=when,
            instructions=instructions,
            query=self._semantic_query(content),
        )

    # ── Freeform text (Gemini, with deterministic fallback) ──────────────

    def _from_text(self, content: str, warnings: list[str]) -> Skill:
        structured = self._gemini_structure(content)
        if structured is not None:
            title = structured.get("title") or "Imported Skill"
            return self._build_skill(
                skill_id=self._gen_id(title),
                title=title,
                when_to_apply=structured.get("when_to_apply") or f"When working on: {title}",
                instructions=_coerce_instructions(structured.get("instructions")) or self._derive_instructions(content),
                query=structured.get("query") or self._semantic_query(content),
            )

        warnings.append("structured extraction unavailable — used heuristic text parsing")
        return self._raw_fallback(content)

    def _gemini_structure(self, content: str) -> Optional[dict[str, Any]]:
        """Ask the skill model to extract {title, when_to_apply, instructions, query}.

        Routes through ``skill_llm.complete_json`` (host CLI by default, no Gemini
        key required). Returns None if the model is unavailable or the response
        can't be parsed, so the caller falls back to a deterministic heuristic.
        """
        prompt = (
            "Extract a reusable coding skill from the text below. Respond with ONLY "
            'a JSON object: {"title": str, "when_to_apply": str, '
            '"instructions": [str, ...], "query": str}. instructions must be '
            "2-10 concrete, actionable steps.\n\nTEXT:\n" + content[:6000]
        )
        try:
            text = (skill_llm.complete_json(prompt) or "").strip()
            if not text:
                logger.warning("Skill-model returned empty response for ingestion structuring")
                return None
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except Exception as e:
            logger.warning("Skill-model text structuring failed: %s", e)
            return None

    # ── shared helpers ───────────────────────────────────────────────────

    def _raw_fallback(self, content: str) -> Skill:
        """Last-resort skill built purely from heuristics. Always valid."""
        title = self._derive_title(content)
        return self._build_skill(
            skill_id=self._gen_id(title),
            title=title,
            when_to_apply=self._derive_when(content, title),
            instructions=self._derive_instructions(content),
            query=self._semantic_query(content),
        )

    def _build_skill(
        self,
        skill_id: str,
        title: str,
        when_to_apply: str,
        instructions: list[str],
        query: str,
        version: str = "0.1",
        score: float = 50.0,
    ) -> Skill:
        instructions = [i for i in (instructions or []) if i.strip()]
        if len(instructions) < _MIN_INSTRUCTIONS:
            instructions = [f"Apply the guidance: {title}"]
        return Skill(
            id=skill_id,
            title=title.strip() or "Imported Skill",
            granularity=Granularity.TASK_LEVEL,
            version=version,
            score=score,
            trigger=Trigger(
                type=TriggerType.SEMANTIC,
                query=query,
                match_on=TriggerMatchOn.TASK_DESCRIPTION,
            ),
            when_to_apply=when_to_apply.strip(),
            instructions=instructions,
            provenance=Provenance(created_from="ingest", task=title, iteration=1),
        )

    @staticmethod
    def _gen_id(title: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", (title or "").lower()).strip("_")
        slug = slug[:32] or uuid.uuid4().hex[:8]
        return f"skill_{slug}"

    @staticmethod
    def _derive_title(content: str) -> str:
        for line in content.splitlines():
            s = line.strip().lstrip("#").strip()
            if s:
                return s[:80]
        return "Imported Skill"

    @staticmethod
    def _derive_when(content: str, title: str) -> str:
        paras = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
        if paras:
            return paras[0][:300]
        return f"When working on: {title}"

    @staticmethod
    def _derive_instructions(content: str) -> list[str]:
        """Pull actionable lines from prose: bullets first, else sentences."""
        bullets = [
            m.group(1).strip()
            for line in content.splitlines()
            if (m := re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)", line)) and m.group(1).strip()
        ]
        if bullets:
            return bullets[:10]
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", content) if len(s.strip()) > 12]
        if sentences:
            return sentences[:6]
        return ["Apply the described approach to the task"]

    def _semantic_query(self, content: str) -> str:
        """Derive a retrieval query from the most salient content tokens.

        Bag-of-tokens with stopword removal and frequency ranking — the same
        token model the SkillBank hashes into embeddings, so the query and the
        corpus share a vocabulary.
        """
        tokens = [t for t in re.findall(r"[a-z0-9]+", content.lower()) if t not in _STOPWORDS and len(t) > 2]
        if not tokens:
            return content.strip()[:120]
        ranked = [tok for tok, _ in Counter(tokens).most_common(_MAX_QUERY_TOKENS)]
        return " ".join(ranked)


# ── module-level coercion helpers ──────────────────────────────────────────


def _first_present(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in data and data[k] is not None:
            return data[k]
    return None


def _first_str(data: dict[str, Any], keys: tuple[str, ...]) -> str:
    val = _first_present(data, keys)
    if isinstance(val, str):
        return val.strip()
    if val is not None:
        return str(val).strip()
    return ""


def _coerce_instructions(val: Any) -> list[str]:
    if val is None:
        return []
    if isinstance(val, str):
        # Split a block of text into lines / bullets.
        parts = [p.strip("-*+ \t").strip() for p in val.splitlines() if p.strip()]
        return [p for p in parts if p]
    if isinstance(val, (list, tuple)):
        out = []
        for item in val:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif isinstance(item, dict):
                # e.g. {"step": "..."} or {"text": "..."}
                for key in ("step", "text", "instruction", "action", "description"):
                    if isinstance(item.get(key), str):
                        out.append(item[key].strip())
                        break
        return out
    return []


def _coerce_float(val: Any, default: float) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default
