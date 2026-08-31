"""FactoryMind Phase 6A.1 - per-iteration digital-twin snapshot tests."""

from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.agent import PlanningRequirements
from app.models.factory import Factory
from app.models.optimization import OptimizationObjective
from app.services.constraints import validate_layout
from app.services.layout import create_layout, place_machine
from app.services.planning_orchestrator import PlanningOrchestrator

EXAMPLES_DIR = pathlib.Path(__file__).parent.parent.parent / "examples"
PRODUCT_ID = "p-electronics-widget"


def _load_electronics() -> Factory:
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        return Factory.model_validate(json.load(fh))


@pytest.fixture
def electronics_factory() -> Factory:
    return _load_electronics()


def _reqs(**overrides) -> PlanningRequirements:
    base = dict(objective=OptimizationObjective.MEET_DEMAND)
    base.update(overrides)
    return PlanningRequirements(**base)


def _run(factory: Factory, reqs: PlanningRequirements, **kwargs):
    return PlanningOrchestrator().run(factory, PRODUCT_ID, reqs, max_iterations=5, **kwargs)


REQS_B = lambda: _reqs(target_units_per_day=1900.0)

# Phase 8A.
REQS_E = lambda: _reqs(
    target_units_per_day=1200.0,
    forbidden_machine_ids=["m-screwdriving", "m-assembly", "m-inspection"],
    notes=["User explicitly requested: ADD_PARALLEL_MACHINE at m-packaging."],
    allowed_action_types=["ADD_PARALLEL_MACHINE"],
)


# 1-2. Accepted iterations / chaining invariant

class TestAcceptedSnapshots:
    def test_accepted_iteration_has_exact_before_and_after(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_B())
        for it in state.iterations:
            assert it.accepted is True
            assert it.state_before is not None
            assert it.state_after is not None
            assert it.rejected_candidate_snapshot is None

    def test_after_machine_count_increases_by_exactly_one_clone(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_B())
        it0 = state.iterations[0]
        assert len(it0.state_after.factory.machines) == len(it0.state_before.factory.machines) + 1

    def test_state_after_bottleneck_matches_its_own_simulation(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_B())
        for it in state.iterations:
            assert it.state_after.bottleneck_machine_id == it.state_after.simulation.system.bottleneck_machine_id

    def test_iteration_n_after_equals_iteration_n_plus_1_before(self, electronics_factory: Factory):
        """Phase 8A: the 1900/day plan is three steps now (relieve
        Screwdriving, hire the staff the next machine needs, then buy it),
        so this asserts the chaining invariant across EVERY consecutive
        pair rather than just the first — which is what it always meant.
        """
        state = _run(electronics_factory, REQS_B())
        assert len(state.iterations) == 3
        for earlier, later in zip(state.iterations, state.iterations[1:]):
            if earlier.accepted:
                assert earlier.state_after.model_dump() == later.state_before.model_dump()

    def test_cumulative_capex_accumulates_across_snapshots(self, electronics_factory: Factory):
        """
        Phase 8A: iteration 2 is now the staffing fix, whose cost is UNKNOWN rather than
        zero — so known CAPEX correctly does not move across it, then jumps when the
        machine it unlocked is bought.
        """
        state = _run(electronics_factory, REQS_B())
        assert state.iterations[0].state_before.cumulative_known_capex == 0.0
        assert state.iterations[0].state_after.cumulative_known_capex == 85_000.0

        # The staffing step: known CAPEX unchanged, cost flagged unknown.
        assert state.iterations[1].state_before.cumulative_known_capex == 85_000.0
        assert state.iterations[1].state_after.cumulative_known_capex == 85_000.0
        assert state.iterations[1].requires_cost_estimate is True

        assert state.iterations[2].state_before.cumulative_known_capex == 85_000.0
        assert state.iterations[2].state_after.cumulative_known_capex == 205_000.0


# 3. Baseline / final snapshot

class TestBaselineAndFinalSnapshot:
    def test_baseline_snapshot_matches_baseline_fields(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_B())
        # baseline_snapshot.factory is the DEMAND-ADJUSTED factory (target
        # applied, per apply_target_demand) — the same factory
        # baseline_simulation was actually run against. session.baseline_factory
        # is the untouched ORIGINAL (pre demand-target) — these legitimately
        # differ only in Product.demand_per_day; machines/layout are identical.
        assert state.baseline_snapshot.simulation.model_dump() == state.baseline_simulation.model_dump()
        assert state.baseline_snapshot.cumulative_known_capex == 0.0
        assert [m.model_dump() for m in state.baseline_snapshot.factory.machines] == [
            m.model_dump() for m in state.baseline_factory.machines
        ]
        assert state.baseline_snapshot.factory.products[0].demand_per_day == 1900.0
        assert state.baseline_factory.products[0].demand_per_day == 1200.0

    def test_final_snapshot_equals_current_state(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_B())
        assert state.final_snapshot.factory.model_dump() == state.current_factory.model_dump()
        assert state.final_snapshot.simulation.model_dump() == state.current_simulation.model_dump()
        assert state.final_snapshot.cumulative_known_capex == state.cumulative_known_capex

    def test_baseline_snapshot_unchanged_by_iterations(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_B())
        # The baseline factory never gained the machines that later iterations added.
        baseline_ids = {m.id for m in state.baseline_snapshot.factory.machines}
        assert "m-screwdriving-parallel-1" not in baseline_ids
        assert "m-assembly-parallel-1" not in baseline_ids
        assert baseline_ids == {m.id for m in electronics_factory.machines}

    def test_earlier_iteration_snapshot_unchanged_after_later_iterations(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_B())
        it0_after_before_dump = state.iterations[0].state_after.model_dump()
        # Force materialization of iteration 1 (already computed by run(),
        # but re-dumping it here proves iteration 0's own snapshot was
        # never touched by whatever produced iteration 1).
        _ = state.iterations[1].state_after.model_dump()
        assert state.iterations[0].state_after.model_dump() == it0_after_before_dump
        # And iteration 0's own machine set is still exactly one clone
        # added over baseline, not two.
        assert len(state.iterations[0].state_after.factory.machines) == len(state.baseline_snapshot.factory.machines) + 1


# 4. Rejected iterations

class TestRejectedSnapshots:
    def test_rejected_iteration_has_state_before_but_no_state_after(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_E())
        rejected = [it for it in state.iterations if not it.accepted and it.selected_proposal is not None]
        assert rejected, "expected at least one evaluated-and-rejected iteration"
        for it in rejected:
            assert it.state_before is not None
            assert it.state_after is None

    def test_rejected_candidate_snapshot_is_explicitly_labeled_separately(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_E())
        rejected = [it for it in state.iterations if not it.accepted and it.selected_proposal is not None]
        it = rejected[0]
        assert it.rejected_candidate_snapshot is not None
        # The candidate DID add a machine (Packaging clone)...
        assert len(it.rejected_candidate_snapshot.factory.machines) == len(it.state_before.factory.machines) + 1

    def test_rejected_candidate_never_becomes_current_state(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_E())
        rejected_ids = set()
        for it in state.iterations:
            if it.rejected_candidate_snapshot is not None:
                rejected_ids |= {m.id for m in it.rejected_candidate_snapshot.factory.machines}
        # None of the rejected candidate's NEW machines ended up in the
        # final accepted factory.
        final_ids = {m.id for m in state.final_snapshot.factory.machines}
        baseline_ids = {m.id for m in state.baseline_snapshot.factory.machines}
        assert (rejected_ids - baseline_ids) - final_ids == (rejected_ids - baseline_ids)

    def test_original_factory_untouched_by_rejected_candidate(self, electronics_factory: Factory):
        before = electronics_factory.model_dump()
        _run(electronics_factory, REQS_E())
        assert electronics_factory.model_dump() == before


# 5. Layout snapshots follow candidate placement

class TestLayoutSnapshots:
    def test_layout_snapshot_gains_new_placement_on_accept(self, electronics_factory: Factory):
        factory = electronics_factory.model_copy(update={"width": 200.0, "length": 100.0})
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-assembly", x=10.0, y=10.0)
        layout = place_machine(factory, layout, "m-screwdriving", x=20.0, y=10.0)
        layout = place_machine(factory, layout, "m-inspection", x=30.0, y=10.0)
        layout = place_machine(factory, layout, "m-packaging", x=40.0, y=10.0)
        assert validate_layout(factory, layout, PRODUCT_ID).error_count == 0

        state = _run(factory, _reqs(target_units_per_day=1200.0), layout=layout)
        it0 = state.iterations[0]
        assert it0.accepted is True
        assert it0.state_before.layout is not None
        assert it0.state_after.layout is not None
        assert len(it0.state_after.layout.placements) == len(it0.state_before.layout.placements) + 1

    def test_layout_none_never_fabricated_when_no_layout_supplied(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_B())
        assert state.baseline_snapshot.layout is None
        assert state.final_snapshot.layout is None
        for it in state.iterations:
            if it.state_before is not None:
                assert it.state_before.layout is None
            if it.state_after is not None:
                assert it.state_after.layout is None


# 6. API serialization

class TestApiSerialization:
    def test_planning_run_response_includes_snapshots(self, electronics_factory: Factory):
        client = TestClient(app)
        resp = client.post("/planning/run", json={
            "factory": electronics_factory.model_dump(),
            "product_id": PRODUCT_ID,
            "user_request": "We need 1900 units per day.",
        })
        assert resp.status_code == 200
        session = resp.json()["session"]
        assert session["baseline_snapshot"]["factory"]["machines"]
        assert session["final_snapshot"]["factory"]["machines"]
        it0 = session["iterations"][0]
        assert it0["state_before"] is not None
        assert it0["state_after"] is not None
        assert len(it0["state_after"]["factory"]["machines"]) == len(it0["state_before"]["factory"]["machines"]) + 1


# 7. 1900/day demonstration (section 9)

class TestDemonstration1900:
    def test_machine_evolution_matches_expected_narrative(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_B())

        baseline_ids = {m.id for m in state.baseline_snapshot.factory.machines}
        assert baseline_ids == {"m-assembly", "m-screwdriving", "m-inspection", "m-packaging"}

        after1_ids = {m.id for m in state.iterations[0].state_after.factory.machines}
        assert after1_ids == baseline_ids | {"m-screwdriving-parallel-1"}

        # Phase 8A: iteration 2 hires operators, so the machine set is
        # deliberately UNCHANGED here — the plan step that makes the third
        # one possible does not itself add equipment.
        after2_ids = {m.id for m in state.iterations[1].state_after.factory.machines}
        assert after2_ids == after1_ids
        assert state.iterations[1].state_after.factory.operators_available > (
            state.iterations[1].state_before.factory.operators_available
        )

        after3_ids = {m.id for m in state.iterations[2].state_after.factory.machines}
        assert after3_ids == after1_ids | {"m-assembly-parallel-1"}

        assert after3_ids == {m.id for m in state.final_snapshot.factory.machines}

    def test_kpis_correspond_to_each_snapshot(self, electronics_factory: Factory):
        """Phase 8A: the gap now closes in three measured steps."""
        state = _run(electronics_factory, REQS_B())
        assert state.baseline_snapshot.simulation.demand_gap_units == 795.0
        assert state.iterations[0].state_after.simulation.demand_gap_units == 281.0
        assert state.iterations[1].state_after.simulation.demand_gap_units == 258.0
        assert state.iterations[2].state_after.simulation.demand_gap_units == 0.0
        assert state.final_snapshot.simulation.demand_met is True

    def test_previous_snapshots_remain_unchanged_through_full_run(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_B())
        # Re-derive iteration 1's expected machine set independently and
        # compare — proves it was never mutated by iteration 2's work.
        expected_after1 = {"m-assembly", "m-screwdriving", "m-inspection", "m-packaging", "m-screwdriving-parallel-1"}
        assert {m.id for m in state.iterations[0].state_after.factory.machines} == expected_after1
        # Phase 8A: 281, not 258 — see test_kpis_correspond_to_each_snapshot.
        assert state.iterations[0].state_after.simulation.demand_gap_units == 281.0
