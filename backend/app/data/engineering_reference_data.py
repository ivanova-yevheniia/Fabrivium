"""
Engineering reference data for preliminary cycle-time estimation — Phase 18B.

EVERY CONSTANT HERE IS DECLARED, NOT ASSUMED
--------------------------------------------
Each entry carries its meaning, unit, process category, a **source
classification** and its applicability limits. Nothing in this file is an
industry standard, and the code that reads it says so on screen.

Two source classifications, and the difference matters:

* ``REFERENCE_DATASET`` — traceable to the bundled *Electronics Assembly
  Demo Dataset*, the same file the concept builder's example data comes
  from. It is one line's worth of data, not a population.
* ``STATED_ASSUMPTION`` — a value we chose, with the reasoning written
  down. Defensible, documented, and explicitly ours.

WHY BANDS AND NOT NUMBERS
-------------------------
A single figure would be false precision at concept stage. Every entry is a
range, and the estimator composes ranges rather than points, so the width of
the answer reflects the width of what is actually known.

REPLACEABILITY
--------------
The estimator reads only this module's tables. Substituting credible
external references later means editing this file — no estimator rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

#: The dataset the REFERENCE_DATASET entries are traceable to.
REFERENCE_DATASET_NAME = "Electronics Assembly Demo Dataset"


class ReferenceClass(str, Enum):
    """How much weight a constant can carry."""

    #: Read from the bundled demo dataset named above.
    REFERENCE_DATASET = "REFERENCE_DATASET"
    #: Chosen by us, with the rationale recorded. Not a standard.
    STATED_ASSUMPTION = "STATED_ASSUMPTION"


@dataclass(frozen=True)
class ReferenceBand:
    """One documented range."""

    low: float
    high: float
    unit: str
    process_category: str
    meaning: str
    source_class: ReferenceClass
    rationale: str
    applicability: str

    def __post_init__(self) -> None:
        if self.low > self.high:
            raise ValueError(f"Reference band for {self.process_category} is inverted.")


@dataclass(frozen=True)
class ProcessProfile:
    """Everything the estimator knows about one process family."""

    process_category: str
    #: Loading, positioning and unloading the unit at the station — the part
    #: that does not repeat with the operation count.
    handling: ReferenceBand
    #: One repetition of the characteristic operation (one screw, one
    #: check, one cable, one carton step).
    per_operation: ReferenceBand
    #: What "one operation" means for this family, shown in the UI so the
    #: engineer knows what number to type.
    operation_noun: str
    #: The dataset's own station value, kept for the sanity check below.
    dataset_station_seconds: float


# ---------------------------------------------------------------------------
# Automation
# ---------------------------------------------------------------------------
#
# These scale the PER-OPERATION part only; handling is dominated by fixture
# and transport design rather than by how the operation itself is performed.
#
# They are STATED_ASSUMPTIONS. We have no measured basis for them and do not
# pretend to: what they encode is the ordinary engineering expectation that
# a powered tool beats a hand tool and a machine beats both. They are
# deliberately coarse — three steps, not a curve — because a finer scale
# would imply a precision that does not exist.

AUTOMATION_FACTORS: dict[str, ReferenceBand] = {
    "MANUAL": ReferenceBand(
        low=1.0, high=1.0, unit="factor", process_category="*",
        meaning="Operation performed by an operator with hand tools.",
        source_class=ReferenceClass.STATED_ASSUMPTION,
        rationale="The reference bands below are written for the manual case, so this is 1.0 by construction.",
        applicability="All four covered families.",
    ),
    "ASSISTED": ReferenceBand(
        low=0.65, high=0.85, unit="factor", process_category="*",
        meaning="Operator works with a powered or guided tool (e.g. a fixtured driver).",
        source_class=ReferenceClass.STATED_ASSUMPTION,
        rationale=(
            "Assumes the tool removes part of the operation time but the operator still "
            "positions and triggers each repetition, so the saving is partial."
        ),
        applicability="Not validated against measurement. Widen or replace before using commercially.",
    ),
    "AUTOMATIC": ReferenceBand(
        low=0.35, high=0.60, unit="factor", process_category="*",
        meaning="Operation performed by the machine without per-repetition operator action.",
        source_class=ReferenceClass.STATED_ASSUMPTION,
        rationale=(
            "Assumes the repetition itself is machine-paced. Deliberately kept well above zero: "
            "an automatic station still indexes, clamps and verifies."
        ),
        applicability="Not validated against measurement. A specific machine's datasheet always overrides this.",
    ),
}

#: Applied when the automation level is not stated. It does not shift the
#: estimate — it widens it, because not knowing should make the answer less
#: precise rather than differently precise.
UNKNOWN_AUTOMATION_WIDENING = ReferenceBand(
    low=0.5, high=1.0, unit="factor", process_category="*",
    meaning="Extra width applied to the low end when automation level is unstated.",
    source_class=ReferenceClass.STATED_ASSUMPTION,
    rationale=(
        "An unstated automation level could be any of the three above. Rather than picking one, "
        "the band is stretched down to cover the automatic case while the manual case sets the top."
    ),
    applicability="Only when the engineer left automation as Unknown.",
)


# ---------------------------------------------------------------------------
# Process families
# ---------------------------------------------------------------------------
#
# Covered: the families the competition demo actually produces. Everything
# else is deliberately absent — the estimator says it cannot help rather than
# extrapolating a band from a family it has no data for.
#
# `labelling` is the one entry that is not anchored to a station value of its
# own, and it says so in every band it carries. It exists because the process
# planner proposes a labelling operation where the source requires a label to
# be APPLIED, and the packaging family's documented scope already includes
# that step — its per-operation band is defined as "bag, insert literature,
# erect or close a carton, seal, LABEL". Reusing that band with the
# derivation stated is not the same as inventing a number for a family we
# know nothing about; what would be dishonest is presenting it as separately
# anchored, so it is not in SANITY_CHECKS and its rationale names its parent.

PROCESS_PROFILES: dict[str, ProcessProfile] = {
    "assembly": ProcessProfile(
        process_category="assembly",
        operation_noun="assembly step (a placement, a connection, a closure)",
        dataset_station_seconds=35.0,
        handling=ReferenceBand(
            low=12.0, high=25.0, unit="s", process_category="assembly",
            meaning="Fetch the housing, present it at the station, set the finished unit down.",
            source_class=ReferenceClass.STATED_ASSUMPTION,
            rationale="Sized so that a three-step manual assembly spans the dataset's 35 s station value.",
            applicability="Bench assembly of a hand-sized product. Not valid for large or heavy assemblies.",
        ),
        per_operation=ReferenceBand(
            low=6.0, high=14.0, unit="s", process_category="assembly",
            meaning="One placement, cable connection or enclosure closure.",
            source_class=ReferenceClass.STATED_ASSUMPTION,
            rationale="Chosen so the composed band contains the dataset's station value; see SANITY_CHECKS.",
            applicability="Small electronics parts handled without tools or with a simple tool.",
        ),
    ),
    "screwdriving": ProcessProfile(
        process_category="screwdriving",
        operation_noun="screw",
        dataset_station_seconds=52.0,
        handling=ReferenceBand(
            low=6.0, high=12.0, unit="s", process_category="screwdriving",
            meaning="Position the unit in the fixture and release it afterwards.",
            source_class=ReferenceClass.STATED_ASSUMPTION,
            rationale="Smaller than assembly handling: the unit arrives already built and only needs locating.",
            applicability="Fixtured bench screwdriving.",
        ),
        per_operation=ReferenceBand(
            low=4.0, high=9.0, unit="s", process_category="screwdriving",
            meaning="Acquire one screw, locate it, drive it to torque.",
            source_class=ReferenceClass.STATED_ASSUMPTION,
            rationale=(
                "Sized so six screws plus handling spans the dataset's 52 s station value, which is the "
                "only screwdriving figure we can point at."
            ),
            applicability="Self-tapping or machine screws into plastic or thin sheet. Not valid for high-torque joints.",
        ),
    ),
    "inspection": ProcessProfile(
        process_category="inspection",
        operation_noun="check",
        dataset_station_seconds=30.0,
        handling=ReferenceBand(
            low=5.0, high=10.0, unit="s", process_category="inspection",
            meaning="Present the unit to the inspector or the camera and pass it on.",
            source_class=ReferenceClass.STATED_ASSUMPTION,
            rationale="Least handling of the four: nothing is fastened or enclosed.",
            applicability="Visual or functional bench inspection.",
        ),
        per_operation=ReferenceBand(
            low=8.0, high=22.0, unit="s", process_category="inspection",
            meaning="One check — a visual criterion, a measurement or a functional test.",
            source_class=ReferenceClass.STATED_ASSUMPTION,
            rationale=(
                "Wide on purpose: a glance and an electrical test are both 'one check' and differ by an "
                "order of magnitude. The width is the honest part."
            ),
            applicability="Not valid for burn-in, soak testing or anything with a fixed dwell time.",
        ),
    ),
    "packaging": ProcessProfile(
        process_category="packaging",
        operation_noun="packaging step (bagging, insert, carton, seal, label)",
        dataset_station_seconds=25.0,
        handling=ReferenceBand(
            low=6.0, high=12.0, unit="s", process_category="packaging",
            meaning="Collect the finished unit and place the finished pack on the outfeed.",
            source_class=ReferenceClass.STATED_ASSUMPTION,
            rationale="Comparable to screwdriving handling; the unit is complete and needs no fixturing.",
            applicability="Single-unit retail or transit packing.",
        ),
        per_operation=ReferenceBand(
            low=6.0, high=14.0, unit="s", process_category="packaging",
            meaning="One packaging step: bag, insert literature, erect or close a carton, seal, label.",
            source_class=ReferenceClass.STATED_ASSUMPTION,
            rationale="Sized so a two-step manual pack spans the dataset's 25 s station value.",
            applicability="Manual or semi-automatic packing. Not valid for case packers or palletisers.",
        ),
    ),
    "labelling": ProcessProfile(
        process_category="labelling",
        operation_noun="label applied",
        # The packaging family's station value, because these bands ARE the
        # packaging family's. Not a labelling measurement — see above.
        dataset_station_seconds=25.0,
        handling=ReferenceBand(
            low=6.0, high=12.0, unit="s", process_category="labelling",
            meaning="Collect the finished unit, present it to the applicator and pass it on.",
            source_class=ReferenceClass.STATED_ASSUMPTION,
            rationale=(
                "The packaging family's handling band, unchanged. The unit is complete and needs "
                "no fixturing in either case, and we have no separate labelling measurement."
            ),
            applicability=(
                "Derived from the packaging family, not measured for labelling. Not valid for "
                "print-and-apply systems or in-line laser marking."
            ),
        ),
        per_operation=ReferenceBand(
            low=6.0, high=14.0, unit="s", process_category="labelling",
            meaning="One label peeled, positioned and pressed down.",
            source_class=ReferenceClass.STATED_ASSUMPTION,
            rationale=(
                "The packaging family's per-operation band, unchanged: its own documented meaning "
                "already lists labelling as one of the steps it covers."
            ),
            applicability=(
                "Derived from the packaging family, not measured for labelling. Not valid where "
                "the label must be verified, scanned or applied to a curved surface."
            ),
        ),
    ),
}


# ---------------------------------------------------------------------------
# Sanity checks
# ---------------------------------------------------------------------------
#
# Each entry is (process_category, operations, expected station seconds from
# the dataset). A test asserts the composed MANUAL band contains the
# dataset's own value for that family — which is what makes these bands
# "anchored" rather than invented. If a band is ever edited so that it no
# longer contains the one real number we have, the test fails.
#
# The operation counts are our reading of what the demo line's stations do.
# They are assumptions about the dataset, not values inside it.

SANITY_CHECKS: list[tuple[str, int, float]] = [
    ("assembly", 3, 35.0),
    ("screwdriving", 6, 52.0),
    ("inspection", 1, 30.0),
    ("packaging", 2, 25.0),
]


def profile_for(process_category: str) -> ProcessProfile | None:
    """The profile for a family, or None when we have no basis for it."""
    return PROCESS_PROFILES.get(process_category.strip().lower())


def covered_categories() -> list[str]:
    return sorted(PROCESS_PROFILES)
