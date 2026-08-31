"""Engineer edits to a proposed manufacturing process."""

from __future__ import annotations

from app.models.process_draft import (
    ManufacturingProcessDraft,
    OperationStatus,
    ProposedOperation,
)
from app.models.product import FactStatus


class OperationNotFound(ValueError):
    """The draft has no operation with that id."""


def _index_of(draft: ManufacturingProcessDraft, operation_id: str) -> int:
    for index, operation in enumerate(draft.operations):
        if operation.id == operation_id:
            return index
    raise OperationNotFound(f"This process has no operation '{operation_id}'.")


def _with_operations(
    draft: ManufacturingProcessDraft, operations: list[ProposedOperation]
) -> ManufacturingProcessDraft:
    return draft.model_copy(update={"operations": operations})


def add_operation(
    draft: ManufacturingProcessDraft,
    *,
    name: str,
    process_type: str,
    basis: str,
    source_fact_keys: list[str] | None = None,
    repeated_operations: int | None = None,
    position: int | None = None,
) -> ManufacturingProcessDraft:
    """Insert an operation the engineer decided the process needs."""
    if not name.strip():
        raise ValueError("An operation needs a name.")
    if not basis.strip():
        raise ValueError("An operation needs a stated reason for existing.")
    if repeated_operations is not None and repeated_operations < 1:
        raise ValueError("An operation that happens fewer than once is not an operation.")

    operation = ProposedOperation(
        id=f"op-engineer-{len(draft.operations) + 1}-{process_type}",
        process_type=process_type,
        name=name.strip(),
        description=basis.strip(),
        repeated_operations=repeated_operations,
        basis=basis.strip(),
        source_fact_keys=list(source_fact_keys or []),
        evidence=[],
        # STATED, not RULE_DERIVED: a person decided this.
        fact_status=FactStatus.STATED,
        confidence="HIGH",
        status=OperationStatus.ACCEPTED,
    )

    operations = list(draft.operations)
    if position is None or position >= len(operations):
        operations.append(operation)
    else:
        operations.insert(max(0, position), operation)
    return _with_operations(draft, operations)


def edit_operation(
    draft: ManufacturingProcessDraft,
    operation_id: str,
    *,
    name: str | None = None,
    process_type: str | None = None,
    repeated_operations: int | None = None,
    description: str | None = None,
    basis: str | None = None,
) -> ManufacturingProcessDraft:
    """Change an operation, recording that a person changed it."""
    index = _index_of(draft, operation_id)
    current = draft.operations[index]

    if repeated_operations is not None and repeated_operations < 1:
        raise ValueError("An operation that happens fewer than once is not an operation.")

    update: dict = {
        "status": OperationStatus.MODIFIED,
        "fact_status": FactStatus.ENGINEER_VERIFIED,
    }
    if name is not None:
        if not name.strip():
            raise ValueError("An operation needs a name.")
        update["name"] = name.strip()
    if process_type is not None:
        update["process_type"] = process_type
    if repeated_operations is not None:
        update["repeated_operations"] = repeated_operations
    if description is not None:
        # What the operation DOES, as opposed to why it exists.
        update["description"] = description.strip()
    if basis is not None:
        if not basis.strip():
            raise ValueError("An operation needs a stated reason for existing.")
        # The engineer's reason replaces the planner's, and says so.
        update["basis"] = f"{basis.strip()} (engineer edit; originally: {current.basis})"

    operations = list(draft.operations)
    operations[index] = current.model_copy(update=update)
    return _with_operations(draft, operations)


def remove_operation(
    draft: ManufacturingProcessDraft, operation_id: str
) -> ManufacturingProcessDraft:
    """Reject an operation."""
    index = _index_of(draft, operation_id)
    operations = list(draft.operations)
    operations[index] = operations[index].reject()
    return _with_operations(draft, operations)


def link_to_requirements(
    draft: ManufacturingProcessDraft, operation_id: str, fact_keys: list[str]
) -> ManufacturingProcessDraft:
    """Record that an existing operation satisfies these source requirements."""
    index = _index_of(draft, operation_id)
    current = draft.operations[index]

    merged = list(current.source_fact_keys)
    for key in fact_keys:
        if key not in merged:
            merged.append(key)

    if merged == current.source_fact_keys:
        return draft

    added = [k for k in fact_keys if k not in current.source_fact_keys]
    operations = list(draft.operations)
    operations[index] = current.model_copy(
        update={
            "source_fact_keys": merged,
            "basis": (
                f"{current.basis} Engineer linked this operation to: {', '.join(added)}."
            ),
            "status": OperationStatus.MODIFIED,
            "fact_status": FactStatus.ENGINEER_VERIFIED,
        }
    )
    return _with_operations(draft, operations)


def restore_operation(
    draft: ManufacturingProcessDraft, operation_id: str
) -> ManufacturingProcessDraft:
    """Bring a rejected operation back into the route."""
    index = _index_of(draft, operation_id)
    current = draft.operations[index]
    if current.status is not OperationStatus.REJECTED:
        return draft

    operations = list(draft.operations)
    operations[index] = current.model_copy(
        update={
            "status": OperationStatus.MODIFIED,
            "fact_status": FactStatus.ENGINEER_VERIFIED,
            "basis": f"{current.basis} Restored by the engineer after being rejected.",
        }
    )
    return _with_operations(draft, operations)


def unlink_requirements(
    draft: ManufacturingProcessDraft, operation_id: str, fact_keys: list[str]
) -> ManufacturingProcessDraft:
    """Record that an operation does NOT satisfy these source requirements."""
    index = _index_of(draft, operation_id)
    current = draft.operations[index]

    remaining = [key for key in current.source_fact_keys if key not in fact_keys]
    if remaining == list(current.source_fact_keys):
        return draft

    removed = [key for key in current.source_fact_keys if key in fact_keys]
    operations = list(draft.operations)
    operations[index] = current.model_copy(
        update={
            "source_fact_keys": remaining,
            "basis": (
                f"{current.basis} Engineer unlinked this operation from: "
                f"{', '.join(removed)}."
            ),
            "status": OperationStatus.MODIFIED,
            "fact_status": FactStatus.ENGINEER_VERIFIED,
        }
    )
    return _with_operations(draft, operations)


def reorder_operations(
    draft: ManufacturingProcessDraft, ordered_ids: list[str]
) -> ManufacturingProcessDraft:
    """Put the route in the order the engineer chose."""
    current_ids = [operation.id for operation in draft.operations]
    if sorted(ordered_ids) != sorted(current_ids):
        raise ValueError(
            "A reorder must list every operation exactly once — "
            "adding or removing one is a different edit."
        )

    by_id = {operation.id: operation for operation in draft.operations}
    return _with_operations(draft, [by_id[op_id] for op_id in ordered_ids])
