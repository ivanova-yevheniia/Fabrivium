"""A mechanical brief produces a mechanical process; a packaging brief does not."""

from __future__ import annotations

import pathlib

import pytest

from app.models.product import ProductUnderstanding
from app.services.input_adapters import ingest_text
from app.services.process_planning import plan_process
from app.services.product_extraction import extract_facts

CASES = pathlib.Path(__file__).resolve().parents[2] / "examples" / "generalization"
MECHANICAL = CASES / "scenario_m_ac6_compact_actuator.txt"
PACKAGING = CASES / "scenario_p_lf3_liquid_fill_line.txt"


def understanding_for(path: pathlib.Path, name: str) -> ProductUnderstanding:
    text = path.read_text(encoding="utf-8")
    facts = extract_facts([ingest_text(text, name=path.name).evidence[0]])
    return ProductUnderstanding(product_name=name, description="", facts=facts)


@pytest.fixture(scope="module")
def mechanical():
    return plan_process(understanding_for(MECHANICAL, "AC-6 Actuator"))


@pytest.fixture(scope="module")
def packaging():
    return plan_process(understanding_for(PACKAGING, "LF-3 Liquid"))


def names(draft) -> list[str]:
    return [op.name for op in draft.operations]


def families(draft) -> set[str]:
    return {op.process_type for op in draft.operations}


# No electronics reaches a product that has none


@pytest.mark.parametrize("case", ["mechanical", "packaging"])
def test_no_electronics_operation_is_proposed(case, request):
    draft = request.getfixturevalue(case)
    joined = " ".join(names(draft)).lower()
    for word in ("pcb", "circuit", "cable", "controller"):
        assert word not in joined, f"{case} route contains '{word}': {names(draft)}"


@pytest.mark.parametrize("case", ["mechanical", "packaging"])
def test_no_cec_cycle_time_or_target_is_carried_in(case, request):
    """A proposed operation carries no engineering value at all — those are
    resolved later, per station, with provenance."""
    draft = request.getfixturevalue(case)
    for op in draft.operations:
        assert not hasattr(op, "cycle_time") or getattr(op, "cycle_time", None) is None


# Each domain's own words drive its own route


def test_the_mechanical_product_gets_fastening_from_its_own_screws(mechanical):
    """The AC-6 states four screws; the route reflects that count and no
    other."""
    fastening = [op for op in mechanical.operations if op.process_type == "screwdriving"]
    assert fastening, names(mechanical)
    assert "×4" in fastening[0].name, fastening[0].name


def test_the_packaging_product_gets_no_fastening_operation(packaging):
    """It has no fasteners. A screwdriving station here would be invented."""
    assert "screwdriving" not in families(packaging), names(packaging)


def test_both_get_the_operations_their_documents_do_state(mechanical, packaging):
    for draft in (mechanical, packaging):
        assert "inspection" in families(draft), names(draft)
        assert "packaging" in families(draft), names(draft)
        assert "labelling" in families(draft), names(draft)


def test_the_two_routes_are_not_the_same_route(mechanical, packaging):
    assert names(mechanical) != names(packaging)


# The coverage limit, named rather than hidden


def test_the_mechanical_route_is_missing_the_operations_no_rule_covers(mechanical):
    """
    Pressing the bearing and greasing the seat are described by the document and have no
    rule.
    """
    joined = " ".join(names(mechanical)).lower()
    assert "press" not in joined
    assert "lubric" not in joined and "greas" not in joined


def test_the_packaging_route_is_missing_filling_and_sealing(packaging):
    """The two operations the LF-3 line is actually built around."""
    joined = " ".join(names(packaging)).lower()
    assert "fill" not in joined
    assert "seal" not in joined
