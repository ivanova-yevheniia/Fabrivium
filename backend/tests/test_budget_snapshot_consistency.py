"""Regression tests for per-stage budget consistency."""

from __future__ import annotations

import json
import pathlib

import pytest

from app.models.agent import PlanningRequirements
from app.models.factory import Factory
from app.models.optimization import OptimizationObjective
from app.models.orchestrator import PlanningSessionState, PlanningStateSnapshot
from app.services.budget import remaining_known_capex
from app.services.planning_orchestrator import PlanningOrchestrator

EXAMPLES_DIR = pathlib.Path(__file__).parent.parent.parent / "examples"

BUDGET = 220_000.0
PRODUCT_ID = "p-electronics-widget"


@pytest.fixture
def electronics_factory() -> Factory:
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        return Factory.model_validate(json.load(fh))


@pytest.fixture
def budgeted_session(electronics_factory: Factory) -> PlanningSessionState:
    """The verified €220,000 / 1900-units-per-day run — the exact scenario
    the defect was reported against."""
    requirements = PlanningRequirements(
        objective=OptimizationObjective.MEET_DEMAND,
        target_units_per_day=1900.0,
        max_capex=BUDGET,
    )
    return PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, requirements, max_iterations=5)


def _stage_snapshots(session: PlanningSessionState) -> list[tuple[str, PlanningStateSnapshot]]:
    """Every stage the UI can select, in timeline order — resolved exactly
    the way the frontend's ``resolveStage`` does."""
    stages: list[tuple[str, PlanningStateSnapshot]] = [("baseline", session.baseline_snapshot)]
    for iteration in session.iterations:
        snapshot = (
            iteration.state_after
            if iteration.accepted
            else (iteration.rejected_candidate_snapshot or iteration.state_before)
        )
        assert snapshot is not None
        stages.append((f"iteration {iteration.iteration_index + 1}", snapshot))
    stages.append(("final", session.final_snapshot))
    return stages


# The single authoritative calculation


class TestBudgetFunction:
    def test_subtracts_committed_spend_from_the_ceiling(self):
        assert remaining_known_capex(220_000.0, 85_000.0) == 135_000.0
        assert remaining_known_capex(220_000.0, 205_000.0) == 15_000.0

    def test_no_ceiling_means_unconstrained_not_exhausted(self):
        """None and 0.0 are genuinely different states — collapsing them
        would render an unlimited budget as spent."""
        assert remaining_known_capex(None, 85_000.0) is None
        assert remaining_known_capex(0.0, 0.0) == 0.0

    def test_an_over_budget_hypothetical_reports_the_overrun_honestly(self):
        assert remaining_known_capex(220_000.0, 300_000.0) == -80_000.0


# The reported scenario, end to end through the real orchestrator


class TestReportedScenario:
    def test_the_session_spends_only_what_it_could_verify(self, budgeted_session):
        """PHASE 8A CHANGE."""
        assert budgeted_session.goal_reached is False
        assert budgeted_session.stop_reason.value == "BUDGET_EXHAUSTED"
        assert budgeted_session.cumulative_known_capex == 85_000.0

    def test_iteration_1_reports_135000_remaining_not_the_final_15000(self, budgeted_session):
        """The headline defect: budget €220,000, Iteration 1 cumulative
        €85,000 — remaining must be €135,000, never the session-final
        €15,000."""
        snapshot = budgeted_session.iterations[0].state_after
        assert snapshot is not None
        assert snapshot.cumulative_known_capex == 85_000.0
        assert snapshot.remaining_known_capex == 135_000.0

    def test_final_reports_the_remaining_budget_for_what_was_actually_committed(self, budgeted_session):
        # Phase 8A: EUR 85,000 committed of EUR 220,000 (see above), so
        # EUR 135,000 is still available — not the EUR 15,000 that a
        # two-machine plan would have left.
        assert budgeted_session.final_snapshot.cumulative_known_capex == 85_000.0
        assert budgeted_session.final_snapshot.remaining_known_capex == 135_000.0

    def test_baseline_has_the_whole_budget_available(self, budgeted_session):
        assert budgeted_session.baseline_snapshot.cumulative_known_capex == 0.0
        assert budgeted_session.baseline_snapshot.remaining_known_capex == BUDGET

    def test_every_stage_in_the_timeline_is_internally_consistent(self, budgeted_session):
        """
        The invariant the UI depends on: at EVERY selectable stage, cumulative +
        remaining == the budget.
        """
        for label, snapshot in _stage_snapshots(budgeted_session):
            assert snapshot.remaining_known_capex is not None, label
            assert snapshot.cumulative_known_capex + snapshot.remaining_known_capex == pytest.approx(BUDGET), label

    def test_remaining_decreases_monotonically_across_accepted_stages(self, budgeted_session):
        """Committed spend only ever grows, so remaining only ever shrinks."""
        remainings = [budgeted_session.baseline_snapshot.remaining_known_capex]
        for iteration in budgeted_session.iterations:
            if iteration.accepted and iteration.state_after is not None:
                remainings.append(iteration.state_after.remaining_known_capex)
        remainings.append(budgeted_session.final_snapshot.remaining_known_capex)

        assert remainings == sorted(remainings, reverse=True), remainings

    def test_a_rejected_candidates_hypothetical_spend_is_still_internally_consistent(
        self, budgeted_session
    ):
        """The rejected branch must not be sloppy just because it was not
        taken: its hypothetical cumulative and remaining must still sum to
        the budget."""
        rejected = [
            it.rejected_candidate_snapshot
            for it in budgeted_session.iterations
            if not it.accepted and it.rejected_candidate_snapshot is not None
        ]
        assert rejected, "expected the unstaffable machine purchase to be evaluated and rejected"
        for snapshot in rejected:
            assert snapshot.cumulative_known_capex + snapshot.remaining_known_capex == pytest.approx(BUDGET)


# Structural invariants


class TestStructuralInvariants:
    def test_the_session_figure_is_the_final_snapshot_figure(self, budgeted_session):
        """Not merely equal by arithmetic — taken from the same value, so
        the two can never drift."""
        assert budgeted_session.remaining_known_capex == budgeted_session.final_snapshot.remaining_known_capex

    def test_an_unbudgeted_session_reports_none_at_every_stage(self, electronics_factory):
        requirements = PlanningRequirements(
            objective=OptimizationObjective.MEET_DEMAND, target_units_per_day=1900.0,
        )
        session = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, requirements, max_iterations=5)

        assert session.remaining_known_capex is None
        for label, snapshot in _stage_snapshots(session):
            assert snapshot.remaining_known_capex is None, label

    def test_the_field_is_serialized_for_the_frontend(self, budgeted_session):
        """The API response must actually carry the per-stage figure —
        otherwise the frontend has nothing to read and the old fallback
        would silently return."""
        payload = json.loads(budgeted_session.model_dump_json())
        assert payload["baseline_snapshot"]["remaining_known_capex"] == BUDGET
        assert payload["final_snapshot"]["remaining_known_capex"] == 135_000.0
        assert payload["iterations"][0]["state_after"]["remaining_known_capex"] == 135_000.0

    def test_iteration_state_after_equals_the_next_state_before(self, budgeted_session):
        """Phase 6A.1's existing invariant must still hold, now including
        the new field."""
        iterations = budgeted_session.iterations
        for earlier, later in zip(iterations, iterations[1:]):
            if earlier.accepted and earlier.state_after and later.state_before:
                assert earlier.state_after.remaining_known_capex == later.state_before.remaining_known_capex
