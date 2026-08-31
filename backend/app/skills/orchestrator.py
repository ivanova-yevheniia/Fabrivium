"""The engineering skill orchestrator."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from app.skills.contract import SkillContext, SkillResult, SkillStatus, SkillTraceEntry
from app.skills.runtime import record_execution
from app.skills.registry import SkillNotFound, SkillRegistry, default_registry


@dataclass(frozen=True)
class WorkflowStage:
    """One step of a declared workflow."""

    # The skill to run.
    skill_id: str
    # Builds this stage's payload from what earlier stages produced.
    payload: Callable[[dict[str, Any]], Any | None]
    # Where to file this stage's data in the shared bag.
    output_key: str
    required: bool = True
    # Pin an exact skill version. Left None, the newest enabled one runs.
    version: str | None = None


@dataclass(frozen=True)
class WorkflowDefinition:
    """A product path, written down."""

    id: str
    name: str
    description: str
    stages: tuple[WorkflowStage, ...]

    @property
    def skill_ids(self) -> tuple[str, ...]:
        return tuple(stage.skill_id for stage in self.stages)


@dataclass
class WorkflowRun:
    """Everything one execution produced."""

    workflow_id: str
    # Stage output by key. What a caller reads.
    outputs: dict[str, Any] = field(default_factory=dict)
    # One entry per stage attempted, in order.
    trace: list[SkillTraceEntry] = field(default_factory=list)
    # Per-stage results, keyed by skill id, for callers wanting detail.
    results: dict[str, SkillResult] = field(default_factory=dict)
    # Skill versions actually used — the reproducibility record.
    versions: dict[str, str] = field(default_factory=dict)
    # Everything every stage said it still needs.
    unresolved_inputs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stopped_at: str | None = None
    stopped_because: str | None = None
    elapsed_seconds: float = 0.0

    @property
    def completed(self) -> bool:
        return self.stopped_at is None

    @property
    def status(self) -> SkillStatus:
        """The run's own status, by the same rules a skill uses."""
        if self.stopped_at is not None:
            failed = self.results.get(self.stopped_at)
            if failed is not None and failed.status is SkillStatus.FAILED:
                return SkillStatus.FAILED
            return SkillStatus.BLOCKED
        if self.unresolved_inputs:
            return SkillStatus.PARTIAL
        return SkillStatus.SUCCESS

    def summary(self) -> str:
        lines = [f"{self.workflow_id}: {self.status.value}"]
        for index, entry in enumerate(self.trace, 1):
            lines.append(
                f"  {index} {entry.skill}@{entry.version} — {entry.status.value}"
            )
            lines.append(f"      {entry.detail}")
        if self.stopped_because:
            lines.append(f"  stopped: {self.stopped_because}")
        return "\n".join(lines)


class EngineeringSkillOrchestrator:
    """Runs declared workflows. Decides nothing."""

    def __init__(self, registry: SkillRegistry | None = None) -> None:
        self._registry = registry or default_registry

    def validate(self, workflow: WorkflowDefinition) -> list[str]:
        """Problems that would stop this workflow before it starts."""
        problems: list[str] = []
        seen: set[str] = set()
        for stage in workflow.stages:
            try:
                definition = self._registry.definition(stage.skill_id, stage.version)
            except SkillNotFound as exc:
                problems.append(str(exc))
                continue
            for prerequisite in definition.prerequisites:
                if prerequisite not in seen and prerequisite in workflow.skill_ids:
                    problems.append(
                        f"'{stage.skill_id}' runs before its prerequisite '{prerequisite}'."
                    )
                elif prerequisite not in workflow.skill_ids:
                    missing = self._registry.missing_prerequisites(stage.skill_id, stage.version)
                    if prerequisite in missing:
                        problems.append(
                            f"'{stage.skill_id}' needs '{prerequisite}', which is not registered "
                            f"and not part of this workflow."
                        )
            seen.add(stage.skill_id)
        return problems

    def run(
        self,
        workflow: WorkflowDefinition,
        seed: dict[str, Any] | None = None,
        context: SkillContext | None = None,
    ) -> WorkflowRun:
        """Execute a workflow."""
        run = WorkflowRun(workflow_id=workflow.id)
        bag: dict[str, Any] = dict(seed or {})
        run.outputs.update(bag)
        ctx = context or SkillContext()
        started = time.perf_counter()

        problems = self.validate(workflow)
        if problems:
            run.stopped_at = workflow.stages[0].skill_id if workflow.stages else workflow.id
            run.stopped_because = "; ".join(problems)
            run.warnings.extend(problems)
            run.elapsed_seconds = time.perf_counter() - started
            return run

        for stage in workflow.stages:
            payload = stage.payload(bag)
            if payload is None:
                # The workflow itself says this stage does not apply here.
                run.trace.append(
                    SkillTraceEntry(
                        skill=stage.skill_id,
                        version=self._registry.definition(stage.skill_id, stage.version).version,
                        status=SkillStatus.NOT_APPLICABLE,
                        detail="Skipped: the workflow supplied no input for this stage.",
                    )
                )
                continue

            skill = self._registry.get(stage.skill_id, stage.version)
            definition = skill.definition
            run.versions[definition.id] = definition.version

            result = skill.execute(payload, ctx)
            # A workflow stage is a skill execution like any other, so it
            # belongs in the request's skill trace. Without this, an endpoint
            # backed by a workflow would report no skills at all.
            record_execution(
                skill.definition.id, skill.definition.version, result.status.value
            )
            run.results[definition.id] = result
            run.trace.extend(result.trace)
            run.warnings.extend(result.warnings)
            run.unresolved_inputs.extend(result.unresolved_inputs)

            if result.usable:
                # The capability's own object, unchanged.
                bag[stage.output_key] = result.data
                run.outputs[stage.output_key] = result.data
                continue

            if stage.required:
                run.stopped_at = definition.id
                run.stopped_because = (
                    result.warnings[0]
                    if result.warnings
                    else f"{definition.id} returned {result.status.value}."
                )
                break
            # Optional stage: recorded and stepped over, never worked around.

        run.elapsed_seconds = time.perf_counter() - started
        return run
