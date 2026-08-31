"""
Equipment knowledge — real records, the catalogues behind them, and the
ceiling on what may be claimed from them.

CANONICAL SOURCE
----------------
``app.services.equipment_catalog.default_registry()``. The registry is asked
the same question the discovery service asks it, through the same interface,
and the answers are described as knowledge items. Nothing is read out of the
JSON files directly: a record's provenance — which catalogue it came from,
and therefore how far it may be trusted — is stamped by the loader, and
bypassing the loader would be how a record promotes itself from an
approved-supplier list to researched manufacturer data.

THREE KINDS OF SOURCE, AND ONE THAT CANNOT ANSWER
-------------------------------------------------
Researched manufacturer data, the customer's own asset register and their
approved supplier list all run through one interface. A fourth, the live
external source, is registered and reports that it is not connected. That
response is published as knowledge too: "we could not consult this source"
is a result, and reporting it as an empty search would be the lie the
catalogue layer was built to avoid.

STANDARD REFERENCES ARE EXTRACTED, NOT AUTHORED
-----------------------------------------------
Where a candidate record cites a published standard, the identifier is
extracted from the record's own text by :data:`_STANDARD_PATTERN`. That way
Fabrivium reports exactly what the cited manufacturer document says and
cannot accumulate standard references nobody wrote down. Each one is
published at the weakest verification there is — MENTIONED_IN_SOURCE — and
carries no content. See ``app.knowledge.standards``.
"""

from __future__ import annotations

import re

from app.knowledge.contract import (
    Applicability,
    EngineeringKnowledgeItem,
    KnowledgeCategory,
    KnowledgeDomain,
    KnowledgeExposure,
    KnowledgeKind,
    Provenance,
    SourceKind,
)
from app.knowledge.standards import StandardReference, StandardVerification

EQUIPMENT_ADAPTER_VERSION = "1.0.0"

#: Designations of published standards, as a citing document writes them.
#: Deliberately narrow: a body name from a closed list, then a number. It
#: will miss an unusual citation, and missing one is the right failure —
#: the alternative is a knowledge base that invents standard references out
#: of ordinary prose.
_STANDARD_PATTERN = re.compile(
    r"\b(?:DIN\s+)?(?:ISO|IEC|EN|VDI|ANSI|ASME)\s+[0-9]{2,6}(?:-[0-9]+)?\b"
)

#: Which SourceKind a catalogue's records are. Read off CatalogKind rather
#: than off the file, for the reason in the module docstring.
_SOURCE_KIND_BY_CATALOG: dict[str, SourceKind] = {
    "RESEARCHED_MANUFACTURER": SourceKind.MANUFACTURER_DOCUMENT,
    "INTERNAL_ASSET_POOL": SourceKind.CUSTOMER_RECORD,
    "APPROVED_SUPPLIER": SourceKind.CUSTOMER_RECORD,
    "EXTERNAL_SOURCE": SourceKind.EXTERNAL_SERVICE,
}

#: An approved supplier list is a standing commercial decision an
#: organisation made — a policy reference rather than a bare fact about the
#: world. The other catalogues report what exists.
_KIND_BY_CATALOG: dict[str, KnowledgeKind] = {
    "APPROVED_SUPPLIER": KnowledgeKind.COMPANY_POLICY_REFERENCE,
}


def _candidate_standards(candidate) -> list[tuple[str, str]]:
    """(identifier, the sentence it was cited in) for each standard cited.

    Deduplicated on the identifier, keeping the first citation, so a
    datasheet naming the same standard in a description and again in a
    caveat produces one reference rather than two.
    """
    found: dict[str, str] = {}
    fragments = [candidate.description, *candidate.caveats]
    for fragment in fragments:
        for match in _STANDARD_PATTERN.finditer(fragment or ""):
            found.setdefault(match.group(0), fragment.strip())
    return list(found.items())


def equipment_knowledge() -> list[EngineeringKnowledgeItem]:
    """Equipment evidence, catalogue provenance and the claim ceiling."""
    from app.models.equipment_discovery import EquipmentCapability, MatchClaim
    from app.services.equipment_catalog import default_registry
    from app.services.equipment_discovery import (
        CAPABILITY_BY_PROCESS_TYPE,
        CAPABILITY_STATEMENTS,
    )

    registry = default_registry()
    items: list[EngineeringKnowledgeItem] = []

    #: Which station process types need each capability, inverted from the
    #: canonical table so an equipment record's applicability is stated in
    #: the same vocabulary a concept stage uses.
    process_types_for: dict[str, tuple[str, ...]] = {}
    for process_type, capability in CAPABILITY_BY_PROCESS_TYPE.items():
        process_types_for.setdefault(capability.value, ())
        process_types_for[capability.value] += (process_type,)

    # --- one item per catalogue, including the one that cannot answer ----
    #
    # A catalogue is asked once per capability, so it answers several times.
    # Its verification date is the OLDEST of those answers, not the first or
    # the newest — the same rule CatalogSearchResult.verified_on applies, and
    # for the same reason: a catalogue is only as fresh as its least recently
    # checked file, and reporting the newest date would overstate it.
    responses_by_catalog: dict[str, list] = {}
    candidates: dict[str, object] = {}

    for capability in EquipmentCapability:
        result = registry.search(capability)
        for response in result.responses:
            responses_by_catalog.setdefault(response.descriptor.catalog_id, []).append(
                response
            )
        for candidate in result.candidates:
            candidates.setdefault(candidate.candidate_id, candidate)

    for descriptor in registry.descriptors:
        responses = responses_by_catalog.get(descriptor.catalog_id, [])
        available = all(r.available for r in responses) if responses else False
        reason = next((r.unavailable_reason for r in responses if not r.available), "")
        dates = [r.verified_on for r in responses if r.verified_on is not None]
        verified_on = min(dates) if dates else None

        items.append(
            EngineeringKnowledgeItem(
                id=f"equipment.catalog.{descriptor.catalog_id}",
                version=EQUIPMENT_ADAPTER_VERSION,
                kind=_KIND_BY_CATALOG.get(descriptor.kind.value, KnowledgeKind.FACT),
                category=KnowledgeCategory.EQUIPMENT,
                domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
                title=f"Equipment source — {descriptor.display_name}",
                description=(
                    descriptor.trust_statement
                    if available
                    else f"{descriptor.trust_statement} {reason}".strip()
                ),
                provenance=Provenance(
                    source_kind=_SOURCE_KIND_BY_CATALOG[descriptor.kind.value],
                    source_reference=(
                        f"app.services.equipment_catalog.default_registry()"
                        f"['{descriptor.catalog_id}']"
                    ),
                    statement=descriptor.trust_statement or descriptor.display_name,
                    classification_vocabulary="CatalogKind",
                    classification=descriptor.kind.value,
                    verified_on=verified_on,
                ),
                applicability=Applicability(
                    scope=(
                        "Consulted for every station whose process type maps to a "
                        "researched capability."
                        if available
                        else "Registered but not consulted in this build."
                    ),
                    not_valid_for=(
                        ""
                        if available
                        else (
                            "Concluding that nothing suitable exists. This source could not "
                            "be consulted, which is different from having found nothing."
                        )
                    ),
                ),
                exposure=KnowledgeExposure.DERIVED_VALUE,
                values={
                    "catalog_id": descriptor.catalog_id,
                    "catalog_kind": descriptor.kind.value,
                    "display_name": descriptor.display_name,
                    "available": available,
                    "unavailable_reason": reason,
                    "records": sum(
                        1
                        for c in candidates.values()
                        if c.catalog_id == descriptor.catalog_id
                    ),
                },
                status="AVAILABLE" if available else "NOT_CONNECTED",
                tags=("equipment", "catalog", "provenance"),
            )
        )

    # --- one item per real equipment record ------------------------------
    for candidate_id, candidate in sorted(candidates.items()):
        primary = candidate.primary_source
        completeness = candidate.completeness

        items.append(
            EngineeringKnowledgeItem(
                id=f"equipment.candidate.{candidate_id}",
                version=EQUIPMENT_ADAPTER_VERSION,
                kind=KnowledgeKind.EQUIPMENT_EVIDENCE,
                category=KnowledgeCategory.EQUIPMENT,
                domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
                title=f"{candidate.manufacturer} {candidate.model}",
                description=(
                    f"{candidate.category} — {candidate.product_scope}. "
                    f"{completeness.published} of {completeness.considered} comparable "
                    f"values are published; the rest are absent rather than filled in. "
                    f"A value the manufacturer does not publish is UNKNOWN, and an unknown "
                    f"never counts as a pass."
                ),
                provenance=Provenance(
                    source_kind=_SOURCE_KIND_BY_CATALOG[candidate.catalog_kind.value],
                    source_reference=(
                        primary.url if primary is not None else candidate.catalog_id
                    ),
                    statement=(
                        f"Read from '{primary.title}' on {primary.retrieved_at.isoformat()}."
                        if primary is not None
                        else "No document is cited for this record."
                    ),
                    classification_vocabulary="CatalogKind",
                    classification=candidate.catalog_kind.value,
                    verified_on=primary.retrieved_at if primary is not None else None,
                ),
                applicability=Applicability(
                    scope=(
                        "A station requiring one of the capabilities this record declares."
                    ),
                    process_categories=tuple(
                        sorted(
                            {
                                process_type
                                for c in candidate.provides
                                for process_type in process_types_for.get(c.value, ())
                            }
                        )
                    ),
                    not_valid_for=(
                        " ".join(candidate.caveats)
                        or "No caveat is recorded against this equipment."
                    ),
                ),
                exposure=KnowledgeExposure.DERIVED_VALUE,
                values={
                    "candidate_id": candidate_id,
                    "manufacturer": candidate.manufacturer,
                    "model": candidate.model,
                    "provides": [c.value for c in candidate.provides],
                    "catalog_id": candidate.catalog_id,
                    "price_status": candidate.price_status.value,
                    "published_specs": completeness.published,
                    "considered_specs": completeness.considered,
                    "source_backed": candidate.source_backed,
                    "sources": [s.url for s in candidate.sources],
                },
                status=candidate.price_status.value,
                tags=("equipment", "evidence", candidate.catalog_kind.value.lower()),
            )
        )

        # --- standards the record itself cites ---------------------------
        for identifier, sentence in _candidate_standards(candidate):
            slug = identifier.lower().replace(" ", "-")
            items.append(
                EngineeringKnowledgeItem(
                    id=f"standard.{slug}.cited_by.{candidate_id}",
                    version=EQUIPMENT_ADAPTER_VERSION,
                    kind=KnowledgeKind.STANDARD_REFERENCE,
                    category=KnowledgeCategory.EQUIPMENT,
                    domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
                    title=f"{identifier} referenced by {candidate.manufacturer} {candidate.model}",
                    description=(
                        f"The cited manufacturer document references {identifier}. Fabrivium "
                        f"holds no content of this standard, has not obtained it, and makes "
                        f"no assessment of compliance with it. What is recorded is that the "
                        f"document names it."
                    ),
                    provenance=Provenance(
                        source_kind=SourceKind.EXTERNAL_STANDARD,
                        source_reference=(
                            primary.url if primary is not None else candidate.catalog_id
                        ),
                        statement=(
                            f"Extracted from the record for {candidate.manufacturer} "
                            f"{candidate.model} in the bundled equipment catalogue."
                        ),
                        classification_vocabulary="CatalogKind",
                        classification=candidate.catalog_kind.value,
                        verified_on=primary.retrieved_at if primary is not None else None,
                    ),
                    applicability=Applicability(
                        scope=(
                            f"Relevant only to the equipment that cites it: "
                            f"{candidate.manufacturer} {candidate.model}."
                        ),
                        not_valid_for=(
                            "Any statement that this project, this concept or this design "
                            "complies with the standard."
                        ),
                    ),
                    exposure=KnowledgeExposure.POINTER,
                    standard=StandardReference(
                        identifier=identifier,
                        cited_by=f"{candidate.manufacturer} {candidate.model} ({candidate_id})",
                        verification=StandardVerification.MENTIONED_IN_SOURCE,
                        scope_note=sentence,
                    ),
                    tags=("equipment", "standard-reference"),
                )
            )

    # --- what a station of a given process type actually needs -----------
    for capability in EquipmentCapability:
        items.append(
            EngineeringKnowledgeItem(
                id=f"equipment.capability.{capability.value.lower()}",
                version=EQUIPMENT_ADAPTER_VERSION,
                kind=KnowledgeKind.RULE,
                category=KnowledgeCategory.EQUIPMENT,
                domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
                title=f"Capability required by a station — {capability.value}",
                description=(
                    f"{CAPABILITY_STATEMENTS[capability]} A candidate reaches a station's "
                    f"shortlist because its catalogue record DECLARES this capability — "
                    f"never because its model name contains the operation's name. A process "
                    f"type absent from the mapping means Fabrivium has not researched "
                    f"equipment for that kind of station, which must never be reported as "
                    f"'nothing suitable exists'."
                ),
                provenance=Provenance(
                    source_kind=SourceKind.IMPLEMENTED_RULE,
                    source_reference=(
                        "app.services.equipment_discovery.CAPABILITY_BY_PROCESS_TYPE"
                    ),
                    statement=(
                        "The declared mapping between a station's process type and the "
                        "capability its equipment must provide."
                    ),
                ),
                applicability=Applicability(
                    scope="Stations whose process type appears in the mapping.",
                    process_categories=process_types_for.get(capability.value, ()),
                    not_valid_for=(
                        "Process types not listed. Those have no researched capability and "
                        "no catalogue is consulted for them."
                    ),
                ),
                exposure=KnowledgeExposure.DERIVED_VALUE,
                values={
                    "capability": capability.value,
                    "requirement_statement": CAPABILITY_STATEMENTS[capability],
                    "process_types": list(process_types_for.get(capability.value, ())),
                },
                tags=("equipment", "capability", "declared-not-inferred"),
            )
        )

    # --- the ceiling on what a match may claim ---------------------------
    items.append(
        EngineeringKnowledgeItem(
            id="equipment.match_claim_ceiling",
            version=EQUIPMENT_ADAPTER_VERSION,
            kind=KnowledgeKind.RULE,
            category=KnowledgeCategory.EQUIPMENT,
            domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
            title="The strongest claim a requirement match may make is POTENTIALLY_SUITABLE",
            description=(
                "Fabrivium checks the bounds a CONCEPT establishes: cycle, envelope, "
                "capacity, operators, budget, declared interfaces, declared capability. A "
                "concept does not establish the joint, the mounting, the control "
                "integration, the safety concept, the air supply or the operator's reach, "
                "so nothing computed can know that a machine fits. There is deliberately no "
                "COMPATIBLE, VALIDATED or GUARANTEED verdict to reach for, and no single "
                "score — averaging seconds against millimetres against euros would hide "
                "which of them is unknown."
            ),
            provenance=Provenance(
                source_kind=SourceKind.IMPLEMENTED_RULE,
                source_reference="app.services.equipment_compatibility",
                statement=(
                    "The verdict ceiling implemented in Fabrivium's deterministic "
                    "requirement matcher. No model is consulted; every verdict is "
                    "arithmetic an engineer can redo by hand from the two records."
                ),
            ),
            applicability=Applicability(
                scope="Every comparison of a station requirement against an equipment record.",
                not_valid_for=(
                    "Concluding that a machine is suitable. That is an engineering "
                    "decision made with the supplier."
                ),
            ),
            exposure=KnowledgeExposure.DERIVED_VALUE,
            values={"claims": [c.value for c in MatchClaim]},
            tags=("equipment", "claim-ceiling", "fail-closed"),
        )
    )

    items.append(
        EngineeringKnowledgeItem(
            id="equipment.unknown_is_never_a_pass",
            version=EQUIPMENT_ADAPTER_VERSION,
            kind=KnowledgeKind.RULE,
            category=KnowledgeCategory.EQUIPMENT,
            domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
            title="An unpublished specification is UNKNOWN, and UNKNOWN never counts as a pass",
            description=(
                "A manufacturer who does not publish a cycle time has not told Fabrivium "
                "the equipment is fast enough; they have told it nothing. Treating that as "
                "a pass is how a procurement shortlist ends up holding a machine that "
                "cannot meet the line's takt. A missing price likewise stays missing — it "
                "never becomes zero. The one legitimate zero price is equipment the "
                "customer already owns, recorded against their asset register with a caveat "
                "naming what the zero excludes."
            ),
            provenance=Provenance(
                source_kind=SourceKind.IMPLEMENTED_RULE,
                source_reference="app.services.equipment_compatibility",
                statement="The matching rule implemented in Fabrivium's compatibility check.",
                classification_vocabulary="EvidenceLevel",
                classification="UNKNOWN",
            ),
            applicability=Applicability(
                scope="Every published specification read from any catalogue.",
            ),
            exposure=KnowledgeExposure.POINTER,
            tags=("equipment", "fail-closed", "provenance"),
        )
    )

    return items
