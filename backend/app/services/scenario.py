"""Scenario application service for Fabrivium Phase 2A."""

from __future__ import annotations

from pydantic import ValidationError

from app.models.equipment import EquipmentLifecycleStatus
from app.models.factory import Factory, Machine
from app.models.scenario import (
    AddParallelMachineAction,
    ChangeBufferCapacityAction,
    ChangeDemandAction,
    ChangeMachineCapacityAction,
    ChangeMachineCycleTimeAction,
    ChangeOperatorCapacityAction,
    ChangeShiftConfigurationAction,
    RemoveMachineAction,
    Scenario,
    ScenarioAction,
)


# Typed errors

class ScenarioError(Exception):
    """Base class for all errors raised while applying a scenario."""


class MachineNotFoundError(ScenarioError):
    """Raised when an action references a machine_id that does not exist."""


class ProductNotFoundError(ScenarioError):
    """Raised when an action references a product_id that does not exist."""


class MachineRemovalError(ScenarioError):
    """Raised when removing a machine would leave a required process
    uncovered by any remaining compatible machine."""


class InvalidScenarioResultError(ScenarioError):
    """Raised when the candidate Factory fails normal domain validation
    after an action has been applied."""


# Public entry point

def apply_scenario(factory: Factory, scenario: Scenario) -> Factory:
    """
    Apply *scenario*'s actions, in order, to *factory* and return the resulting
    candidate ``Factory``.
    """
    candidate = factory
    for action in scenario.actions:
        candidate = _apply_action(candidate, action)
        candidate = _revalidate(candidate)
    return candidate


def _revalidate(factory: Factory) -> Factory:
    """Re-run full Pydantic validation on *factory*."""
    try:
        return Factory.model_validate(factory.model_dump())
    except ValidationError as exc:
        raise InvalidScenarioResultError(
            f"Resulting factory failed domain validation: {exc}"
        ) from exc



def _apply_action(factory: Factory, action: ScenarioAction) -> Factory:
    if isinstance(action, AddParallelMachineAction):
        return _add_parallel_machine(factory, action)
    if isinstance(action, ChangeMachineCycleTimeAction):
        return _change_machine_cycle_time(factory, action)
    if isinstance(action, ChangeMachineCapacityAction):
        return _change_machine_capacity(factory, action)
    if isinstance(action, ChangeDemandAction):
        return _change_demand(factory, action)
    if isinstance(action, RemoveMachineAction):
        return _remove_machine(factory, action)
    if isinstance(action, ChangeShiftConfigurationAction):
        return _change_shift_configuration(factory, action)
    if isinstance(action, ChangeOperatorCapacityAction):
        return _change_operator_capacity(factory, action)
    if isinstance(action, ChangeBufferCapacityAction):
        return _change_buffer_capacity(factory, action)
    raise ScenarioError(f"Unsupported scenario action: {action!r}")  # pragma: no cover


# Phase 8A handlers — shifts / operators / buffers
#
# Each returns a NEW Factory via model_copy, exactly like every handler
# before them; the baseline is never touched (Phase 2A's immutability
# guarantee, unchanged).


class BufferNotFoundError(ScenarioError):
    """Raised when an action references a buffer_id that does not exist."""


def _change_shift_configuration(factory: Factory, action: ChangeShiftConfigurationAction) -> Factory:
    """
    Apply a new shift configuration, carrying over whichever field the action did not
    specify.
    """
    shifts = action.shifts_per_day if action.shifts_per_day is not None else factory.shifts_per_day
    hours = action.hours_per_shift if action.hours_per_shift is not None else factory.hours_per_shift

    total_hours = shifts * hours
    if total_hours > 24.0:
        raise ScenarioError(
            f"CHANGE_SHIFT_CONFIGURATION would schedule {shifts} x {hours:g} h = "
            f"{total_hours:g} production hours in a 24-hour day."
        )

    return factory.model_copy(update={"shifts_per_day": shifts, "hours_per_shift": hours})


def _change_operator_capacity(factory: Factory, action: ChangeOperatorCapacityAction) -> Factory:
    return factory.model_copy(update={"operators_available": action.operators_available})


def _change_buffer_capacity(factory: Factory, action: ChangeBufferCapacityAction) -> Factory:
    known = {b.id for b in factory.buffers}
    if action.buffer_id not in known:
        raise BufferNotFoundError(
            f"Buffer '{action.buffer_id}' not found in factory '{factory.name}'. "
            f"Available IDs: {sorted(known)}"
        )
    new_buffers = [
        b.model_copy(update={"capacity": action.new_capacity}) if b.id == action.buffer_id else b
        for b in factory.buffers
    ]
    return factory.model_copy(update={"buffers": new_buffers})


# Lookups

def _find_machine(factory: Factory, machine_id: str) -> Machine:
    for machine in factory.machines:
        if machine.id == machine_id:
            return machine
    raise MachineNotFoundError(
        f"Machine '{machine_id}' does not exist in factory '{factory.name}'. "
        f"Available IDs: {sorted(m.id for m in factory.machines)}"
    )


def _find_product_id(factory: Factory, product_id: str) -> None:
    if not any(p.id == product_id for p in factory.products):
        raise ProductNotFoundError(
            f"Product '{product_id}' does not exist in factory '{factory.name}'. "
            f"Available IDs: {sorted(p.id for p in factory.products)}"
        )


# ADD_PARALLEL_MACHINE

def _add_parallel_machine(factory: Factory, action: AddParallelMachineAction) -> Factory:
    source = _find_machine(factory, action.machine_id)

    existing_ids = {m.id for m in factory.machines}
    existing_names = {m.name for m in factory.machines}

    n = 1
    while True:
        new_id = f"{source.id}-parallel-{n}"
        new_name = f"{source.name} (Parallel {n})"
        if new_id not in existing_ids and new_name not in existing_names:
            break
        n += 1

    # Independent position: offset along X by the source machine's own
    # footprint plus a fixed clearance gap, so the clone never overlaps
    # the source machine's coordinates.
    clearance = 1.0

    # Flatten clone-of-clone chains: a clone's parallel_of_machine_id always
    # points at the ultimate reference machine, not at an intermediate clone,
    # so machine_pool.resolve_pool never has to walk more than one hop.
    root_id = source.parallel_of_machine_id or source.id

    # A freshly-cloned parallel machine doesn't physically exist yet — it's a what-if
    # candidate — regardless of the source's own lifecycle_status.
    new_machine = source.model_copy(
        update={
            "id": new_id,
            "name": new_name,
            "position_x": source.position_x + source.width + clearance,
            "position_y": source.position_y,
            "parallel_of_machine_id": root_id,
            "lifecycle_status": EquipmentLifecycleStatus.PURCHASE_CANDIDATE,
        }
    )

    return factory.model_copy(update={"machines": [*factory.machines, new_machine]})


# CHANGE_MACHINE_CYCLE_TIME

def _change_machine_cycle_time(
    factory: Factory, action: ChangeMachineCycleTimeAction
) -> Factory:
    """
    Update the machine's own cycle_time AND every ProcessStep.cycle_time that references
    it.
    """
    _find_machine(factory, action.machine_id)

    new_machines = [
        m.model_copy(update={"cycle_time": action.cycle_time})
        if m.id == action.machine_id
        else m
        for m in factory.machines
    ]
    new_products = [
        p.model_copy(
            update={
                "route": [
                    step.model_copy(update={"cycle_time": action.cycle_time})
                    if step.machine_id == action.machine_id
                    else step
                    for step in p.route
                ]
            }
        )
        for p in factory.products
    ]
    return factory.model_copy(update={"machines": new_machines, "products": new_products})


# CHANGE_MACHINE_CAPACITY

def _change_machine_capacity(
    factory: Factory, action: ChangeMachineCapacityAction
) -> Factory:
    _find_machine(factory, action.machine_id)
    new_machines = [
        m.model_copy(update={"capacity": action.capacity})
        if m.id == action.machine_id
        else m
        for m in factory.machines
    ]
    return factory.model_copy(update={"machines": new_machines})


# CHANGE_DEMAND

def _change_demand(factory: Factory, action: ChangeDemandAction) -> Factory:
    _find_product_id(factory, action.product_id)
    new_products = [
        p.model_copy(update={"demand_per_day": action.demand_per_day})
        if p.id == action.product_id
        else p
        for p in factory.products
    ]
    return factory.model_copy(update={"products": new_products})


# REMOVE_MACHINE

def _remove_machine(factory: Factory, action: RemoveMachineAction) -> Factory:
    target = _find_machine(factory, action.machine_id)

    remaining = [m for m in factory.machines if m.id != action.machine_id]
    remaining_process_types = {m.process_type for m in remaining}

    unsatisfied: list[str] = []
    for product in factory.products:
        for step in product.route:
            if step.machine_id != action.machine_id:
                continue
            if target.process_type not in remaining_process_types:
                unsatisfied.append(
                    f"product '{product.id}' step '{step.name}' requires "
                    f"process '{target.process_type}'"
                )

    if unsatisfied:
        raise MachineRemovalError(
            f"Cannot remove machine '{action.machine_id}': no compatible "
            f"machine (process_type='{target.process_type}') would remain "
            f"to serve: {'; '.join(unsatisfied)}."
        )

    return factory.model_copy(update={"machines": remaining})


# Human-readable rendering


def describe_scenario_action(action: ScenarioAction) -> str:
    """One deterministic, human-readable sentence fragment for *action*."""
    machine_id = getattr(action, "machine_id", None)

    if action.action_type == "ADD_PARALLEL_MACHINE":
        return f"Add parallel machine at {machine_id}"
    if action.action_type == "CHANGE_MACHINE_CYCLE_TIME":
        return f"Change cycle time at {machine_id} to {action.cycle_time:g}s"
    if action.action_type == "CHANGE_MACHINE_CAPACITY":
        return f"Change capacity at {machine_id} to {action.capacity}"
    if action.action_type == "REMOVE_MACHINE":
        return f"Remove machine {machine_id}"
    if action.action_type == "CHANGE_DEMAND":
        return f"Change demand for {getattr(action, 'product_id', None)} to {action.demand_per_day:g}/day"

    # -- Phase 8A levers.
    if action.action_type == "CHANGE_SHIFT_CONFIGURATION":
        parts = []
        if action.shifts_per_day is not None:
            parts.append(f"{action.shifts_per_day} shift(s)/day")
        if action.hours_per_shift is not None:
            parts.append(f"{action.hours_per_shift:g} h/shift")
        return f"Change shift configuration to {', '.join(parts)}"
    if action.action_type == "CHANGE_OPERATOR_CAPACITY":
        return f"Change operator capacity to {action.operators_available}"
    if action.action_type == "CHANGE_BUFFER_CAPACITY":
        return f"Change buffer {action.buffer_id} capacity to {action.new_capacity}"

    return action.action_type  # pragma: no cover - defensive
