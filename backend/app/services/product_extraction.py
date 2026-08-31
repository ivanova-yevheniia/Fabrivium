"""Deterministic product-fact extraction — Phase 19."""

from __future__ import annotations

import re

from app.models.product import (
    EvidenceRef,
    FactStatus,
    InformationGap,
    ProductFact,
    SourceProductionRequirement,
)
from app.services.input_adapters import NormalizedEvidence

_NUMERALS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "twelve": 12,
}

#: Nouns whose count matters downstream, with the fact key they produce and
#: the operation family they imply.
_COUNTABLE = (
    ("fastener.screw.count", "Screws", ("screw", "screws")),
    ("fastener.bolt.count", "Bolts", ("bolt", "bolts")),
    ("connection.cable.count", "Cable connections", ("cable", "cables", "connector", "connectors")),
)

#: Fastener nouns, used to decide WHICH fastener a thread, drive or torque
#: found in the same sentence belongs to. A designation with no fastener
#: named beside it is not recorded at all — "M3" on its own is as likely to
#: be a model number as a thread.
_FASTENER_FAMILIES = (
    ("fastener.screw", "Screw", ("screw", "screws")),
    ("fastener.bolt", "Bolt", ("bolt", "bolts")),
)

# ISO metric thread designations — "M3", "M2.5", "M12".
_THREAD_RE = re.compile(r"\bM(\d{1,2}(?:[.,]\d)?)\b")

# Drive types a screwdriving station is actually selected against.
_SCREW_DRIVES = (
    ("hexalobular", "Hexalobular"), ("hex socket", "Hex socket"),
    ("torx", "Torx"), ("pozidriv", "Pozidriv"), ("phillips", "Phillips"),
    ("square drive", "Square drive"), ("slotted", "Slotted"),
    ("internal hex", "Internal hex"), ("allen", "Internal hex"),
)

# A fastening torque, with its unit.
_TORQUE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:n\s?m|newton[\s-]?met(?:er|re)s?)\b", re.IGNORECASE)

# Materials worth recording, because Phase 16 compares against them.
_MATERIALS = (
    ("stainless", "Stainless steel"), ("polycarbonate", "Polycarbonate"),
    ("pc/abs", "PC/ABS"), ("abs", "ABS"),
    ("aluminium", "Aluminium"), ("aluminum", "Aluminium"), ("steel", "Steel"),
    ("plastic", "Plastic"), ("metal", "Metal"),
)

# Material families.
_MATERIAL_FAMILIES: dict[str, str] = {
    "ABS": "Plastic",
    "Polycarbonate": "Plastic",
    "PC/ABS": "Plastic",
    "Aluminium": "Metal",
    "Steel": "Metal",
    "Stainless steel": "Metal",
}


def _supersedes(specific: str | None, general: str | None) -> bool:
    """Whether `specific` is a more precise reading of `general`."""
    if specific is None or general is None:
        return False
    return _MATERIAL_FAMILIES.get(specific) == general

# Components whose presence implies a placement or handling operation.
_COMPONENTS = (
    ("component.pcb", "PCB", ("pcb", "printed circuit board", "circuit board")),
    ("component.enclosure", "Enclosure", ("enclosure", "housing", "casing")),
    ("component.lid", "Lid or cover", ("lid", "cover")),
    # The inflections are listed rather than reached by substring, the same way
    # `_INSPECTION_STEMS` lists "inspect" and "inspection" separately.
    ("component.label", "Label", ("label", "nameplate", "labelled", "labeled", "labelling", "labeling")),
)

# Matched as WHOLE TOKENS with a prefix allowance, never as substrings.
_INSPECTION_STEMS = ("inspect", "inspection", "verify", "verified")
_INSPECTION_PHRASES = ("visual check", "quality check", "visual inspection")
_PACKAGING_STEMS = ("packaging", "packed", "packing", "carton", "box", "bag", "leaflet")

_DIMENSION_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:x|×|by)\s*(\d+(?:[.,]\d+)?)\s*(?:(?:x|×|by)\s*(\d+(?:[.,]\d+)?)\s*)?(mm|cm|m)\b",
    re.IGNORECASE,
)

# A newline ends a sentence here, deliberately.
_SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]?")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.findall(text) if s.strip()]


def _tokens(sentence: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", sentence.lower())


# Words that reverse the claim a sentence makes about a term near them.
_NEGATIONS = frozenset({"no", "not", "never", "without", "excluding", "exclude", "neither", "nor"})

# How far a negation reaches.
_NEGATION_WINDOW = 4


def _negated(tokens: list[str], index: int) -> bool:
    """Whether the term at `index` sits inside a negation."""
    for step in range(1, _NEGATION_WINDOW + 1):
        position = index - step
        if position < 0:
            return False
        token = tokens[position]
        if token in _NEGATIONS:
            return True
        # A conjunction ends the reach of an earlier negation.
        if token in ("and", "but", "however", "although"):
            return False
    return False


def _first_index(tokens: list[str], marker: str) -> int | None:
    """Where a marker's first token appears, or None."""
    head = marker.split()[0]
    for index, token in enumerate(tokens):
        if token == head or token.startswith(head):
            return index
    return None


def _same_word(token: str, wanted: str) -> bool:
    """One token against one marker word, allowing only a plural."""
    return token == wanted or token == f"{wanted}s" or token == f"{wanted}es"


def _marker_position(tokens: list[str], marker: str) -> int | None:
    """Where *marker* occurs as WHOLE TOKENS, or ``None``."""
    wanted = _tokens(marker)
    if not wanted:
        return None
    last = len(tokens) - len(wanted)
    for start in range(last + 1):
        if all(_same_word(tokens[start + offset], word) for offset, word in enumerate(wanted)):
            return start
    return None


def _count_near(tokens: list[str], index: int) -> int | None:
    """A quantity stated immediately before the noun, or None."""
    for step in (1, 2):
        position = index - step
        if position < 0:
            return None
        token = tokens[position]
        if token.isdigit():
            return int(token)
        if token in _NUMERALS:
            return _NUMERALS[token]
    return None


def extract_facts(evidence: list[NormalizedEvidence]) -> list[ProductFact]:
    """Every product fact the supplied text states, with its evidence."""
    found: dict[str, list[ProductFact]] = {}

    for item in evidence:
        for sentence in _sentences(item.text):
            for fact in _facts_in_sentence(sentence, item):
                found.setdefault(fact.key, []).append(fact)

    return [_merge(key, candidates) for key, candidates in sorted(found.items())]


def production_requirements_in(
    evidence: list[NormalizedEvidence],
) -> list[SourceProductionRequirement]:
    """What the SOURCE DOCUMENT states about production, with its evidence."""
    from app.services.concept_builder import PRODUCTION_KEYS, production_values_in

    labels = dict(PRODUCTION_KEYS)
    found: dict[str, SourceProductionRequirement] = {}

    for item in evidence:
        for sentence in _sentences(item.text):
            for key, (display, quantity, secondary) in production_values_in(sentence).items():
                if key in found:
                    continue
                found[key] = SourceProductionRequirement(
                    key=key,
                    label=labels.get(key, key),
                    value=display,
                    quantity=quantity,
                    quantity_secondary=secondary,
                    evidence=_ref(item, sentence),
                )

    return [found[key] for key, _ in PRODUCTION_KEYS if key in found]


def _ref(item: NormalizedEvidence, sentence: str) -> EvidenceRef:
    return EvidenceRef(
        document_id=item.document_id,
        document_name=item.document_name,
        page=item.page,
        quote=sentence[:180],
    )


# Leading glyphs a PDF text layer carries into a bullet line.
_BULLET_CHARS = "•·▪●*-–— \t"

# A span carrying one of these states a requirement rather than naming a thing.
_REQUIREMENT_MODALS = frozenset({"shall", "must", "should", "will"})

# A finite verb makes a span a clause rather than a caption.
_STATEMENT_VERBS = frozenset({
    "is", "are", "was", "were", "has", "have", "consists", "contains",
    "provided", "provides", "placed", "applied", "secured", "installed",
    "connected", "mounted", "closed", "fitted", "undergo", "undergoes",
    "requires", "required", "supplied", "marked", "attached", "affixed",
})


def _quote_quality(quote: str | None) -> int:
    """How well a span supports the fact it was taken from."""
    if not quote:
        return 0
    text = quote.strip().strip(_BULLET_CHARS).strip()
    tokens = set(_tokens(text))
    words = text.split()

    score = 0
    if tokens & _REQUIREMENT_MODALS:
        score += 4
    if tokens & _STATEMENT_VERBS:
        score += 2
    if len(words) >= 8:
        score += 3
    elif len(words) >= 5:
        score += 2
    elif len(words) >= 3:
        score += 1
    else:
        # One or two words is a heading, a column label or a BOM cell.
        score -= 2
    if text.endswith((".", "!", "?")):
        score += 1
    return score


def _ranked_evidence(candidates: list[ProductFact], limit: int = 4) -> list[EvidenceRef]:
    """The strongest distinct citations for a merged fact, best first."""
    seen: set[tuple[int | None, str]] = set()
    distinct: list[EvidenceRef] = []
    for candidate in candidates:
        for ref in candidate.evidence:
            key = (ref.page, (ref.quote or "").strip())
            if key in seen:
                continue
            seen.add(key)
            distinct.append(ref)
    return sorted(distinct, key=lambda ref: -_quote_quality(ref.quote))[:limit]


def _facts_in_sentence(sentence: str, item: NormalizedEvidence) -> list[ProductFact]:
    tokens = _tokens(sentence)
    lowered = sentence.lower()
    ref = _ref(item, sentence)
    facts: list[ProductFact] = []

    # Counted things A NAMED THING WITH NO STATED COUNT IS STILL A STATED THING.
    for key, label, nouns in _COUNTABLE:
        positions = [index for index, token in enumerate(tokens) if token in nouns]
        if not positions:
            continue

        count = next(
            (found for found in (_count_near(tokens, index) for index in positions) if found is not None),
            None,
        )
        if count is None:
            # Only the PRESENCE reading consults the negation window.
            if all(_negated(tokens, index) for index in positions):
                continue
            facts.append(
                ProductFact(
                    key=key, category="quantity", label=label,
                    value="present", quantity=None, unit=None,
                    # EXTRACTED, not UNKNOWN: the source really does state
                    # that these are there. What it does not state is how
                    # many, and `gaps_for` declares exactly that.
                    status=FactStatus.EXTRACTED, confidence="MEDIUM", evidence=[ref],
                )
            )
        else:
            facts.append(
                ProductFact(
                    key=key, category="quantity", label=label,
                    value=str(count), quantity=float(count), unit="units",
                    status=FactStatus.EXTRACTED, confidence="HIGH", evidence=[ref],
                )
            )

    # Fastener specification THREAD, DRIVE AND TORQUE ARE THREE SEPARATE QUESTIONS.
    for prefix, family, nouns in _FASTENER_FAMILIES:
        positions = [index for index, token in enumerate(tokens) if token in nouns]
        if not positions:
            continue
        if all(_negated(tokens, index) for index in positions):
            continue

        thread = _THREAD_RE.search(sentence)
        if thread:
            facts.append(
                ProductFact(
                    key=f"{prefix}.thread", category="fastener",
                    label=f"{family} thread", value=f"M{thread.group(1).replace(',', '.')}",
                    status=FactStatus.EXTRACTED, confidence="HIGH", evidence=[ref],
                )
            )

        drive = next(
            (name for marker, name in _SCREW_DRIVES if _marker_position(tokens, marker) is not None),
            None,
        )
        if drive:
            facts.append(
                ProductFact(
                    key=f"{prefix}.drive", category="fastener",
                    label=f"{family} drive type", value=drive,
                    status=FactStatus.EXTRACTED, confidence="HIGH", evidence=[ref],
                )
            )

        torque = _TORQUE_RE.search(sentence)
        if torque:
            value = float(torque.group(1).replace(",", "."))
            facts.append(
                ProductFact(
                    key=f"{prefix}.torque", category="fastener",
                    label=f"{family} fastening torque", value=f"{value:g} Nm",
                    quantity=value, unit="Nm",
                    status=FactStatus.EXTRACTED, confidence="HIGH", evidence=[ref],
                )
            )

    # Components
    for key, label, markers in _COMPONENTS:
        position = next(
            (p for p in (_marker_position(tokens, m) for m in markers) if p is not None),
            None,
        )
        if position is None:
            continue
        if _negated(tokens, position):
            continue
        facts.append(
            ProductFact(
                key=key, category="component", label=label, value="present",
                status=FactStatus.EXTRACTED, confidence="HIGH", evidence=[ref],
            )
        )

    # Material
    for marker, name in _MATERIALS:
        position = _marker_position(tokens, marker)
        if position is None:
            continue
        if _negated(tokens, position):
            # The sentence says this material is NOT used.
            continue
        facts.append(
            ProductFact(
                key="material.enclosure", category="material", label="Enclosure material",
                value=name, status=FactStatus.EXTRACTED, confidence="MEDIUM", evidence=[ref],
            )
        )
        break

    # Dimensions
    match = _DIMENSION_RE.search(sentence)
    if match:
        parts = [p for p in match.groups()[:3] if p]
        unit = match.group(4)
        facts.append(
            ProductFact(
                key="dimensions.overall", category="geometry", label="Overall dimensions",
                value=" × ".join(p.replace(",", ".") for p in parts) + f" {unit}",
                status=FactStatus.EXTRACTED, confidence="HIGH", evidence=[ref],
            )
        )

    # Required downstream operations
    token_set = set(tokens)
    for key, label, stems, phrases in (
        ("requirement.inspection", "Inspection required", _INSPECTION_STEMS, _INSPECTION_PHRASES),
        ("requirement.packaging", "Packaging required", _PACKAGING_STEMS, ()),
    ):
        matched = any(t in token_set for t in stems) or any(p in lowered for p in phrases)
        if matched:
            facts.append(
                ProductFact(
                    key=key, category="requirement", label=label, value="stated",
                    status=FactStatus.EXTRACTED, confidence="MEDIUM", evidence=[ref],
                )
            )

    return facts


def _merge(key: str, candidates: list[ProductFact]) -> ProductFact:
    """One fact per key — or a CONFLICT when the readings disagree."""
    distinct = {c.value for c in candidates}
    first = candidates[0]
    evidence = _ranked_evidence(candidates)

    if len(distinct) == 1:
        return first.model_copy(update={"evidence": evidence})

    # A sentence that names something without counting it does not disagree
    # with one that counts it — it is the same reading, less precise. The
    # counted one wins and keeps every citation. Two DIFFERENT counts still
    # conflict, which is the case this must not swallow.
    counted = [c for c in candidates if c.quantity is not None]
    if counted and len({c.value for c in counted}) == 1:
        return counted[0].model_copy(update={"evidence": evidence})

    # A more specific reading is not a disagreement.
    if len(distinct) == 2:
        a, b = sorted(distinct, key=lambda v: v or "")
        if _supersedes(a, b) or _supersedes(b, a):
            precise = a if _supersedes(a, b) else b
            winner = next(c for c in candidates if c.value == precise)
            return winner.model_copy(update={"evidence": evidence})

    # Two sources, two answers.
    return ProductFact(
        key=key, category=first.category, label=first.label,
        value=None, quantity=None, unit=first.unit,
        status=FactStatus.CONFLICT, confidence=None, evidence=evidence,
        alternatives=[
            c.model_copy(update={"alternatives": []})
            for c in {c.value: c for c in candidates}.values()
        ],
    )


def _join(names: list[str]) -> str:
    """"a", "a and b", "a, b and c" — so a gap reads as a sentence."""
    if len(names) <= 1:
        return names[0] if names else ""
    return f"{', '.join(names[:-1])} and {names[-1]}"


def gaps_for(facts: list[ProductFact]) -> list[InformationGap]:
    """What is still missing, classified by the consumer that needs it."""
    known = {f.key for f in facts if f.known}
    gaps: list[InformationGap] = []

    # THE GAP NAMES WHAT IS MISSING, NOT A CATEGORY IT BELONGS TO.
    screw_missing = [
        name
        for key, name in (
            ("fastener.screw.thread", "thread size"),
            ("fastener.screw.drive", "drive type"),
            ("fastener.screw.torque", "fastening torque"),
        )
        if key not in known
    ]
    if "fastener.screw.count" in known and screw_missing:
        stated = [
            name
            for key, name in (
                ("fastener.screw.thread", "thread size"),
                ("fastener.screw.drive", "drive type"),
                ("fastener.screw.torque", "fastening torque"),
            )
            if key in known
        ]
        reason = (
            f"A screwdriving station is validated against {_join(screw_missing)}. "
            f"The source does not state {'it' if len(screw_missing) == 1 else 'them'}"
        )
        reason += f", although it does state the {_join(stated)}." if stated else "."
        gaps.append(
            InformationGap(
                key="fastener.screw.drive_torque",
                label=f"Screw {_join(screw_missing)}",
                severity="LIMITS_EQUIPMENT_VALIDATION",
                reason=reason,
            )
        )
    for fact in facts:
        # The source names it but never says how many.
        if fact.category == "quantity" and fact.known and fact.quantity is None:
            gaps.append(
                InformationGap(
                    key=fact.key,
                    label=f"{fact.label} — count not stated",
                    severity="BLOCKS_DETAILED_ENGINEERING",
                    reason=(
                        "The source names this but does not say how many. The operation is "
                        "proposed; its repeat count has to be entered before a cycle time can "
                        "be estimated from it."
                    ),
                )
            )

    if "dimensions.overall" not in known:
        gaps.append(
            InformationGap(
                key="dimensions.overall", label="Overall product dimensions",
                severity="BLOCKS_DETAILED_ENGINEERING",
                reason="Fixture and handling design need the part envelope. Concept simulation does not.",
            )
        )
    if "material.enclosure" not in known:
        gaps.append(
            InformationGap(
                key="material.enclosure", label="Enclosure material",
                severity="BLOCKS_EQUIPMENT_SELECTION",
                reason="Material determines which fastening and handling equipment is suitable.",
            )
        )
    for fact in facts:
        if fact.status is FactStatus.CONFLICT:
            gaps.append(
                InformationGap(
                    key=fact.key, label=f"{fact.label} — sources disagree",
                    severity="BLOCKS_EQUIPMENT_SELECTION",
                    reason="Two sources give different values; the engineer must choose before equipment is selected.",
                )
            )

    # One gap per key.
    deduped: dict[str, InformationGap] = {}
    for gap in gaps:
        deduped[gap.key] = gap
    return list(deduped.values())
