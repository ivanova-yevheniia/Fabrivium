"""Deterministic requirement matching — Phase 16, widened by the breadth phase."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.models.equipment_discovery import (
    CatalogKind,
    EquipmentCandidate,
    EquipmentRequirement,
    MatchClaim,
    PriceStatus,
    PublishedSpec,
)

# Concept envelopes are in metres, published equipment dimensions in millimetres.
MM_PER_M = 1000.0


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class CompatibilityCheck(BaseModel):
    """One field, compared once."""

    model_config = {"frozen": True}

    field: str
    label: str
    status: CheckStatus
    # What the concept asked for, already formatted for display.
    requirement_text: str
    # What the manufacturer published, or why nothing could be compared.
    candidate_text: str
    #: The reason in one sentence — always present for FAIL and UNKNOWN,
    #: because "why not" is the useful half of the answer.
    reason: str = ""


class CompatibilityReport(BaseModel):
    """The result of comparing one candidate against one requirement."""

    model_config = {"frozen": True}

    candidate_id: str
    station_id: str
    checks: list[CompatibilityCheck] = Field(default_factory=list)

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.checks if c.status is CheckStatus.PASS)

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if c.status is CheckStatus.FAIL)

    @property
    def unknown_count(self) -> int:
        return sum(1 for c in self.checks if c.status is CheckStatus.UNKNOWN)

    @property
    def blocked(self) -> bool:
        """Any hard failure at all disqualifies, regardless of the passes."""
        return self.fail_count > 0

    @property
    def claim(self) -> MatchClaim:
        """The strongest thing that may be said about this candidate."""
        if self.fail_count > 0:
            return MatchClaim.CONSTRAINT_MISMATCH
        if self.unknown_count > 0:
            return MatchClaim.CANDIDATE
        return MatchClaim.POTENTIALLY_SUITABLE

    @property
    def claim_text(self) -> str:
        """The claim as a sentence, with the reason it is capped."""
        if self.claim is MatchClaim.CONSTRAINT_MISMATCH:
            return (
                f"Constraint mismatch — {self.fail_count} of this station's requirements "
                f"is contradicted by a published value."
                if self.fail_count == 1
                else (
                    f"Constraint mismatch — {self.fail_count} of this station's requirements "
                    f"are contradicted by published values."
                )
            )
        if self.claim is MatchClaim.CANDIDATE:
            # Written out rather than "requirement(s)": this sentence is the
            # headline an engineer reads on every card, and a parenthesised
            # plural in the headline reads as a template nobody finished.
            noun = "requirement" if self.pass_count == 1 else "requirements"
            return (
                f"Candidate equipment — {self.pass_count} {noun} matched, "
                f"{self.unknown_count} could not be checked against published data."
            )
        return (
            f"Potentially suitable — all {self.pass_count} requirements this concept states "
            "were matched. Fabrivium has not checked the joint, the mounting, the control "
            "integration or the safety concept, so this is not a compatibility statement."
        )

    @property
    def matched(self) -> list[CompatibilityCheck]:
        return [c for c in self.checks if c.status is CheckStatus.PASS]

    @property
    def unverified(self) -> list[CompatibilityCheck]:
        """Requirements that could not be checked. Never folded into passes."""
        return [c for c in self.checks if c.status is CheckStatus.UNKNOWN]

    @property
    def mismatched(self) -> list[CompatibilityCheck]:
        return [c for c in self.checks if c.status is CheckStatus.FAIL]

    def summary(self) -> str:
        return (
            f"{self.pass_count} matched · {self.fail_count} mismatched · "
            f"{self.unknown_count} not verified"
        )


# Individual checks

def _unchecked(field: str, label: str, reason: str, requirement_text: str = "—") -> CompatibilityCheck:
    return CompatibilityCheck(
        field=field,
        label=label,
        status=CheckStatus.UNKNOWN,
        requirement_text=requirement_text,
        candidate_text="Not published",
        reason=reason,
    )


def _at_most(
    *,
    field: str,
    label: str,
    limit: float,
    limit_text: str,
    spec: PublishedSpec,
    spec_text: str,
    scale: float = 1.0,
) -> CompatibilityCheck:
    """The shared shape of every "candidate must not exceed" comparison."""
    if spec.value is None:
        return _unchecked(field, label, "The manufacturer does not publish this value.", limit_text)

    actual = spec.value * scale
    ok = actual <= limit
    return CompatibilityCheck(
        field=field,
        label=label,
        status=CheckStatus.PASS if ok else CheckStatus.FAIL,
        requirement_text=limit_text,
        candidate_text=spec_text,
        reason="" if ok else f"Published value exceeds the concept's limit of {limit_text}.",
    )


# How to name the source in a "does not publish this" sentence, per kind of catalogue.
_MISSING_VALUE_PHRASE: dict[CatalogKind, str] = {
    CatalogKind.RESEARCHED_MANUFACTURER: "The manufacturer does not publish",
    CatalogKind.INTERNAL_ASSET_POOL: "The customer's asset register does not record",
    CatalogKind.APPROVED_SUPPLIER: "The approved supplier list does not record",
    CatalogKind.EXTERNAL_SOURCE: "The external source does not provide",
}
assert set(_MISSING_VALUE_PHRASE) == set(CatalogKind), "every catalogue kind needs a phrase"


def _missing(cand: EquipmentCandidate, what: str) -> str:
    """"<source> does not publish <what>." — with the right source named."""
    return f"{_MISSING_VALUE_PHRASE[cand.catalog_kind]} {what}."


def _capability(req: EquipmentRequirement, cand: EquipmentCandidate) -> CompatibilityCheck:
    """Does this record DECLARE the capability the station needs?"""
    label = "Required capability"
    if req.required_capability is None:
        return _unchecked(
            "capability",
            label,
            "Fabrivium has no researched equipment capability for this kind of station, "
            "so nothing was searched for.",
        )

    wanted = req.required_capability.value.replace("_", " ").lower()
    declared = ", ".join(c.value.replace("_", " ").lower() for c in cand.provides) or "none"
    if cand.provides_capability(req.required_capability):
        return CompatibilityCheck(
            field="capability",
            label=label,
            status=CheckStatus.PASS,
            requirement_text=wanted,
            candidate_text=declared,
            reason="",
        )
    return CompatibilityCheck(
        field="capability",
        label=label,
        status=CheckStatus.FAIL,
        requirement_text=wanted,
        candidate_text=declared,
        # Never "the name does not match".
        reason=f"This record does not declare {wanted}.",
    )


def _cycle_time(req: EquipmentRequirement, cand: EquipmentCandidate) -> CompatibilityCheck:
    label = "Cycle time"
    if not req.max_cycle_time_seconds.known:
        return _unchecked("cycle_time", label, "The concept has no cycle time for this station yet.")

    station_limit = float(req.max_cycle_time_seconds.value or 0.0)

    # THE STATION'S BUDGET IS NOT THE EQUIPMENT'S BUDGET.
    repeats = int(req.operations_per_unit.value or 0) if req.operations_per_unit.known else 0
    if repeats > 1:
        limit = station_limit / repeats
        limit_text = f"≤ {limit:g} s per operation"
        divided = (
            f" The station's {station_limit:g} s covers {repeats} operations per unit, "
            f"so each one has {limit:g} s."
        )
    else:
        limit = station_limit
        limit_text = f"≤ {limit:g} s"
        divided = ""

    spec = cand.cycle_time_seconds
    if spec.value is None:
        # The common real-world case: cycle depends on the joint, the screw
        # manufacturer publishes a figure that could be compared here.
        return _unchecked(
            "cycle_time",
            label,
            _missing(cand, "a cycle time for this model")
            + " It has to be established with the supplier for this application."
            + divided,
            limit_text,
        )

    check = _at_most(
        field="cycle_time",
        label=label,
        limit=limit,
        limit_text=limit_text,
        spec=spec,
        spec_text=f"{spec.value:g} s",
    )
    # A cycle time WE derived from a published maximum is a best case, and a
    # PASS against a best case is a weaker statement than a PASS against a
    # published figure. Say so in the same sentence as the verdict.
    extra = f" {spec.basis}" if spec.basis else ""
    return check.model_copy(update={"reason": (check.reason + divided + extra).strip()})


def _footprint(req: EquipmentRequirement, cand: EquipmentCandidate) -> list[CompatibilityCheck]:
    checks = []
    for axis, bound, spec in (
        ("width", req.max_width_m, cand.width_mm),
        ("length", req.max_length_m, cand.length_mm),
    ):
        label = f"Footprint {axis}"
        field = f"footprint_{axis}"
        if not bound.known:
            checks.append(_unchecked(field, label, "The concept allocates no envelope for this axis."))
            continue
        limit_m = float(bound.value or 0.0)
        if spec.value is None:
            checks.append(
                _unchecked(field, label, _missing(cand, "this dimension"), f"≤ {limit_m:g} m")
            )
            continue
        checks.append(
            _at_most(
                field=field,
                label=label,
                limit=limit_m,
                limit_text=f"≤ {limit_m:g} m",
                spec=spec,
                spec_text=f"{spec.value:g} mm",
                scale=1.0 / MM_PER_M,
            )
        )
    return checks


def _capacity(req: EquipmentRequirement, cand: EquipmentCandidate) -> CompatibilityCheck:
    label = "Capacity"
    if not req.required_capacity.known:
        return _unchecked("capacity", label, "The concept does not state a required capacity.")
    needed = int(req.required_capacity.value or 0)
    spec = cand.capacity
    if spec.value is None:
        return _unchecked("capacity", label, _missing(cand, "a parallel-unit capacity"), f"≥ {needed}")
    ok = spec.value >= needed
    return CompatibilityCheck(
        field="capacity",
        label=label,
        status=CheckStatus.PASS if ok else CheckStatus.FAIL,
        requirement_text=f"≥ {needed}",
        candidate_text=f"{spec.value:g}",
        reason="" if ok else f"Published capacity is below the required {needed}.",
    )


def _operators(req: EquipmentRequirement, cand: EquipmentCandidate) -> CompatibilityCheck:
    label = "Operator requirement"
    if not req.operator_requirement.known:
        return _unchecked("operators", label, "The concept does not state an operator requirement.")
    allowed = int(req.operator_requirement.value or 0)
    spec = cand.operators_required
    if spec.value is None:
        return _unchecked(
            "operators",
            label,
            _missing(cand, "an operator requirement") + " It depends on how the station is loaded.",
            f"≤ {allowed}",
        )
    return _at_most(
        field="operators",
        label=label,
        limit=float(allowed),
        limit_text=f"≤ {allowed}",
        spec=spec,
        spec_text=f"{spec.value:g}",
    )


def _payload(req: EquipmentRequirement, cand: EquipmentCandidate) -> CompatibilityCheck:
    """What the equipment must hold or move, against what it can."""
    label = "Payload"
    if not req.max_payload_kg.known:
        return _unchecked(
            "payload",
            label,
            "Nothing has established how heavy the part this station handles is, so no "
            "payload requirement could be derived.",
        )
    needed = float(req.max_payload_kg.value or 0.0)
    return _unchecked(
        "payload",
        label,
        "None of the bundled catalogues records a payload rating for this model; it has "
        "to be confirmed with the supplier.",
        f"≥ {needed:g} kg",
    )


def _budget(req: EquipmentRequirement, cand: EquipmentCandidate) -> CompatibilityCheck:
    label = "Budget"
    if not req.budget_limit.known:
        # No bound to check against — but the candidate's price status is a
        # fact about the candidate, not about the concept, and hiding it
        # here left a station with no budget showing "Not published" for a
        # supplier who had actually told us they quote.
        return CompatibilityCheck(
            field="budget",
            label=label,
            status=CheckStatus.UNKNOWN,
            requirement_text="—",
            candidate_text=_price_text(cand),
            reason="No budget is recorded for this station, so nothing was checked.",
        )

    limit = float(req.budget_limit.value or 0.0)
    limit_text = f"≤ €{limit:,.0f}"

    if cand.price_status is PriceStatus.QUOTE_REQUIRED:
        # Not a hole in our data — it is how this market sells.
        return CompatibilityCheck(
            field="budget",
            label=label,
            status=CheckStatus.UNKNOWN,
            requirement_text=limit_text,
            candidate_text="Quote required",
            reason="The manufacturer does not publish a price; this one needs a quotation.",
        )
    if cand.price.value is None:
        return _unchecked("budget", label, _missing(cand, "a price for this model"), limit_text)

    return _at_most(
        field="budget",
        label=label,
        limit=limit,
        limit_text=limit_text,
        spec=cand.price,
        spec_text=f"€{cand.price.value:,.0f}",
    )


def _price_text(cand: EquipmentCandidate) -> str:
    """What to show in the price cell, without ever showing a euro sign for
    a price nobody published."""
    if cand.price_status is PriceStatus.QUOTE_REQUIRED:
        return "Quote required"
    if cand.price.value is not None:
        return f"€{cand.price.value:,.0f}"
    return "Not published"


def _interfaces(req: EquipmentRequirement, cand: EquipmentCandidate) -> list[CompatibilityCheck]:
    """Only ever checked against interfaces the concept explicitly demands."""
    if not req.required_interfaces:
        return []

    published = {i.strip().lower() for i in cand.interfaces}
    checks = []
    for wanted in req.required_interfaces:
        key = wanted.strip().lower()
        if not published:
            checks.append(
                _unchecked(
                    f"interface_{key}",
                    f"Interface · {wanted}",
                    _missing(cand, "an interface list for this model"),
                    wanted,
                )
            )
            continue
        ok = any(key in candidate_iface for candidate_iface in published)
        checks.append(
            CompatibilityCheck(
                field=f"interface_{key}",
                label=f"Interface · {wanted}",
                status=CheckStatus.PASS if ok else CheckStatus.FAIL,
                requirement_text=wanted,
                candidate_text=", ".join(cand.interfaces),
                reason="" if ok else f"{wanted} is not among the published interfaces.",
            )
        )
    return checks


# Entry point

def check_compatibility(
    requirement: EquipmentRequirement,
    candidate: EquipmentCandidate,
) -> CompatibilityReport:
    """Compare one candidate against one requirement, deterministically."""
    checks: list[CompatibilityCheck] = [
        _capability(requirement, candidate),
        _cycle_time(requirement, candidate),
        *_footprint(requirement, candidate),
        _capacity(requirement, candidate),
        _operators(requirement, candidate),
        _payload(requirement, candidate),
        _budget(requirement, candidate),
        *_interfaces(requirement, candidate),
    ]
    return CompatibilityReport(
        candidate_id=candidate.candidate_id,
        station_id=requirement.station_id,
        checks=checks,
    )
