"""
Yunaki Skills — Interface Contracts
All components implement these interfaces. Subagents: implement your module
against these exact signatures. Do not change method names, param types, or
return types without updating this file.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel

# ─── Skill Schema ───────────────────────────────────────────────────────────


class Granularity(str, Enum):
    TASK_LEVEL = "task-level"
    EVENT_DRIVEN = "event-driven"


class TriggerType(str, Enum):
    PATTERN = "pattern"
    SEMANTIC = "semantic"


class TriggerMatchOn(str, Enum):
    TASK_DESCRIPTION = "task_description"
    OBSERVATION = "observation"
    ERROR = "error"


class SkillStatus(str, Enum):
    """Governance lifecycle of a skill.

    draft → pending_review → approved → active is the forward path. rejected is
    a terminal state. Only APPROVED and ACTIVE skills are retrieved for agent
    injection (see governance.retrievable_statuses).
    """

    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    ACTIVE = "active"
    REJECTED = "rejected"


class Trigger(BaseModel):
    type: TriggerType
    patterns: list[str] = []  # regex patterns for event-driven
    query: str = ""  # semantic search query for task-level
    match_on: TriggerMatchOn = TriggerMatchOn.TASK_DESCRIPTION


class Provenance(BaseModel):
    created_from: str = ""  # trace_id
    task: str = ""  # original task description
    iteration: int = 1
    parent_skill: Optional[str] = None  # ID of parent if evolved
    merged_from: list[str] = []  # IDs of skills merged into this one
    evolved_at: str = ""  # ISO8601 timestamp


class Skill(BaseModel):
    """The canonical skill object. Stored in MongoDB as-is."""

    id: str  # e.g. "skill_dep_injection"
    title: str  # human-readable
    granularity: Granularity
    version: str = "0.1"  # semver-like
    score: float = 50.0  # 0-100 effectiveness score
    trigger: Trigger
    when_to_apply: str  # natural language description
    instructions: list[str]  # 2-10 actionable steps
    provenance: Provenance = Provenance()
    status: SkillStatus = SkillStatus.ACTIVE  # governance lifecycle state
    repo_id: Optional[str] = None  # namespace owner; None = global skill bank


# ─── Skill Bank Interface ──────────────────────────────────────────────────


class SkillBank:
    """MongoDB-backed skill storage. Implemented by subagent A."""

    def add(self, skill: Skill) -> str:
        """Add a new skill. Returns the skill ID."""
        ...

    def get(self, skill_id: str) -> Optional[Skill]:
        """Get a skill by ID."""
        ...

    def update(self, skill_id: str, skill: Skill) -> bool:
        """Update an existing skill (evolution). Returns success."""
        ...

    def search_semantic(self, query: str, top_k: int = 3) -> list[Skill]:
        """Semantic search for task-level skills. Uses local embeddings."""
        ...

    def search_pattern(self, text: str) -> list[Skill]:
        """Pattern match for event-driven skills. Regex on text."""
        ...

    def list_all(self) -> list[Skill]:
        """List all skills (for dashboard)."""
        ...

    def get_history(self, skill_id: str) -> list[Skill]:
        """Get version history of a skill (for evolution timeline)."""
        ...


# ─── Skill Extractor Interface ─────────────────────────────────────────────


class SkillExtractor:
    """Gemini-powered skill extraction from traces. Subagent A."""

    def extract(self, task_description: str, trace: str, eval_result: "EvalResult") -> Optional[Skill]:
        """Analyze a failed task execution and extract a reusable skill.
        Returns None if no skill can be extracted."""
        ...


# ─── Skill Evolver Interface ───────────────────────────────────────────────


class SkillEvolver:
    """Gemini-powered skill evolution. Subagent A."""

    def evolve(self, skill: Skill, new_trace: str, new_eval: "EvalResult") -> Skill:
        """Evolve an existing skill based on new execution evidence."""
        ...


# ─── Skill Retriever Interface ─────────────────────────────────────────────


class SkillRetriever:
    """Combines semantic + pattern skill retrieval. Subagent A."""

    def retrieve_for_task(self, task_description: str) -> list[Skill]:
        """Get task-level skills via semantic search."""
        ...

    def check_triggers(self, agent_output: str) -> list[Skill]:
        """Get event-driven skills whose patterns match the output."""
        ...

    def inject_skills(self, system_prompt: str, skills: list[Skill]) -> str:
        """Stuff skills into the system prompt. Pure string concat."""
        ...


# ─── Eval Result ────────────────────────────────────────────────────────────


class EvalResult(BaseModel):
    """Result of evaluating an agent's output."""

    passed: bool
    score: float  # 0-100
    details: str = ""  # human-readable explanation
    test_output: str = ""  # raw test/linter output
    tasks_passed: int = 0
    tasks_total: int = 0


# ─── Eval Scorer Interface ─────────────────────────────────────────────────


class EvalScorer:
    """Scores agent output against the target repo. Subagent B."""

    def evaluate(self, task_description: str, repo_path: str) -> EvalResult:
        """Run tests + linter against the target repo. Return score."""
        ...


# ─── Agent Client Interface ────────────────────────────────────────────────


class AgentClient:
    """Executes coding tasks. Subagent B."""

    def run_task(self, task_description: str, skills: list[Skill], repo_path: str) -> str:
        """Run a coding task with injected skills. Returns the agent's trace."""
        ...


# ─── Task Result ────────────────────────────────────────────────────────────


class TaskResult(BaseModel):
    """Complete result of a task run through the evolution loop."""

    task_description: str
    score_before: float  # score before skill injection
    score_after: float  # score after skill injection
    skills_used: list[str]  # skill IDs that were injected
    skills_created: list[str]  # skill IDs that were extracted
    skills_evolved: list[str]  # skill IDs that were evolved
    iterations: int = 0
    trace: str = ""


# ─── Task Runner Interface ─────────────────────────────────────────────────


class TaskRunner:
    """Orchestrates the full evolution loop. Subagent B."""

    def run(self, task_description: str, max_iterations: int = 3) -> TaskResult:
        """Run a task through the full skill evolution loop."""
        ...
