"""The engineering skill contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generic, TypeVar

from app.llm import LLMProvider


class SkillCategory(str, Enum):
    """What kind of engineering work a skill does."""

    # Turning unstructured input into structured facts.
    UNDERSTANDING = "UNDERSTANDING"
    # Proposing what should be built or done.
    PLANNING = "PLANNING"
    # Producing a number nobody has measured yet.
    ESTIMATION = "ESTIMATION"
    # Checking that something holds.
    VALIDATION = "VALIDATION"
    # Running the deterministic model.
    SIMULATION = "SIMULATION"
    # Generating and comparing alternatives.
    OPTIMIZATION = "OPTIMIZATION"
    # Finding real-world options and data.
    DISCOVERY = "DISCOVERY"
    # Talking to an external engineering tool.
    INTEGRATION = "INTEGRATION"


class SkillStatus(str, Enum):
    """How a skill execution ended."""

    # Ran, produced everything it promised, nothing left unresolved.
    SUCCESS = "SUCCESS"
    # Ran and produced something useful, but unresolved inputs remain.
    PARTIAL = "PARTIAL"
    # Could not run because engineering information is missing.
    BLOCKED = "BLOCKED"
    # This skill does not apply to this input. Also not an error.
    NOT_APPLICABLE = "NOT_APPLICABLE"
    # Technical failure — an exception, an unreachable tool, a bug.
    FAILED = "FAILED"


class ExecutionMode(str, Enum):
    """How a skill obtains its answer when it has more than one route."""

    # Purely deterministic. No model involved, ever.
    DETERMINISTIC = "DETERMINISTIC"
    # Prefers a model, falls back to a deterministic path on any failure.
    MODEL_WITH_FALLBACK = "MODEL_WITH_FALLBACK"
    # Requires a model; BLOCKED when none is available.
    MODEL_REQUIRED = "MODEL_REQUIRED"


class SideEffect(str, Enum):
    """What a skill changes outside its own return value."""

    NONE = "NONE"
    # Reads a bundled dataset or document from disk.
    READS_LOCAL_DATA = "READS_LOCAL_DATA"
    # Writes a file the user will keep.
    WRITES_FILE = "WRITES_FILE"
    # Drives an external application.
    CONTROLS_EXTERNAL_TOOL = "CONTROLS_EXTERNAL_TOOL"
    # Calls a network service.
    NETWORK_CALL = "NETWORK_CALL"


@dataclass(frozen=True)
class SkillDefinition:
    """Everything about a skill that can be known without running it."""

    id: str
    version: str
    name: str
    description: str
    category: SkillCategory

    # What this skill can do, as stable strings the registry can search.
    capabilities: tuple[str, ...] = ()

    # Skill ids whose output this one consumes.
    prerequisites: tuple[str, ...] = ()

    # The domain types this skill accepts and returns, by name.
    input_types: tuple[str, ...] = ()
    output_types: tuple[str, ...] = ()

    # Media a skill can consume, for the multimodal extension point.
    supported_inputs: tuple[str, ...] = ()

    deterministic: bool = True
    uses_llm: bool = False
    uses_external_data: bool = False
    side_effects: tuple[SideEffect, ...] = (SideEffect.NONE,)
    execution_mode: ExecutionMode = ExecutionMode.DETERMINISTIC

    # Provenance values this skill may legitimately produce.
    supported_provenance: tuple[str, ...] = ()

    enabled: bool = True

    # Namespace and owner exist for future company skills.
    namespace: str = "factorymind"
    owner: str = "Fabrivium"

    # Higher runs first where order is otherwise undefined.
    priority: int = 50

    @property
    def qualified_id(self) -> str:
        """`namespace/id@version` — what a trace records."""
        return f"{self.namespace}/{self.id}@{self.version}"

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("A skill needs an id.")
        if not self.version or not self.version.strip():
            raise ValueError(f"Skill '{self.id}' needs a version — traces record it.")
        if self.uses_llm and self.execution_mode is ExecutionMode.DETERMINISTIC:
            raise ValueError(
                f"Skill '{self.id}' declares uses_llm but a DETERMINISTIC execution mode. "
                f"One of the two is wrong, and a reader cannot tell which."
            )
        if not self.uses_llm and self.execution_mode is not ExecutionMode.DETERMINISTIC:
            raise ValueError(
                f"Skill '{self.id}' declares execution mode {self.execution_mode.value} "
                f"without uses_llm."
            )


@dataclass(frozen=True)
class SkillTraceEntry:
    """One line of the record of what happened."""

    skill: str
    version: str
    status: SkillStatus
    # One sentence an engineer can read.
    detail: str
    # Wall time, so the Architecture view can show what a run cost.
    elapsed_seconds: float = 0.0
    # Simulations this step consumed, where it consumed any.
    simulations_run: int = 0


T = TypeVar("T")


@dataclass(frozen=True)
class SkillResult(Generic[T]):
    """What a skill execution produced, and how far it got."""

    status: SkillStatus
    data: T | None = None

    # Where the output came from, in the existing vocabulary.
    provenance: dict[str, str] = field(default_factory=dict)
    # Citations, quotes, source documents — whatever the capability already produces.
    evidence: list[Any] = field(default_factory=list)
    # The capability's own confidence, when it has one.
    confidence: str | None = None

    warnings: list[str] = field(default_factory=list)
    # What the skill still needs. Non-empty forbids SUCCESS.
    unresolved_inputs: list[str] = field(default_factory=list)
    trace: list[SkillTraceEntry] = field(default_factory=list)
    # Files or models produced, by path or id.
    artifacts: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status is SkillStatus.SUCCESS and self.unresolved_inputs:
            raise ValueError(
                f"A result with unresolved inputs {self.unresolved_inputs} cannot be SUCCESS. "
                f"Use PARTIAL — the caller has to be able to see what is still missing."
            )
        if self.status in (SkillStatus.SUCCESS, SkillStatus.PARTIAL) and self.data is None:
            raise ValueError(
                f"Status {self.status.value} promises output, but data is None."
            )

    @property
    def usable(self) -> bool:
        """True when there is real output, complete or not."""
        return self.status in (SkillStatus.SUCCESS, SkillStatus.PARTIAL) and self.data is not None


@dataclass
class SkillContext:
    """What a skill may reach for beyond its own arguments."""

    # None means no model.
    llm_provider: LLMProvider | None = None
    # Per-skill settings, by skill id.
    settings: dict[str, dict[str, Any]] = field(default_factory=dict)

    def settings_for(self, skill_id: str) -> dict[str, Any]:
        return self.settings.get(skill_id, {})


class Skill(ABC, Generic[T]):
    """One engineering capability, declared and callable."""

    @property
    @abstractmethod
    def definition(self) -> SkillDefinition:
        """Everything knowable without running. Constant per instance."""

    @abstractmethod
    def execute(self, payload: Any, context: SkillContext) -> SkillResult[T]:
        """Run the capability."""

    # Helpers, so every adapter reports failure the same way

    def _blocked(self, reason: str, *, missing: list[str] | None = None) -> SkillResult[T]:
        return SkillResult(
            status=SkillStatus.BLOCKED,
            warnings=[reason],
            unresolved_inputs=missing or [],
            trace=[self._entry(SkillStatus.BLOCKED, reason)],
        )

    def _failed(self, reason: str) -> SkillResult[T]:
        return SkillResult(
            status=SkillStatus.FAILED,
            warnings=[reason],
            trace=[self._entry(SkillStatus.FAILED, reason)],
        )

    def _not_applicable(self, reason: str) -> SkillResult[T]:
        return SkillResult(
            status=SkillStatus.NOT_APPLICABLE,
            warnings=[reason],
            trace=[self._entry(SkillStatus.NOT_APPLICABLE, reason)],
        )

    def _entry(
        self,
        status: SkillStatus,
        detail: str,
        *,
        elapsed_seconds: float = 0.0,
        simulations_run: int = 0,
    ) -> SkillTraceEntry:
        return SkillTraceEntry(
            skill=self.definition.id,
            version=self.definition.version,
            status=status,
            detail=detail,
            elapsed_seconds=elapsed_seconds,
            simulations_run=simulations_run,
        )
