"""Source statements that look like manufacturing work and were not mapped."""

from __future__ import annotations

import re

from app.services.input_adapters import NormalizedEvidence
from app.models.product import EvidenceRef, ProductFact, UnresolvedSourceStatement

# The extractor's own sentence splitter, tokeniser and per-sentence rule pass.
from app.services.product_extraction import _facts_in_sentence, _sentences, _tokens

# Modals that put a following bare "be" into the specification voice.
_MODALS = frozenset({"shall", "must", "should", "will", "can", "may", "would"})

# Be-verbs that can head a passive.
_BE = frozenset({"is", "are", "was", "were"})

# Tokens that, sitting between the be-verb and a candidate participle, mean the
# construction is NOT an instruction to perform work.
_BLOCKERS = frozenset(
    {
        "a", "an", "the", "this", "that", "these", "those",
        "no", "not", "never", "neither", "nor",
        "being", "been",
        "still", "already", "also", "only", "just", "now", "then",
        "therefore", "hereby", "however",
    }
)

# A regular English past participle.
_PARTICIPLE_RE = re.compile(r"^[a-z]{3,}ed$")

# Nouns naming a PIECE OF PAPER.
_META_SUBJECTS = frozenset(
    {
        "specification", "specifications", "spec", "document", "documentation",
        "drawing", "drawings", "revision", "release", "section", "clause",
        "page", "table", "figure", "figures", "appendix", "note", "notes",
        "list", "standard", "report",
        # "Detailed electrical design data is issued separately", "the
        # following figures are supplied by the customer" — information about
        # the product, published on paper. Nothing is done to a unit here.
        "data", "record", "records", "figures",
        # The document's LEGAL framing, which is paperwork about the paperwork.
        "resemblance", "resemblances",
        "organisation", "organisations", "organization", "organizations",
        "copyright", "trademark", "trademarks",
    }
)

# Any of these anywhere in the sentence and it is not read as work to do.
_NEGATIONS = frozenset(
    {"no", "not", "never", "neither", "nor", "without", "cannot", "excluding", "except"}
)

#: A run of newlines this long or longer separates paragraphs; anything
#: shorter is hard wrapping inside one sentence.
_PARAGRAPH_BREAK = "\n\n"

# A full stop between two digits is a decimal point, not a sentence end.
_DECIMAL_RE = re.compile(r"(\d)\.(\d)")
_DECIMAL_SENTINEL = "\x00"

# Shorter than this and it is a heading or a fragment, not a statement.
_MIN_STATEMENT_CHARS = 25

REASON = (
    "This sentence states work performed on the product, and Fabrivium's structured "
    "extraction produced no fact from it. It may be a manufacturing requirement that was "
    "not mapped — Fabrivium has not interpreted it, and has not created any operation "
    "from it."
)


def _is_participle(token: str) -> bool:
    return bool(_PARTICIPLE_RE.match(token))


def _unwrapped(text: str) -> str:
    """Hard-wrapped source text with its sentences put back together."""
    return _PARAGRAPH_BREAK.join(
        " ".join(paragraph.split()) for paragraph in text.split(_PARAGRAPH_BREAK)
    )


def _statements(text: str) -> list[str]:
    """The source's sentences, with decimal points left intact."""
    guarded = _DECIMAL_RE.sub(lambda m: m.group(1) + _DECIMAL_SENTINEL + m.group(2), text)
    return [
        sentence.replace(_DECIMAL_SENTINEL, ".")
        for sentence in _sentences(guarded)
    ]


def _about_the_paperwork(tokens: list[str], be_index: int) -> bool:
    """Whether the thing being described is a document rather than a product."""
    return any(token in _META_SUBJECTS for token in tokens[:be_index])


def _states_work(tokens: list[str]) -> bool:
    """Whether the sentence contains ``<be> [token] <participle>``."""
    if any(token in _NEGATIONS for token in tokens):
        return False

    for index, token in enumerate(tokens):
        if token in _BE:
            pass
        elif token == "be" and index > 0 and tokens[index - 1] in _MODALS:
            pass
        else:
            continue

        if _about_the_paperwork(tokens, index):
            continue

        after = tokens[index + 1 : index + 3]
        if not after:
            continue
        if _is_participle(after[0]):
            return True
        if len(after) == 2 and after[0] not in _BLOCKERS and _is_participle(after[1]):
            return True
    return False


def _cited_quotes(facts: list[ProductFact]) -> set[str]:
    """Every sentence any supplied fact cites."""
    return {
        reference.quote.strip()
        for fact in facts
        for reference in fact.evidence
        if reference.quote
    }


def unresolved_statements(
    evidence: list[NormalizedEvidence],
    facts: list[ProductFact] | None = None,
) -> list[UnresolvedSourceStatement]:
    """Sentences that read as manufacturing work and produced no fact."""
    cited = _cited_quotes(facts or [])
    seen: set[str] = set()
    found: list[UnresolvedSourceStatement] = []

    for item in evidence:
        for sentence in _statements(_unwrapped(item.text)):
            statement = sentence.strip()
            if len(statement) < _MIN_STATEMENT_CHARS:
                continue
            if statement in seen:
                continue
            if not _states_work(_tokens(statement)):
                continue
            # The extractor's own verdict on this exact sentence, not a
            # lookup against merged evidence. See the module note.
            if _facts_in_sentence(statement, item):
                continue
            if statement[:180] in cited or statement in cited:
                continue

            seen.add(statement)
            found.append(
                UnresolvedSourceStatement(
                    statement=statement,
                    evidence=EvidenceRef(
                        document_id=item.document_id,
                        document_name=item.document_name,
                        page=item.page,
                        quote=statement[:180],
                    ),
                    reason=REASON,
                )
            )

    return found


def describe(statements: list[UnresolvedSourceStatement]) -> str:
    """One sentence for the panel heading."""
    if not statements:
        return (
            "No further sentence in the source states work on the product that Fabrivium "
            "failed to map. This is not a claim that the document is fully understood."
        )
    count = len(statements)
    plural = "" if count == 1 else "s"
    return (
        f"{count} sentence{plural} in the source state{'s' if count == 1 else ''} work on the "
        "product that Fabrivium could not map to a requirement. Each needs an engineer's "
        "decision; Fabrivium has not created any operation from them."
    )
