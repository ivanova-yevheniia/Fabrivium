"""Route integrity validator for Fabrivium Phase 1."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.factory import Factory, Product
from app.services.machine_pool import MachinePoolError, resolve_pool


# Result dataclass (not a Pydantic model – used internally by the service)

@dataclass(frozen=True)
class RouteValidationResult:
    """Outcome of route validation."""
    valid: bool
    errors: list[str] = field(default_factory=list)


# Validator

def validate_route(factory: Factory, product: Product) -> RouteValidationResult:
    """Validate *product*'s route against *factory*."""
    errors: list[str] = []

    if len(product.route) == 0:
        errors.append(
            f"Product '{product.id}' has an empty route; "
            "at least one ProcessStep is required."
        )
        # No point checking individual steps; return early.
        return RouteValidationResult(valid=False, errors=errors)

    for idx, step in enumerate(product.route):
        position = f"step[{idx}] '{step.name}'"

        # Machine (service pool) existence — see docstring for why this is
        # a pool resolution, not a literal machine_id lookup.
        try:
            resolve_pool(factory, step.machine_id)
        except MachinePoolError:
            errors.append(
                f"Product '{product.id}' {position} references machine "
                f"'{step.machine_id}', which does not exist in factory "
                f"'{factory.name}' and has no surviving parallel clone."
            )

        # Positive cycle time (defence-in-depth)
        if step.cycle_time <= 0:
            errors.append(
                f"Product '{product.id}' {position} has non-positive "
                f"cycle_time {step.cycle_time!r}."
            )

    return RouteValidationResult(valid=len(errors) == 0, errors=errors)
