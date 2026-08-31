"""Layout application service for Fabrivium Phase 3A."""

from __future__ import annotations

from pydantic import ValidationError

from app.models.factory import Factory, Machine
from app.models.layout import FactoryLayout, MachinePhysicalEnvelope, MachinePlacement


# Typed errors

class LayoutError(Exception):
    """Base class for all errors raised by the layout service."""


class MachineNotFoundForLayoutError(LayoutError):
    """Raised when a placement references a machine_id absent from the Factory."""


class DuplicatePlacementError(LayoutError):
    """Raised when placing a machine that already has a placement in this layout."""


class PlacementNotFoundError(LayoutError):
    """Raised when moving/rotating/removing a placement that doesn't exist."""


class InvalidCoordinateError(LayoutError):
    """Raised when a coordinate or rotation value is not a finite number."""


# Envelope helper

def machine_envelope(machine: Machine) -> MachinePhysicalEnvelope:
    """Build a full ``MachinePhysicalEnvelope`` for *machine*."""
    extras = machine.physical_envelope
    return MachinePhysicalEnvelope(
        width=machine.width,
        length=machine.length,
        height=extras.height if extras is not None else None,
        safety_clearance_front=extras.safety_clearance_front if extras is not None else 0.0,
        safety_clearance_back=extras.safety_clearance_back if extras is not None else 0.0,
        safety_clearance_left=extras.safety_clearance_left if extras is not None else 0.0,
        safety_clearance_right=extras.safety_clearance_right if extras is not None else 0.0,
    )


# Lookups

def _machine_exists(factory: Factory, machine_id: str) -> bool:
    return any(m.id == machine_id for m in factory.machines)


def get_placement(layout: FactoryLayout, machine_id: str) -> MachinePlacement | None:
    """Return *machine_id*'s placement, or None if it has none."""
    return next((p for p in layout.placements if p.machine_id == machine_id), None)


def _build_placement(machine_id: str, x: float, y: float, z: float, rotation_deg: float) -> MachinePlacement:
    try:
        return MachinePlacement(machine_id=machine_id, x=x, y=y, z=z, rotation_deg=rotation_deg)
    except ValidationError as exc:
        raise InvalidCoordinateError(str(exc)) from exc


def _replace_placement(layout: FactoryLayout, new_placement: MachinePlacement) -> FactoryLayout:
    new_placements = [
        new_placement if p.machine_id == new_placement.machine_id else p
        for p in layout.placements
    ]
    return layout.model_copy(update={"placements": new_placements})


# Public operations

def create_layout(factory: Factory) -> FactoryLayout:
    """Create an empty ``FactoryLayout`` sized to *factory*'s floor
    dimensions, with no placements or zones yet."""
    return FactoryLayout(factory_width=factory.width, factory_length=factory.length)


def place_machine(
    factory: Factory,
    layout: FactoryLayout,
    machine_id: str,
    x: float,
    y: float,
    rotation_deg: float = 0.0,
    z: float = 0.0,
) -> FactoryLayout:
    """
    Add a new placement for *machine_id*. Returns a NEW ``FactoryLayout`` — *layout* is
    never mutated.
    """
    if not _machine_exists(factory, machine_id):
        raise MachineNotFoundForLayoutError(
            f"Machine '{machine_id}' does not exist in factory '{factory.name}'."
        )
    if get_placement(layout, machine_id) is not None:
        raise DuplicatePlacementError(
            f"Machine '{machine_id}' already has a placement in this layout."
        )

    new_placement = _build_placement(machine_id, x, y, z, rotation_deg)
    return layout.model_copy(update={"placements": [*layout.placements, new_placement]})


def move_machine(
    layout: FactoryLayout, machine_id: str, x: float, y: float, z: float | None = None
) -> FactoryLayout:
    """
    Update the x/y (and optionally z) of *machine_id*'s existing placement, preserving
    its current rotation.
    """
    existing = get_placement(layout, machine_id)
    if existing is None:
        raise PlacementNotFoundError(f"Machine '{machine_id}' has no placement to move.")

    new_placement = _build_placement(
        machine_id, x, y, existing.z if z is None else z, existing.rotation_deg
    )
    return _replace_placement(layout, new_placement)


def rotate_machine(layout: FactoryLayout, machine_id: str, rotation_deg: float) -> FactoryLayout:
    """
    Update *machine_id*'s rotation, preserving its current position. Returns a NEW
    ``FactoryLayout``.
    """
    existing = get_placement(layout, machine_id)
    if existing is None:
        raise PlacementNotFoundError(f"Machine '{machine_id}' has no placement to rotate.")

    new_placement = _build_placement(machine_id, existing.x, existing.y, existing.z, rotation_deg)
    return _replace_placement(layout, new_placement)


def remove_placement(layout: FactoryLayout, machine_id: str) -> FactoryLayout:
    """Remove *machine_id*'s placement. Returns a NEW ``FactoryLayout``."""
    if get_placement(layout, machine_id) is None:
        raise PlacementNotFoundError(f"Machine '{machine_id}' has no placement to remove.")

    new_placements = [p for p in layout.placements if p.machine_id != machine_id]
    return layout.model_copy(update={"placements": new_placements})
