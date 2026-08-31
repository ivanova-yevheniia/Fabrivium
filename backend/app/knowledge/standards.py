"""Standard references — a pointer to a standard, never its content."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class StandardVerification(str, Enum):
    """How far a standard reference has been established."""

    MENTIONED_IN_SOURCE = "MENTIONED_IN_SOURCE"

    DECLARED_IN_SCOPE = "DECLARED_IN_SCOPE"

    NOT_ASSESSED = "NOT_ASSESSED"


@dataclass(frozen=True)
class StandardReference:
    """A citation of a published standard."""

    # The designation as the citing source writes it, e.g. "DIN ISO 8573-1".
    identifier: str

    #: What is doing the citing — a candidate record, a company policy, a
    #: customer requirement. A reference with no citer is an assertion.
    cited_by: str

    verification: StandardVerification

    # Only where publicly available and actually known.
    title: str = ""

    # Edition or date, only where the citing source states one.
    edition: str = ""

    # What the standard was cited FOR, in the citing source's own words.
    scope_note: str = ""

    def __post_init__(self) -> None:
        if not self.identifier.strip():
            raise ValueError("A standard reference needs an identifier.")
        if not self.cited_by.strip():
            raise ValueError(
                f"Standard reference '{self.identifier}' names no citing source. "
                f"An uncited standard reference is Fabrivium asserting a standard, "
                f"which is exactly what this type must not be usable for."
            )

    @property
    def content_available(self) -> bool:
        """Whether Fabrivium holds the text of this standard."""
        return False

    @property
    def establishes_compliance(self) -> bool:
        """Whether this reference means the design complies. Always False."""
        return False

    @property
    def disclosure(self) -> str:
        """The sentence that must accompany this reference wherever it is shown."""
        return (
            f"{self.identifier} is referenced by {self.cited_by}. Fabrivium holds no "
            f"content of this standard and makes no assessment of compliance with it."
        )


# Field names that would turn a reference into a reproduction.
FORBIDDEN_CONTENT_FIELDS: frozenset[str] = frozenset(
    {
        "text",
        "full_text",
        "content",
        "body",
        "clause",
        "clauses",
        "requirements",
        "excerpt",
        "extract",
    }
)
