"""Manufacturing process draft — Phase 19."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator

from app.models.product import EvidenceRef, FactStatus


class OperationStatus(str, Enum):
    """Where one proposed operation stands with the engineer."""

    # Proposed by the planning skill. Nothing is built on it yet.
    PROPOSED = "PROPOSED"
    # The engineer accepted it, possibly after editing.
    ACCEPTED = "ACCEPTED"
    # The engineer rejected it.
    REJECTED = "REJECTED"
    # The engineer changed what the planner proposed and stands behind the result.
    MODIFIED = "MODIFIED"


class ProposedOperation(BaseModel):
    """One manufacturing operation the product appears to require."""

    model_config = {"frozen": True}

    id: str = Field(..., min_length=1)
    #: Must match the vocabulary `concept_builder` recognises ("assembly",
    #: "screwdriving", "inspection", "packaging", …). A process type outside
    #: it converts fine but finds no reference bands in Phase 18B, so the
    #: planner sticks to known families and says when it cannot.
    process_type: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str = ""

    #: How many times the characteristic action happens per unit, when the
    #: product facts say. Feeds Phase 18B's decomposition directly.
    repeated_operations: int | None = Field(None, gt=0)

    # Why this operation was proposed, in one sentence.
    basis: str = Field(..., min_length=1)
    #: Which product facts implied it — the "why does this station exist?"
    #: answer, by key.
    source_fact_keys: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)

    #: How the operation was derived while proposed: RULE_DERIVED for the
    #: deterministic planner, AI_INFERRED when a model proposed it. Becomes
    #: ENGINEER_VERIFIED once accepted, and never before.
    fact_status: FactStatus = FactStatus.AI_INFERRED
    confidence: str = "MEDIUM"
    status: OperationStatus = OperationStatus.PROPOSED

    @model_validator(mode="after")
    def _accepted_means_verified(self) -> "ProposedOperation":
        # Acceptance is what turns an inference into something an engineer
        # stands behind. The two must not drift apart.
        unreviewed = {FactStatus.AI_INFERRED, FactStatus.RULE_DERIVED}
        decided = {OperationStatus.ACCEPTED, OperationStatus.MODIFIED}
        if self.status in decided and self.fact_status in unreviewed:
            raise ValueError(
                f"Operation '{self.id}' is ACCEPTED but still marked "
                f"{self.fact_status.value}."
            )
        return self

    # `model_copy` does NOT re-run validators, and this codebase copies
    # models constantly. A validator alone therefore guards construction
    # and nothing else. These two methods set both fields together, so the
    # inconsistent state cannot be produced by the normal route at all.

    def accept(self) -> "ProposedOperation":
        """The engineer stands behind this operation."""
        return self.model_copy(
            update={
                "status": OperationStatus.ACCEPTED,
                "fact_status": FactStatus.ENGINEER_VERIFIED,
            }
        )

    def reject(self) -> "ProposedOperation":
        """Kept in the draft rather than deleted, so the decision stays visible."""
        return self.model_copy(update={"status": OperationStatus.REJECTED})


class ManufacturingProcessDraft(BaseModel):
    """The proposed route, in order, before it becomes a concept."""

    model_config = {"frozen": True}

    product_name: str = Field("Product", min_length=1)
    operations: list[ProposedOperation] = Field(default_factory=list)

    #: How the proposal was produced: "PROCESS_PLANNING_SKILL" always, plus
    #: the method underneath — "LANGUAGE_MODEL" or "LOCAL_RULES".
    planner: str = "PROCESS_PLANNING_SKILL"
    method: str = "LOCAL_RULES"
    model_name: str | None = None

    # What the planner could not decide, phrased as questions.
    open_questions: list[str] = Field(default_factory=list)

    @property
    def accepted(self) -> list[ProposedOperation]:
        """Operations the engineer stands behind."""
        return [
            op
            for op in self.operations
            if op.status in (OperationStatus.ACCEPTED, OperationStatus.MODIFIED)
        ]

    @property
    def pending(self) -> list[ProposedOperation]:
        return [op for op in self.operations if op.status is OperationStatus.PROPOSED]

    @property
    def ready_to_build(self) -> bool:
        """A concept needs at least one accepted operation and no pending ones."""
        return bool(self.accepted) and not self.pending
