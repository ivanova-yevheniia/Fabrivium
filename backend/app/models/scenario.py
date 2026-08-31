"""Domain models for Fabrivium Phase 2A – Scenario / factory-modification actions."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, model_validator

# Reusable annotated types (mirrors app.models.factory)

PositiveFloat = Annotated[float, Field(gt=0)]
PositiveInt = Annotated[int, Field(gt=0)]


# Individual actions

class AddParallelMachineAction(BaseModel):
    """Clone an existing machine as a physically distinct parallel unit."""

    model_config = {"frozen": True}

    action_type: Literal["ADD_PARALLEL_MACHINE"] = "ADD_PARALLEL_MACHINE"
    machine_id: str = Field(..., min_length=1, description="ID of the machine to clone")


class ChangeMachineCycleTimeAction(BaseModel):
    """Set a machine's cycle_time on the candidate factory only."""

    model_config = {"frozen": True}

    action_type: Literal["CHANGE_MACHINE_CYCLE_TIME"] = "CHANGE_MACHINE_CYCLE_TIME"
    machine_id: str = Field(..., min_length=1, description="ID of the target machine")
    cycle_time: PositiveFloat = Field(..., description="New processing time per unit (s)")


class ChangeMachineCapacityAction(BaseModel):
    """Set a machine's capacity on the candidate factory only."""

    model_config = {"frozen": True}

    action_type: Literal["CHANGE_MACHINE_CAPACITY"] = "CHANGE_MACHINE_CAPACITY"
    machine_id: str = Field(..., min_length=1, description="ID of the target machine")
    capacity: PositiveInt = Field(..., description="New max concurrent units in process")


class ChangeDemandAction(BaseModel):
    """Set a product's demand_per_day on the candidate factory only."""

    model_config = {"frozen": True}

    action_type: Literal["CHANGE_DEMAND"] = "CHANGE_DEMAND"
    product_id: str = Field(..., min_length=1, description="ID of the target product")
    demand_per_day: PositiveFloat = Field(..., description="New required daily output (units/day)")


class RemoveMachineAction(BaseModel):
    """Remove a machine from the candidate factory."""

    model_config = {"frozen": True}

    action_type: Literal["REMOVE_MACHINE"] = "REMOVE_MACHINE"
    machine_id: str = Field(..., min_length=1, description="ID of the machine to remove")


# Phase 8A — non-machine engineering levers Three interventions that change how a line
# performs WITHOUT buying a machine:


class ChangeShiftConfigurationAction(BaseModel):
    """Change how much production time a day actually contains."""

    model_config = {"frozen": True}

    action_type: Literal["CHANGE_SHIFT_CONFIGURATION"] = "CHANGE_SHIFT_CONFIGURATION"
    shifts_per_day: PositiveInt | None = Field(
        None, le=6, description="New shifts per day (1-6). None = keep the factory's current value."
    )
    hours_per_shift: PositiveFloat | None = Field(
        None, le=24.0, description="New hours per shift (0-24). None = keep the factory's current value."
    )

    @model_validator(mode="after")
    def _at_least_one(self) -> "ChangeShiftConfigurationAction":
        if self.shifts_per_day is None and self.hours_per_shift is None:
            raise ValueError(
                "CHANGE_SHIFT_CONFIGURATION requires shifts_per_day, hours_per_shift, or both."
            )
        return self

    @model_validator(mode="after")
    def _within_a_day(self) -> "ChangeShiftConfigurationAction":
        # Only checkable when BOTH are supplied here; the combination with a
        # carried-over baseline value is validated in apply_scenario, which
        # is the only place that knows the baseline.
        if self.shifts_per_day is not None and self.hours_per_shift is not None:
            total = self.shifts_per_day * self.hours_per_shift
            if total > 24.0:
                raise ValueError(
                    f"CHANGE_SHIFT_CONFIGURATION would schedule {total:g} production hours "
                    f"in a 24-hour day."
                )
        return self


class ChangeOperatorCapacityAction(BaseModel):
    """Change the size of the shared workforce pool."""

    model_config = {"frozen": True}

    action_type: Literal["CHANGE_OPERATOR_CAPACITY"] = "CHANGE_OPERATOR_CAPACITY"
    operators_available: PositiveInt = Field(
        ..., le=1000, description="New total number of operators available simultaneously."
    )


class ChangeBufferCapacityAction(BaseModel):
    """Change how many units one buffer can hold between two stages."""

    model_config = {"frozen": True}

    action_type: Literal["CHANGE_BUFFER_CAPACITY"] = "CHANGE_BUFFER_CAPACITY"
    buffer_id: str = Field(..., min_length=1, description="ID of the buffer to resize")
    new_capacity: PositiveInt = Field(..., le=100_000, description="New maximum units the buffer can hold")


# Discriminated union

ScenarioAction = Annotated[
    Union[
        AddParallelMachineAction,
        ChangeMachineCycleTimeAction,
        ChangeMachineCapacityAction,
        ChangeDemandAction,
        RemoveMachineAction,
        ChangeShiftConfigurationAction,
        ChangeOperatorCapacityAction,
        ChangeBufferCapacityAction,
    ],
    Field(discriminator="action_type"),
]

# Every action_type Fabrivium can actually execute, derived from the union above rather
# than written out by hand — so it cannot drift from what apply_scenario supports.
SUPPORTED_ACTION_TYPES: frozenset[str] = frozenset(
    member.model_fields["action_type"].default
    for member in ScenarioAction.__origin__.__args__  # type: ignore[attr-defined]
)


# Scenario

class Scenario(BaseModel):
    """A named, ordered set of modifications to apply to a baseline Factory."""

    model_config = {"frozen": True}

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str = Field("", description="Human-readable summary of intent")
    actions: list[ScenarioAction] = Field(default_factory=list)
