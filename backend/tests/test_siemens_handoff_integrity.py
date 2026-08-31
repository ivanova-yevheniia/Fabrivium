"""P0 — Siemens handoff integrity."""

from __future__ import annotations

import math
import pathlib

import pytest

from app.integrations.plant_simulation.adapter import (
    HandoffResult,
    LinkCheck,
    PositionCheck,
    StationCheck,
    assign_identifiers,
    simtalk_identifier,
)
from app.integrations.plant_simulation.exchange_schema import FactoryMindExchange
from app.integrations.plant_simulation.layout import (
    ICON_UNITS,
    MAX_COORDINATE,
    MIN_ANCHOR,
    MIN_SEPARATION_UNITS,
    collisions,
    generated_line,
    plan_layout,
    separation,
)


def package(names: list[str], *, with_buffers: bool = False, coords=None) -> FactoryMindExchange:
    stations = []
    for index, name in enumerate(names):
        station = {
            "id": f"s{index}",
            "name": name,
            "process_type": "assembly",
            "cycle_time_seconds": 10.0 + index,
            "capacity": 1,
            "operators_required": 1,
        }
        if coords is not None:
            station["x"], station["y"] = coords[index]
        stations.append(station)

    buffers = []
    if with_buffers:
        for index in range(len(names) - 1):
            buffers.append(
                {
                    "id": f"b{index}",
                    "name": f"{names[index]}_{names[index + 1]}",
                    "capacity": 5,
                    "upstream_station_id": f"s{index}",
                    "downstream_station_id": f"s{index + 1}",
                }
            )

    return FactoryMindExchange.model_validate(
        {
            "project_name": "P",
            "factory_name": "F",
            "product_name": "Product",
            "stations": stations,
            "flow": [],
            "buffers": buffers,
            "resources": {
                "shifts_per_day": 2,
                "hours_per_shift": 8.0,
                "operators_available": 8,
                "production_target_per_day": 1000.0,
            },
        }
    )


def chain_of(names: list[str]) -> list[str]:
    return ["Source", *[simtalk_identifier(n) for n in names], "Drain"]


# 8 — identifiers

class TestIdentifiers:
    def test_distinct_stations_never_collapse_into_one_object(self):
        """The normalisation is many-to-one, so the ASSIGNMENT must not be."""
        names = ["Assembly Station", "Assembly-Station", "Assembly/Station", "Assembly.Station"]
        assigned = assign_identifiers(package(names))

        assert len(set(assigned.values())) == 4
        assert simtalk_identifier(names[0]) in assigned.values()

    def test_a_station_cannot_take_the_frame_s_own_object_names(self):
        assigned = assign_identifiers(package(["Source", "Drain", "Packaging"]))
        assert "Source" not in assigned.values()
        assert "Drain" not in assigned.values()

    def test_the_first_claimant_keeps_the_plain_name(self):
        """A package with no clash must produce exactly the names it always
        did, or every existing model changes shape for no reason."""
        assigned = assign_identifiers(package(["Assembly", "Packaging"]))
        assert list(assigned.values()) == ["Assembly", "Packaging"]

    def test_buffers_share_the_namespace_with_stations(self):
        pkg = package(["Weld", "Test"], with_buffers=True)
        assigned = assign_identifiers(pkg)
        assert len(set(assigned.values())) == len(assigned)

    def test_assignment_is_deterministic(self):
        pkg = package(["Assembly Station", "Assembly-Station"])
        assert assign_identifiers(pkg) == assign_identifiers(pkg)

    def test_every_identifier_is_a_legal_simtalk_name(self):
        assigned = assign_identifiers(package(["6 axis robot", "Löten!", "A/B", "A B"]))
        for identifier in assigned.values():
            assert identifier
            assert not identifier[0].isdigit()
            assert all(c.isalnum() or c == "_" for c in identifier)


# 1-5, 12 — geometry

class TestGeometry:
    def test_no_two_objects_share_a_coordinate(self):
        """The original defect, in one assertion."""
        pkg = package([f"Station {i}" for i in range(6)], with_buffers=True)
        plan = plan_layout(chain_of([f"Station {i}" for i in range(6)]) , neighbours=_neighbours(pkg))
        positions = list(plan.positions.values())
        assert len(set(positions)) == len(positions)

    def test_minimum_spacing_is_enforced(self):
        plan = generated_line(chain_of([f"S{i}" for i in range(8)]))
        assert plan.min_separation >= MIN_SEPARATION_UNITS
        assert collisions(plan.positions) == []

    def test_source_and_drain_do_not_collide_with_any_station(self):
        names = [f"S{i}" for i in range(5)]
        plan = generated_line(chain_of(names))
        for station in (simtalk_identifier(n) for n in names):
            for terminal in ("Source", "Drain"):
                assert separation(plan.positions[terminal], plan.positions[station]) >= ICON_UNITS

    def test_buffers_do_not_inherit_one_shared_coordinate(self):
        """Every derived object gets its own place, or several buffers stack
        on the same point exactly as the stations once did."""
        names = ["A", "B", "C", "D"]
        pkg = package(names, with_buffers=True, coords=[(0, 0), (5, 0), (10, 0), (15, 0)])
        plan = plan_layout(
            _chain_with_buffers(names),
            concept_points={simtalk_identifier(n): c for n, c in zip(names, [(0, 0), (5, 0), (10, 0), (15, 0)])},
            neighbours=_neighbours(pkg, buffers=True),
        )
        # Named explicitly rather than sniffed out of the string, so the
        buffer_names = [simtalk_identifier(f"{a}_{b}") for a, b in zip(names, names[1:])]
        buffer_positions = [plan.positions[name] for name in buffer_names]

        assert len(set(plan.positions.values())) == len(plan.positions)
        assert len(set(buffer_positions)) == len(buffer_names)

    def test_coordinates_stay_finite_and_inside_the_frame(self):
        plan = generated_line(chain_of([f"S{i}" for i in range(30)]))
        for x, y in plan.positions.values():
            assert math.isfinite(x) and math.isfinite(y)
            assert MIN_ANCHOR <= x <= MAX_COORDINATE
            assert MIN_ANCHOR <= y <= MAX_COORDINATE

    def test_nothing_is_placed_where_the_product_would_clamp_it(self):
        """createObject silently clamps anything below 20 to 20 — which is
        how four stations were created on one point without an error."""
        plan = generated_line(chain_of(["A", "B", "C"]))
        assert all(x > MIN_ANCHOR and y > MIN_ANCHOR for x, y in plan.positions.values())

    def test_a_concept_that_cannot_be_separated_falls_back_and_says_why(self):
        names = ["A", "B"]
        pkg = package(names, coords=[(1.0, 1.0), (1.0, 1.0)])
        plan = plan_layout(
            chain_of(names),
            concept_points={simtalk_identifier(n): (1.0, 1.0) for n in names},
            neighbours=_neighbours(pkg),
        )
        assert plan.mode == "generated-line"
        assert plan.reason
        assert collisions(plan.positions) == []

    def test_collision_detection_actually_catches_an_overlap(self):
        """The check has to be able to fail, or it proves nothing."""
        overlapping = {"A": (100, 100), "B": (100 + ICON_UNITS - 1, 100)}
        assert collisions(overlapping)


def _neighbours(pkg: FactoryMindExchange, buffers: bool = False):
    names = [simtalk_identifier(s.name) for s in pkg.stations]
    chain = _chain_with_buffers([s.name for s in pkg.stations]) if buffers else ["Source", *names, "Drain"]
    return {
        name: (
            chain[i - 1] if i > 0 else None,
            chain[i + 1] if i + 1 < len(chain) else None,
        )
        for i, name in enumerate(chain)
    }


def _chain_with_buffers(names: list[str]) -> list[str]:
    chain = ["Source"]
    for index, name in enumerate(names):
        chain.append(simtalk_identifier(name))
        if index + 1 < len(names):
            chain.append(simtalk_identifier(f"{name}_{names[index + 1]}"))
    chain.append("Drain")
    return chain


# 6, 7 — topology

class TestTopology:
    def test_a_serial_route_produces_a_complete_source_to_drain_chain(self):
        names = [f"S{i}" for i in range(6)]
        plan = generated_line(chain_of(names))
        assert plan.chain[0] == "Source"
        assert plan.chain[-1] == "Drain"
        assert len(plan.chain) == len(names) + 2
        assert set(plan.positions) == set(plan.chain)

    def test_every_object_on_the_chain_receives_a_position(self):
        names = ["A", "B", "C"]
        pkg = package(names, with_buffers=True)
        plan = plan_layout(_chain_with_buffers(names), neighbours=_neighbours(pkg, buffers=True))
        assert set(plan.positions) == set(plan.chain)

    def test_a_multi_capacity_station_does_not_change_the_topology(self):
        """Capacity is built as a different Plant Simulation class; the route
        it sits on is the same route."""
        names = ["A", "B"]
        plan = generated_line(chain_of(names))
        assert plan.chain == ["Source", "A", "B", "Drain"]


# 13, 14 — what a claim may say

def _result(**kwargs) -> HandoffResult:
    result = HandoffResult()
    for key, value in kwargs.items():
        setattr(result, key, value)
    return result


def _station(ok: bool = True) -> StationCheck:
    return StationCheck(
        station_id="s0",
        source_name="A",
        name_expected="A",
        name_actual="A" if ok else None,
        cycle_time_expected=10.0,
        cycle_time_actual=10.0 if ok else 99.0,
        capacity_expected=1,
        capacity_actual=1,
    )


def _position(ok: bool = True) -> PositionCheck:
    return PositionCheck(name="A", x_expected=100, y_expected=100,
                         x_actual=100 if ok else 20, y_actual=100 if ok else 20)


def _link(ok: bool = True) -> LinkCheck:
    return LinkCheck(from_name="Source", to_name="A", actual_successor="A" if ok else None)


class TestClaims:
    def test_structure_green_does_not_make_layout_green(self):
        """The exact shape of the original defect: contents verified, model
        unusable."""
        result = _result(
            stations=[_station(ok=True)],
            positions=[_position(ok=False)],
            overlaps=["A and B are 0 units apart"],
            links=[_link(ok=True)],
            route_complete=True,
        )
        tiers = {tier.tier: tier.status for tier in result.tiers()}
        assert tiers["STRUCTURE"] == "VERIFIED"
        assert tiers["LAYOUT"] == "FAILED"

    def test_a_failed_layer_means_the_handoff_is_not_fully_verified(self):
        result = _result(
            stations=[_station()], positions=[_position(ok=False)],
            links=[_link()], route_complete=True,
        )
        assert result.fully_verified is False

    def test_runtime_is_not_run_when_no_smoke_run_happened(self):
        result = _result(
            stations=[_station()], positions=[_position()],
            links=[_link()], route_complete=True,
        )
        runtime = next(t for t in result.tiers() if t.tier == "RUNTIME")
        assert runtime.status == "NOT_RUN"
        assert "no smoke run" in runtime.detail

    def test_not_run_is_not_a_failure(self):
        """A handoff without a smoke run is a weaker claim, not a broken one."""
        result = _result(
            stations=[_station()], positions=[_position()],
            links=[_link()], route_complete=True,
        )
        assert result.fully_verified is True

    def test_runtime_verified_requires_a_unit_to_have_arrived(self):
        result = _result(
            stations=[_station()], positions=[_position()], links=[_link()],
            route_complete=True, traversal_units=0, traversal_verified=False,
        )
        runtime = next(t for t in result.tiers() if t.tier == "RUNTIME")
        assert runtime.status == "FAILED"

    def test_flow_fails_when_an_object_sits_off_the_route(self):
        result = _result(
            stations=[_station()], positions=[_position()], links=[_link()],
            route_complete=False, disconnected=["Packaging"],
        )
        flow = next(t for t in result.tiers() if t.tier == "FLOW")
        assert flow.status == "FAILED"
        assert "Packaging" in flow.detail

    def test_every_tier_carries_the_evidence_behind_it(self):
        result = _result(
            stations=[_station()], positions=[_position()], links=[_link()],
            route_complete=True, layout_min_separation=90,
        )
        for tier in result.tiers():
            assert tier.detail, f"{tier.tier} states a verdict with no evidence"


# 15 — equipment metadata

class TestEquipmentMetadataCannotChangeTheModel:
    def test_a_selected_candidate_does_not_touch_the_station_s_values(self):
        """Equipment travels as text on the station."""
        from app.integrations.plant_simulation.from_factory import exchange_from_factory
        from app.models.factory import Factory

        factory = Factory.model_validate(
            {
                "id": "f", "name": "F", "width": 30.0, "length": 18.0,
                "shifts_per_day": 2, "hours_per_shift": 8.0, "operators_available": 8,
                "machines": [
                    {"id": "m1", "name": "Screwdriving", "process_type": "screwdriving",
                     "width": 2.0, "length": 2.0, "capacity": 1, "operators_required": 1,
                     "cycle_time": 42.0},
                ],
                "products": [
                    {"id": "p", "name": "P", "demand_per_day": 100.0,
                     "route": [{"machine_id": "m1", "name": "Screw", "cycle_time": 42.0}]},
                ],
                "buffers": [],
            }
        )

        plain = exchange_from_factory(factory, "p")
        with_equipment = exchange_from_factory(
            factory,
            "p",
            equipment_selections={
                "m1": {"manufacturer": "Kolver", "model": "KDS-NT120CA",
                       "source_url": "https://example.invalid/x.pdf"}
            },
        )

        assert plain.stations[0].cycle_time_seconds == 42.0
        assert with_equipment.stations[0].cycle_time_seconds == 42.0
        assert with_equipment.stations[0].capacity == plain.stations[0].capacity
        assert with_equipment.stations[0].operators_required == plain.stations[0].operators_required
        # It travels, as metadata, and only as metadata.
        assert with_equipment.stations[0].selected_model == "KDS-NT120CA"


# 9, 10, 11 — read-back stays honest

class TestReadBack:
    def test_a_wrong_cycle_time_is_not_verified(self):
        assert _station(ok=False).verified is False

    def test_a_clamped_position_is_not_verified(self):
        """20/20 is what the product returns when it clamps."""
        assert _position(ok=False).verified is False

    def test_a_missing_successor_is_not_a_verified_link(self):
        assert _link(ok=False).verified is False

    def test_counts_come_from_read_back_not_from_what_was_sent(self):
        result = _result(stations=[_station(ok=True), _station(ok=False)])
        structure = next(t for t in result.tiers() if t.tier == "STRUCTURE")
        assert structure.status == "FAILED"
        assert "1/2" in structure.detail


# The engineering manifest

class TestManifest:
    """
    It was written once, silently failed on a wrong attribute name, and looked exactly
    like "no manifest was requested".
    """

    def test_a_manifest_is_written_beside_the_model(self, tmp_path):
        from app.main import _write_handoff_manifest

        pkg = package(["Assembly", "Packaging"])
        result = _result(
            model_path=str(tmp_path / "concept.spp"),
            stations=[_station()],
            positions=[_position()],
            links=[_link()],
            route_complete=True,
            product_version="Plant Simulation 2404",
        )
        (tmp_path / "concept.spp").write_bytes(b"x")

        path, warning = _write_handoff_manifest(pkg, result)

        assert warning is None
        assert path is not None
        text = pathlib.Path(path).read_text(encoding="utf-8")
        assert "Plant Simulation 2404" in text
        assert "STRUCTURE" in text and "LAYOUT" in text and "FLOW" in text and "RUNTIME" in text
        # The limitations travel with the file, not only with the screen.
        assert "workforce" in text.lower() or "operator pool" in text.lower()
        assert "UNDER CONSIDERATION" in text

    def test_no_manifest_is_claimed_when_no_model_was_written(self, tmp_path):
        from app.main import _write_handoff_manifest

        path, warning = _write_handoff_manifest(package(["A"]), _result(model_path=None))
        assert path is None
        assert warning is None

    def test_a_failure_to_write_is_reported_rather_than_swallowed(self):
        from app.main import _write_handoff_manifest

        # An unwritable path: the manifest must not silently vanish.
        result = _result(model_path="Z:/does/not/exist/concept.spp", stations=[_station()])
        path, warning = _write_handoff_manifest(package(["A"]), result)
        assert path is None
        assert warning and "manifest" in warning.lower()
