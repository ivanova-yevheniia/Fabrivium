"""Rebuilding a verified strategy's factory from what a PROJECT actually keeps."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.factory import Factory
from app.models.scenario import AddParallelMachineAction, Scenario
from app.models.strategy import StrategyActionSummary, StrategyMetrics
from app.models.simulation import SimulationResult
from app.services.scenario import apply_scenario


class PlaybackNotReplayable(Exception):
    """This strategy cannot be replayed from what the project stores."""


# Levers whose effect is fully determined by ``StrategyActionSummary``.
_REPLAYABLE_ACTION_TYPES = frozenset({
    "ADD_PARALLEL_MACHINE",
    "CHANGE_SHIFT_CONFIGURATION",
    "CHANGE_OPERATOR_CAPACITY",
})

# Why each unreplayable lever is unreplayable, in the words the engineer needs.
_UNREPLAYABLE_REASON: dict[str, str] = {
    "CHANGE_MACHINE_CAPACITY": (
        "the plan changes a station's capacity, and the saved summary records that a "
        "capacity change happened without recording the value it was changed to"
    ),
    "CHANGE_MACHINE_CYCLE_TIME": (
        "the plan changes a station's cycle time, and the saved summary records that a "
        "cycle-time change happened without recording the new time"
    ),
    "CHANGE_BUFFER_CAPACITY": (
        "the plan resizes a buffer, and the saved summary records that only as a line of "
        "text written for a reader rather than as a number"
    ),
    "CHANGE_DEMAND": (
        "the plan changes the production target, which the saved summary does not record"
    ),
    "REMOVE_MACHINE": (
        "the plan removes a station, which the saved summary does not record"
    ),
}


@dataclass(frozen=True)
class ReplayCheck:
    """Whether a stored strategy can be replayed, and why not when it cannot."""

    replayable: bool
    reason: str | None = None


def replay_support(actions: StrategyActionSummary | None) -> ReplayCheck:
    """Can this strategy's factory be rebuilt exactly from its summary?"""
    if actions is None:
        return ReplayCheck(replayable=True)

    for action_type in actions.action_types:
        if action_type not in _REPLAYABLE_ACTION_TYPES:
            reason = _UNREPLAYABLE_REASON.get(
                action_type,
                f"the plan uses {action_type}, which the saved summary does not record in full",
            )
            return ReplayCheck(
                replayable=False,
                reason=f"This plan cannot be replayed from the saved project because {reason}.",
            )

    # A machine appeared that no recorded ADD_PARALLEL_MACHINE accounts for.
    if actions.added_machine_count != len(actions.added_machine_ids):
        return ReplayCheck(
            replayable=False,
            reason=(
                "This plan cannot be replayed from the saved project because it added "
                f"{actions.added_machine_count} machine(s) and the saved summary identifies "
                f"{len(actions.added_machine_ids)} of them."
            ),
        )

    if actions.buffer_changes:
        return ReplayCheck(
            replayable=False,
            reason=(
                "This plan cannot be replayed from the saved project because "
                + _UNREPLAYABLE_REASON["CHANGE_BUFFER_CAPACITY"]
                + "."
            ),
        )

    return ReplayCheck(replayable=True)


def reconstruct_factory(baseline: Factory, actions: StrategyActionSummary | None) -> Factory:
    """The factory a verified strategy was simulated on, rebuilt from *baseline*."""
    support = replay_support(actions)
    if not support.replayable:
        raise PlaybackNotReplayable(support.reason or "This plan cannot be replayed.")
    if actions is None:
        return baseline

    candidate = baseline

    # Cloned stations, through the same primitive the arena used, so the new
    # machine's id, name and position are identical to the verified ones
    # rather than merely similar.
    if actions.added_machine_ids:
        candidate = apply_scenario(
            candidate,
            Scenario(
                id="playback-reconstruction",
                name="playback-reconstruction",
                actions=[
                    AddParallelMachineAction(machine_id=machine_id)
                    for machine_id in actions.added_machine_ids
                ],
            ),
        )

    # The operating model, as deltas against the baseline — which is exactly
    # how the summary recorded them.
    shifts = candidate.shifts_per_day + actions.added_shift_count
    hours = candidate.hours_per_shift + actions.hours_per_shift_delta
    operators = candidate.operators_available + actions.operator_delta

    if (shifts, hours, operators) != (
        candidate.shifts_per_day,
        candidate.hours_per_shift,
        candidate.operators_available,
    ):
        candidate = Factory.model_validate({
            **candidate.model_dump(),
            "shifts_per_day": shifts,
            "hours_per_shift": hours,
            "operators_available": operators,
        })

    return candidate


# Fields a replayed run must reproduce before its trace may be shown.
def verify_reproduces(result: SimulationResult, expected: StrategyMetrics) -> None:
    """Raise unless *result* is the run *expected* describes."""
    mismatches: list[str] = []
    if result.completed_units != expected.completed_units:
        mismatches.append(
            f"output {result.completed_units:,}/day against a verified {expected.completed_units:,}/day"
        )
    if result.target_units != expected.target_units:
        mismatches.append(
            f"target {result.target_units:,}/day against a verified {expected.target_units:,}/day"
        )

    if mismatches:
        raise PlaybackNotReplayable(
            "This plan can no longer be replayed: re-running it now produces "
            + ", and ".join(mismatches)
            + ". The concept has changed since this result was verified, so the saved "
            "figures and a fresh run no longer describe the same factory."
        )
