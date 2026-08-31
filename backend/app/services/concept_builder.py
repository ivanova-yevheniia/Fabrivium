"""Building a factory concept from a customer brief — Phase 13."""

from __future__ import annotations

import re

from app.models.concept import (
    ConceptBuffer,
    ConceptStage,
    FactoryConceptDraft,
    SourcedFloat,
    SourcedInt,
    ValueSource,
)
from app.models.layout import FactoryLayout, LayoutZone, LayoutZoneType, MachinePlacement
from app.services.concept_validation import (
    DEFAULT_BUFFER_CAPACITY,
    DEFAULT_STATION_LENGTH_M,
    DEFAULT_STATION_WIDTH_M,
    FLOOR_MARGIN_M,
    STATION_GAP_M,
)

# Extraction patterns

# Time words that must never be read as the thing being produced.
_NOT_A_PRODUCT_NOUN = (
    r"hours?|hrs?|minutes?|mins?|seconds?|secs?|shifts?|days?|weeks?|months?|years?"
)

#: "1,900 units per day", "1900 units/day", "about 1900 a day", "1,900
#: finished units/day" — and, since a customer counts in whatever the
#: product is, "18,000 bottles per day" and "4,000 cassettes per day".
#:
#: WHY THE NOUN LIST IS NEGATIVE
# :
#: This pattern used to require the noun to be one of `units|pieces|pcs`.
#: That is not a description of how customers write; it is a list of the
#: three words the demo happened to use. A brief saying "18,000 bottles per
#: day" parsed to NO target at all, and the production target is the single
#: number the entire optimisation aims at — so a beverage line and a
#: medical-device line both arrived at the concept with their goal missing,
#: reported as an unresolved input the customer had in fact stated plainly.
#:
#: So any noun is accepted EXCEPT a unit of time. The exclusion is what the
#: closed list was really buying: without it "8 hours a day" reads as a
#: production target of eight. Up to two words may sit between the number
#: and "per day", and none of them may be a time word.
_TARGET_RE = re.compile(
    # `\s*` after the noun, not `\s+`: a customer writes "units/day" with no
    # space at all, and requiring one silently dropped the target.
    rf"(\d[\d,\.]*)\s*(?:(?!(?:{_NOT_A_PRODUCT_NOUN})\b)[a-z]+\s*){{0,2}}(?:per|/|a)\s*day",
    re.IGNORECASE,
)

# "8 operators", "eight operators", "we have 8 people".
_OPERATORS_RE = re.compile(
    r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s*"
    r"(?:operators?|workers?|people|staff)",
    re.IGNORECASE,
)

# "30 by 18 meters", "30 x 18 m", "30×18m".
_FLOOR_RE = re.compile(
    r"(\d[\d\.]*)\s*(?:m|meters?|metres?)?\s*(?:by|x|×)\s*(\d[\d\.]*)\s*(?:m\b|meters?|metres?)",
    re.IGNORECASE,
)

# "two 8-hour shifts", "2 shifts of 8 hours", "8 hour shift".
_SHIFT_COUNT_RE = re.compile(
    r"(\d+|one|two|three)\s*(?:x\s*)?(?:\d+[\-\s]?(?:hour|h)\s*)?shifts?",
    re.IGNORECASE,
)
_SHIFT_HOURS_RE = re.compile(
    r"(\d[\d\.]*)\s*[\-\s]?(?:hour|hours|h)\b",
    re.IGNORECASE,
)

_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}

# "avoid buying new machines", "prefer not to buy equipment", "without new machines".
_NO_NEW_EQUIPMENT_RE = re.compile(
    r"(?:avoid|without|prefer\s+not\s+to|rather\s+not|do\s+not|don't|no)\s+"
    r"(?:add\s+|adding\s+|buy\s+|buying\s+|purchase\s+|purchasing\s+|invest\s+in\s+)?"
    r"(?:(?:unnecessary|new|additional|extra|any|more|another|a)\s+)*"
    r"(?:equipment|machines?|stations?)",
    re.IGNORECASE,
)

_STAGE_VOCABULARY: list[tuple[str, str, list[str]]] = [
    # (canonical name, process_type, aliases)
    ("Assembly", "assembly", ["assembl", "mounting"]),
    ("Screwdriving", "screwdriving", ["screwdriv", "screw driving", "screwing", "fastening"]),
    ("Inspection", "inspection", ["inspect", "quality check", "testing", "test station"]),
    ("Packaging", "packaging", ["packag", "packing", "boxing"]),
    ("Welding", "welding", ["weld"]),
    ("Soldering", "soldering", ["solder"]),
    ("Painting", "painting", ["painting", "paint", "coating"]),
    ("Machining", "machining", ["machining", "milling", "turning", "cnc"]),
    ("Cleaning", "cleaning", ["cleaning", "washing", "degreasing"]),
    ("Labelling", "labelling", ["labelling", "labeling", "marking"]),
    ("Curing", "curing", ["curing", "drying", "oven"]),
    ("Palletizing", "palletizing", ["palletiz", "palletis", "stacking"]),
]


# A phrase SHAPED like a floor size, whatever unit word follows it.
_FLOOR_SHAPE_RE = re.compile(
    r"\d[\d\.]*\s*(?:m|meters?|metres?)?\s*(?:by|x|×)\s*\d[\d\.]*\s*[a-z]*",
    re.IGNORECASE,
)


def unreadable_floor_phrase(text: str) -> str | None:
    """A floor size the text appears to state and this module cannot read."""
    if _FLOOR_RE.search(text):
        return None
    match = _FLOOR_SHAPE_RE.search(text)
    return match.group(0).strip() if match else None


#: Keys for the production boundary conditions this module can read, with
#: the label each carries when it is quoted back.
PRODUCTION_KEYS: tuple[tuple[str, str], ...] = (
    ("production.target_per_day", "Required production volume"),
    ("production.floor_area", "Available production area"),
    ("production.operators", "Available production workforce"),
    ("production.shifts_per_day", "Shifts per day"),
    ("production.hours_per_shift", "Hours per shift"),
)


def production_values_in(text: str) -> dict[str, tuple[str, float, float | None]]:
    """Every production boundary condition *text* states, as plain numbers."""
    lowered = text.lower()
    found: dict[str, tuple[str, float, float | None]] = {}

    target = _TARGET_RE.search(text)
    if target:
        value = float(target.group(1).replace(",", ""))
        found["production.target_per_day"] = (f"{value:g} units/day", value, None)

    floor = _FLOOR_RE.search(text)
    if floor:
        width, length = float(floor.group(1)), float(floor.group(2))
        found["production.floor_area"] = (f"{width:g} × {length:g} m", width, length)

    operators = _OPERATORS_RE.search(text)
    if operators:
        raw = operators.group(1).lower()
        count = float(_WORD_NUMBERS.get(raw, raw if raw.isdigit() else 0))
        if count:
            found["production.operators"] = (f"{count:g} operators", count, None)

    # Shifts and hours are only read where the text is talking about shifts.
    if "shift" in lowered:
        shifts = _SHIFT_COUNT_RE.search(text)
        if shifts:
            raw = shifts.group(1).lower()
            count = float(_WORD_NUMBERS.get(raw, raw if raw.isdigit() else 0))
            if count:
                found["production.shifts_per_day"] = (f"{count:g} shifts/day", count, None)
        hours = _SHIFT_HOURS_RE.search(text)
        if hours:
            value = float(hours.group(1))
            found["production.hours_per_shift"] = (f"{value:g} h", value, None)

    return found


def stage_id_for(name: str) -> str:
    """Stable stage id derived from a stage name."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"m-{slug or 'stage'}"


# Brief → concept

def extract_stages(brief: str) -> list[ConceptStage]:
    """The process route the brief describes, in the order it describes it."""
    lowered = brief.lower()
    found: list[tuple[int, str, str]] = []

    for name, process_type, aliases in _STAGE_VOCABULARY:
        best: int | None = None
        for alias in aliases:
            index = lowered.find(alias)
            if index != -1 and (best is None or index < best):
                best = index
        if best is not None:
            found.append((best, name, process_type))

    found.sort(key=lambda item: item[0])

    return [
        ConceptStage(
            id=stage_id_for(name),
            name=name,
            process_type=process_type,
            # Physics is deliberately left unknown — the brief did not state
            # it, and this module does not invent it.
            cycle_time=SourcedFloat.unknown(),
            capacity=SourcedInt.unknown(),
            operators_required=SourcedInt.unknown(),
            width=SourcedFloat.unknown(),
            length=SourcedFloat.unknown(),
            purchase_cost=SourcedFloat.unknown(),
        )
        for _, name, process_type in found
    ]


def _extract_target(brief: str) -> SourcedFloat:
    match = _TARGET_RE.search(brief)
    if not match:
        return SourcedFloat.unknown()
    value = float(match.group(1).replace(",", ""))
    return SourcedFloat.of(value, ValueSource.CUSTOMER, "Stated in the customer brief")


def _extract_operators(brief: str) -> SourcedInt:
    match = _OPERATORS_RE.search(brief)
    if not match:
        return SourcedInt.unknown()
    raw = match.group(1).lower()
    count = int(raw) if raw.isdigit() else _WORD_NUMBERS.get(raw)
    if count is None:
        return SourcedInt.unknown()
    return SourcedInt.of(count, ValueSource.CUSTOMER, "Stated in the customer brief")


def _extract_floor(brief: str) -> tuple[SourcedFloat, SourcedFloat]:
    match = _FLOOR_RE.search(brief)
    if not match:
        return SourcedFloat.unknown(), SourcedFloat.unknown()
    first = float(match.group(1))
    second = float(match.group(2))
    detail = "Stated in the customer brief"
    # The larger figure is taken as the width (the direction a line runs);
    # the engineer can swap them in the builder. Stated rather than assumed
    # silently, because it is a presentation choice about the same two
    # numbers the customer gave.
    width, length = (first, second) if first >= second else (second, first)
    return (
        SourcedFloat.of(width, ValueSource.CUSTOMER, detail),
        SourcedFloat.of(length, ValueSource.CUSTOMER, detail),
    )


def _extract_schedule(brief: str) -> tuple[SourcedInt, SourcedFloat]:
    shifts: SourcedInt = SourcedInt.unknown()
    hours: SourcedFloat = SourcedFloat.unknown()

    match = _SHIFT_COUNT_RE.search(brief)
    if match:
        raw = match.group(1).lower()
        count = _WORD_NUMBERS.get(raw)
        if count is None and raw.isdigit():
            count = int(raw)
        if count is not None and count > 0:
            shifts = SourcedInt.of(count, ValueSource.CUSTOMER, "Stated in the customer brief")

    hours_match = _SHIFT_HOURS_RE.search(brief)
    if hours_match:
        value = float(hours_match.group(1))
        if 0 < value <= 24:
            hours = SourcedFloat.of(value, ValueSource.CUSTOMER, "Stated in the customer brief")

    return shifts, hours


def concept_from_brief(brief: str, *, name: str | None = None) -> FactoryConceptDraft:
    """Structure a customer brief into a factory concept draft."""
    shifts, hours = _extract_schedule(brief)
    floor_width, floor_length = _extract_floor(brief)

    return FactoryConceptDraft(
        name=name or "New factory concept",
        customer_brief=brief,
        production_target=_extract_target(brief),
        stages=extract_stages(brief),
        buffers=[],
        shifts_per_day=shifts,
        hours_per_shift=hours,
        operators_available=_extract_operators(brief),
        floor_width=floor_width,
        floor_length=floor_length,
        budget=SourcedFloat.unknown(),
        prefer_no_new_machines=bool(_NO_NEW_EQUIPMENT_RE.search(brief)),
    )


def buffers_between_stages(draft: FactoryConceptDraft, capacity: int = DEFAULT_BUFFER_CAPACITY) -> list[ConceptBuffer]:
    """One wired buffer between each pair of consecutive stages."""
    result: list[ConceptBuffer] = []
    for upstream, downstream in zip(draft.stages, draft.stages[1:]):
        result.append(
            ConceptBuffer(
                id=f"buf-{upstream.id}-{downstream.id}",
                name=f"{upstream.name} → {downstream.name}",
                upstream_stage_id=upstream.id,
                downstream_stage_id=downstream.id,
                capacity=SourcedInt.of(
                    capacity, ValueSource.CATALOG_DEFAULT, "Fabrivium planning default"
                ),
            )
        )
    return result


# Initial layout

def generate_initial_layout(draft: FactoryConceptDraft) -> FactoryLayout:
    """A planning-level layout: stations in route order, wrapped into rows."""
    floor_width = draft.floor_width.value
    floor_length = draft.floor_length.value

    widths = [
        stage.width.value if stage.width.value is not None else DEFAULT_STATION_WIDTH_M
        for stage in draft.stages
    ]
    lengths = [
        stage.length.value if stage.length.value is not None else DEFAULT_STATION_LENGTH_M
        for stage in draft.stages
    ]

    line_width = sum(widths) + STATION_GAP_M * max(0, len(widths) - 1)
    deepest = max(lengths) if lengths else DEFAULT_STATION_LENGTH_M

    if floor_width is None:
        floor_width = round(line_width + 2 * FLOOR_MARGIN_M, 3)
    if floor_length is None:
        floor_length = round(deepest + 2 * FLOOR_MARGIN_M, 3)

    # How many stations fit across before the row must wrap.
    usable_width = max(0.0, floor_width - 2 * FLOOR_MARGIN_M)
    widest = max(widths) if widths else DEFAULT_STATION_WIDTH_M
    per_row = max(1, int((usable_width + STATION_GAP_M) // (widest + STATION_GAP_M)))
    rows = -(-len(widths) // per_row) if widths else 1
    row_pitch = deepest + STATION_GAP_M

    # Centre the block horizontally; place it in the upper third so the
    # aisle sits behind it, which is how the bundled example line is
    # arranged. With several rows the block is pulled up far enough that the
    # last row still lands inside the building.
    row_width = min(line_width, per_row * widest + STATION_GAP_M * max(0, per_row - 1))
    start_x = max(FLOOR_MARGIN_M, (floor_width - row_width) / 2)

    block_depth = rows * deepest + STATION_GAP_M * max(0, rows - 1)
    line_y = min(
        floor_length / 3,
        max(FLOOR_MARGIN_M + deepest / 2, floor_length - block_depth - FLOOR_MARGIN_M),
    )

    placements: list[MachinePlacement] = []
    cursor = start_x
    row = 0
    in_row = 0
    for stage, width in zip(draft.stages, widths):
        if in_row == per_row:
            row += 1
            in_row = 0
            cursor = start_x

        placements.append(
            MachinePlacement(
                machine_id=stage.id,
                x=round(cursor + width / 2, 3),
                y=round(line_y + row * row_pitch, 3),
                z=0.0,
                rotation_deg=0.0,
            )
        )
        cursor += width + STATION_GAP_M
        in_row += 1

    zones: list[LayoutZone] = []
    aisle_y = line_y + (rows - 1) * row_pitch + deepest / 2 + 1.0
    aisle_length = 2.5
    if aisle_y + aisle_length <= floor_length:
        zones.append(
            LayoutZone(
                id="zone-main-aisle",
                name="Main Aisle",
                x=0.0,
                y=round(aisle_y, 3),
                width=floor_width,
                length=aisle_length,
                zone_type=LayoutZoneType.AISLE,
            )
        )

    return FactoryLayout(
        factory_width=floor_width,
        factory_length=floor_length,
        placements=placements,
        reserved_zones=[],
        aisle_zones=zones,
    )
