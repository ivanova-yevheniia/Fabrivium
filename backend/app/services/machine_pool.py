"""Machine service-pool resolution for Fabrivium Phase 2B."""

from __future__ import annotations

from app.models.factory import Factory, Machine


class MachinePoolError(Exception):
    """
    Raised when a service pool cannot be resolved for a requested reference machine_id
    (i.e.
    """


def _root_id(machine_index: dict[str, Machine], machine_id: str) -> str:
    """Resolve *machine_id* to its pool's reference (root) machine id."""
    seen: set[str] = set()
    current = machine_id
    while True:
        machine = machine_index.get(current)
        if machine is None or not machine.parallel_of_machine_id:
            return current
        if current in seen:  # pragma: no cover - defensive cycle guard
            return current
        seen.add(current)
        current = machine.parallel_of_machine_id


def resolve_pool(factory: Factory, reference_machine_id: str) -> list[Machine]:
    """Return the deterministic service pool for *reference_machine_id*."""
    machine_index = {m.id: m for m in factory.machines}
    root = _root_id(machine_index, reference_machine_id)

    pool = [
        m for m in factory.machines
        if _root_id(machine_index, m.id) == root
    ]
    if not pool:
        raise MachinePoolError(
            f"No machine resolves to pool root '{root}' "
            f"(requested reference '{reference_machine_id}') in factory "
            f"'{factory.name}'."
        )
    return sorted(pool, key=lambda m: m.id)
