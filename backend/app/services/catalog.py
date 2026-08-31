"""Equipment catalog and CAD/proxy ingestion service for Fabrivium Phase 3C."""

from __future__ import annotations

from app.models.catalog import (
    EquipmentAvailability,
    EquipmentCatalogEntry,
    EquipmentModelRequest,
    EquipmentReadiness,
    EquipmentSourceType,
    ExternalEquipmentReference,
    ModelRequestStatus,
)
from app.models.equipment import (
    EquipmentAsset,
    EquipmentAssetStatus,
    EquipmentAssetType,
    EquipmentLifecycleStatus,
    create_proxy_asset,
)
from app.models.factory import Factory, Machine, MachineEnvelopeExtras


# Typed errors

class CatalogError(Exception):
    """Base class for all errors raised by the catalog service."""


class DuplicateCatalogIdError(CatalogError):
    """Raised when registering a catalog_id that already exists."""


class CatalogEntryNotFoundError(CatalogError):
    """Raised when looking up/removing/updating a catalog_id that doesn't exist."""


class DuplicateModelRequestIdError(CatalogError):
    """Raised when creating a model request with a request_id already in use."""


class ModelRequestNotFoundError(CatalogError):
    """Raised when looking up/updating a request_id that doesn't exist."""


class MissingCycleTimeError(CatalogError):
    """
    Raised when building a Machine from a catalog entry that has no resolvable
    cycle_time (neither on the entry nor passed explicitly).
    """


class MachineNotFoundInFactoryError(CatalogError):
    """Raised by ``replace_machine_asset`` when machine_id doesn't exist."""


# EquipmentCatalog

class EquipmentCatalog:
    """In-memory, deterministic registry of ``EquipmentCatalogEntry``."""

    def __init__(self) -> None:
        self._entries: dict[str, EquipmentCatalogEntry] = {}

    def register_entry(self, entry: EquipmentCatalogEntry) -> EquipmentCatalogEntry:
        """Register *entry*. Raises ``DuplicateCatalogIdError`` if
        ``entry.catalog_id`` is already registered."""
        if entry.catalog_id in self._entries:
            raise DuplicateCatalogIdError(
                f"Catalog entry '{entry.catalog_id}' is already registered."
            )
        self._entries[entry.catalog_id] = entry
        return entry

    def get_entry(self, catalog_id: str) -> EquipmentCatalogEntry | None:
        """Return the entry for *catalog_id*, or None if not registered."""
        return self._entries.get(catalog_id)

    def list_entries(self) -> list[EquipmentCatalogEntry]:
        """Return every registered entry, in registration order."""
        return list(self._entries.values())

    def search(
        self,
        *,
        process_type: str | None = None,
        manufacturer: str | None = None,
        model_number: str | None = None,
        text: str | None = None,
    ) -> list[EquipmentCatalogEntry]:
        """
        Return every entry matching ALL given filters (AND semantics), in registration
        order.
        """
        results = self.list_entries()
        if process_type is not None:
            results = [e for e in results if e.process_type == process_type]
        if manufacturer is not None:
            results = [e for e in results if e.manufacturer == manufacturer]
        if model_number is not None:
            results = [e for e in results if e.model_number == model_number]
        if text is not None:
            needle = text.lower()
            results = [
                e for e in results
                if needle in e.name.lower() or (e.description is not None and needle in e.description.lower())
            ]
        return results

    def remove_entry(self, catalog_id: str) -> None:
        """Remove *catalog_id*. Raises ``CatalogEntryNotFoundError`` if
        not registered."""
        if catalog_id not in self._entries:
            raise CatalogEntryNotFoundError(f"Catalog entry '{catalog_id}' does not exist.")
        del self._entries[catalog_id]

    def update_asset(self, catalog_id: str, new_asset: EquipmentAsset) -> EquipmentCatalogEntry:
        """
        Replace *catalog_id*'s ``asset`` field only, in place in the registry (the
        returned/stored entry is a NEW object — catalog entries are frozen; the old
        object is discarded, never mutated).
        """
        entry = self.get_entry(catalog_id)
        if entry is None:
            raise CatalogEntryNotFoundError(f"Catalog entry '{catalog_id}' does not exist.")
        updated = entry.model_copy(update={"asset": new_asset})
        self._entries[catalog_id] = updated
        return updated


# EquipmentModelRequestBook

class EquipmentModelRequestBook:
    """In-memory, deterministic tracker for ``EquipmentModelRequest`` lifecycle."""

    def __init__(self) -> None:
        self._requests: dict[str, EquipmentModelRequest] = {}
        self._next_sequence = 1

    def create_request(
        self,
        request_id: str,
        catalog_id: str,
        requested_asset_type: EquipmentAssetType,
        notes: str | None = None,
    ) -> EquipmentModelRequest:
        if request_id in self._requests:
            raise DuplicateModelRequestIdError(f"Model request '{request_id}' already exists.")
        request = EquipmentModelRequest(
            request_id=request_id,
            catalog_id=catalog_id,
            requested_asset_type=requested_asset_type,
            status=ModelRequestStatus.REQUESTED,
            notes=notes,
            sequence=self._next_sequence,
        )
        self._next_sequence += 1
        self._requests[request_id] = request
        return request

    def get_request(self, request_id: str) -> EquipmentModelRequest | None:
        return self._requests.get(request_id)

    def list_requests(self) -> list[EquipmentModelRequest]:
        """Every request, ordered by creation sequence."""
        return sorted(self._requests.values(), key=lambda r: r.sequence)

    def set_status(self, request_id: str, status: ModelRequestStatus) -> EquipmentModelRequest:
        request = self._requests.get(request_id)
        if request is None:
            raise ModelRequestNotFoundError(f"Model request '{request_id}' does not exist.")
        updated = request.model_copy(update={"status": status})
        self._requests[request_id] = updated
        return updated

    def mark_available(self, request_id: str) -> EquipmentModelRequest:
        """Convenience for the common 'exact CAD arrived' transition —
        see Phase 3C use case C."""
        return self.set_status(request_id, ModelRequestStatus.AVAILABLE)


# create_machine_from_catalog_entry

_DEFAULT_LIFECYCLE_BY_AVAILABILITY: dict[EquipmentAvailability, EquipmentLifecycleStatus] = {
    EquipmentAvailability.AVAILABLE: EquipmentLifecycleStatus.EXISTING,
    EquipmentAvailability.PURCHASE_CANDIDATE: EquipmentLifecycleStatus.PURCHASE_CANDIDATE,
    EquipmentAvailability.CUSTOM_BUILD: EquipmentLifecycleStatus.CUSTOM_DESIGN,
    EquipmentAvailability.UNKNOWN: EquipmentLifecycleStatus.EXISTING,
}


def create_machine_from_catalog_entry(
    entry: EquipmentCatalogEntry,
    machine_id: str,
    *,
    name: str | None = None,
    position_x: float = 0.0,
    position_y: float = 0.0,
    lifecycle_status: EquipmentLifecycleStatus | None = None,
    cycle_time: float | None = None,
) -> Machine:
    """Build a fully independent ``Machine`` from *entry*."""
    resolved_cycle_time = cycle_time if cycle_time is not None else entry.cycle_time
    if resolved_cycle_time is None:
        raise MissingCycleTimeError(
            f"Catalog entry '{entry.catalog_id}' has no cycle_time and none was "
            f"provided; a Machine cannot be constructed without one (Machine."
            f"cycle_time is required). Pass cycle_time= explicitly — e.g. a rough "
            f"placeholder estimate — if this machine is only needed for layout "
            f"planning right now; see app.services.catalog.evaluate_readiness "
            f"to check SIMULATION_READY before relying on simulation results."
        )

    resolved_lifecycle = (
        lifecycle_status
        if lifecycle_status is not None
        else _DEFAULT_LIFECYCLE_BY_AVAILABILITY[entry.equipment_availability]
    )

    physical_envelope = (
        MachineEnvelopeExtras(height=entry.height) if entry.height is not None else None
    )

    return Machine(
        id=machine_id,
        name=name if name is not None else entry.name,
        process_type=entry.process_type,
        cycle_time=resolved_cycle_time,
        setup_time=entry.setup_time,
        capacity=entry.capacity,
        failure_rate=entry.failure_rate,
        mean_repair_time=entry.mean_repair_time,
        operators_required=entry.operators_required,
        purchase_cost=entry.purchase_cost,
        position_x=position_x,
        position_y=position_y,
        width=entry.width,
        length=entry.length,
        asset=entry.asset,
        lifecycle_status=resolved_lifecycle,
        physical_envelope=physical_envelope,
    )


# Proxy creation workflow

def create_proxy_equipment_spec(
    *,
    catalog_id: str,
    name: str,
    process_type: str,
    width: float,
    length: float,
    height: float,
    cycle_time: float | None = None,
    purchase_cost: float = 0.0,
    capacity: int = 1,
    operators_required: int = 0,
    manufacturer: str | None = None,
    model_number: str | None = None,
    description: str | None = None,
    source_type: EquipmentSourceType = EquipmentSourceType.CUSTOM_REQUEST,
    equipment_availability: EquipmentAvailability = EquipmentAvailability.UNKNOWN,
) -> EquipmentCatalogEntry:
    """Create a ``PROXY`` catalog entry from minimal engineering input."""
    return EquipmentCatalogEntry(
        catalog_id=catalog_id,
        name=name,
        manufacturer=manufacturer,
        model_number=model_number,
        process_type=process_type,
        description=description,
        width=width,
        length=length,
        height=height,
        cycle_time=cycle_time,
        capacity=capacity,
        operators_required=operators_required,
        purchase_cost=purchase_cost,
        asset=create_proxy_asset(manufacturer=manufacturer, model_number=model_number),
        source_type=source_type,
        equipment_availability=equipment_availability,
    )


# External reference (Phase 3C section 6)

def create_asset_from_external_reference(
    reference: ExternalEquipmentReference,
    *,
    status: EquipmentAssetStatus = EquipmentAssetStatus.REQUESTED,
) -> EquipmentAsset:
    """Represent *reference* (e.g."""
    return EquipmentAsset(
        asset_type=EquipmentAssetType.EXACT_CAD,
        status=status,
        asset_uri=reference.source_uri if status == EquipmentAssetStatus.AVAILABLE else None,
        source_uri=reference.source_uri,
        manufacturer=reference.manufacturer,
        model_number=reference.model_number,
        license_name=reference.license_name,
        notes=f"External reference via {reference.provider_name}: {reference.title}",
    )


# Asset replacement (Phase 3C section 8)

def replace_machine_asset(factory: Factory, machine_id: str, new_asset: EquipmentAsset) -> Factory:
    """Replace *machine_id*'s ``asset`` field with *new_asset*."""
    if not any(m.id == machine_id for m in factory.machines):
        raise MachineNotFoundInFactoryError(
            f"Machine '{machine_id}' does not exist in factory '{factory.name}'."
        )
    new_machines = [
        m.model_copy(update={"asset": new_asset}) if m.id == machine_id else m
        for m in factory.machines
    ]
    return factory.model_copy(update={"machines": new_machines})


# Readiness (Phase 3C section 9)

def evaluate_readiness(entry: EquipmentCatalogEntry) -> EquipmentReadiness:
    """
    Explicit, rule-based readiness evaluation for *entry* — never an LLM/heuristic
    judgement call.
    """
    reasons: list[str] = []

    layout_ready = True  # width/length are required fields — always satisfied.

    simulation_ready = entry.cycle_time is not None
    if not simulation_ready:
        reasons.append(
            "cycle_time is not specified on this catalog entry; required for simulation."
        )

    asset = entry.asset
    if asset.asset_type == EquipmentAssetType.PROXY:
        visual_ready = True
    elif asset.asset_type in (EquipmentAssetType.EXACT_CAD, EquipmentAssetType.LIBRARY):
        visual_ready = asset.status == EquipmentAssetStatus.AVAILABLE
        if not visual_ready:
            reasons.append(
                f"{asset.asset_type.value} asset is not yet available "
                f"(status={asset.status.value})."
            )
    else:  # MISSING
        visual_ready = False
        reasons.append("No visual asset recorded (asset_type=MISSING).")

    return EquipmentReadiness(
        layout_ready=layout_ready,
        simulation_ready=simulation_ready,
        visual_ready=visual_ready,
        reasons=reasons,
    )
