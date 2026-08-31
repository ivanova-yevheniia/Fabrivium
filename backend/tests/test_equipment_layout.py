"""FactoryMind Phase 3A – equipment asset & factory layout domain tests."""

from __future__ import annotations

import json
import math
import pathlib

import pytest
from pydantic import ValidationError

from app.models.equipment import (
    EquipmentAsset,
    EquipmentAssetStatus,
    EquipmentAssetType,
    EquipmentLifecycleStatus,
    create_proxy_asset,
)
from app.models.factory import Factory, Machine, MachineEnvelopeExtras
from app.models.layout import (
    FactoryLayout,
    LayoutZone,
    LayoutZoneType,
    MachinePhysicalEnvelope,
    MachinePlacement,
)
from app.models.scenario import AddParallelMachineAction, Scenario
from app.services.asset_registry import EquipmentAssetRegistry
from app.services.layout import (
    DuplicatePlacementError,
    InvalidCoordinateError,
    MachineNotFoundForLayoutError,
    PlacementNotFoundError,
    create_layout,
    get_placement,
    machine_envelope,
    move_machine,
    place_machine,
    remove_placement,
    rotate_machine,
)
from app.services.scenario import apply_scenario
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


def minimal_machine(**overrides) -> dict:
    base = {
        "id": "m-1",
        "name": "Test Machine",
        "process_type": "assembly",
        "cycle_time": 30.0,
        "width": 2.0,
        "length": 1.5,
    }
    base.update(overrides)
    return base


def minimal_factory(**overrides) -> dict:
    base = {
        "name": "Test Factory",
        "width": 100.0,
        "length": 50.0,
        "shifts_per_day": 2,
        "hours_per_shift": 8.0,
        "operators_available": 10,
        "budget": 0.0,
        "machines": [minimal_machine()],
        "products": [],
        "buffers": [],
    }
    base.update(overrides)
    return base


# 1. EquipmentAsset

class TestEquipmentAsset:
    def test_exact_cad_available_requires_uri(self):
        with pytest.raises(ValidationError):
            EquipmentAsset(asset_type=EquipmentAssetType.EXACT_CAD, status=EquipmentAssetStatus.AVAILABLE)

    def test_library_available_requires_uri(self):
        with pytest.raises(ValidationError):
            EquipmentAsset(asset_type=EquipmentAssetType.LIBRARY, status=EquipmentAssetStatus.AVAILABLE)

    def test_exact_cad_available_with_uri_valid(self):
        asset = EquipmentAsset(
            asset_type=EquipmentAssetType.EXACT_CAD,
            status=EquipmentAssetStatus.AVAILABLE,
            asset_uri="s3://bucket/model.step",
        )
        assert asset.asset_uri == "s3://bucket/model.step"

    def test_exact_cad_missing_status_does_not_require_uri(self):
        """An EXACT_CAD asset that hasn't arrived yet (status=MISSING) is
        valid without a URI — the requirement only applies to AVAILABLE."""
        asset = EquipmentAsset(asset_type=EquipmentAssetType.EXACT_CAD, status=EquipmentAssetStatus.MISSING)
        assert asset.asset_uri is None

    def test_exact_cad_requested_status_does_not_require_uri(self):
        asset = EquipmentAsset(asset_type=EquipmentAssetType.EXACT_CAD, status=EquipmentAssetStatus.REQUESTED)
        assert asset.asset_uri is None

    def test_proxy_available_valid_without_uri(self):
        asset = EquipmentAsset(asset_type=EquipmentAssetType.PROXY, status=EquipmentAssetStatus.AVAILABLE)
        assert asset.asset_uri is None

    def test_missing_type_valid_without_uri(self):
        asset = EquipmentAsset(asset_type=EquipmentAssetType.MISSING, status=EquipmentAssetStatus.MISSING)
        assert asset.asset_uri is None

    def test_full_metadata_fields(self):
        asset = EquipmentAsset(
            asset_type=EquipmentAssetType.LIBRARY,
            status=EquipmentAssetStatus.AVAILABLE,
            asset_uri="https://library.example/model.gltf",
            source_uri="https://vendor.example/product/123",
            manufacturer="Acme Robotics",
            model_number="AR-500",
            license_name="CC-BY-4.0",
            attribution="Model by Acme Robotics",
            file_format="glTF",
            notes="Stock library model, not the exact purchased unit",
        )
        assert asset.manufacturer == "Acme Robotics"
        assert asset.file_format == "glTF"

    def test_frozen(self):
        asset = create_proxy_asset()
        with pytest.raises(ValidationError):
            asset.notes = "changed"

    def test_serializable(self):
        asset = create_proxy_asset(manufacturer="Acme", model_number="X-1")
        dumped = asset.model_dump()
        assert dumped["asset_type"] == "PROXY"
        restored = EquipmentAsset.model_validate(dumped)
        assert restored == asset


class TestCreateProxyAsset:
    def test_returns_proxy_available(self):
        asset = create_proxy_asset()
        assert asset.asset_type == EquipmentAssetType.PROXY
        assert asset.status == EquipmentAssetStatus.AVAILABLE
        assert asset.asset_uri is None

    def test_no_uri_required_and_is_valid_object(self):
        asset = create_proxy_asset(manufacturer="Acme Lasers", model_number="LWC-3200", notes="Laser welding cell")
        assert asset.manufacturer == "Acme Lasers"
        assert asset.model_number == "LWC-3200"


# 2. Machine backward compatibility

class TestMachineBackwardCompatibility:
    def test_electronics_line_json_validates_unmodified(self):
        factory = _load_electronics()
        assert len(factory.machines) == 4

    def test_default_lifecycle_status_is_existing(self, electronics_factory: Factory):
        for m in electronics_factory.machines:
            assert m.lifecycle_status == EquipmentLifecycleStatus.EXISTING

    def test_default_asset_is_none(self, electronics_factory: Factory):
        # m-screwdriving intentionally carries a real LIBRARY/GLB asset
        # (Phase 6C's GLB-rendering pipeline test) — every OTHER machine in
        # the fixture still has no asset set at all, which is what this
        # test actually verifies: the field defaults to None when omitted,
        # not that the whole fixture is asset-free.
        for m in electronics_factory.machines:
            if m.id == "m-screwdriving":
                assert m.asset is not None
                assert m.asset.asset_type == EquipmentAssetType.LIBRARY
            else:
                assert m.asset is None

    def test_default_physical_envelope_is_none(self, electronics_factory: Factory):
        for m in electronics_factory.machines:
            assert m.physical_envelope is None

    def test_machine_still_constructible_without_any_new_fields(self):
        machine = Machine(**minimal_machine())
        assert machine.asset is None
        assert machine.lifecycle_status == EquipmentLifecycleStatus.EXISTING
        assert machine.physical_envelope is None

    def test_machine_accepts_full_phase3a_metadata(self):
        machine = Machine(
            **minimal_machine(
                asset=create_proxy_asset(manufacturer="Acme", model_number="X-1"),
                lifecycle_status=EquipmentLifecycleStatus.PURCHASE_CANDIDATE,
                physical_envelope=MachineEnvelopeExtras(height=2.4, safety_clearance_front=1.0),
            )
        )
        assert machine.asset.asset_type == EquipmentAssetType.PROXY
        assert machine.lifecycle_status == EquipmentLifecycleStatus.PURCHASE_CANDIDATE
        assert machine.physical_envelope.height == 2.4

    def test_width_length_remain_required_single_source_of_truth(self):
        """MachineEnvelopeExtras never carries width/length — Machine's own
        fields are the only place footprint lives."""
        extras_fields = MachineEnvelopeExtras.model_fields.keys()
        assert "width" not in extras_fields
        assert "length" not in extras_fields


# 3. Layout domain models

class TestMachinePlacementModel:
    def test_valid_construction(self):
        p = MachinePlacement(machine_id="m-1", x=5.0, y=3.0, rotation_deg=90.0)
        assert p.z == 0.0  # default

    def test_nan_x_rejected(self):
        with pytest.raises(ValidationError):
            MachinePlacement(machine_id="m-1", x=float("nan"), y=0.0)

    def test_inf_y_rejected(self):
        with pytest.raises(ValidationError):
            MachinePlacement(machine_id="m-1", x=0.0, y=float("inf"))

    def test_nan_rotation_rejected(self):
        with pytest.raises(ValidationError):
            MachinePlacement(machine_id="m-1", x=0.0, y=0.0, rotation_deg=float("nan"))

    def test_frozen(self):
        p = MachinePlacement(machine_id="m-1", x=0.0, y=0.0)
        with pytest.raises(ValidationError):
            p.x = 5.0

    def test_serializable(self):
        p = MachinePlacement(machine_id="m-1", x=1.0, y=2.0, z=0.5, rotation_deg=180.0)
        restored = MachinePlacement.model_validate(p.model_dump())
        assert restored == p


class TestMachinePhysicalEnvelopeModel:
    def test_valid_construction(self):
        env = MachinePhysicalEnvelope(width=3.2, length=2.1, height=2.4)
        assert env.safety_clearance_front == 0.0  # default

    def test_height_optional(self):
        env = MachinePhysicalEnvelope(width=1.0, length=1.0)
        assert env.height is None

    def test_width_must_be_positive(self):
        with pytest.raises(ValidationError):
            MachinePhysicalEnvelope(width=0.0, length=1.0)

    def test_clearance_cannot_be_negative(self):
        with pytest.raises(ValidationError):
            MachinePhysicalEnvelope(width=1.0, length=1.0, safety_clearance_front=-0.5)

    def test_zero_clearance_valid(self):
        env = MachinePhysicalEnvelope(width=1.0, length=1.0, safety_clearance_front=0.0)
        assert env.safety_clearance_front == 0.0


class TestLayoutZoneModel:
    def test_valid_construction(self):
        zone = LayoutZone(id="z-1", name="Main Aisle", x=0.0, y=0.0, width=2.0, length=40.0, zone_type=LayoutZoneType.AISLE)
        assert zone.zone_type == LayoutZoneType.AISLE

    def test_all_zone_types_constructible(self):
        for zt in LayoutZoneType:
            zone = LayoutZone(id="z", name="Z", x=0.0, y=0.0, width=1.0, length=1.0, zone_type=zt)
            assert zone.zone_type == zt

    def test_serializable(self):
        zone = LayoutZone(id="z-1", name="Input Dock", x=1.0, y=1.0, width=3.0, length=3.0, zone_type=LayoutZoneType.INPUT)
        dumped = zone.model_dump_json()
        restored = LayoutZone.model_validate_json(dumped)
        assert restored == zone

    def test_negative_width_rejected(self):
        with pytest.raises(ValidationError):
            LayoutZone(id="z", name="Z", x=0.0, y=0.0, width=-1.0, length=1.0, zone_type=LayoutZoneType.SAFETY)


class TestFactoryLayoutModel:
    def test_empty_layout_construction(self):
        layout = FactoryLayout(factory_width=50.0, factory_length=20.0)
        assert layout.placements == []
        assert layout.reserved_zones == []
        assert layout.aisle_zones == []

    def test_layout_with_zones_serializable(self):
        layout = FactoryLayout(
            factory_width=50.0,
            factory_length=20.0,
            reserved_zones=[
                LayoutZone(id="r-1", name="Reserved", x=0.0, y=0.0, width=2.0, length=2.0, zone_type=LayoutZoneType.RESERVED)
            ],
            aisle_zones=[
                LayoutZone(id="a-1", name="Main Aisle", x=0.0, y=10.0, width=50.0, length=2.0, zone_type=LayoutZoneType.AISLE)
            ],
        )
        dumped = layout.model_dump_json()
        restored = FactoryLayout.model_validate_json(dumped)
        assert restored == layout


# 4. Layout service

class TestLayoutServiceCreate:
    def test_create_layout_sized_to_factory(self, electronics_factory: Factory):
        layout = create_layout(electronics_factory)
        assert layout.factory_width == electronics_factory.width
        assert layout.factory_length == electronics_factory.length
        assert layout.placements == []


class TestLayoutServicePlace:
    def test_place_machine(self, electronics_factory: Factory):
        layout = create_layout(electronics_factory)
        result = place_machine(electronics_factory, layout, "m-assembly", x=5.0, y=5.0, rotation_deg=0.0)
        placement = get_placement(result, "m-assembly")
        assert placement is not None
        assert placement.x == 5.0
        assert placement.y == 5.0

    def test_place_does_not_mutate_original_layout(self, electronics_factory: Factory):
        layout = create_layout(electronics_factory)
        result = place_machine(electronics_factory, layout, "m-assembly", x=5.0, y=5.0)
        assert layout.placements == []
        assert len(result.placements) == 1

    def test_place_nonexistent_machine_rejected(self, electronics_factory: Factory):
        layout = create_layout(electronics_factory)
        with pytest.raises(MachineNotFoundForLayoutError):
            place_machine(electronics_factory, layout, "does-not-exist", x=0.0, y=0.0)

    def test_duplicate_placement_rejected(self, electronics_factory: Factory):
        layout = create_layout(electronics_factory)
        layout = place_machine(electronics_factory, layout, "m-assembly", x=5.0, y=5.0)
        with pytest.raises(DuplicatePlacementError):
            place_machine(electronics_factory, layout, "m-assembly", x=10.0, y=10.0)

    def test_nan_coordinate_rejected(self, electronics_factory: Factory):
        layout = create_layout(electronics_factory)
        with pytest.raises(InvalidCoordinateError):
            place_machine(electronics_factory, layout, "m-assembly", x=float("nan"), y=0.0)

    def test_inf_coordinate_rejected(self, electronics_factory: Factory):
        layout = create_layout(electronics_factory)
        with pytest.raises(InvalidCoordinateError):
            place_machine(electronics_factory, layout, "m-assembly", x=float("inf"), y=0.0)

    def test_multiple_distinct_machines_placeable(self, electronics_factory: Factory):
        layout = create_layout(electronics_factory)
        layout = place_machine(electronics_factory, layout, "m-assembly", x=5.0, y=5.0)
        layout = place_machine(electronics_factory, layout, "m-screwdriving", x=12.0, y=5.0)
        assert len(layout.placements) == 2


class TestLayoutServiceMove:
    def test_move_updates_position(self, electronics_factory: Factory):
        layout = create_layout(electronics_factory)
        layout = place_machine(electronics_factory, layout, "m-assembly", x=5.0, y=5.0, rotation_deg=30.0)
        moved = move_machine(layout, "m-assembly", x=10.0, y=15.0)
        placement = get_placement(moved, "m-assembly")
        assert placement.x == 10.0
        assert placement.y == 15.0

    def test_move_preserves_rotation(self, electronics_factory: Factory):
        layout = create_layout(electronics_factory)
        layout = place_machine(electronics_factory, layout, "m-assembly", x=5.0, y=5.0, rotation_deg=30.0)
        moved = move_machine(layout, "m-assembly", x=10.0, y=15.0)
        assert get_placement(moved, "m-assembly").rotation_deg == 30.0

    def test_move_does_not_mutate_original(self, electronics_factory: Factory):
        layout = create_layout(electronics_factory)
        layout = place_machine(electronics_factory, layout, "m-assembly", x=5.0, y=5.0)
        moved = move_machine(layout, "m-assembly", x=99.0, y=99.0)
        assert get_placement(layout, "m-assembly").x == 5.0
        assert get_placement(moved, "m-assembly").x == 99.0

    def test_move_nonexistent_placement_rejected(self, electronics_factory: Factory):
        layout = create_layout(electronics_factory)
        with pytest.raises(PlacementNotFoundError):
            move_machine(layout, "m-assembly", x=1.0, y=1.0)

    def test_move_nan_rejected(self, electronics_factory: Factory):
        layout = create_layout(electronics_factory)
        layout = place_machine(electronics_factory, layout, "m-assembly", x=5.0, y=5.0)
        with pytest.raises(InvalidCoordinateError):
            move_machine(layout, "m-assembly", x=float("nan"), y=0.0)


class TestLayoutServiceRotate:
    def test_rotate_updates_rotation(self, electronics_factory: Factory):
        layout = create_layout(electronics_factory)
        layout = place_machine(electronics_factory, layout, "m-assembly", x=5.0, y=5.0)
        rotated = rotate_machine(layout, "m-assembly", rotation_deg=270.0)
        assert get_placement(rotated, "m-assembly").rotation_deg == 270.0

    def test_rotate_preserves_position(self, electronics_factory: Factory):
        layout = create_layout(electronics_factory)
        layout = place_machine(electronics_factory, layout, "m-assembly", x=5.0, y=5.0)
        rotated = rotate_machine(layout, "m-assembly", rotation_deg=270.0)
        placement = get_placement(rotated, "m-assembly")
        assert placement.x == 5.0 and placement.y == 5.0

    def test_rotate_does_not_mutate_original(self, electronics_factory: Factory):
        layout = create_layout(electronics_factory)
        layout = place_machine(electronics_factory, layout, "m-assembly", x=5.0, y=5.0, rotation_deg=0.0)
        rotate_machine(layout, "m-assembly", rotation_deg=90.0)
        assert get_placement(layout, "m-assembly").rotation_deg == 0.0

    def test_rotate_nonexistent_placement_rejected(self, electronics_factory: Factory):
        layout = create_layout(electronics_factory)
        with pytest.raises(PlacementNotFoundError):
            rotate_machine(layout, "m-assembly", rotation_deg=45.0)


class TestLayoutServiceRemove:
    def test_remove_placement(self, electronics_factory: Factory):
        layout = create_layout(electronics_factory)
        layout = place_machine(electronics_factory, layout, "m-assembly", x=5.0, y=5.0)
        layout = place_machine(electronics_factory, layout, "m-screwdriving", x=12.0, y=5.0)
        removed = remove_placement(layout, "m-assembly")
        assert get_placement(removed, "m-assembly") is None
        assert get_placement(removed, "m-screwdriving") is not None

    def test_remove_does_not_mutate_original(self, electronics_factory: Factory):
        layout = create_layout(electronics_factory)
        layout = place_machine(electronics_factory, layout, "m-assembly", x=5.0, y=5.0)
        remove_placement(layout, "m-assembly")
        assert get_placement(layout, "m-assembly") is not None

    def test_remove_nonexistent_placement_rejected(self, electronics_factory: Factory):
        layout = create_layout(electronics_factory)
        with pytest.raises(PlacementNotFoundError):
            remove_placement(layout, "m-assembly")


class TestLayoutServiceGetPlacement:
    def test_returns_none_when_absent(self, electronics_factory: Factory):
        layout = create_layout(electronics_factory)
        assert get_placement(layout, "m-assembly") is None

    def test_returns_placement_when_present(self, electronics_factory: Factory):
        layout = create_layout(electronics_factory)
        layout = place_machine(electronics_factory, layout, "m-assembly", x=1.0, y=2.0)
        assert get_placement(layout, "m-assembly").x == 1.0


# 5. machine_envelope helper

class TestMachineEnvelopeHelper:
    def test_uses_machine_width_length_as_footprint(self, electronics_factory: Factory):
        machine = electronics_factory.machines[0]
        env = machine_envelope(machine)
        assert env.width == machine.width
        assert env.length == machine.length

    def test_no_extras_defaults_to_zero_clearance_none_height(self, electronics_factory: Factory):
        env = machine_envelope(electronics_factory.machines[0])
        assert env.height is None
        assert env.safety_clearance_front == 0.0

    def test_extras_are_combined(self):
        machine = Machine(
            **minimal_machine(
                physical_envelope=MachineEnvelopeExtras(
                    height=2.4,
                    safety_clearance_front=1.0,
                    safety_clearance_back=0.5,
                    safety_clearance_left=0.3,
                    safety_clearance_right=0.3,
                )
            )
        )
        env = machine_envelope(machine)
        assert env.width == machine.width
        assert env.length == machine.length
        assert env.height == 2.4
        assert env.safety_clearance_front == 1.0
        assert env.safety_clearance_back == 0.5


# 6. Asset registry

class TestAssetRegistry:
    def test_register_and_lookup_by_manufacturer_model(self):
        registry = EquipmentAssetRegistry()
        asset = EquipmentAsset(
            asset_type=EquipmentAssetType.LIBRARY,
            status=EquipmentAssetStatus.AVAILABLE,
            asset_uri="https://library.example/model.gltf",
            manufacturer="Acme Robotics",
            model_number="AR-500",
        )
        registry.register(asset)
        found = registry.find_by_manufacturer_model("Acme Robotics", "AR-500")
        assert found == asset

    def test_lookup_unknown_manufacturer_model_returns_none(self):
        registry = EquipmentAssetRegistry()
        assert registry.find_by_manufacturer_model("Nobody", "X-1") is None

    def test_lookup_by_process_type(self):
        registry = EquipmentAssetRegistry()
        asset = create_proxy_asset(manufacturer="Acme Lasers", model_number="LWC-3200")
        registry.register(asset, process_type="welding")
        results = registry.find_by_process_type("welding")
        assert results == [asset]

    def test_lookup_unknown_process_type_returns_empty_list(self):
        registry = EquipmentAssetRegistry()
        assert registry.find_by_process_type("nonexistent") == []

    def test_explicit_manufacturer_model_override(self):
        """register() accepts explicit manufacturer/model_number that
        differ from the asset's own fields, for indexing convenience."""
        registry = EquipmentAssetRegistry()
        asset = create_proxy_asset()  # no manufacturer/model on the asset itself
        registry.register(asset, manufacturer="Acme", model_number="P-1")
        assert registry.find_by_manufacturer_model("Acme", "P-1") == asset

    def test_all_assets(self):
        registry = EquipmentAssetRegistry()
        a1 = create_proxy_asset(model_number="A")
        a2 = create_proxy_asset(model_number="B")
        registry.register(a1)
        registry.register(a2)
        assert registry.all_assets() == [a1, a2]

    def test_registry_does_not_hit_network(self):
        """
        Sanity check that the registry module has no HTTP/requests dependency — it is a
        pure in-memory abstraction.
        """
        import app.services.asset_registry as mod
        source = pathlib.Path(mod.__file__).read_text()
        assert "import requests" not in source
        assert "import httpx" not in source
        assert "grabcad.com" not in source.lower()
        assert "api.grabcad" not in source.lower()


# 7. Architectural rule — machine identity independent of visual asset

class TestArchitecturalRule:
    def test_missing_asset_machine_simulates_normally(self, electronics_factory: Factory):
        assert electronics_factory.machines[0].asset is None
        result = run_simulation(electronics_factory, "p-electronics-widget")
        assert result.completed_units > 0

    def test_proxy_asset_machine_simulates_identically_to_no_asset(self, electronics_factory: Factory):
        data = electronics_factory.model_dump()
        no_asset_result = run_simulation(Factory.model_validate(data), "p-electronics-widget")

        data["machines"][1]["asset"] = create_proxy_asset(
            manufacturer="Acme", model_number="X-1"
        ).model_dump()
        with_proxy_result = run_simulation(Factory.model_validate(data), "p-electronics-widget")

        assert no_asset_result.model_dump() == with_proxy_result.model_dump()

    def test_replacing_proxy_with_exact_cad_does_not_change_identity(self):
        machine_proxy = Machine(
            **minimal_machine(
                id="m-laser", name="Laser Welding Cell", process_type="welding",
                asset=create_proxy_asset(manufacturer="Acme Lasers", model_number="LWC-3200"),
            )
        )
        machine_exact = machine_proxy.model_copy(
            update={
                "asset": EquipmentAsset(
                    asset_type=EquipmentAssetType.EXACT_CAD,
                    status=EquipmentAssetStatus.AVAILABLE,
                    asset_uri="s3://bucket/laser-welding-cell.step",
                )
            }
        )
        assert machine_proxy.id == machine_exact.id
        assert machine_proxy.process_type == machine_exact.process_type
        assert machine_proxy.cycle_time == machine_exact.cycle_time
        assert machine_proxy.capacity == machine_exact.capacity
        assert machine_proxy.width == machine_exact.width
        assert machine_proxy.length == machine_exact.length
        assert machine_proxy.asset.asset_type != machine_exact.asset.asset_type  # only this changed

    def test_asset_replacement_does_not_change_simulation_result(self, electronics_factory: Factory):
        data = electronics_factory.model_dump()

        data_proxy = json.loads(json.dumps(data))
        data_proxy["machines"][1]["asset"] = create_proxy_asset(model_number="proxy-v1").model_dump()
        result_proxy = run_simulation(Factory.model_validate(data_proxy), "p-electronics-widget")

        data_exact = json.loads(json.dumps(data))
        data_exact["machines"][1]["asset"] = EquipmentAsset(
            asset_type=EquipmentAssetType.EXACT_CAD,
            status=EquipmentAssetStatus.AVAILABLE,
            asset_uri="s3://bucket/screwdriving-station.step",
        ).model_dump()
        result_exact = run_simulation(Factory.model_validate(data_exact), "p-electronics-widget")

        assert result_proxy.model_dump() == result_exact.model_dump()

    def test_asset_replacement_does_not_change_scenario_verdict(self, electronics_factory: Factory):
        data = electronics_factory.model_dump()
        data["machines"][1]["asset"] = create_proxy_asset(model_number="proxy-v1").model_dump()
        factory_with_asset = Factory.model_validate(data)

        scenario = Scenario(
            id="s-1", name="parallel screwdriving",
            actions=[AddParallelMachineAction(machine_id="m-screwdriving")],
        )
        with_asset_result = run_scenario(factory_with_asset, "p-electronics-widget", scenario)
        without_asset_result = run_scenario(electronics_factory, "p-electronics-widget", scenario)

        assert with_asset_result.verdict == without_asset_result.verdict
        assert with_asset_result.comparison.model_dump() == without_asset_result.comparison.model_dump()


# 8. ADD_PARALLEL_MACHINE + asset/envelope/lifecycle metadata

class TestAddParallelMachineAssetMetadata:
    @pytest.fixture
    def factory_with_asset(self, electronics_factory: Factory) -> Factory:
        data = electronics_factory.model_dump()
        data["machines"][1]["asset"] = create_proxy_asset(
            manufacturer="Acme", model_number="Screwdriver-9000"
        ).model_dump()
        data["machines"][1]["physical_envelope"] = MachineEnvelopeExtras(
            height=1.8, safety_clearance_front=0.5
        ).model_dump()
        return Factory.model_validate(data)

    def test_clone_copies_asset_verbatim(self, factory_with_asset: Factory):
        scenario = Scenario(id="s", name="x", actions=[AddParallelMachineAction(machine_id="m-screwdriving")])
        candidate = apply_scenario(factory_with_asset, scenario)
        source = next(m for m in factory_with_asset.machines if m.id == "m-screwdriving")
        clone = next(m for m in candidate.machines if m.id == "m-screwdriving-parallel-1")
        assert clone.asset == source.asset

    def test_clone_copies_physical_envelope_verbatim(self, factory_with_asset: Factory):
        scenario = Scenario(id="s", name="x", actions=[AddParallelMachineAction(machine_id="m-screwdriving")])
        candidate = apply_scenario(factory_with_asset, scenario)
        source = next(m for m in factory_with_asset.machines if m.id == "m-screwdriving")
        clone = next(m for m in candidate.machines if m.id == "m-screwdriving-parallel-1")
        assert clone.physical_envelope == source.physical_envelope

    def test_clone_gets_purchase_candidate_lifecycle_status(self, electronics_factory: Factory):
        scenario = Scenario(id="s", name="x", actions=[AddParallelMachineAction(machine_id="m-screwdriving")])
        candidate = apply_scenario(electronics_factory, scenario)
        clone = next(m for m in candidate.machines if m.id == "m-screwdriving-parallel-1")
        assert clone.lifecycle_status == EquipmentLifecycleStatus.PURCHASE_CANDIDATE

    def test_source_lifecycle_status_unaffected(self, electronics_factory: Factory):
        scenario = Scenario(id="s", name="x", actions=[AddParallelMachineAction(machine_id="m-screwdriving")])
        candidate = apply_scenario(electronics_factory, scenario)
        source_in_candidate = next(m for m in candidate.machines if m.id == "m-screwdriving")
        assert source_in_candidate.lifecycle_status == EquipmentLifecycleStatus.EXISTING
        assert electronics_factory.machines[1].lifecycle_status == EquipmentLifecycleStatus.EXISTING


# 9. Full worked example (mirrors final-report requirements)

class TestWorkedExample:
    def test_existing_machine_with_library_asset(self):
        machine = Machine(
            **minimal_machine(
                id="m-assembly", name="Assembly Station",
                lifecycle_status=EquipmentLifecycleStatus.EXISTING,
                asset=EquipmentAsset(
                    asset_type=EquipmentAssetType.LIBRARY,
                    status=EquipmentAssetStatus.AVAILABLE,
                    asset_uri="https://library.example/assembly-station.gltf",
                    manufacturer="Generic Fixtures Co",
                    model_number="GF-ASM-1",
                ),
            )
        )
        assert machine.lifecycle_status == EquipmentLifecycleStatus.EXISTING
        assert machine.asset.asset_type == EquipmentAssetType.LIBRARY
        assert machine.asset.status == EquipmentAssetStatus.AVAILABLE

    def test_purchase_candidate_with_proxy(self):
        machine = Machine(
            **minimal_machine(
                id="m-laser", name="Laser Welding Cell", process_type="welding",
                width=3.2, length=2.1,
                lifecycle_status=EquipmentLifecycleStatus.PURCHASE_CANDIDATE,
                asset=create_proxy_asset(manufacturer="Acme Lasers", model_number="LWC-3200"),
                physical_envelope=MachineEnvelopeExtras(height=2.4),
            )
        )
        assert machine.lifecycle_status == EquipmentLifecycleStatus.PURCHASE_CANDIDATE
        assert machine.asset.asset_type == EquipmentAssetType.PROXY
        assert machine.physical_envelope.height == 2.4

    def test_custom_design_with_missing_asset(self):
        machine = Machine(
            **minimal_machine(
                id="m-custom", name="Custom Fixture Cell",
                lifecycle_status=EquipmentLifecycleStatus.CUSTOM_DESIGN,
                asset=EquipmentAsset(asset_type=EquipmentAssetType.MISSING, status=EquipmentAssetStatus.REQUESTED),
            )
        )
        assert machine.lifecycle_status == EquipmentLifecycleStatus.CUSTOM_DESIGN
        assert machine.asset.asset_type == EquipmentAssetType.MISSING
        assert machine.asset.status == EquipmentAssetStatus.REQUESTED

    def test_factory_layout_containing_all_three(self):
        factory = Factory(
            **minimal_factory(
                machines=[
                    minimal_machine(
                        id="m-assembly", name="Assembly Station",
                        lifecycle_status=EquipmentLifecycleStatus.EXISTING,
                        asset=EquipmentAsset(
                            asset_type=EquipmentAssetType.LIBRARY,
                            status=EquipmentAssetStatus.AVAILABLE,
                            asset_uri="https://library.example/assembly-station.gltf",
                        ),
                    ),
                    minimal_machine(
                        id="m-laser", name="Laser Welding Cell", process_type="welding",
                        width=3.2, length=2.1, position_x=10.0,
                        lifecycle_status=EquipmentLifecycleStatus.PURCHASE_CANDIDATE,
                        asset=create_proxy_asset(manufacturer="Acme Lasers", model_number="LWC-3200"),
                    ),
                    minimal_machine(
                        id="m-custom", name="Custom Fixture Cell", position_x=20.0,
                        lifecycle_status=EquipmentLifecycleStatus.CUSTOM_DESIGN,
                        asset=EquipmentAsset(asset_type=EquipmentAssetType.MISSING, status=EquipmentAssetStatus.REQUESTED),
                    ),
                ]
            )
        )
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-assembly", x=5.0, y=5.0)
        layout = place_machine(factory, layout, "m-laser", x=10.0, y=5.0, rotation_deg=90.0)
        layout = place_machine(factory, layout, "m-custom", x=20.0, y=5.0)

        assert len(layout.placements) == 3
        assert {p.machine_id for p in layout.placements} == {"m-assembly", "m-laser", "m-custom"}
