"""The skill runtime boundary."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from app.skills.contract import SkillContext, SkillResult, SkillStatus
from app.skills.registry import SkillNotFound, SkillRegistry, default_registry

# Skills executed while handling the current request, in order.
_current_execution: ContextVar[list[str] | None] = ContextVar(
    "factorymind_skill_execution", default=None
)


def begin_request_trace() -> list[str]:
    """Start collecting skill executions for one request."""
    entries: list[str] = []
    _current_execution.set(entries)
    return entries


def record_execution(skill_id: str, version: str, status: str) -> None:
    entries = _current_execution.get()
    if entries is not None and len(entries) < 24:
        # Identifiers and an outcome.
        entries.append(f"{skill_id}@{version}:{status}")


class SkillExecutionError(RuntimeError):
    """A skill could not produce a result the caller can use."""

    def __init__(
        self,
        message: str,
        *,
        status: SkillStatus,
        skill_id: str,
        unresolved_inputs: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.skill_id = skill_id
        self.unresolved_inputs = unresolved_inputs or []


@dataclass
class ExecutionRecord:
    """Runtime metadata for one skill execution."""

    skill_id: str
    version: str
    status: str
    elapsed_seconds: float = 0.0
    simulations_run: int = 0
    # One sentence from the skill's own trace. Never a payload dump.
    detail: str = ""


@dataclass
class RuntimeTrace:
    """What the runtime executed, most recent last."""

    records: list[ExecutionRecord] = field(default_factory=list)

    @property
    def simulations_run(self) -> int:
        return sum(record.simulations_run for record in self.records)

    def add(self, result: SkillResult, skill_id: str, version: str) -> None:
        entry = result.trace[-1] if result.trace else None
        self.records.append(
            ExecutionRecord(
                skill_id=skill_id,
                version=version,
                status=result.status.value,
                elapsed_seconds=entry.elapsed_seconds if entry else 0.0,
                simulations_run=entry.simulations_run if entry else 0,
                detail=entry.detail if entry else "",
            )
        )


class SkillRuntime:
    """The one way an endpoint reaches a skill."""

    def __init__(self, registry: SkillRegistry | None = None) -> None:
        self._registry = registry or default_registry

    @property
    def registry(self) -> SkillRegistry:
        return self._registry

    def execute(
        self,
        skill_id: str,
        payload: Any,
        *,
        version: str | None = None,
        context: SkillContext | None = None,
        trace: RuntimeTrace | None = None,
    ) -> SkillResult:
        """Run one skill and return its result, whatever the status."""
        skill = self._registry.get(skill_id, version)  # SkillNotFound if absent
        definition = skill.definition
        result = skill.execute(payload, context or SkillContext())
        if trace is not None:
            trace.add(result, definition.id, definition.version)
        record_execution(definition.id, definition.version, result.status.value)
        return result

    def unwrap(
        self,
        skill_id: str,
        payload: Any,
        *,
        version: str | None = None,
        context: SkillContext | None = None,
        trace: RuntimeTrace | None = None,
        allow_partial: bool = True,
    ) -> Any:
        """Run one skill and return its DATA, or raise."""
        result = self.execute(
            skill_id, payload, version=version, context=context, trace=trace
        )

        if result.status is SkillStatus.SUCCESS:
            return result.data
        if result.status is SkillStatus.PARTIAL and allow_partial:
            return result.data

        raise SkillExecutionError(
            result.warnings[0] if result.warnings else f"{skill_id} returned {result.status.value}.",
            status=result.status,
            skill_id=skill_id,
            unresolved_inputs=result.unresolved_inputs,
        )


# The process-wide runtime.
_runtime: SkillRuntime | None = None


def get_runtime() -> SkillRuntime:
    global _runtime
    if _runtime is None:
        from app.skills.builtin import register_builtin_skills

        _runtime = SkillRuntime(register_builtin_skills(default_registry))
    return _runtime


__all__ = [
    "ExecutionRecord",
    "begin_request_trace",
    "record_execution",
    "RuntimeTrace",
    "SkillExecutionError",
    "SkillNotFound",
    "SkillRuntime",
    "get_runtime",
]
