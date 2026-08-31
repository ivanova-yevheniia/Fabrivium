"""No production prompt may assume the product is an electronics controller."""

from __future__ import annotations

import pytest

# Every system prompt a provider is actually sent in production.
from app.services.conversation_parser import DEFAULT_UPDATE_SYSTEM_PROMPT
from app.services.estimation import _SYSTEM_PROMPT as ESTIMATION_PROMPT
from app.services.explanation_agent import DEFAULT_EXPLANATION_SYSTEM_PROMPT
from app.services.planning_agent import DEFAULT_PLANNING_SYSTEM_PROMPT
from app.services.product_intelligence import _build_system_prompt
from app.services.requirements_parser import DEFAULT_SYSTEM_PROMPT as REQUIREMENTS_PROMPT

PROMPTS = {
    "requirements_parser.DEFAULT_SYSTEM_PROMPT": REQUIREMENTS_PROMPT,
    "planning_agent.DEFAULT_PLANNING_SYSTEM_PROMPT": DEFAULT_PLANNING_SYSTEM_PROMPT,
    "explanation_agent.DEFAULT_EXPLANATION_SYSTEM_PROMPT": DEFAULT_EXPLANATION_SYSTEM_PROMPT,
    "conversation_parser.DEFAULT_UPDATE_SYSTEM_PROMPT": DEFAULT_UPDATE_SYSTEM_PROMPT,
    "estimation._SYSTEM_PROMPT": ESTIMATION_PROMPT,
    "product_intelligence.system prompt": _build_system_prompt(),
}

# Words that would tell a model what industry it is reading about.
FORBIDDEN = (
    "cec", "cec-120", "controller", "pcb", "printed circuit",
    "cable", "enclosure", "lid", "electronics", "electronic",
)

# Shapes of line that would tell a model how many stations to expect.
FORBIDDEN_SHAPES = ("seven operation", "seven station", "1900", "1,900", "18,000")


@pytest.mark.parametrize("name", sorted(PROMPTS))
def test_no_production_prompt_names_a_specific_product_or_industry(name):
    text = PROMPTS[name].lower()
    hits = [word for word in FORBIDDEN if word in text]
    assert not hits, (
        f"{name} contains product-specific vocabulary {hits}. A prompt that names an "
        f"industry tells the model what to look for, and it will find it — in a "
        f"packaging specification too."
    )


@pytest.mark.parametrize("name", sorted(PROMPTS))
def test_no_production_prompt_assumes_a_line_shape(name):
    text = PROMPTS[name].lower()
    hits = [shape for shape in FORBIDDEN_SHAPES if shape in text]
    assert not hits, f"{name} assumes a specific line: {hits}."


@pytest.mark.parametrize("name", sorted(PROMPTS))
def test_every_prompt_still_says_what_it_is_for(name):
    """A prompt emptied of everything is neutral and useless."""
    text = PROMPTS[name].lower()
    assert any(
        word in text
        for word in ("manufactur", "production", "product specification", "factory")
    ), f"{name} no longer states its domain at all."


# The one prompt that DOES carry process vocabulary, and why that is right


class TestProcessFamilyVocabulary:
    """`product_intelligence` names the process families on purpose."""

    def test_the_catalog_reaches_the_prompt(self):
        from app.services.process_families import process_family_catalog

        prompt = _build_system_prompt().lower()
        for family in process_family_catalog().families:
            assert family.label.lower() in prompt, f"{family.label} missing from the prompt"

    def test_it_includes_families_the_demo_never_uses(self):
        """The proof that it is generated and not typed from the demo."""
        prompt = _build_system_prompt().lower()
        for family in ("welding", "machining", "curing", "palletizing"):
            assert family in prompt

    def test_the_vocabulary_is_offered_not_imposed(self):
        """A checklist would make the model invent an operation to fill it."""
        prompt = _build_system_prompt().lower()
        assert "not as a checklist" in prompt
        assert "must not invent" in prompt

    def test_the_prompt_says_not_to_assume_a_domain(self):
        assert "do not assume a" in _build_system_prompt().lower()


# Unknown stays unknown


@pytest.mark.parametrize("name", sorted(PROMPTS))
def test_no_prompt_invites_a_guess(name):
    """Every prompt must tell the model what to do when it does not know,
    and none may ask it to fill a gap."""
    text = PROMPTS[name].lower()
    admits_ignorance = any(
        phrase in text
        for phrase in (
            "omit", "unknown", "not confident", "does not say",
            "confidence low", "never invent", "must not invent", "never guess",
        )
    )
    assert admits_ignorance, f"{name} does not say what to do when the answer is not known."
