"""FactoryMind Phase 3C – equipment catalog and CAD/proxy ingestion tests."""

from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.catalog import (
    EquipmentAvailability,
    EquipmentCatalogEntry,
    EquipmentSourceType,
    ExternalEquipmentReference,
    ModelRequestStatus,
)
from app.models.equipment import (
    EquipmentAsset,
    EquipmentAssetStatus,
    EquipmentAssetType,
    EquipmentLifecycleStatus,
    create_exact_cad_asset,
    create_proxy_asset,
)
from app.models.factory import Factory
from app.models.scenario import AddParallelMachineAction, Scenario
from app.services.catalog import (
    CatalogEntryNotFoundError,
    DuplicateCatalogIdError,
    DuplicateModelRequestIdError,
    EquipmentCatalog,
    EquipmentModelRequestBook,
    MachineNotFoundInFactoryError,
    MissingCycleTimeError,
    ModelRequestNotFoundError,
    create_asset_from_external_reference,
    create_machine_from_catalog_entry,
    create_proxy_equipment_spec,
    evaluate_readiness,
    replace_machine_asset,
)
from app.services.constraints import validate_layout
from app.services.layout import create_layout, place_machine
from app.services.scenario_runner import run_scenario
from app.services.simulation import run_simulation

EXAMPLES_DIR = pathlib.Path(__file__).parent.parent.parent / "examples"


# Helpers / fixtures

def _load_electronics() -> Factory:
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        return Factory.model_validate(json.load(fh))


@pytest.fixture
def electronics_factory() -> Factory:
    return _load_electronics()


@pytest.fixture
def catalog() -> EquipmentCatalog:
    return EquipmentCatalog()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _library_entry(**overrides) -> EquipmentCatalogEntry:
    base = dict(
        catalog_id="c-assembly-station",
        name="Assembly Station",
        process_type="assembly",
        width=3.0, length=2.0, height=1.8,
        cycle_time=35.0, capacity=1, setup_time=300.0,
        operators_required=2, purchase_cost=120000.0,
        asset=EquipmentAsset(
            asset_type=EquipmentAssetType.LIBRARY, status=EquipmentAssetStatus.AVAILABLE,
            asset_uri="https://library.example/assembly-station.gltf",
        ),
        source_type=EquipmentSourceType.INTERNAL_LIBRARY,
        equipment_availability=EquipmentAvailability.AVAILABLE,
    )
    base.update(overrides)
    return EquipmentCatalogEntry(**base)


def _electronics_layout(factory: Factory):
    layout = create_layout(factory)
    for m in factory.machines:
        layout = place_machine(factory, layout, m.id, x=m.position_x, y=m.position_y)
    return layout


# 1. EquipmentCatalog

class TestEquipmentCatalog:
    def test_register_and_get(self, catalog: EquipmentCatalog):
        entry = _library_entry()
        catalog.register_entry(entry)
        assert catalog.get_entry("c-assembly-station") == entry

    def test_get_unknown_returns_none(self, catalog: EquipmentCatalog):
        assert catalog.get_entry("does-not-exist") is None

    def test_duplicate_catalog_id_rejected(self, catalog: EquipmentCatalog):
        catalog.register_entry(_library_entry())
        with pytest.raises(DuplicateCatalogIdError):
            catalog.register_entry(_library_entry())

    def test_list_entries_deterministic_registration_order(self, catalog: EquipmentCatalog):
        e1 = _library_entry(catalog_id="c-1", name="A")
        e2 = _library_entry(catalog_id="c-2", name="B")
        e3 = _library_entry(catalog_id="c-3", name="C")
        catalog.register_entry(e2)
        catalog.register_entry(e3)
        catalog.register_entry(e1)
        assert [e.catalog_id for e in catalog.list_entries()] == ["c-2", "c-3", "c-1"]

    def test_search_by_process_type(self, catalog: EquipmentCatalog):
        catalog.register_entry(_library_entry(catalog_id="c-1", process_type="assembly"))
        catalog.register_entry(_library_entry(catalog_id="c-2", process_type="welding"))
        results = catalog.search(process_type="welding")
        assert [e.catalog_id for e in results] == ["c-2"]

    def test_search_by_manufacturer(self, catalog: EquipmentCatalog):
        catalog.register_entry(_library_entry(catalog_id="c-1", manufacturer="Acme"))
        catalog.register_entry(_library_entry(catalog_id="c-2", manufacturer="Other"))
        results = catalog.search(manufacturer="Acme")
        assert [e.catalog_id for e in results] == ["c-1"]

    def test_search_by_model_number(self, catalog: EquipmentCatalog):
        catalog.register_entry(_library_entry(catalog_id="c-1", model_number="AR-500"))
        catalog.register_entry(_library_entry(catalog_id="c-2", model_number="XY-1"))
        results = catalog.search(model_number="AR-500")
        assert [e.catalog_id for e in results] == ["c-1"]

    def test_search_by_text_matches_name_case_insensitive(self, catalog: EquipmentCatalog):
        catalog.register_entry(_library_entry(catalog_id="c-1", name="Laser Welding Cell"))
        catalog.register_entry(_library_entry(catalog_id="c-2", name="Packaging Station"))
        results = catalog.search(text="laser")
        assert [e.catalog_id for e in results] == ["c-1"]

    def test_search_by_text_matches_description(self, catalog: EquipmentCatalog):
        catalog.register_entry(_library_entry(catalog_id="c-1", name="X", description="High-precision robotic arm"))
        catalog.register_entry(_library_entry(catalog_id="c-2", name="Y", description="Simple conveyor"))
        results = catalog.search(text="robotic")
        assert [e.catalog_id for e in results] == ["c-1"]

    def test_search_combines_filters_with_and(self, catalog: EquipmentCatalog):
        catalog.register_entry(_library_entry(catalog_id="c-1", process_type="welding", manufacturer="Acme"))
        catalog.register_entry(_library_entry(catalog_id="c-2", process_type="welding", manufacturer="Other"))
        results = catalog.search(process_type="welding", manufacturer="Acme")
        assert [e.catalog_id for e in results] == ["c-1"]

    def test_search_no_filters_returns_all(self, catalog: EquipmentCatalog):
        catalog.register_entry(_library_entry(catalog_id="c-1"))
        catalog.register_entry(_library_entry(catalog_id="c-2"))
        assert len(catalog.search()) == 2

    def test_search_is_deterministic_repeated_calls(self, catalog: EquipmentCatalog):
        catalog.register_entry(_library_entry(catalog_id="c-1", process_type="welding"))
        catalog.register_entry(_library_entry(catalog_id="c-2", process_type="welding"))
        r1 = [e.catalog_id for e in catalog.search(process_type="welding")]
        r2 = [e.catalog_id for e in catalog.search(process_type="welding")]
        assert r1 == r2

    def test_remove_entry(self, catalog: EquipmentCatalog):
        catalog.register_entry(_library_entry())
        catalog.remove_entry("c-assembly-station")
        assert catalog.get_entry("c-assembly-station") is None

    def test_remove_unknown_entry_raises(self, catalog: EquipmentCatalog):
        with pytest.raises(CatalogEntryNotFoundError):
            catalog.remove_entry("does-not-exist")

    def test_update_asset(self, catalog: EquipmentCatalog):
        catalog.register_entry(_library_entry())
        new_asset = create_exact_cad_asset(asset_uri="s3://bucket/exact.step")
        updated = catalog.update_asset("c-assembly-station", new_asset)
        assert updated.asset.asset_type == EquipmentAssetType.EXACT_CAD
        assert catalog.get_entry("c-assembly-station").asset.asset_type == EquipmentAssetType.EXACT_CAD

    def test_update_asset_unknown_entry_raises(self, catalog: EquipmentCatalog):
        with pytest.raises(CatalogEntryNotFoundError):
            catalog.update_asset("does-not-exist", create_proxy_asset())


# 2. create_machine_from_catalog_entry

class TestCreateMachineFromCatalogEntry:
    def test_creates_machine_with_engineering_fields(self):
        entry = _library_entry()
        machine = create_machine_from_catalog_entry(entry, "m-1", position_x=5.0, position_y=3.0)
        assert machine.id == "m-1"
        assert machine.process_type == "assembly"
        assert machine.cycle_time == 35.0
        assert machine.width == 3.0
        assert machine.length == 2.0
        assert machine.position_x == 5.0
        assert machine.position_y == 3.0
        assert machine.physical_envelope.height == 1.8

    def test_default_name_from_entry(self):
        entry = _library_entry(name="Assembly Station")
        machine = create_machine_from_catalog_entry(entry, "m-1")
        assert machine.name == "Assembly Station"

    def test_name_override(self):
        entry = _library_entry()
        machine = create_machine_from_catalog_entry(entry, "m-1", name="Line 2 Assembly")
        assert machine.name == "Line 2 Assembly"

    def test_lifecycle_status_default_from_availability(self):
        entry = _library_entry(equipment_availability=EquipmentAvailability.PURCHASE_CANDIDATE)
        machine = create_machine_from_catalog_entry(entry, "m-1")
        assert machine.lifecycle_status == EquipmentLifecycleStatus.PURCHASE_CANDIDATE

    def test_lifecycle_status_override(self):
        entry = _library_entry(equipment_availability=EquipmentAvailability.AVAILABLE)
        machine = create_machine_from_catalog_entry(entry, "m-1", lifecycle_status=EquipmentLifecycleStatus.INSTALLED)
        assert machine.lifecycle_status == EquipmentLifecycleStatus.INSTALLED

    def test_missing_cycle_time_raises(self):
        entry = _library_entry(cycle_time=None)
        with pytest.raises(MissingCycleTimeError):
            create_machine_from_catalog_entry(entry, "m-1")

    def test_cycle_time_override_used_when_entry_lacks_one(self):
        entry = _library_entry(cycle_time=None)
        machine = create_machine_from_catalog_entry(entry, "m-1", cycle_time=42.0)
        assert machine.cycle_time == 42.0

    def test_cycle_time_override_takes_precedence_over_entry_value(self):
        entry = _library_entry(cycle_time=35.0)
        machine = create_machine_from_catalog_entry(entry, "m-1", cycle_time=99.0)
        assert machine.cycle_time == 99.0

    def test_no_height_means_no_physical_envelope(self):
        entry = _library_entry(height=None)
        machine = create_machine_from_catalog_entry(entry, "m-1")
        assert machine.physical_envelope is None

    def test_catalog_mutation_does_not_affect_existing_machine(self, catalog: EquipmentCatalog):
        """Once a Machine is built, later catalog changes (asset update,
        or even removing/re-registering the entry) must never retroactively
        change it — the Machine holds independent, copied-by-value data."""
        entry = _library_entry()
        catalog.register_entry(entry)
        machine = create_machine_from_catalog_entry(entry, "m-1")
        original_asset_type = machine.asset.asset_type

        catalog.update_asset("c-assembly-station", create_exact_cad_asset(asset_uri="s3://new.step"))
        assert machine.asset.asset_type == original_asset_type  # unchanged

        catalog.remove_entry("c-assembly-station")
        assert machine.id == "m-1"  # still fully intact, no dangling reference issue

    def test_two_machines_from_same_entry_are_independent(self):
        entry = _library_entry()
        m1 = create_machine_from_catalog_entry(entry, "m-1", position_x=1.0, position_y=1.0)
        m2 = create_machine_from_catalog_entry(entry, "m-2", position_x=9.0, position_y=9.0)
        assert m1.id != m2.id
        assert m1.position_x != m2.position_x
        assert m1.cycle_time == m2.cycle_time == 35.0


# 3. create_proxy_equipment_spec

class TestCreateProxyEquipmentSpec:
    def test_minimal_inputs(self):
        entry = create_proxy_equipment_spec(
            catalog_id="c-laser", name="Laser Welding Cell", process_type="welding",
            width=3.2, length=2.1, height=2.4,
        )
        assert entry.asset.asset_type == EquipmentAssetType.PROXY
        assert entry.asset.asset_uri is None
        assert entry.width == 3.2 and entry.length == 2.1 and entry.height == 2.4
        assert entry.cycle_time is None

    def test_optional_fields(self):
        entry = create_proxy_equipment_spec(
            catalog_id="c-laser", name="Laser Welding Cell", process_type="welding",
            width=3.2, length=2.1, height=2.4, cycle_time=45.0, purchase_cost=250000.0,
            capacity=1, operators_required=1, manufacturer="Acme Lasers", model_number="LWC-3200",
        )
        assert entry.cycle_time == 45.0
        assert entry.purchase_cost == 250000.0
        assert entry.manufacturer == "Acme Lasers"

    def test_usable_immediately_for_machine_creation_when_cycle_time_given(self):
        entry = create_proxy_equipment_spec(
            catalog_id="c-laser", name="Laser Welding Cell", process_type="welding",
            width=3.2, length=2.1, height=2.4, cycle_time=45.0,
        )
        machine = create_machine_from_catalog_entry(entry, "m-laser")
        assert machine.cycle_time == 45.0

    def test_layout_ready_proxy_without_cycle_time(self):
        entry = create_proxy_equipment_spec(
            catalog_id="c-laser", name="Laser Welding Cell", process_type="welding",
            width=3.2, length=2.1, height=2.4,
        )
        readiness = evaluate_readiness(entry)
        assert readiness.layout_ready is True
        assert readiness.simulation_ready is False
        assert readiness.visual_ready is True


# 4. External reference (GrabCAD-like), no network

class TestExternalReference:
    def test_construction(self):
        ref = ExternalEquipmentReference(
            provider_name="GrabCAD",
            source_uri="https://grabcad.com/library/abb-robotic-welding-cell",
            title="ABB robotic welding cell",
            manufacturer="ABB",
            model_number="IRB-6700",
        )
        assert ref.provider_name == "GrabCAD"

    def test_provider_agnostic_any_string_accepted(self):
        ref = ExternalEquipmentReference(
            provider_name="TraceParts", source_uri="https://traceparts.com/x", title="Conveyor"
        )
        assert ref.provider_name == "TraceParts"

    def test_creates_asset_without_network_access(self):
        ref = ExternalEquipmentReference(
            provider_name="GrabCAD", source_uri="https://grabcad.com/library/x", title="Welding Cell"
        )
        asset = create_asset_from_external_reference(ref)
        assert asset.status == EquipmentAssetStatus.REQUESTED
        assert asset.asset_uri is None  # never fetched, so nothing to load from yet
        assert asset.source_uri == ref.source_uri
        assert "GrabCAD" in asset.notes

    def test_available_status_sets_asset_uri_to_source_uri(self):
        ref = ExternalEquipmentReference(
            provider_name="GrabCAD", source_uri="https://grabcad.com/library/x", title="Welding Cell"
        )
        asset = create_asset_from_external_reference(ref, status=EquipmentAssetStatus.AVAILABLE)
        assert asset.asset_uri == ref.source_uri

    def test_module_has_no_network_dependency(self):
        import app.services.catalog as mod
        source = pathlib.Path(mod.__file__).read_text()
        assert "import requests" not in source
        assert "import httpx" not in source
        assert "urllib.request" not in source


# 5. EquipmentModelRequestBook

class TestEquipmentModelRequestBook:
    def test_create_request(self):
        book = EquipmentModelRequestBook()
        req = book.create_request("req-1", "c-1", EquipmentAssetType.PROXY, notes="need CAD")
        assert req.status == ModelRequestStatus.REQUESTED
        assert req.sequence == 1

    def test_sequence_is_deterministic_increasing(self):
        book = EquipmentModelRequestBook()
        r1 = book.create_request("req-1", "c-1", EquipmentAssetType.PROXY)
        r2 = book.create_request("req-2", "c-2", EquipmentAssetType.MISSING)
        assert r1.sequence == 1
        assert r2.sequence == 2

    def test_duplicate_request_id_rejected(self):
        book = EquipmentModelRequestBook()
        book.create_request("req-1", "c-1", EquipmentAssetType.PROXY)
        with pytest.raises(DuplicateModelRequestIdError):
            book.create_request("req-1", "c-2", EquipmentAssetType.MISSING)

    def test_list_requests_ordered_by_sequence(self):
        book = EquipmentModelRequestBook()
        book.create_request("req-b", "c-1", EquipmentAssetType.PROXY)
        book.create_request("req-a", "c-2", EquipmentAssetType.MISSING)
        assert [r.request_id for r in book.list_requests()] == ["req-b", "req-a"]

    def test_get_unknown_returns_none(self):
        book = EquipmentModelRequestBook()
        assert book.get_request("does-not-exist") is None

    def test_set_status_unknown_raises(self):
        book = EquipmentModelRequestBook()
        with pytest.raises(ModelRequestNotFoundError):
            book.set_status("does-not-exist", ModelRequestStatus.IN_PROGRESS)

    def test_full_lifecycle_proxy_then_available(self):
        """Use case A/C: proxy + REQUESTED -> exact CAD arrives -> AVAILABLE."""
        book = EquipmentModelRequestBook()
        req = book.create_request("req-1", "c-laser", EquipmentAssetType.EXACT_CAD, notes="Vendor CAD pending")
        assert req.status == ModelRequestStatus.REQUESTED

        in_progress = book.set_status("req-1", ModelRequestStatus.IN_PROGRESS)
        assert in_progress.status == ModelRequestStatus.IN_PROGRESS

        available = book.mark_available("req-1")
        assert available.status == ModelRequestStatus.AVAILABLE
        # Earlier snapshots are untouched (frozen model, no in-place mutation).
        assert req.status == ModelRequestStatus.REQUESTED

    def test_rejected_status(self):
        book = EquipmentModelRequestBook()
        book.create_request("req-1", "c-1", EquipmentAssetType.PROXY)
        rejected = book.set_status("req-1", ModelRequestStatus.REJECTED)
        assert rejected.status == ModelRequestStatus.REJECTED


# 6. Asset replacement

class TestAssetReplacement:
    def test_replace_missing_with_proxy(self, electronics_factory: Factory):
        factory = electronics_factory.model_copy(update={"machines": [
            m.model_copy(update={"asset": EquipmentAsset(asset_type=EquipmentAssetType.MISSING, status=EquipmentAssetStatus.MISSING)})
            if m.id == "m-screwdriving" else m for m in electronics_factory.machines
        ]})
        updated = replace_machine_asset(factory, "m-screwdriving", create_proxy_asset())
        m = next(m for m in updated.machines if m.id == "m-screwdriving")
        assert m.asset.asset_type == EquipmentAssetType.PROXY

    def test_replace_proxy_with_exact_cad(self, electronics_factory: Factory):
        factory = electronics_factory.model_copy(update={"machines": [
            m.model_copy(update={"asset": create_proxy_asset()}) if m.id == "m-screwdriving" else m
            for m in electronics_factory.machines
        ]})
        updated = replace_machine_asset(
            factory, "m-screwdriving", create_exact_cad_asset(asset_uri="s3://bucket/x.step")
        )
        m = next(m for m in updated.machines if m.id == "m-screwdriving")
        assert m.asset.asset_type == EquipmentAssetType.EXACT_CAD

    def test_original_factory_untouched(self, electronics_factory: Factory):
        before = electronics_factory.model_dump()
        replace_machine_asset(electronics_factory, "m-screwdriving", create_proxy_asset())
        assert electronics_factory.model_dump() == before

    def test_unknown_machine_raises(self, electronics_factory: Factory):
        with pytest.raises(MachineNotFoundInFactoryError):
            replace_machine_asset(electronics_factory, "does-not-exist", create_proxy_asset())

    def test_engineering_identity_preserved(self, electronics_factory: Factory):
        original = next(m for m in electronics_factory.machines if m.id == "m-screwdriving")
        updated_factory = replace_machine_asset(
            electronics_factory, "m-screwdriving", create_exact_cad_asset(asset_uri="s3://bucket/x.step")
        )
        updated = next(m for m in updated_factory.machines if m.id == "m-screwdriving")
        assert updated.id == original.id
        assert updated.process_type == original.process_type
        assert updated.cycle_time == original.cycle_time
        assert updated.capacity == original.capacity
        assert updated.width == original.width
        assert updated.length == original.length
        assert updated.purchase_cost == original.purchase_cost
        # route references (by machine_id) are structurally unaffected since
        # machine_id itself never changes and Product.route is untouched
        assert updated_factory.products == electronics_factory.products

    def test_simulation_result_preserved(self, electronics_factory: Factory):
        factory_proxy = electronics_factory.model_copy(update={"machines": [
            m.model_copy(update={"asset": create_proxy_asset()}) if m.id == "m-screwdriving" else m
            for m in electronics_factory.machines
        ]})
        before = run_simulation(factory_proxy, "p-electronics-widget")

        factory_exact = replace_machine_asset(
            factory_proxy, "m-screwdriving", create_exact_cad_asset(asset_uri="s3://bucket/x.step")
        )
        after = run_simulation(factory_exact, "p-electronics-widget")

        assert before.model_dump() == after.model_dump()

    def test_scenario_result_preserved(self, electronics_factory: Factory):
        factory_proxy = electronics_factory.model_copy(update={"machines": [
            m.model_copy(update={"asset": create_proxy_asset()}) if m.id == "m-screwdriving" else m
            for m in electronics_factory.machines
        ]})
        scenario = Scenario(
            id="s-1", name="parallel screwdriving",
            actions=[AddParallelMachineAction(machine_id="m-screwdriving")],
        )
        before = run_scenario(factory_proxy, "p-electronics-widget", scenario)

        factory_exact = replace_machine_asset(
            factory_proxy, "m-screwdriving", create_exact_cad_asset(asset_uri="s3://bucket/x.step")
        )
        after = run_scenario(factory_exact, "p-electronics-widget", scenario)

        assert before.verdict == after.verdict
        assert before.comparison.model_dump() == after.comparison.model_dump()

    def test_layout_result_preserved(self, electronics_factory: Factory):
        factory_proxy = electronics_factory.model_copy(update={"machines": [
            m.model_copy(update={"asset": create_proxy_asset()}) if m.id == "m-screwdriving" else m
            for m in electronics_factory.machines
        ]})
        layout = _electronics_layout(factory_proxy)
        before = validate_layout(factory_proxy, layout, "p-electronics-widget")

        factory_exact = replace_machine_asset(
            factory_proxy, "m-screwdriving", create_exact_cad_asset(asset_uri="s3://bucket/x.step")
        )
        after = validate_layout(factory_exact, layout, "p-electronics-widget")

        assert before.model_dump() == after.model_dump()


# 7. Readiness flags

class TestReadiness:
    def test_full_catalog_machine_all_ready(self):
        entry = _library_entry()
        readiness = evaluate_readiness(entry)
        assert readiness.layout_ready is True
        assert readiness.simulation_ready is True
        assert readiness.visual_ready is True
        assert readiness.reasons == []

    def test_proxy_with_dimensions_no_cycle_time(self):
        entry = create_proxy_equipment_spec(
            catalog_id="c-1", name="X", process_type="welding", width=1.0, length=1.0, height=1.0
        )
        readiness = evaluate_readiness(entry)
        assert readiness.layout_ready is True
        assert readiness.simulation_ready is False
        assert readiness.visual_ready is True
        assert len(readiness.reasons) == 1

    def test_exact_cad_missing_cycle_time(self):
        entry = _library_entry(
            cycle_time=None,
            asset=create_exact_cad_asset(asset_uri="s3://bucket/x.step"),
        )
        readiness = evaluate_readiness(entry)
        assert readiness.layout_ready is True
        assert readiness.simulation_ready is False
        assert readiness.visual_ready is True

    def test_missing_asset_not_visual_ready(self):
        entry = _library_entry(
            asset=EquipmentAsset(asset_type=EquipmentAssetType.MISSING, status=EquipmentAssetStatus.MISSING)
        )
        readiness = evaluate_readiness(entry)
        assert readiness.visual_ready is False
        assert any("MISSING" in r for r in readiness.reasons)

    def test_exact_cad_requested_not_yet_visual_ready(self):
        entry = _library_entry(
            cycle_time=None,
            asset=EquipmentAsset(asset_type=EquipmentAssetType.EXACT_CAD, status=EquipmentAssetStatus.REQUESTED),
        )
        readiness = evaluate_readiness(entry)
        assert readiness.visual_ready is False
        assert readiness.simulation_ready is False

    def test_layout_ready_always_true(self):
        for cycle_time in (None, 10.0):
            entry = _library_entry(cycle_time=cycle_time)
            assert evaluate_readiness(entry).layout_ready is True


# 8. Required demonstration workflows A-D

class TestWorkflowA_InternalLibraryMachine:
    def test_full_workflow(self, catalog: EquipmentCatalog, electronics_factory: Factory):
        entry = _library_entry()
        catalog.register_entry(entry)
        machine = create_machine_from_catalog_entry(entry, "m-assembly-2", position_x=40.0, position_y=5.0)

        factory = electronics_factory.model_copy(update={"machines": [*electronics_factory.machines, machine]})
        assert any(m.id == "m-assembly-2" for m in factory.machines)
        assert machine.lifecycle_status == EquipmentLifecycleStatus.EXISTING


class TestWorkflowB_GrabCadLikeExternalReference:
    def test_full_workflow(self, electronics_factory: Factory):
        ref = ExternalEquipmentReference(
            provider_name="GrabCAD",
            source_uri="https://grabcad.com/library/abb-robotic-welding-cell",
            title="ABB robotic welding cell",
            manufacturer="ABB",
            model_number="IRB-6700",
        )
        entry = create_proxy_equipment_spec(
            catalog_id="c-welding-cell", name="ABB Welding Cell (proxy pending CAD)",
            process_type="welding", width=2.0, length=2.0, height=2.2,
            manufacturer=ref.manufacturer, model_number=ref.model_number,
            source_type=EquipmentSourceType.EXTERNAL_CATALOG,
        )
        readiness_no_timing = evaluate_readiness(entry)
        assert readiness_no_timing.layout_ready is True
        assert readiness_no_timing.simulation_ready is False

        machine = create_machine_from_catalog_entry(entry, "m-welding", position_x=40.0, position_y=5.0, cycle_time=40.0)
        factory = electronics_factory.model_copy(update={"machines": [*electronics_factory.machines, machine]})

        # _electronics_layout places every machine (incl.
        layout = _electronics_layout(factory)
        layout_result = validate_layout(factory, layout, "p-electronics-widget")
        assert layout_result.valid is True

        sim_result = run_simulation(factory, "p-electronics-widget")
        assert sim_result.completed_units > 0


class TestWorkflowC_CustomMachineNotBuiltYet:
    def test_full_workflow(self, electronics_factory: Factory):
        entry = EquipmentCatalogEntry(
            catalog_id="c-custom-fixture", name="Custom Load Fixture", process_type="handling",
            width=1.5, length=1.5, height=1.2,
            asset=EquipmentAsset(asset_type=EquipmentAssetType.MISSING, status=EquipmentAssetStatus.REQUESTED),
            source_type=EquipmentSourceType.CUSTOM_REQUEST,
            equipment_availability=EquipmentAvailability.CUSTOM_BUILD,
        )
        readiness = evaluate_readiness(entry)
        assert readiness.simulation_ready is False
        assert readiness.visual_ready is False
        assert readiness.layout_ready is True

        book = EquipmentModelRequestBook()
        request = book.create_request(
            "req-custom-1", "c-custom-fixture", EquipmentAssetType.MISSING, notes="Needs in-house design"
        )
        assert request.status == ModelRequestStatus.REQUESTED

        machine = create_machine_from_catalog_entry(
            entry, "m-custom-fixture", position_x=46.0, position_y=5.0,
            lifecycle_status=EquipmentLifecycleStatus.CUSTOM_DESIGN, cycle_time=15.0,
        )
        factory = electronics_factory.model_copy(update={"machines": [*electronics_factory.machines, machine]})
        # _electronics_layout places every machine (incl.
        layout = _electronics_layout(factory)
        layout_result = validate_layout(factory, layout, "p-electronics-widget")
        assert layout_result.valid is True  # future-layout planning works despite no CAD


class TestWorkflowD_ExactModelArrives:
    def test_full_workflow(self, electronics_factory: Factory):
        factory_proxy = electronics_factory.model_copy(update={"machines": [
            m.model_copy(update={"asset": create_proxy_asset(manufacturer="ABB", model_number="IRB-6700")})
            if m.id == "m-screwdriving" else m for m in electronics_factory.machines
        ]})
        layout = _electronics_layout(factory_proxy)
        scenario = Scenario(id="s-1", name="x", actions=[AddParallelMachineAction(machine_id="m-screwdriving")])

        layout_before = validate_layout(factory_proxy, layout, "p-electronics-widget")
        sim_before = run_simulation(factory_proxy, "p-electronics-widget")
        scenario_before = run_scenario(factory_proxy, "p-electronics-widget", scenario)
        machine_before = next(m for m in factory_proxy.machines if m.id == "m-screwdriving")

        factory_exact = replace_machine_asset(
            factory_proxy, "m-screwdriving",
            create_exact_cad_asset(asset_uri="s3://bucket/abb-irb6700.step", file_format="STEP", manufacturer="ABB", model_number="IRB-6700"),
        )

        layout_after = validate_layout(factory_exact, layout, "p-electronics-widget")
        sim_after = run_simulation(factory_exact, "p-electronics-widget")
        scenario_after = run_scenario(factory_exact, "p-electronics-widget", scenario)
        machine_after = next(m for m in factory_exact.machines if m.id == "m-screwdriving")

        assert machine_before.id == machine_after.id
        assert machine_before.process_type == machine_after.process_type
        assert machine_before.cycle_time == machine_after.cycle_time
        assert machine_before.asset.asset_type != machine_after.asset.asset_type  # only this changed

        assert layout_before.model_dump() == layout_after.model_dump()
        assert sim_before.model_dump() == sim_after.model_dump()
        assert scenario_before.comparison.model_dump() == scenario_after.comparison.model_dump()
        assert scenario_before.verdict == scenario_after.verdict


# 9. API

class TestCatalogAPI:
    def _entry_payload(self, catalog_id="c-api-1"):
        return {
            "catalog_id": catalog_id, "name": "Assembly Station", "process_type": "assembly",
            "width": 3.0, "length": 2.0, "height": 1.8, "cycle_time": 35.0,
            "asset": {
                "asset_type": "LIBRARY", "status": "AVAILABLE",
                "asset_uri": "https://library.example/assembly-station.gltf",
            },
            "source_type": "INTERNAL_LIBRARY",
        }

    def test_register_catalog_entry(self, client: TestClient):
        resp = client.post("/equipment/catalog", json={"entry": self._entry_payload()})
        assert resp.status_code == 200
        assert resp.json()["catalog_id"] == "c-api-1"

    def test_register_duplicate_returns_400(self, client: TestClient):
        client.post("/equipment/catalog", json={"entry": self._entry_payload("c-api-dup")})
        resp = client.post("/equipment/catalog", json={"entry": self._entry_payload("c-api-dup")})
        assert resp.status_code == 400

    def test_register_bad_entry_returns_422(self, client: TestClient):
        resp = client.post("/equipment/catalog", json={"entry": {"name": ""}})
        assert resp.status_code == 422

    def test_list_catalog_entries(self, client: TestClient):
        client.post("/equipment/catalog", json={"entry": self._entry_payload("c-api-list-1")})
        resp = client.get("/equipment/catalog")
        assert resp.status_code == 200
        ids = [e["catalog_id"] for e in resp.json()]
        assert "c-api-list-1" in ids

    def test_list_catalog_entries_filtered_by_process_type(self, client: TestClient):
        client.post("/equipment/catalog", json={"entry": self._entry_payload("c-api-filt")})
        resp = client.get("/equipment/catalog", params={"process_type": "assembly"})
        assert resp.status_code == 200
        assert all(e["process_type"] == "assembly" for e in resp.json())

    def test_create_proxy_endpoint(self, client: TestClient):
        payload = {
            "catalog_id": "c-api-proxy-1", "name": "Laser Welding Cell", "process_type": "welding",
            "width": 3.2, "length": 2.1, "height": 2.4,
        }
        resp = client.post("/equipment/proxy", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["asset"]["asset_type"] == "PROXY"
        assert body["cycle_time"] is None

    def test_create_model_request_endpoint(self, client: TestClient):
        payload = {"request_id": "req-api-1", "catalog_id": "c-api-1", "requested_asset_type": "PROXY", "notes": "x"}
        resp = client.post("/equipment/model-request", json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "REQUESTED"

    def test_create_model_request_bad_asset_type_returns_422(self, client: TestClient):
        payload = {"request_id": "req-api-bad", "catalog_id": "c-api-1", "requested_asset_type": "NOT_REAL"}
        resp = client.post("/equipment/model-request", json=payload)
        assert resp.status_code == 422

    def test_create_model_request_duplicate_returns_400(self, client: TestClient):
        payload = {"request_id": "req-api-dup", "catalog_id": "c-api-1", "requested_asset_type": "PROXY"}
        client.post("/equipment/model-request", json=payload)
        resp = client.post("/equipment/model-request", json=payload)
        assert resp.status_code == 400

    def test_create_machine_from_catalog_endpoint(self, client: TestClient):
        client.post("/equipment/catalog", json={"entry": self._entry_payload("c-api-from-cat")})
        payload = {"catalog_id": "c-api-from-cat", "machine_id": "m-api-1", "position_x": 5.0, "position_y": 5.0}
        resp = client.post("/equipment/from-catalog", json=payload)
        assert resp.status_code == 200
        assert resp.json()["id"] == "m-api-1"

    def test_create_machine_from_unknown_catalog_returns_400(self, client: TestClient):
        payload = {"catalog_id": "does-not-exist", "machine_id": "m-api-2"}
        resp = client.post("/equipment/from-catalog", json=payload)
        assert resp.status_code == 400

    def test_create_machine_missing_cycle_time_returns_400(self, client: TestClient):
        proxy_payload = {
            "catalog_id": "c-api-no-ct", "name": "X", "process_type": "welding",
            "width": 1.0, "length": 1.0, "height": 1.0,
        }
        client.post("/equipment/proxy", json=proxy_payload)
        resp = client.post("/equipment/from-catalog", json={"catalog_id": "c-api-no-ct", "machine_id": "m-x"})
        assert resp.status_code == 400

    def test_error_response_has_no_stack_trace(self, client: TestClient):
        resp = client.post("/equipment/from-catalog", json={"catalog_id": "does-not-exist", "machine_id": "m-x"})
        body_text = json.dumps(resp.json())
        assert "Traceback" not in body_text
        assert ".py\"" not in body_text
