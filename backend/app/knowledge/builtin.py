"""Assembling the built-in Engineering Knowledge Base."""

from __future__ import annotations

from app.knowledge.adapters import (
    commercial_knowledge,
    equipment_knowledge,
    estimation_knowledge,
    layout_knowledge,
    process_knowledge,
    validation_knowledge,
)
from app.knowledge.base import EngineeringKnowledgeBase
from app.knowledge.contract import EngineeringKnowledgeItem

#: Bumped when the SET of published knowledge changes — an adapter added, a
#: category retired. Not when a band or a catalogue record changes: that is
#: a change to a source, and the source carries its own verification date.
KNOWLEDGE_BASE_VERSION = "1.0.0"

#: In the order their categories are introduced in the documentation, so a
#: reader following the doc and a reader following the code see the same
#: shape. Query results are sorted regardless — see app.knowledge.base.
ADAPTERS = (
    process_knowledge,
    estimation_knowledge,
    equipment_knowledge,
    validation_knowledge,
    layout_knowledge,
    commercial_knowledge,
)


def build_knowledge_base() -> EngineeringKnowledgeBase:
    """The knowledge Fabrivium holds, read from its canonical sources."""
    items: list[EngineeringKnowledgeItem] = []
    for adapter in ADAPTERS:
        items.extend(adapter())
    return EngineeringKnowledgeBase(items, version=KNOWLEDGE_BASE_VERSION)
