"""Scenario what-if runner for Fabrivium Phase 2C."""

from __future__ import annotations

from app.models.comparison import ScenarioResult
from app.models.factory import Factory
from app.models.scenario import Scenario
from app.services.comparison import calculate_capex_delta, compare_results, evaluate_verdict
from app.services.scenario import apply_scenario
from app.services.simulation import run_simulation


def run_scenario(factory: Factory, product_id: str, scenario: Scenario) -> ScenarioResult:
    """
    Simulate *factory* (baseline) and the candidate produced by *scenario*, then return
    a full typed comparison and deterministic verdict.
    """
    baseline_result = run_simulation(factory, product_id)

    candidate_factory = apply_scenario(factory, scenario)
    candidate_result = run_simulation(candidate_factory, product_id)

    capex_delta = calculate_capex_delta(factory, scenario)
    comparison = compare_results(baseline_result, candidate_result, scenario, capex_delta)
    verdict, verdict_reasons = evaluate_verdict(comparison)

    return ScenarioResult(
        scenario_id=scenario.id,
        scenario_name=scenario.name,
        baseline_result=baseline_result,
        candidate_result=candidate_result,
        comparison=comparison,
        verdict=verdict,
        verdict_reasons=verdict_reasons,
    )
