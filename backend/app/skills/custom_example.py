"""An example company skill — proving the extension boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.skills.contract import (
    Skill,
    SkillCategory,
    SkillContext,
    SkillDefinition,
    SkillResult,
    SkillStatus,
)

# The threshold this skill checks against when a project configures none.
DEFAULT_CAPEX_THRESHOLD_EUR = 150_000.0


@dataclass(frozen=True)
class CapexAnnotation:
    """One plan, judged against the configured capex policy."""

    strategy_id: str
    known_capex: float
    # WITHIN_POLICY / ABOVE_THRESHOLD / COST_UNKNOWN.
    verdict: str
    note: str


class AvoidHighCapexPreferenceSkill(Skill):
    """Flag verified plans whose known capital cost exceeds a company limit."""

    @property
    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            id="avoid_high_capex_preference",
            version="1.0.0",
            name="Capex preference policy",
            description=(
                "Annotates verified strategies against a company capital-expenditure "
                "threshold. Adds a preference signal; never re-ranks, never alters a "
                "simulated value, and never assumes a missing price."
            ),
            category=SkillCategory.OPTIMIZATION,
            capabilities=("apply_capex_policy",),
            prerequisites=("strategy_generation",),
            input_types=("list[VerifiedStrategyOption]",),
            output_types=("list[CapexAnnotation]",),
            # A different namespace and owner: this is what keeps a company
            # skill from colliding with a first-party one in the registry.
            namespace="acme",
            owner="ACME Manufacturing GmbH",
            # Below the first-party default of 50: a preference must never
            # outrank a capability that produces engineering output.
            priority=10,
            supported_provenance=("EXTERNAL_DATA",),
        )

    def execute(self, payload: Any, context: SkillContext) -> SkillResult:
        strategies = payload.get("strategies") if isinstance(payload, dict) else payload
        if not strategies:
            return self._blocked(
                "No verified strategies were supplied to apply the policy to.",
                missing=["strategies"],
            )

        settings = context.settings_for(self.definition.id)
        threshold = float(settings.get("threshold_eur", DEFAULT_CAPEX_THRESHOLD_EUR))

        annotations: list[CapexAnnotation] = []
        unknown_cost = 0

        for option in strategies:
            cost = getattr(getattr(option, "cost", None), "known_capex", None)
            complete = bool(getattr(option, "commercially_complete", False))
            strategy_id = getattr(option, "strategy_id", "unknown")

            if cost is None or not complete:
                # A policy check against a number nobody has is not a pass
                # and not a failure. Saying so is the whole point.
                unknown_cost += 1
                annotations.append(
                    CapexAnnotation(
                        strategy_id=strategy_id,
                        known_capex=float(cost or 0.0),
                        verdict="COST_UNKNOWN",
                        note=(
                            "This plan is not fully priced, so it cannot be checked against the "
                            f"€{threshold:,.0f} threshold. A quotation is needed before the "
                            "policy means anything here."
                        ),
                    )
                )
                continue

            if float(cost) > threshold:
                annotations.append(
                    CapexAnnotation(
                        strategy_id=strategy_id,
                        known_capex=float(cost),
                        verdict="ABOVE_THRESHOLD",
                        note=(
                            f"€{float(cost):,.0f} exceeds the €{threshold:,.0f} capital approval "
                            f"threshold. Still a valid engineering option — it needs a capital "
                            f"request."
                        ),
                    )
                )
            else:
                annotations.append(
                    CapexAnnotation(
                        strategy_id=strategy_id,
                        known_capex=float(cost),
                        verdict="WITHIN_POLICY",
                        note=f"€{float(cost):,.0f} is within the €{threshold:,.0f} threshold.",
                    )
                )

        above = sum(1 for a in annotations if a.verdict == "ABOVE_THRESHOLD")
        # Unpriced plans leave the policy question open, which is PARTIAL.
        status = SkillStatus.PARTIAL if unknown_cost else SkillStatus.SUCCESS

        return SkillResult(
            status=status,
            data=annotations,
            provenance={"policy": "EXTERNAL_DATA"},
            unresolved_inputs=[
                f"price:{a.strategy_id}" for a in annotations if a.verdict == "COST_UNKNOWN"
            ],
            trace=[
                self._entry(
                    status,
                    f"{len(annotations)} plan(s) annotated; {above} above the threshold"
                    + (f", {unknown_cost} not priced" if unknown_cost else ""),
                )
            ],
        )
