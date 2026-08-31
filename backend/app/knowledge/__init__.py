"""
The Fabrivium Engineering Knowledge Base.

WHAT THIS PACKAGE IS
--------------------
An explicit, versioned, inspectable description of the engineering knowledge
Fabrivium already holds — process rules, estimation methods, equipment
evidence, validation rules, layout rules and cost semantics — derived from
the canonical sources that hold it, and adding none of its own.

WHAT IT IS NOT
--------------
Not a second copy of that knowledge, not a runtime, and not part of any
production engineering path. Nothing in this package computes a cycle time,
proposes an operation, validates a concept or prices a strategy. It reads
what the canonical modules hold and describes it under one contract.

    the knowledge base changes what Fabrivium can SAY about itself,
    never what Fabrivium DOES

That is enforced, not just intended: ``test_engineering_knowledge_base``
asserts that no module outside this package and the two read-only API
endpoints imports it.

WHAT IS NEXT
------------
``app.knowledge.packaging`` defines the Engineering Skill contract — the
reusable, versioned company knowledge packages this foundation is for. It is
a contract only; there is no loader. See its module docstring, and
docs/FABRIVIUM_ENGINEERING_KNOWLEDGE_BASE.md.
"""

from app.knowledge.base import (
    CategorySummary,
    EngineeringKnowledgeBase,
    KnowledgeBaseSummary,
    KnowledgeItemNotFound,
    KnowledgeRegistrationError,
)
from app.knowledge.builtin import KNOWLEDGE_BASE_VERSION, build_knowledge_base
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

__all__ = [
    "Applicability",
    "CategorySummary",
    "EngineeringKnowledgeBase",
    "EngineeringKnowledgeItem",
    "KNOWLEDGE_BASE_VERSION",
    "KnowledgeBaseSummary",
    "KnowledgeCategory",
    "KnowledgeDomain",
    "KnowledgeExposure",
    "KnowledgeItemNotFound",
    "KnowledgeKind",
    "KnowledgeRegistrationError",
    "Provenance",
    "SourceKind",
    "StandardReference",
    "StandardVerification",
    "build_knowledge_base",
]
