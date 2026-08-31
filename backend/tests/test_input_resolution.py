"""Real data first — engineering input resolution."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.concept import ValueSource
from app.services.buffer_sensitivity import CANDIDATE_SIZES, sweep_buffer_sizes
from app.services.concept_builder import concept_from_brief
from app.services.concept_example_data import apply_example_engineering_data
from app.services.concept_validation import GapSeverity, concept_gaps
from app.services.input_resolution import (
    Necessity,
    ResolutionAction,
    UnknownInputKey,
    apply_example_data_to_unresolved,
    estimatable_keys,
    read_input,
    resolution_plan,
    write_input,
)

BRIEF = (
    "We need a new electronics assembly line. The product goes through assembly, screwdriving, "
    "inspection and packaging. We need about 1,900 units per day. The available production area is "
    "30 by 18 meters. We have eight operators."
)


@pytest.fixture
def draft():
    return concept_from_brief(BRIEF)


@pytest.fixture
def filled(draft):
    return apply_example_engineering_data(draft)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def find(plan, key: str):
    for item in plan.inputs:
        if item.key == key:
            return item
    raise AssertionError(f"no input '{key}' in the plan")


def computed(plan, key: str):
    for item in plan.computed:
        if item.key == key:
            return item
    raise AssertionError(f"no computed value '{key}' in the plan")


# Precedence

class TestPrecedence:
    def test_a_customer_value_is_never_replaced_by_demo_data(self, draft):
        # The brief states 1,900 units/day and 8 operators.
        out = apply_example_data_to_unresolved(draft)

        target = read_input(out.draft, "production_target")
        operators = read_input(out.draft, "operators_available")
        assert target.value == 1900
        assert target.source is ValueSource.CUSTOMER
        assert operators.value == 8
        assert operators.source is ValueSource.CUSTOMER
        assert "production_target" in out.protected
        assert "operators_available" in out.protected

    def test_an_engineer_edit_is_never_replaced_by_demo_data(self, draft):
        # The exact failure a bulk action invites: the engineer measures one
        # station, then presses a convenience button, and their number is
        # quietly swapped for the dataset's.
        decided = write_input(
            draft,
            "stage.m-screwdriving.cycle_time",
            61.0,
            ValueSource.ENGINEER,
            "Stopwatch study on the pilot cell",
        )
        out = apply_example_data_to_unresolved(decided)

        cycle = read_input(out.draft, "stage.m-screwdriving.cycle_time")
        assert cycle.value == 61.0
        assert cycle.source is ValueSource.ENGINEER
        assert cycle.detail == "Stopwatch study on the pilot cell"
        assert "stage.m-screwdriving.cycle_time" in out.protected

    def test_an_engineer_edit_replaces_a_demo_value(self, filled):
        # Precedence runs the other way too: a person may always overrule
        # the dataset, and the record says who did.
        before = read_input(filled, "stage.m-screwdriving.cycle_time")
        assert before.source is ValueSource.EXAMPLE_DATA

        after = write_input(
            filled, "stage.m-screwdriving.cycle_time", 48.0, ValueSource.ENGINEER, "Vendor trial"
        )
        cycle = read_input(after, "stage.m-screwdriving.cycle_time")
        assert cycle.value == 48.0
        assert cycle.source is ValueSource.ENGINEER

    def test_bulk_accounting_balances(self, draft):
        # Every pre-existing input is either filled, protected, or reported
        # as something the action could not help with. A missing category
        # would hide a value that quietly changed.
        before_keys = {i.key for i in resolution_plan(draft).inputs}
        out = apply_example_data_to_unresolved(draft)

        assert set(out.filled) | set(out.protected) | set(out.unavailable) == before_keys
        assert not (set(out.filled) & set(out.protected))
        # Buffers are CREATED by the dataset, not filled in.
        assert all(k.startswith("buffer.") for k in out.added)


# Unknown stays unknown

class TestUnknownStaysUnknown:
    def test_an_unresolved_value_is_none_not_zero(self, draft):
        cost = find(resolution_plan(draft), "stage.m-screwdriving.purchase_cost")
        assert cost.value is None
        assert cost.source is ValueSource.UNKNOWN
        assert cost.resolved is False

    def test_clearing_a_value_also_clears_its_attribution(self, filled):
        # A cleared number that kept "Electronics Assembly Demo Dataset"
        # would be an unknown wearing a source.
        cleared = write_input(filled, "budget", None, ValueSource.ENGINEER, "irrelevant")
        budget = read_input(cleared, "budget")
        assert budget.value is None
        assert budget.source is ValueSource.UNKNOWN
        assert budget.detail is None

    def test_leaving_unknown_is_offered_everywhere(self, draft):
        # "I do not know this" must always be expressible; a form that
        # cannot say it forces a fabricated answer.
        for item in resolution_plan(draft).inputs:
            assert ResolutionAction.LEAVE_UNKNOWN in item.actions, item.key



class TestComputed:
    def test_takt_is_computed_from_the_schedule_and_target(self, draft):
        scheduled = write_input(draft, "shifts_per_day", 2, ValueSource.ENGINEER, "Operations")
        scheduled = write_input(scheduled, "hours_per_shift", 8, ValueSource.ENGINEER, "Operations")
        plan = resolution_plan(scheduled)

        available = computed(plan, "available_production_time")
        takt = computed(plan, "required_takt")

        assert available.value == pytest.approx(57_600.0)
        assert takt.value == pytest.approx(57_600.0 / 1900.0, rel=1e-9)
        assert takt.value == pytest.approx(30.3, abs=0.05)

    def test_a_computed_value_is_tagged_calculated_not_estimated(self, filled):
        takt = computed(resolution_plan(filled), "required_takt")
        assert takt.source is ValueSource.CALCULATED
        assert takt.source is not ValueSource.ENGINEERING_ESTIMATE
        assert takt.source is not ValueSource.CUSTOMER

    def test_a_computed_value_shows_its_arithmetic(self, filled):
        available = computed(resolution_plan(filled), "available_production_time")
        assert "3600" in available.formula
        takt = computed(resolution_plan(filled), "required_takt")
        assert "÷" in takt.formula

    def test_an_uncomputable_value_names_what_is_missing(self, draft):
        # No schedule in this brief, so takt cannot exist yet.
        takt = computed(resolution_plan(draft), "required_takt")
        assert takt.value is None
        assert takt.blocked_by == "the operating schedule"

    def test_computed_values_are_not_offered_as_inputs(self, filled):
        # Nobody may hand-edit takt into disagreeing with its own definition.
        input_keys = {i.key for i in resolution_plan(filled).inputs}
        for key in ("required_takt", "available_production_time", "slowest_stage_cycle_time"):
            assert key not in input_keys


# Estimate only what can be estimated

class TestEstimationBoundaries:
    def test_operation_physics_can_be_estimated(self, draft):
        plan = resolution_plan(draft)
        for key in (
            "stage.m-screwdriving.cycle_time",
            "stage.m-screwdriving.capacity",
            "stage.m-screwdriving.operators_required",
        ):
            assert ResolutionAction.ESTIMATE in find(plan, key).actions

    def test_an_equipment_price_is_never_estimated(self, draft):
        # §7.
        cost = find(resolution_plan(draft), "stage.m-screwdriving.purchase_cost")
        assert ResolutionAction.ESTIMATE not in cost.actions
        assert ResolutionAction.ENTER_QUOTE in cost.actions
        assert ResolutionAction.EXTERNAL_DATA in cost.actions

    def test_an_unpriced_station_is_marked_quote_required(self, draft):
        cost = find(resolution_plan(draft), "stage.m-assembly.purchase_cost")
        assert cost.quote_required is True
        assert cost.value is None

    def test_a_capital_budget_is_never_estimated_or_computed(self, draft):
        # §8. Nothing in the factory model implies what a company will spend.
        budget = find(resolution_plan(draft), "budget")
        assert ResolutionAction.ESTIMATE not in budget.actions
        assert budget.value is None
        assert "never proposes a figure" in budget.consequence

    def test_the_schedule_is_asked_for_never_derived(self, draft):
        # §9.
        for key in ("shifts_per_day", "hours_per_shift"):
            item = find(resolution_plan(draft), key)
            assert ResolutionAction.ESTIMATE not in item.actions
            assert "cannot be inferred from the target" in item.consequence

    def test_the_estimatable_set_excludes_money(self, draft):
        keys = estimatable_keys(draft)
        assert keys, "the estimator should have something to offer on a fresh concept"
        assert not any("purchase_cost" in k for k in keys)
        assert "budget" not in keys


# Blocking rules

class TestBlockingRules:
    def test_only_the_simulator_decides_what_blocks(self, draft):
        plan = resolution_plan(draft)
        assert find(plan, "stage.m-screwdriving.cycle_time").necessity is Necessity.BLOCKS_SIMULATION
        assert find(plan, "shifts_per_day").necessity is Necessity.BLOCKS_SIMULATION
        assert find(plan, "hours_per_shift").necessity is Necessity.BLOCKS_SIMULATION

        assert find(plan, "stage.m-screwdriving.purchase_cost").necessity is Necessity.COMMERCIAL_ONLY
        assert find(plan, "budget").necessity is Necessity.COMMERCIAL_ONLY
        assert find(plan, "floor_width").necessity is Necessity.AFFECTS_LAYOUT

    def test_necessity_agrees_with_the_validator(self, draft):
        # concept_gaps is the existing single source of truth for "does the
        # simulator need this". Two independent statements of the same fact
        # is exactly how a UI ends up blocking on a price.
        required = {g.key for g in concept_gaps(draft) if g.severity is GapSeverity.REQUIRED}
        blocking = {
            i.key
            for i in resolution_plan(draft).inputs
            if i.necessity is Necessity.BLOCKS_SIMULATION and not i.resolved
        }
        assert blocking == required

    def test_a_complete_concept_is_ready_to_simulate(self, filled):
        plan = resolution_plan(filled)
        assert plan.blocking_unresolved == []
        assert plan.ready_to_simulate is True

    def test_missing_money_never_blocks_simulation(self, filled):
        cleared = write_input(filled, "budget", None, ValueSource.ENGINEER, None)
        cleared = write_input(cleared, "stage.m-assembly.purchase_cost", None, ValueSource.ENGINEER, None)
        assert resolution_plan(cleared).ready_to_simulate is True


# Buffer sizing by simulation

class TestBufferSensitivity:
    def test_every_candidate_size_is_a_real_simulation(self, filled):
        result = sweep_buffer_sizes(filled)
        assert result.simulations_run == len(CANDIDATE_SIZES)
        assert [p.size for p in result.points] == list(CANDIDATE_SIZES)
        # Real runs produce real output, not a template.
        assert all(p.completed_units > 0 for p in result.points)
        assert all(p.target_units == 1900 for p in result.points)

    def test_it_reports_when_buffers_do_not_matter(self, filled):
        # On the golden line the constraint is screwdriving's cycle time, so
        # storage changes nothing. Saying so is the finding; silently
        # adopting "50 units" was not.
        result = sweep_buffer_sizes(filled)
        assert result.indifferent is True
        assert result.throughput_span == 0.0
        assert "does not change this line's output" in result.summary

    def test_it_carries_the_blocking_evidence(self, filled):
        # Whether an upstream station was ever stuck holding a finished unit
        # is the only thing that makes a bigger buffer worth buying.
        result = sweep_buffer_sizes(filled)
        assert all(p.upstream_blocked_seconds >= 0.0 for p in result.points)
        no_buffer = result.points[0]
        assert no_buffer.size == 0
        assert no_buffer.upstream_blocked_seconds == 0.0

    def test_a_concept_without_buffers_is_refused_rather_than_faked(self, draft):
        # Six identical runs presented as a buffer study would be a lie
        # dressed as evidence.
        with pytest.raises(ValueError, match="no buffers"):
            sweep_buffer_sizes(draft)


# The API surface

class TestResolutionApi:
    def _draft(self, client):
        return client.post("/concept/from-brief", json={"brief": BRIEF}).json()["draft"]

    def test_the_plan_reports_provenance_and_consequence_per_input(self, client):
        body = client.post("/concept/resolution-plan", json={"draft": self._draft(client)}).json()
        assert body["inputs"]
        for item in body["inputs"]:
            assert item["source"]
            assert item["consequence"]
            assert item["actions"]
            assert item["necessity"] in {
                "BLOCKS_SIMULATION",
                "AFFECTS_LAYOUT",
                "COMMERCIAL_ONLY",
                "HAS_DEFAULT",
            }

    def test_one_value_can_be_resolved_without_touching_the_others(self, client):
        draft = self._draft(client)
        before = client.post("/concept/resolution-plan", json={"draft": draft}).json()

        response = client.post(
            "/concept/resolve-input",
            json={
                "draft": draft,
                "key": "shifts_per_day",
                "value": 2,
                "source": "ENGINEER",
                "detail": "Confirmed with operations",
            },
        )
        assert response.status_code == 200
        after = client.post(
            "/concept/resolution-plan", json={"draft": response.json()["draft"]}
        ).json()

        changed = [
            (b["key"], b["value"], a["value"])
            for b, a in zip(before["inputs"], after["inputs"])
            if b["value"] != a["value"]
        ]
        assert changed == [("shifts_per_day", None, 2.0)]

    def test_the_api_refuses_to_forge_the_strongest_provenances(self, client):
        # A number typed into a form is an ENGINEER value.
        for source in ("CUSTOMER", "MEASURED"):
            response = client.post(
                "/concept/resolve-input",
                json={"draft": self._draft(client), "key": "shifts_per_day", "value": 2, "source": source},
            )
            assert response.status_code == 422
            assert source in response.json()["detail"]

    def test_a_whole_number_field_refuses_a_fraction(self, client):
        response = client.post(
            "/concept/resolve-input",
            json={"draft": self._draft(client), "key": "shifts_per_day", "value": 2.5, "source": "ENGINEER"},
        )
        assert response.status_code == 422
        assert "whole number" in response.json()["detail"]

    def test_an_unknown_key_is_a_404_not_a_silent_no_op(self, client):
        response = client.post(
            "/concept/resolve-input",
            json={"draft": self._draft(client), "key": "stage.nope.cycle_time", "value": 1, "source": "ENGINEER"},
        )
        assert response.status_code == 404

    def test_buffer_sensitivity_runs_real_simulations_through_the_api(self, client):
        draft = client.post(
            "/concept/example-data", json={"draft": self._draft(client)}
        ).json()["draft"]
        body = client.post("/concept/buffer-sensitivity", json={"draft": draft}).json()

        assert body["simulations_run"] == len(CANDIDATE_SIZES)
        assert body["indifferent"] is True
        assert body["summary"]

    def test_buffer_sensitivity_refuses_a_concept_without_buffers(self, client):
        response = client.post("/concept/buffer-sensitivity", json={"draft": self._draft(client)})
        assert response.status_code == 422
        assert "no buffers" in response.json()["detail"]


# Addressing

class TestKeys:
    def test_every_key_in_the_plan_round_trips(self, filled):
        # The plan's keys are the UI's only handle on a value.
        for item in resolution_plan(filled).inputs:
            current = read_input(filled, item.key)
            assert current.value == item.value

    def test_an_unaddressable_key_raises(self, filled):
        for key in ("nonsense", "stage.m-assembly.colour", "buffer.nope.capacity"):
            with pytest.raises(UnknownInputKey):
                read_input(filled, key)
