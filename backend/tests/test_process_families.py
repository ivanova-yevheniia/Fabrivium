"""The process-family vocabulary is one list, published, with honest coverage."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.data.engineering_reference_data import PROCESS_PROFILES, covered_categories
from app.main import app
from app.services.concept_builder import _STAGE_VOCABULARY
from app.services.process_families import (
    known_process_types,
    process_family_catalog,
    unknown_process_type_note,
)

client = TestClient(app)


def test_the_catalog_is_the_vocabulary_and_nothing_else():
    """No family may be added or dropped on the way to the API."""
    catalog = process_family_catalog()
    assert [f.process_type for f in catalog.families] == [pt for _, pt, _ in _STAGE_VOCABULARY]


def test_order_follows_the_vocabulary_so_the_ui_shows_the_parsers_precedence():
    catalog = process_family_catalog()
    assert [f.label for f in catalog.families][:4] == [
        "Assembly", "Screwdriving", "Inspection", "Packaging",
    ]


def test_every_family_the_two_hardcoded_ui_lists_omitted_is_present():
    """The seven that a non-electronics project actually needs."""
    published = {f.process_type for f in process_family_catalog().families}
    assert {
        "welding", "soldering", "painting", "machining", "cleaning", "curing", "palletizing",
    } <= published


def test_labelling_has_exactly_one_spelling():
    """`labeling` was one screen's spelling; the reference bands key on
    `labelling`, so the other spelling matched no band at all."""
    published = {f.process_type for f in process_family_catalog().families}
    assert "labelling" in published
    assert "labeling" not in published


def test_testing_is_not_a_family():
    """It is an alias of inspection."""
    assert "testing" not in known_process_types()
    note = unknown_process_type_note("testing")
    assert note is not None
    assert "reference cycle-time band" in note
    # The note must not read as "unsupported": the operation simulates fine.
    assert "still simulates" in note


def test_a_known_family_produces_no_note():
    assert unknown_process_type_note("welding") is None
    assert unknown_process_type_note("WELDING") is None


def test_coverage_is_reported_per_family_and_is_not_uniform():
    """Seven of twelve have no reference band."""
    catalog = process_family_catalog()
    with_estimate = [f.process_type for f in catalog.families if f.has_reference_estimate]
    assert sorted(with_estimate) == sorted(covered_categories())
    assert catalog.families_with_reference_estimate == len(with_estimate)
    assert catalog.families_with_reference_estimate < len(catalog.families)


def test_a_family_with_a_band_names_what_one_operation_means():
    catalog = process_family_catalog()
    for family in catalog.families:
        if family.has_reference_estimate:
            assert family.operation_noun, f"{family.process_type} has a band but no operation noun"
        else:
            assert family.operation_noun is None


def test_no_reference_profile_is_keyed_to_a_family_no_stage_can_carry():
    """An unreachable band is a band that silently never applies."""
    assert set(PROCESS_PROFILES) <= known_process_types()


def test_equipment_evidence_is_reported_and_is_narrower_than_estimation():
    catalog = process_family_catalog()
    assert 0 < catalog.families_with_equipment_evidence <= catalog.families_with_reference_estimate


@pytest.mark.parametrize("field", ["families", "families_with_reference_estimate",
                                   "families_with_equipment_evidence", "reference_dataset_name"])
def test_endpoint_serves_the_whole_contract(field):
    response = client.get("/process/families")
    assert response.status_code == 200
    assert field in response.json()


def test_endpoint_matches_the_service():
    body = client.get("/process/families").json()
    assert body == process_family_catalog().model_dump()


def test_the_estimate_dataset_is_named_so_a_screen_can_attribute_it():
    """An offered estimate should be able to say what it is anchored to."""
    assert process_family_catalog().reference_dataset_name.strip()
