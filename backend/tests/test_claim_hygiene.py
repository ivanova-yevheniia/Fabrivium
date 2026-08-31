"""Claim hygiene — what the backend is allowed to SAY."""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from app.models.agent import PlanningRequirements
from app.models.factory import Factory
from app.models.optimization import OptimizationObjective
from app.models.process_draft import ManufacturingProcessDraft, ProposedOperation
from app.models.product import EvidenceRef, FactStatus, ProductFact, ProductUnderstanding
from app.models.strategy import CostCategory, InformationGapType, UserCostInput
from app.services.requirement_coverage import CoverageStatus, coverage_for
from app.services.strategy_arena import StrategyArena
from app.services.strategy_comparison import compare_strategies
from app.services.strategy_cost import build_cost_profile
from app.services.strategy_language import (
    UnmappedInternalTerm,
    action_phrase,
    category_phrase,
    category_title,
    gap_phrase,
    gap_phrases_for,
    gap_title,
    join_phrases,
)
from app.services.strategy_query import answer_strategy_query, reprice_arena

EXAMPLES_DIR = pathlib.Path(__file__).parent.parent.parent / "examples"
PRODUCT_ID = "p-electronics-widget"


@pytest.fixture(scope="module")
def electronics_factory() -> Factory:
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        return Factory.model_validate(json.load(fh))


@pytest.fixture(scope="module")
def arena_result(electronics_factory):
    result, sessions = StrategyArena().explore(
        electronics_factory,
        PRODUCT_ID,
        PlanningRequirements(
            objective=OptimizationObjective.MEET_DEMAND, target_units_per_day=1900.0
        ),
    )
    return result, sessions


# The alphabet of things that must never appear in prose

# Every internal identifier that could plausibly be interpolated into a strategy answer.
INTERNAL_TOKENS: list[str] = sorted(
    {g.value for g in InformationGapType}
    # Only the underscored category forms.
    | {c.value for c in CostCategory if "_" in c.value}
    | {
        "ADD_PARALLEL_MACHINE",
        "CHANGE_SHIFT_CONFIGURATION",
        "CHANGE_OPERATOR_CAPACITY",
        "CHANGE_BUFFER_CAPACITY",
        "CHANGE_MACHINE_CYCLE_TIME",
    }
)

# Any SCREAMING_SNAKE run of two or more words.
SCREAMING_SNAKE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")

# The follow-ups a user can actually ask.
USER_QUESTIONS: list[str] = [
    "Show me a cheaper option.",
    "Can we do it without another machine?",
    "Which plan uses the fewest changes?",
    "Compare Plan A and Plan B.",
    "What information do we still need before choosing?",
    "An extra shift costs EUR 18,000 per day.",
    "How is the weather?",
]


def assert_no_internal_tokens(text: str, where: str) -> None:
    for token in INTERNAL_TOKENS:
        assert not re.search(rf"\b{re.escape(token)}\b", text), (
            f"{where} leaked the internal identifier {token!r}: {text!r}"
        )
    stray = SCREAMING_SNAKE.findall(text)
    assert not stray, f"{where} leaked identifier-shaped tokens {stray}: {text!r}"


# DEFECT 1 — internal identifiers in user-facing strategy prose


class TestStrategyAnswersSpeakEnglish:
    @pytest.mark.parametrize("question", USER_QUESTIONS)
    def test_no_answer_leaks_an_internal_identifier(self, arena_result, question):
        result, _ = arena_result
        answer = answer_strategy_query(result, question)
        assert_no_internal_tokens(answer.answer, f"answer to {question!r}")

    def test_the_cheaper_answer_names_missing_costs_in_words(self, arena_result):
        """The exact sentence from the defect report."""
        result, _ = arena_result
        unpriced = [o for o in result.strategies if not o.commercially_complete]
        assert unpriced, "fixture must contain an unpriced option for this to mean anything"

        text = answer_strategy_query(result, "Show me a cheaper option.").answer
        assert_no_internal_tokens(text, "cheaper answer")
        # Not merely token-free — the missing thing is actually named.
        expected = {gap_phrase(g.gap_type) for o in unpriced for g in o.cost.information_gaps}
        assert any(phrase in text for phrase in expected), text

    def test_the_information_needed_answer_speaks_english(self, arena_result):
        result, _ = arena_result
        answer = answer_strategy_query(result, "What information do we still need?")
        assert_no_internal_tokens(answer.answer, "information-needed answer")
        # The typed gaps still travel on the response — the identifiers are
        # removed from the PROSE, not from the protocol.
        if answer.information_gaps:
            assert all(g.gap_type in set(InformationGapType) for g in answer.information_gaps)

    def test_a_supplied_cost_is_acknowledged_in_words(self, arena_result):
        result, _ = arena_result
        answer = answer_strategy_query(result, "An extra shift costs EUR 18,000 per day.")
        assert_no_internal_tokens(answer.answer, "provide-cost answer")
        assert gap_phrase(InformationGapType.SHIFT_COST) in answer.answer
        assert category_phrase(CostCategory.OPEX_PER_DAY) in answer.answer
        # And the machine-readable side is untouched.
        assert answer.cost_inputs and answer.cost_inputs[0].gap_type is InformationGapType.SHIFT_COST

    def test_the_fewest_changes_answer_names_levers_not_action_types(self, arena_result):
        result, _ = arena_result
        answer = answer_strategy_query(result, "Which plan uses the fewest changes?")
        assert_no_internal_tokens(answer.answer, "fewest-changes answer")

    def test_gap_descriptions_are_prose(self, arena_result):
        """The templated ``description`` on each gap is user-facing too."""
        result, _ = arena_result
        for option in result.strategies:
            for gap in option.cost.information_gaps:
                assert_no_internal_tokens(gap.description, f"gap description on {option.label}")

    def test_cost_component_labels_are_prose(self, arena_result):
        result, sessions = arena_result
        for option in result.strategies:
            for component in option.cost.components:
                assert_no_internal_tokens(component.label, f"cost component on {option.label}")

    def test_comparison_row_labels_are_headings_not_enum_members(self, arena_result):
        result, _ = arena_result
        if len(result.strategies) < 2:
            pytest.skip("needs two strategies to compare")
        comparison = compare_strategies(result.strategies[0], result.strategies[1])
        for row in [*comparison.metrics, *comparison.cost_rows]:
            assert_no_internal_tokens(row.label, "comparison row label")
        assert_no_internal_tokens(comparison.headline, "comparison headline")
        for note in comparison.notes:
            assert_no_internal_tokens(note, "comparison note")
        # The machine key still IS the enum — the fix is to the label only.
        assert any(row.metric.startswith("cost_") for row in comparison.cost_rows)

    def test_repricing_answers_stay_clean(self, arena_result, electronics_factory):
        result, sessions = arena_result
        repriced = reprice_arena(
            result,
            sessions,
            [UserCostInput(
                gap_type=InformationGapType.SHIFT_COST,
                amount=18_000.0,
                category=CostCategory.OPEX_PER_DAY,
            )],
        )
        for question in USER_QUESTIONS:
            assert_no_internal_tokens(
                answer_strategy_query(repriced, question).answer,
                f"repriced answer to {question!r}",
            )


class TestTheLanguageTableIsExhaustive:
    """The table is only a fix while it covers every member."""

    @pytest.mark.parametrize("gap_type", list(InformationGapType))
    def test_every_gap_type_has_words(self, gap_type):
        for text in (gap_phrase(gap_type), gap_title(gap_type)):
            assert text and not SCREAMING_SNAKE.search(text)
            assert gap_type.value.lower() not in text.replace(" ", "_")

    @pytest.mark.parametrize("category", list(CostCategory))
    def test_every_cost_category_has_words(self, category):
        for text in (category_phrase(category), category_title(category)):
            assert text and not SCREAMING_SNAKE.search(text)

    def test_an_unmapped_term_fails_loudly_rather_than_leaking(self):
        with pytest.raises((UnmappedInternalTerm, ValueError, KeyError)):
            gap_phrase("SOME_FUTURE_COST")

    def test_action_phrases_are_words(self):
        for action in (
            "ADD_PARALLEL_MACHINE",
            "CHANGE_SHIFT_CONFIGURATION",
            "CHANGE_OPERATOR_CAPACITY",
            "CHANGE_BUFFER_CAPACITY",
            "CHANGE_MACHINE_CYCLE_TIME",
        ):
            assert not SCREAMING_SNAKE.search(action_phrase(action))

    def test_an_unknown_action_degrades_to_english_not_an_identifier(self):
        """``action_type`` is an open string, so this one falls back — but it
        falls back to words, never to the raw token."""
        assert not SCREAMING_SNAKE.search(action_phrase("SOME_NEW_LEVER"))

    def test_phrases_are_joined_as_english(self):
        assert join_phrases(["a"]) == "a"
        assert join_phrases(["a", "b"]) == "a and b"
        assert join_phrases(["a", "b", "c"]) == "a, b and c"
        assert join_phrases([]) == ""

    def test_repeated_gaps_are_named_once(self):
        text = gap_phrases_for([
            InformationGapType.SHIFT_COST,
            InformationGapType.SHIFT_COST,
            InformationGapType.MACHINE_CAPACITY_COST,
        ])
        assert text.count(gap_phrase(InformationGapType.SHIFT_COST)) == 1
        assert gap_phrase(InformationGapType.MACHINE_CAPACITY_COST) in text

    def test_the_backend_and_frontend_vocabularies_agree(self):
        """The display layer keeps its own translation table as a net."""
        source = (
            pathlib.Path(__file__).parent.parent.parent
            / "frontend" / "src" / "utils" / "informationGaps.ts"
        )
        if not source.exists():  # pragma: no cover - frontend may be absent
            pytest.skip("frontend not present")
        text = source.read_text(encoding="utf-8")
        for gap_type in InformationGapType:
            assert f'{gap_type.value}: "{gap_phrase(gap_type)}"' in text, (
                f"frontend GAP_PHRASE disagrees with the backend for {gap_type.value}"
            )


# DEFECT 2 — coverage claiming more than extraction can prove


def _fact(key: str, label: str) -> ProductFact:
    return ProductFact(
        key=key,
        category=key.split(".")[0],
        label=label,
        value="yes",
        status=FactStatus.EXTRACTED,
        # The model refuses an EXTRACTED fact with no evidence, which is the
        # invariant this whole file is downstream of: a claim cites a source.
        evidence=[EvidenceRef(
            document_id="TRR-CEC120-SPEC-001",
            document_name="CEC-120 Compact Electronics Controller Specification",
            page=1,
            quote=f"{label} is required.",
        )],
    )


def _understanding(*facts: ProductFact) -> ProductUnderstanding:
    return ProductUnderstanding(product_name="CEC-120", facts=list(facts))


def _draft(*ops: ProposedOperation) -> ManufacturingProcessDraft:
    return ManufacturingProcessDraft(product_name="CEC-120", operations=list(ops))


def _op(name: str, *fact_keys: str) -> ProposedOperation:
    return ProposedOperation(
        id=name.lower().replace(" ", "-"),
        process_type="inspection",
        name=name,
        basis="test fixture",
        source_fact_keys=list(fact_keys),
    )


#: Wording that asserts something about the DOCUMENT rather than about what
#: was extracted from it.
FORBIDDEN_COVERAGE_CLAIMS = [
    "requirements in the source are addressed",
    "found in the source are addressed",
    "the source states no manufacturing requirements",
    "all manufacturing requirements in the source",
]


class TestCoverageClaimsOnlyWhatItExtracted:
    def test_complete_coverage_is_scoped_to_the_extraction(self):
        report = coverage_for(
            _understanding(_fact("requirement.inspection", "Visual inspection")),
            _draft(_op("Visual inspection", "requirement.inspection")),
        )
        assert report.complete
        summary = report.summary()
        assert summary == "All 1 extracted manufacturing requirement are addressed."
        for claim in FORBIDDEN_COVERAGE_CLAIMS:
            assert claim not in summary.lower(), summary

    def test_plural_agreement(self):
        report = coverage_for(
            _understanding(
                _fact("requirement.inspection", "Visual inspection"),
                _fact("component.label", "Identification label"),
            ),
            _draft(
                _op("Visual inspection", "requirement.inspection"),
                _op("Apply label", "component.label"),
            ),
        )
        assert report.summary() == "All 2 extracted manufacturing requirements are addressed."

    def test_no_requirements_extracted_is_stated_as_such(self):
        """
        "The source states no manufacturing requirements" was a claim about a document
        nobody read exhaustively.
        """
        report = coverage_for(_understanding(_fact("material.body", "ABS")), _draft())
        summary = report.summary()
        assert summary == "No manufacturing requirements were extracted from the source."
        for claim in FORBIDDEN_COVERAGE_CLAIMS:
            assert claim not in summary.lower(), summary

    def test_the_incomplete_sentence_is_not_weakened(self):
        """The correction runs one way only."""
        report = coverage_for(
            _understanding(
                _fact("requirement.inspection", "Visual inspection"),
                _fact("component.label", "Identification label"),
            ),
            _draft(_op("Visual inspection", "requirement.inspection")),
        )
        assert not report.complete
        summary = report.summary()
        # "extracted" appears in BOTH sentences now: a qualifier that shows up
        # only when the news is good reads as a hedge attached to success.
        assert "1 of 2 extracted manufacturing requirements are addressed" in summary
        assert "1 unresolved" in summary
        assert "stated explicitly by the source" in summary

    def test_an_unresolved_requirement_is_still_reported_as_unresolved(self):
        """The wording change must not touch the finding itself."""
        report = coverage_for(
            _understanding(_fact("component.label", "Identification label")),
            _draft(),
        )
        assert [i.fact_key for i in report.unresolved] == ["component.label"]
        assert report.approval_blocked
        assert report.items[0].status is CoverageStatus.UNRESOLVED

    def test_no_coverage_sentence_claims_source_completeness(self):
        """Sweep every branch of ``summary()`` at once."""
        cases = [
            coverage_for(_understanding(), _draft()),
            coverage_for(_understanding(_fact("material.body", "ABS")), _draft()),
            coverage_for(
                _understanding(_fact("requirement.inspection", "Visual inspection")),
                _draft(_op("Visual inspection", "requirement.inspection")),
            ),
            coverage_for(
                _understanding(
                    _fact("requirement.inspection", "Visual inspection"),
                    _fact("component.label", "Identification label"),
                ),
                _draft(_op("Visual inspection", "requirement.inspection")),
            ),
        ]
        for report in cases:
            summary = report.summary().lower()
            for claim in FORBIDDEN_COVERAGE_CLAIMS:
                assert claim not in summary, report.summary()
