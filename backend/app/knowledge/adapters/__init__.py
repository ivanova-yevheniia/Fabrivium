"""
Adapters over Fabrivium's canonical engineering knowledge.

ONE JOB
-------
Read what a canonical source already holds and describe it as knowledge
items. An adapter never decides an engineering question, never computes a
value, and never holds a value the source does not hold.

    if an adapter starts stating engineering, the abstraction is wrong

That is the same rule ``app.skills.contract`` states about skill adapters,
for the same reason: a second statement of a value can disagree with the
first, and then the product has two answers.

WHY THESE READ PRIVATE MODULE ATTRIBUTES
----------------------------------------
Two canonical tables — ``process_planning._RULES`` and
``strategy_cost._ACTION_COST_RULES`` — are module-private. The adapters read
them anyway, and that is the deliberate choice: the alternative is to
restate the rules here, which is the copy this whole layer exists to avoid.
Reading the real table means a rule added to the planner appears in the
knowledge base with no second edit, and a rule changed there cannot leave a
stale description behind.

The tidier follow-up is a public accessor on each of those modules. It was
not taken in this pass because it would edit production files for a purely
additive, read-only layer, and "no production engineering module was
modified" is a stronger guarantee to be able to make before a competition
freeze than a slightly cleaner import.

EACH ADAPTER DECLARES ITS OWN VERSION
-------------------------------------
The version describes the EXPOSURE — the shape and the selection of what is
published — not the engineering value. See ``app.knowledge.contract``.
"""

from app.knowledge.adapters.commercial import commercial_knowledge
from app.knowledge.adapters.equipment import equipment_knowledge
from app.knowledge.adapters.estimation import estimation_knowledge
from app.knowledge.adapters.layout import layout_knowledge
from app.knowledge.adapters.process import process_knowledge
from app.knowledge.adapters.validation import validation_knowledge

__all__ = [
    "commercial_knowledge",
    "equipment_knowledge",
    "estimation_knowledge",
    "layout_knowledge",
    "process_knowledge",
    "validation_knowledge",
]
