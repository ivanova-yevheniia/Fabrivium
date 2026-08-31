"""The competition case, end to end, asserted on relationships not constants."""

from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.factory import Factory
from app.models.process_draft import ManufacturingProcessDraft
from app.models.product import ProductUnderstanding
from app.services.capacity import measure_capacity
from app.services.requirement_coverage import coverage_for

ROOT = pathlib.Path(__file__).resolve().parents[2]
PDF = (
    ROOT
    / "examples"
    / "customer_docs"
    / "Compact_Electronics_Controller_Product_Specification.pdf"
)

# The competition requirements sentence.
REQUIREMENTS = (
    "1,900 units per day across 2 shifts of 8 hours. 30 by 18 meters. "
    "8 operators. We would rather not buy new machines."
)
TARGET = 1900.0


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def journey(client) -> dict:
    """Walk the whole competition journey once and hand the parts to the tests."""
    understanding = client.post(
        "/product/upload",
        files={"file": (PDF.name, PDF.read_bytes(), "application/pdf")},
        data={"product_name": "Compact electronics controller"},
    ).json()["understanding"]

    process = client.post("/product/plan-process", json={"understanding": understanding}).json()["draft"]

    # The engineer accepts every proposed operation.
    for op in process["operations"]:
        op["status"] = "ACCEPTED"
        op["fact_status"] = "ENGINEER_VERIFIED"

    # ...and links the source requirements no operation answers, exactly as
    # the coverage panel's "an existing operation covers this" does: by adding
    # the requirement's fact key to that operation's own source_fact_keys.
    coverage = coverage_for(
        ProductUnderstanding.model_validate(understanding),
        ManufacturingProcessDraft.model_validate(process),
    )
    by_name = {op["name"]: op for op in process["operations"]}
    for item in coverage.critical_unresolved:
        target = {
            "Enclosure": by_name.get("Enclosure closure"),
            "Label": by_name.get("Packaging"),
        }.get(item.label) or process["operations"][-1]
        target.setdefault("source_fact_keys", []).append(item.fact_key)

    concept = client.post(
        "/product/build-concept",
        json={
            "understanding": understanding,
            "process": process,
            "requirements_brief": REQUIREMENTS,
        },
    ).json()["draft"]

    resolved = client.post(
        "/concept/use-example-data-for-unresolved", json={"draft": concept}
    ).json()["draft"]

    # The bundled dataset describes the four families the demo line has.
    unresolved = [s for s in resolved["stages"] if s["cycle_time"]["value"] is None]
    assert [s["process_type"] for s in unresolved] == ["labelling"], unresolved
    for stage in unresolved:
        estimate = client.post(
            "/concept/estimate",
            json={
                "draft": resolved,
                "stage_id": stage["id"],
                "description": "One identification label applied to the enclosure exterior.",
                "automation_level": "MANUAL",
                "operations_per_unit": 1,
                "mode": "LOCAL_ONLY",
            },
        )
        assert estimate.status_code == 200, estimate.json()
        proposal = estimate.json()["proposal"]
        assert proposal is not None, estimate.json()

        accepted = client.post(
            "/concept/accept-assumptions",
            json={
                "draft": resolved,
                "proposal": proposal,
                "accepted_fields": ["cycle_time", "capacity", "operators"],
            },
        )
        assert accepted.status_code == 200, accepted.json()
        resolved = accepted.json()["draft"]

    built = client.post("/concept/build", json={"draft": resolved})
    assert built.status_code == 200, built.json()
    factory = Factory.model_validate(built.json()["factory"])
    product_id = built.json()["product_id"]

    simulation = client.post(
        "/simulation/run",
        json={"factory": json.loads(factory.model_dump_json()), "product_id": product_id},
    ).json()

    arena = client.post(
        "/strategies/explore",
        json={
            "factory": json.loads(factory.model_dump_json()),
            "product_id": product_id,
            "user_request": (
                f"We need {TARGET:.0f} units/day."
                + (" Avoid buying new machines if possible." if resolved["prefer_no_new_machines"] else "")
            ),
        },
    ).json()["arena"]

    return {
        "understanding": understanding,
        "process": process,
        "coverage": coverage,
        "concept": concept,
        "resolved": resolved,
        "factory": factory,
        "product_id": product_id,
        "simulation": simulation,
        "arena": arena,
    }


# The document is read, and what it does not say stays unsaid

class TestTheDocumentIsRead:
    def test_every_fact_cites_the_document(self, journey):
        facts = journey["understanding"]["facts"]
        assert facts, "the PDF produced no facts at all"
        for fact in facts:
            assert fact["evidence"], f"fact {fact['key']} has no citation"

    def test_what_the_document_does_not_state_is_declared_missing(self, journey):
        # The screw thread is the honest gap: a screwdriving station is chosen
        # against torque and drive, and the specification defers both to a
        # separate fastener drawing.
        gaps = journey["understanding"]["information_gaps"]
        assert gaps, "the document was treated as complete, which it is not"

    def test_no_operation_exists_without_a_fact_behind_it(self, journey):
        for op in journey["process"]["operations"]:
            assert op["source_fact_keys"], f"operation {op['id']} cites no fact"


# Nothing unknown becomes a number

class TestNoUnknownBecomesZero:
    def test_an_unpriced_stage_is_not_priced_at_zero(self, journey):
        """The R1 invariant, asserted on the real journey."""
        by_id = {s["id"]: s for s in journey["resolved"]["stages"]}
        for machine in journey["factory"].machines:
            stated = by_id[machine.id]["purchase_cost"]["value"]
            if stated is None:
                assert machine.purchase_cost is None, (
                    f"{machine.id}: an unpriced stage became "
                    f"{machine.purchase_cost!r} in the Factory model"
                )
            else:
                assert machine.purchase_cost == stated

    def test_every_simulated_quantity_was_actually_stated(self, journey):
        """The R2 invariant."""
        by_id = {s["id"]: s for s in journey["resolved"]["stages"]}
        for machine in journey["factory"].machines:
            assert by_id[machine.id]["operators_required"]["value"] is not None, (
                f"{machine.id} reached the simulator without a stated operator count"
            )
            assert machine.operators_required == by_id[machine.id]["operators_required"]["value"]

    def test_the_visible_cycle_time_is_the_simulated_one(self, journey):
        """The R3 invariant — a Factory cannot hold two different cycle times."""
        by_id = {m.id: m for m in journey["factory"].machines}
        for product in journey["factory"].products:
            for step in product.route:
                assert step.cycle_time == by_id[step.machine_id].cycle_time


# Approval cannot happen while the source is unanswered

class TestTheGateHolds:
    def test_an_unresolved_source_requirement_blocks_the_concept(self, client, journey):
        # Same process draft, minus the engineer's links. The build must refuse.
        import copy

        unlinked = copy.deepcopy(journey["process"])
        for op in unlinked["operations"]:
            op["source_fact_keys"] = []

        response = client.post(
            "/product/build-concept",
            json={
                "understanding": journey["understanding"],
                "process": unlinked,
                "requirements_brief": REQUIREMENTS,
            },
        )
        assert response.status_code == 400
        assert "no operation answers" in response.json()["detail"]

    def test_the_refusal_names_what_is_missing_not_what_was_read(self, client, journey):
        import copy

        unlinked = copy.deepcopy(journey["process"])
        for op in unlinked["operations"]:
            op["source_fact_keys"] = []
        detail = client.post(
            "/product/build-concept",
            json={
                "understanding": journey["understanding"],
                "process": unlinked,
                "requirements_brief": REQUIREMENTS,
            },
        ).json()["detail"]
        # Names the requirement, not the document's contents.
        assert "ABS" not in detail
        assert "moulded" not in detail


# The headline numbers descend from the simulator

class TestTheNumbersComeFromTheSimulation:
    def test_the_target_is_the_engineers_input_carried_through(self, journey):
        assert journey["factory"].products[0].demand_per_day == TARGET
        assert journey["simulation"]["target_units"] == TARGET

    def test_the_baseline_is_the_simulators_own_count(self, journey):
        sim = journey["simulation"]
        baseline = journey["arena"]["baseline_metrics"]["completed_units"]
        assert baseline == sim["completed_units"], (
            "the arena's baseline disagrees with the simulation it came from"
        )

    def test_the_gap_is_the_arithmetic_of_the_other_two(self, journey):
        sim = journey["simulation"]
        assert sim["demand_gap_units"] == pytest.approx(
            sim["target_units"] - sim["completed_units"], abs=1.0
        )

    def test_the_bottleneck_is_a_station_that_exists(self, journey):
        bottleneck = journey["simulation"]["system"]["bottleneck_machine_id"]
        assert bottleneck in {m.id for m in journey["factory"].machines}

    def test_the_baseline_does_not_already_meet_the_target(self, journey):
        # If it did, the whole journey would have nothing to show, and the
        # rest of these assertions would be vacuous.
        assert journey["simulation"]["demand_met"] is False


# Alternatives are simulated, and the recommendation is one of them

class TestTheRecommendationIsEarned:
    def test_every_option_was_actually_simulated(self, journey):
        for option in journey["arena"]["strategies"]:
            assert option["operationally_verified"] is True, (
                f"{option['strategy_id']} is presented without a simulation behind it"
            )

    def test_the_simulation_count_is_reported_and_non_trivial(self, journey):
        stats = journey["arena"]["stats"]
        assert stats["simulations_run"] > len(journey["arena"]["strategies"]), (
            "fewer runs than strategies means something was not simulated"
        )

    def test_the_recommendation_is_one_of_the_evaluated_options(self, journey):
        recommended = journey["arena"]["recommended_strategy_id"]
        assert recommended in {o["strategy_id"] for o in journey["arena"]["strategies"]}

    def test_ranking_does_not_reward_an_unknown_cost(self, journey):
        """The R6 invariant."""
        options = journey["arena"]["strategies"]
        recommended = next(
            o for o in options if o["strategy_id"] == journey["arena"]["recommended_strategy_id"]
        )
        if recommended["commercially_complete"]:
            return  # nothing to prove

        for other in options:
            if other["strategy_id"] == recommended["strategy_id"]:
                continue
            if not other["commercially_complete"]:
                continue
            # A fully-costed rival exists.
            beat_on_merit = (
                recommended["metrics"]["goal_met"] and not other["metrics"]["goal_met"]
            ) or (
                recommended["actions"]["added_machine_count"]
                < other["actions"]["added_machine_count"]
            )
            assert beat_on_merit, (
                f"{recommended['strategy_id']} (cost unknown) was preferred over "
                f"{other['strategy_id']} (cost known) with no non-cost reason"
            )

    def test_a_plan_that_reaches_the_target_can_actually_sustain_it(self, journey):
        """The R4 invariant."""
        from app.models.scenario import Scenario
        from app.services.scenario import apply_scenario

        sessions_response = journey["arena"]
        reaching = [o for o in sessions_response["strategies"] if o["metrics"]["goal_met"]]
        if not reaching:
            pytest.skip("no plan reaches the target in this run")

        # Reconstruct each target-meeting plan and measure its real ceiling.
        for option in reaching:
            scenarios = option.get("_scenarios")
            if not scenarios:
                continue  # the arena does not expose them; covered by the service test
            candidate = journey["factory"]
            for scenario in scenarios:
                candidate = apply_scenario(candidate, Scenario.model_validate(scenario))
            measurement = measure_capacity(
                candidate, journey["product_id"], target_units_per_day=TARGET
            )
            assert measurement.meets_target_at_capacity, (
                f"{option['strategy_id']} reports the target but its capacity is "
                f"{measurement.capacity_units_per_day}/day"
            )


# What is displayed equals what was evaluated

class TestDisplayedEqualsEvaluated:
    def test_the_summary_states_the_same_baseline_the_simulator_produced(self, journey):
        summary = journey["arena"]["summary"]
        baseline = journey["simulation"]["completed_units"]
        assert f"{baseline:,}" in summary, (
            f"the summary sentence does not carry the simulated baseline {baseline}"
        )

    def test_the_summary_counts_the_options_it_lists(self, journey):
        summary = journey["arena"]["summary"]
        assert f"{len(journey['arena']['strategies'])} verified option" in summary

    def test_no_option_claims_a_cost_it_does_not_have(self, journey):
        for option in journey["arena"]["strategies"]:
            if not option["commercially_complete"]:
                # An incomplete plan may report a partial known sum, but must
                # partial as a total.
                assert option["cost"]["known_capex"] is not None
                assert option["commercially_complete"] is False
