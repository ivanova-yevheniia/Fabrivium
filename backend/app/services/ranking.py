"""Deterministic candidate ranking and Pareto selection for Fabrivium Phase 4C."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.evaluation import CandidateEvaluation, CandidateFeasibilityStatus, OptimizationEvaluationResult
from app.models.optimization import OptimizationGoal, OptimizationObjective
from app.models.ranking import CandidateRanking, CandidateRankStatus, OptimizationRecommendation
from app.services.pareto import Dimension, compute_dominance

_MAX_RECOMMENDED = 3


@dataclass(frozen=True)
class _Metrics:
    candidate_id: str
    demand_met: bool
    demand_gap: float
    completed_units: int
    known_capex: float
    # False when at least one action in this scenario has no known cost.
    commercially_complete: bool
    wip: int
    avg_flow_time: float
    added_machine_count: int
    action_count: int

    @property
    def cost_incomplete(self) -> float:
        """0.0 when the cost is fully known, 1.0 when it is not."""
        return 0.0 if self.commercially_complete else 1.0

    @property
    def comparable_capex(self) -> float:
        """The CAPEX figure it is legitimate to rank on."""
        return self.known_capex if self.commercially_complete else 0.0

    def as_dims(self) -> dict[str, float]:
        return {
            "demand_gap": self.demand_gap,
            "completed_units": float(self.completed_units),
            "cost_incomplete": self.cost_incomplete,
            "known_capex": self.comparable_capex,
            "wip": float(self.wip),
            "avg_flow_time": self.avg_flow_time,
        }


def _extract_metrics(evaluation: CandidateEvaluation) -> _Metrics:
    sim = evaluation.simulation_result
    actions = evaluation.candidate.scenario.actions
    return _Metrics(
        candidate_id=evaluation.candidate.candidate_id,
        demand_met=sim.demand_met,
        demand_gap=sim.demand_gap_units,
        completed_units=sim.completed_units,
        known_capex=evaluation.known_capex,
        commercially_complete=not evaluation.requires_cost_estimate,
        wip=sim.system.work_in_progress,
        avg_flow_time=sim.system.average_flow_time_seconds,
        added_machine_count=sum(1 for a in actions if a.action_type == "ADD_PARALLEL_MACHINE"),
        action_count=len(actions),
    )


# Objective-specific dimensions / comparators

def _pareto_dimensions(objective: OptimizationObjective) -> list[Dimension]:
    if objective == OptimizationObjective.MEET_DEMAND:
        return [("demand_gap", "min"), ("cost_incomplete", "min"), ("known_capex", "min"), ("wip", "min"), ("avg_flow_time", "min")]
    if objective == OptimizationObjective.MAXIMIZE_THROUGHPUT:
        return [("completed_units", "max"), ("cost_incomplete", "min"), ("known_capex", "min"), ("wip", "min"), ("avg_flow_time", "min")]
    if objective == OptimizationObjective.MINIMIZE_WIP:
        return [("wip", "min"), ("avg_flow_time", "min"), ("cost_incomplete", "min"), ("known_capex", "min")]
    if objective == OptimizationObjective.MINIMIZE_FLOW_TIME:
        return [("avg_flow_time", "min"), ("wip", "min"), ("cost_incomplete", "min"), ("known_capex", "min")]
    raise ValueError(f"Unsupported objective: {objective}")  # pragma: no cover - enum is exhaustive


def _ranking_key(objective: OptimizationObjective):
    def key(m: _Metrics):
        tail = (m.added_machine_count, m.action_count, m.candidate_id)
        if objective == OptimizationObjective.MEET_DEMAND:
            return (
                0 if m.demand_met else 1,
                m.demand_gap,
                m.cost_incomplete,
                m.comparable_capex,
                m.wip,
                m.avg_flow_time,
                *tail,
            )
        if objective == OptimizationObjective.MAXIMIZE_THROUGHPUT:
            return (-m.completed_units, 0 if m.demand_met else 1, m.cost_incomplete, m.comparable_capex, m.wip, m.avg_flow_time, *tail)
        if objective == OptimizationObjective.MINIMIZE_WIP:
            return (m.wip, m.avg_flow_time, m.cost_incomplete, m.comparable_capex, *tail)
        if objective == OptimizationObjective.MINIMIZE_FLOW_TIME:
            return (m.avg_flow_time, m.wip, m.cost_incomplete, m.comparable_capex, *tail)
        raise ValueError(f"Unsupported objective: {objective}")  # pragma: no cover
    return key


def _requires_demand_gate(objective: OptimizationObjective) -> bool:
    """Whether this objective ranks demand fulfilment above cost, WIP and flow time."""
    return objective in (
        OptimizationObjective.MEET_DEMAND,
        OptimizationObjective.MINIMIZE_WIP,
        OptimizationObjective.MINIMIZE_FLOW_TIME,
    )


def _same_primary_tier(objective: OptimizationObjective, m: _Metrics, primary: _Metrics) -> bool:
    """Is *m* in the same top-priority tier as *primary* — i.e."""
    if objective in (
        OptimizationObjective.MEET_DEMAND,
        OptimizationObjective.MINIMIZE_WIP,
        OptimizationObjective.MINIMIZE_FLOW_TIME,
    ):
        return m.demand_met == primary.demand_met
    return True


# Rationale / tradeoff templates (deterministic — never LLM output)

def _fmt_money(v: float) -> str:
    return f"€{v:,.0f}"


def _known_rationale(m: _Metrics, rank: int, status: CandidateRankStatus, dominated_by: list[str]) -> list[str]:
    lines = [
        f"Rank #{rank}: demand_met={m.demand_met}, demand_gap={m.demand_gap:g} units, "
        f"completed_units={m.completed_units}, known_capex={_fmt_money(m.known_capex)}, "
        f"WIP={m.wip}, avg_flow_time={m.avg_flow_time:.1f}s, added_machines={m.added_machine_count}."
    ]
    if status == CandidateRankStatus.DOMINATED:
        lines.append(
            f"Dominated by {', '.join(dominated_by)}: at least one alternative matches or exceeds "
            f"this candidate on every measured dimension and is strictly better in at least one."
        )
    return lines


def _known_tradeoffs(m: _Metrics, primary: _Metrics) -> list[str]:
    if m.candidate_id == primary.candidate_id:
        return []
    diffs: list[str] = []
    # "Lower CAPEX" is a comparison, and a comparison needs two comparable numbers.
    if not (m.commercially_complete and primary.commercially_complete):
        diffs.append(
            f"Cost cannot be compared with {primary.candidate_id}: "
            f"{'both plans have' if not m.commercially_complete and not primary.commercially_complete else 'one plan has'} "
            f"cost inputs that are not yet known."
        )
    elif m.known_capex < primary.known_capex - 1e-6:
        diffs.append(f"Lower CAPEX than {primary.candidate_id} ({_fmt_money(m.known_capex)} vs {_fmt_money(primary.known_capex)}).")
    elif m.known_capex > primary.known_capex + 1e-6:
        diffs.append(f"Higher CAPEX than {primary.candidate_id} ({_fmt_money(m.known_capex)} vs {_fmt_money(primary.known_capex)}).")
    if m.demand_met and not primary.demand_met:
        diffs.append(f"Meets demand while {primary.candidate_id} does not.")
    elif not m.demand_met and primary.demand_met:
        diffs.append(f"Does not fully meet demand (gap={m.demand_gap:g} units), unlike {primary.candidate_id}.")
    if m.wip < primary.wip - 1e-6:
        diffs.append(f"Lower WIP than {primary.candidate_id} ({m.wip} vs {primary.wip}).")
    elif m.wip > primary.wip + 1e-6:
        diffs.append(f"Higher WIP than {primary.candidate_id} ({m.wip} vs {primary.wip}).")
    return diffs


def _unknown_rationale(evaluation: CandidateEvaluation, primary: _Metrics | None) -> list[str]:
    sim = evaluation.simulation_result
    if sim is None:
        return ["Cost is not yet estimated (requires_cost_estimate=True); no operational data is available."]

    lines = [
        f"Operationally feasible (demand_met={sim.demand_met}, WIP={sim.system.work_in_progress}, "
        f"avg_flow_time={sim.system.average_flow_time_seconds:.1f}s), but cost is not yet estimated "
        f"(requires_cost_estimate=True) — cannot be ranked against known-cost candidates on CAPEX. "
        f"Potentially attractive pending cost estimate."
    ]

    # Never assert dominance on the unmeasurable cost dimension — but when
    # this candidate offers no operational edge at all over the recommended
    # known-cost primary, say so plainly (Phase 4C section 8: a combined
    # candidate "could be dominated by the simpler/cheaper parallel-only
    # solution if both meet demand equally").
    if primary is not None and (
        sim.demand_met == primary.demand_met
        and sim.system.work_in_progress >= primary.wip - 1e-6
        and sim.system.average_flow_time_seconds >= primary.avg_flow_time - 1e-6
    ):
        lines.append(
            f"Offers no operational advantage over the recommended {primary.candidate_id} "
            f"(already demand_met={primary.demand_met} at known cost {_fmt_money(primary.known_capex)}); "
            f"not preferred over it pending a cost estimate."
        )
    return lines


def _infeasible_rationale(evaluation: CandidateEvaluation) -> list[str]:
    reasons = ", ".join(r.value for r in evaluation.rejection_reasons) or "unspecified"
    return [f"Excluded from ranking: infeasible ({reasons})."]


# Public entry point

def rank_candidates(result: OptimizationEvaluationResult, goal: OptimizationGoal) -> OptimizationRecommendation:
    """
    Rank every candidate in *result* and select a recommendation set, per *goal*'s
    objective.
    """
    known_metrics: list[_Metrics] = []
    unknown_evals: list[CandidateEvaluation] = []
    infeasible_evals: list[CandidateEvaluation] = []

    for evaluation in result.candidates:
        if evaluation.status == CandidateFeasibilityStatus.INFEASIBLE:
            infeasible_evals.append(evaluation)
        elif evaluation.requires_cost_estimate:
            unknown_evals.append(evaluation)
        else:
            known_metrics.append(_extract_metrics(evaluation))

    # Demand-fulfillment gate (MINIMIZE_WIP / MINIMIZE_FLOW_TIME only)
    gated_fallback = False
    eligible = known_metrics
    if _requires_demand_gate(goal.objective) and known_metrics:
        met = [m for m in known_metrics if m.demand_met]
        if met:
            eligible = met
        else:
            gated_fallback = True  # none meet demand; fall back to full set

    dims = _pareto_dimensions(goal.objective)
    frontier_ids, dominated_by_map, dominates_map = compute_dominance(
        [(m.candidate_id, m.as_dims()) for m in eligible], dims
    )

    key_fn = _ranking_key(goal.objective)
    ordered = sorted(eligible, key=key_fn)
    rank_of = {m.candidate_id: i + 1 for i, m in enumerate(ordered)}

    # Recommendation set
    recommended_ids: list[str] = []
    if ordered:
        primary_pick = ordered[0]
        recommended_ids.append(primary_pick.candidate_id)
        for m in ordered[1:]:
            if len(recommended_ids) >= _MAX_RECOMMENDED:
                break
            if m.candidate_id in frontier_ids and _same_primary_tier(goal.objective, m, primary_pick):
                recommended_ids.append(m.candidate_id)

    metrics_by_id = {m.candidate_id: m for m in known_metrics}
    primary = metrics_by_id[recommended_ids[0]] if recommended_ids else None

    rankings: list[CandidateRanking] = []
    for evaluation in result.candidates:
        cid = evaluation.candidate.candidate_id

        if evaluation.status == CandidateFeasibilityStatus.INFEASIBLE:
            rankings.append(CandidateRanking(
                candidate_id=cid, status=CandidateRankStatus.INFEASIBLE,
                rationale=_infeasible_rationale(evaluation),
            ))
            continue

        if evaluation.requires_cost_estimate:
            rankings.append(CandidateRanking(
                candidate_id=cid, status=CandidateRankStatus.REQUIRES_INFORMATION,
                rationale=_unknown_rationale(evaluation, primary),
            ))
            continue

        m = metrics_by_id[cid]
        if cid not in rank_of:
            # Gated out for this objective (didn't meet the demand gate,
            # and the gate wasn't in fallback mode) — still known-cost and
            # feasible, but not part of THIS objective's comparison set.
            rankings.append(CandidateRanking(
                candidate_id=cid, status=CandidateRankStatus.DOMINATED,
                rationale=[
                    f"Excluded from {goal.objective.value} ranking: does not meet demand "
                    f"(demand_gap={m.demand_gap:g} units), and at least one other known-cost "
                    f"candidate does."
                ],
            ))
            continue

        if cid in recommended_ids:
            status = CandidateRankStatus.RECOMMENDED
        elif cid in frontier_ids:
            status = CandidateRankStatus.PARETO_OPTIMAL
        else:
            status = CandidateRankStatus.DOMINATED

        tradeoffs = _known_tradeoffs(m, primary) if primary is not None else []
        rankings.append(CandidateRanking(
            candidate_id=cid, status=status, rank=rank_of[cid],
            dominated_by=dominated_by_map.get(cid, []),
            dominates=dominates_map.get(cid, []),
            rationale=_known_rationale(m, rank_of[cid], status, dominated_by_map.get(cid, [])),
            tradeoffs=tradeoffs,
        ))

    summary = _build_summary(goal, ordered, recommended_ids, unknown_evals, infeasible_evals, gated_fallback)

    return OptimizationRecommendation(
        goal=goal,
        baseline_result=result.baseline_simulation,
        rankings=rankings,
        pareto_candidate_ids=[m.candidate_id for m in ordered if m.candidate_id in frontier_ids],
        recommended_candidate_ids=recommended_ids,
        summary=summary,
    )


def _build_summary(
    goal: OptimizationGoal,
    ordered: list[_Metrics],
    recommended_ids: list[str],
    unknown_evals: list[CandidateEvaluation],
    infeasible_evals: list[CandidateEvaluation],
    gated_fallback: bool,
) -> str:
    parts: list[str] = []

    if not ordered:
        parts.append(f"No feasible known-cost candidate is available for objective {goal.objective.value}.")
        if unknown_evals:
            ids = ", ".join(e.candidate.candidate_id for e in unknown_evals)
            parts.append(
                f"{len(unknown_evals)} candidate(s) remain REQUIRES_INFORMATION (cost not yet estimated) "
                f"and may be potentially attractive pending a cost estimate: {ids}."
            )
        if infeasible_evals:
            parts.append(f"{len(infeasible_evals)} candidate(s) are INFEASIBLE and excluded from ranking.")
        return " ".join(parts)

    top = ordered[0]
    if goal.objective == OptimizationObjective.MEET_DEMAND:
        if top.demand_met:
            parts.append(
                f"Recommended: {top.candidate_id} (demand_met=True, known_capex={_fmt_money(top.known_capex)}, "
                f"WIP={top.wip}, avg_flow_time={top.avg_flow_time:.1f}s)."
            )
        else:
            parts.append(
                f"No known-cost candidate fully meets demand; the target remains UNMET. Best available: "
                f"{top.candidate_id} (demand_gap={top.demand_gap:g} units, "
                f"known_capex={_fmt_money(top.known_capex)})."
            )
    else:
        parts.append(f"Recommended: {top.candidate_id} for objective {goal.objective.value}.")
        if _requires_demand_gate(goal.objective) and not top.demand_met:
            parts.append("Note: this candidate does not fully meet demand.")

    if len(recommended_ids) > 1:
        parts.append(f"Alternative(s) with meaningful tradeoffs: {', '.join(recommended_ids[1:])}.")

    if gated_fallback:
        parts.append(
            "No known-cost candidate meets demand; ranking fell back to comparing all feasible "
            "known-cost candidates directly on this objective."
        )
    if unknown_evals:
        ids = ", ".join(e.candidate.candidate_id for e in unknown_evals)
        parts.append(f"{len(unknown_evals)} candidate(s) remain REQUIRES_INFORMATION (cost not yet estimated): {ids}.")
    if infeasible_evals:
        parts.append(f"{len(infeasible_evals)} candidate(s) are INFEASIBLE and excluded from ranking.")

    return " ".join(parts)
