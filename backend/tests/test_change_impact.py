"""Change impact — a changed input must not leave a stale answer on screen."""

from __future__ import annotations

import pytest

from app.models.concept import ValueSource
from app.services.change_impact import (
    ChangeKind,
    ResultNode,
    assess,
    diff_inputs,
    explain,
    stale_results,
)
from app.services.concept_builder import concept_from_brief
from app.services.concept_example_data import apply_example_engineering_data
from app.services.input_resolution import write_input

BRIEF = (
    "We need a new electronics assembly line. The product goes through assembly, screwdriving, "
    "inspection and packaging. We need about 1,900 units per day. The available production area is "
    "30 by 18 meters. We have eight operators."
)


@pytest.fixture
def concept():
    return apply_example_engineering_data(concept_from_brief(BRIEF))


class TestScenarioA_ProductionTarget:
    """1,900 → 2,400 units/day."""

    def test_the_change_is_detected_with_both_values(self, concept):
        after = write_input(concept, "production_target", 2400, ValueSource.ENGINEER, "Customer raised it")
        changes = diff_inputs(concept, after)

        assert len(changes) == 1
        change = changes[0]
        assert change.key == "production_target"
        assert change.kind is ChangeKind.VALUE_CHANGED
        assert (change.before, change.after) == (1900.0, 2400.0)

    def test_every_downstream_result_goes_stale(self, concept):
        after = write_input(concept, "production_target", 2400, ValueSource.ENGINEER, "Customer raised it")
        report = assess(concept, after)

        for node in (
            ResultNode.BASELINE_RESULT,
            ResultNode.BOTTLENECK,
            ResultNode.STRATEGIES,
            ResultNode.STRATEGY_EVALUATION,
            ResultNode.RECOMMENDATION,
        ):
            assert node in report.stale, f"{node.value} still depends on the old target"

    def test_the_layout_survives(self, concept):
        # Placement does not depend on how many units are wanted.
        after = write_input(concept, "production_target", 2400, ValueSource.ENGINEER, "Customer raised it")
        assert ResultNode.LAYOUT in assess(concept, after).unaffected

    def test_the_explanation_names_what_survived_as_well(self, concept):
        after = write_input(concept, "production_target", 2400, ValueSource.ENGINEER, "Customer raised it")
        text = explain(concept, after)

        assert "1900 → 2400" in text
        assert "Unaffected:" in text
        assert "layout" in text


class TestScenarioB_Workforce:
    """8 → 6 operators."""

    def test_shrinking_the_workforce_invalidates_the_physics(self, concept):
        after = write_input(concept, "operators_available", 6, ValueSource.ENGINEER, "Two reassigned")
        report = assess(concept, after)

        assert ResultNode.BASELINE_RESULT in report.stale
        assert ResultNode.RECOMMENDATION in report.stale


class TestScenarioC_Constraint:
    """A preference hardening into a constraint."""

    def test_a_preference_flag_is_not_yet_tracked_as_an_input(self, concept):
        after = concept.model_copy(update={"prefer_no_new_machines": True})
        assert diff_inputs(concept, after) == []


class TestScenarioD_EstimateReplacedByMeasurement:
    """An estimate replaced by a measured value."""

    def test_the_same_number_from_a_stronger_source_still_counts_as_a_change(self, concept):
        # The point of the whole provenance system: 52 s measured is not 52 s
        # assumed, because what may be built on it differs.
        current = concept.stage_by_id("m-screwdriving").cycle_time.value
        after = write_input(
            concept, "stage.m-screwdriving.cycle_time", current, ValueSource.MEASURED, "Stopwatch study"
        )
        changes = diff_inputs(concept, after)

        assert len(changes) == 1
        assert changes[0].kind is ChangeKind.SOURCE_CHANGED
        assert changes[0].before == changes[0].after
        assert "provenance changed" in changes[0].describe()

    def test_a_measured_cycle_time_invalidates_the_simulation(self, concept):
        after = write_input(
            concept, "stage.m-screwdriving.cycle_time", 36.0, ValueSource.MEASURED, "Stopwatch study"
        )
        report = assess(concept, after)

        assert ResultNode.SIMULATION_CONFIG in report.stale
        assert ResultNode.BASELINE_RESULT in report.stale
        assert ResultNode.SENSITIVITY in report.stale


class TestCommercialChangesDoNotMovePhysics:
    def test_a_price_re_ranks_without_invalidating_throughput(self, concept):
        # A quotation changes what a plan costs and therefore how plans compare.
        after = write_input(
            concept, "stage.m-screwdriving.purchase_cost", 91_000, ValueSource.EXTERNAL_DATA, "Supplier quote"
        )
        report = assess(concept, after)

        assert ResultNode.STRATEGY_EVALUATION in report.stale
        assert ResultNode.RECOMMENDATION in report.stale
        assert ResultNode.BASELINE_RESULT not in report.stale
        assert ResultNode.BOTTLENECK not in report.stale

    def test_a_budget_behaves_the_same_way(self, concept):
        after = write_input(concept, "budget", 250_000, ValueSource.CUSTOMER if False else ValueSource.ENGINEER, "Approved")
        report = assess(concept, after)

        assert ResultNode.RECOMMENDATION in report.stale
        assert ResultNode.BASELINE_RESULT not in report.stale


class TestInvalidationRules:
    def test_nothing_changed_means_nothing_stale(self, concept):
        report = assess(concept, concept)
        assert report.anything_changed is False
        assert report.stale == set()
        assert report.summary() == "Nothing changed."

    def test_staleness_propagates_transitively(self, concept):
        # RECOMMENDATION depends on STRATEGY_EVALUATION depends on
        # STRATEGIES depends on BOTTLENECK depends on BASELINE_RESULT.
        # Nothing lists RECOMMENDATION as depending on the target directly.
        stale = stale_results({"production_target"})
        assert ResultNode.RECOMMENDATION in stale

    def test_clearing_a_value_invalidates_as_much_as_changing_it(self, concept):
        after = write_input(concept, "stage.m-assembly.cycle_time", None, ValueSource.ENGINEER, None)
        changes = diff_inputs(concept, after)

        assert changes[0].kind is ChangeKind.CLEARED
        assert ResultNode.BASELINE_RESULT in assess(concept, after).stale

    def test_a_layout_only_input_does_not_invalidate_throughput(self, concept):
        after = write_input(concept, "floor_width", 26.0, ValueSource.ENGINEER, "Surveyed")
        report = assess(concept, after)

        assert ResultNode.LAYOUT in report.stale
        assert ResultNode.BASELINE_RESULT not in report.stale

    def test_every_result_node_is_reachable_from_some_input(self):
        # A node nothing can invalidate would silently stay "current" forever.
        from app.services.change_impact import _DERIVED_FROM, _DIRECT_DEPENDENCIES

        covered = set(_DIRECT_DEPENDENCIES) | set(_DERIVED_FROM)
        assert covered == set(ResultNode), (
            f"no dependency declared for: {set(ResultNode) - covered}"
        )


# Decision robustness

class TestRobustness:
    """"If this estimate is wrong, does the decision change?"""

    def _achievable(self, concept):
        from app.models.concept import SourcedFloat

        return concept.model_copy(
            update={"production_target": SourcedFloat.of(1400, ValueSource.CUSTOMER, "brief")}
        )

    def test_a_range_that_always_meets_the_target_is_robust(self, concept):
        from app.services.robustness import Robustness, assess_robustness

        result = assess_robustness(
            self._achievable(concept), "m-screwdriving", low=20.0, high=30.0, working=25.0
        )
        assert result.verdict is Robustness.ROBUST
        assert result.flips_at is None
        assert "does not depend on this estimate" in result.statement

    def test_a_range_that_flips_names_the_value_it_flips_at(self, concept):
        # The one fact that changes what the engineer does next.
        from app.services.robustness import Robustness, assess_robustness

        result = assess_robustness(
            self._achievable(concept), "m-screwdriving", low=35.0, high=50.0, working=42.0
        )
        assert result.verdict is Robustness.SENSITIVE
        assert result.flips_at is not None
        assert f"{result.flips_at:g}" in result.statement

    def test_an_unreachable_target_says_the_constraint_is_elsewhere(self, concept):
        # Sharpening this estimate would be wasted effort, and saying so is
        # more useful than reporting a curve.
        from app.services.robustness import Robustness, assess_robustness

        result = assess_robustness(concept, "m-screwdriving", low=35.0, high=50.0, working=42.0)
        assert result.verdict is Robustness.NOT_ACHIEVABLE
        assert "constraint is elsewhere" in result.statement

    def test_an_unusably_wide_range_refuses_to_recommend(self, concept):
        from app.services.robustness import Robustness, assess_robustness

        result = assess_robustness(
            self._achievable(concept), "m-screwdriving", low=20.0, high=70.0, working=42.0
        )
        assert result.verdict is Robustness.CRITICAL_UNKNOWN
        assert "needs measuring" in result.statement

    def test_every_verdict_rests_on_real_simulation_runs(self, concept):
        from app.services.robustness import assess_robustness

        result = assess_robustness(
            self._achievable(concept), "m-screwdriving", low=35.0, high=50.0, working=42.0
        )
        assert result.simulations_run >= 5
        assert len(result.points) >= 5
        assert all(point.completed_units > 0 for point in result.points)

    def test_no_confidence_score_is_produced(self, concept):
        # A percentage invites arithmetic that four runs cannot justify, and
        # hides the flip point, which is the part that matters.
        from app.services.robustness import assess_robustness

        result = assess_robustness(
            self._achievable(concept), "m-screwdriving", low=35.0, high=50.0, working=42.0
        )
        assert "%" not in result.statement
        assert not hasattr(result, "confidence_score")

    def test_an_inverted_range_is_refused(self, concept):
        from app.services.robustness import assess_robustness

        with pytest.raises(ValueError, match="upper bound"):
            assess_robustness(concept, "m-screwdriving", low=50.0, high=20.0, working=35.0)
