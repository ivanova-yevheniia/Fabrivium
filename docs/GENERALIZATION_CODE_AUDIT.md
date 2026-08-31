# Generalization code audit — is Fabrivium a CEC-120 demonstration?

> **Historical record — read this first.**
>
> This audit was written when the product was called FactoryMind, and when the
> CEC-120 case ran at a 1,058 units/day baseline with a 2,033 units/day
> capacity. The published case study now reports 1,435 → 1,900 units/day; see
> [CEC-120 case provenance](FABRIVIUM_CEC_CASE_PROVENANCE.md). The name was
> replaced with *Fabrivium* in this file; nothing else was changed.
>
> A later and wider audit, run with Python's tokenizer over the whole source
> tree, is [the generalization audit](FABRIVIUM_GENERALIZATION_AUDIT.md).


**Scope:** the whole product-to-factory pipeline —
`product/describe` → product understanding → process proposal → requirement
coverage → factory concept → input resolution and estimation → simulation →
bottleneck → strategy arena → recommendation — plus the frontend that drives
it.

**Baseline:** commit `5a9fe53` / tag `competition-strong-finalist-v1`.

**Method:** every occurrence of a CEC-120-specific token was located and
classified, then each classification was checked against what the code
actually does — not against what its comments say it does. The searched
tokens were:

```
CEC, CEC-120, "compact electronics controller", ABS, "six screws",
screw/screwdriving, 1900, 1058, 2033, 52, 35, 30, 25, enclosure, PCB, lid,
moulded, cardboard, leaflet, electronics_line, "Electronics Assembly Demo
Dataset", demo, example, golden
```

Note on false positives: a case-insensitive search for `ABS` matches Python's
`abs()`, which accounts for the hits in `placement_search.py`,
`branch_comparison.py`, `comparison.py`, `explanation_validator.py`,
`simulation.py` and `plant_simulation/adapter.py`. Those are arithmetic, not
product knowledge, and are not listed below.

## Classification key

| Class | Meaning |
|---|---|
| **TEST/FIXTURE ONLY** | Appears only in tests, fixtures, bundled example data or UI placeholder copy. No production decision reads it. |
| **GENERIC RULE** | Production logic that happens to be *illustrated* by CEC-120 in a comment or docstring, but branches on nothing product-specific. |
| **SUSPICIOUS** | Generic in form, but with a real path by which CEC-120 data or vocabulary could reach another product. Mitigated, and the mitigation is named. |
| **PRODUCT-SPECIFIC LEAKAGE** | A production decision that is only correct for CEC-120. |

## Summary

Every occurrence is classified in §§1-6 below. The one count that matters:

| Class | Count |
|---|---|
| **PRODUCT-SPECIFIC LEAKAGE** | **0** |

The rest divide into bundled example data and UI copy (TEST/FIXTURE ONLY),
rule tables and vocabularies that branch on nothing product-specific (GENERIC
RULE), and five places where CEC-120 data or vocabulary has a real path to
another product (SUSPICIOUS, §3 and §6).

**No `if product == …`, `if demo:` or equivalent branch exists anywhere in
the pipeline.** The searched forms (`if .*(demo|example|cec|golden)`) return
only docstrings, a file-existence check and a `None` guard. The four golden
figures (1900, 1058, 2033, 52) appear in production code exclusively inside
comments and inside one declared anchor table, never as a value a decision
reads.

What the audit *did* find is a different shape of narrowness: the pipeline is
not tuned to CEC-120, but several of its vocabularies and rule tables are
sized to the *class of product CEC-120 belongs to* (small bench-assembled
goods). That is a coverage limit, and it is declared in the code — but until
this phase it was nowhere measured. Sections 5 and 6 below list where it
bites, and `GENERALIZATION_VALIDATION_REPORT.md` reports what happened when
three other products were run through it.

---

## 1. Bundled CEC-120 data

| Location | Class | Reasoning |
|---|---|---|
| `app/data/electronics_controller_reference_product.txt` | TEST/FIXTURE ONLY | The bundled reference document, served by `GET /product/reference` and marked `EXAMPLE / REFERENCE DATA`. It is *input*, read by the same extractor any uploaded document goes through; `reference_product()` does no interpretation. |
| `examples/customer_docs/Compact_Electronics_Controller_Product_Specification.pdf` | TEST/FIXTURE ONLY | Used by `test_credibility_product_path.py` as an adversarial input. Not reachable from any endpoint. |
| `examples/electronics_line.json` / `_layout.json` | TEST/FIXTURE ONLY | The demo factory, served by `GET /factory/example`. See §3 for the one path by which its numbers can enter a concept. |
| `app/data/screwdriving_candidates.json` | GENERIC RULE | A researched equipment dataset keyed by `process_category`. `load_cached_candidates()` looks up by category and returns an empty shortlist plus a note for any other category. Being the only category researched is a declared scope limit, not a branch. |

## 2. The four golden figures (1900 / 1058 / 2033 / 52)

| Location | Class | Reasoning |
|---|---|---|
| `concept_builder.py:56`, `models/conversation.py:177`, `models/strategy.py:102`, `services/requirement_update.py:19-21`, `simulation.py:1612-1623` | GENERIC RULE | Comments and docstrings using the demo run as a worked example. No code reads them. |
| `data/engineering_reference_data.py` `SANITY_CHECKS` and `dataset_station_seconds` | GENERIC RULE | The four dataset station values (35/52/30/25) are recorded as the **anchor** the reference bands are checked against, with the anchoring stated in the module docstring and enforced by a test. They are never returned as an estimate. |
| `frontend/.../GoalInput.tsx`, `ConversationPanel.tsx`, `ProductStart.tsx`, `EstimateAssistant.tsx` | TEST/FIXTURE ONLY | Placeholder and example-prompt copy. |
| `frontend/src/test/fixtures.ts` | TEST/FIXTURE ONLY | Test fixtures. |

## 3. `concept_example_data.apply_example_engineering_data` — SUSPICIOUS

This is the one function that can put CEC-120's measured numbers into another
product's concept. It fills a stage's cycle time, capacity, operator demand,
size and price from `examples/electronics_line.json`, **matched by
`process_type`** — so a "Packaging" stage on any product would be filled with
the demo line's packaging figures.

**Why it is SUSPICIOUS and not LEAKAGE:**

* it runs only on an explicit user action (`POST /concept/example-data`,
  `POST /concept/use-example-data-for-unresolved`) and is never reached by
  the product path;
* every value it writes is tagged `ValueSource.EXAMPLE_DATA` and carries the
  dataset's name, so the provenance surfaces show where it came from;
* a stage whose `process_type` the dataset does not know is left as a
  visible required gap rather than filled;
* `app/skills/workflows.py` and `app/skills/orchestrator.py` both state as a
  rule that no workflow stage may substitute example data for a missing
  input.

**Residual risk, stated plainly:** the label is honest but the value is still
CEC-120's, and a reviewer scanning KPIs rather than provenance badges would
not notice. The generalization run therefore never called it, and the audit
script asserts that no case's concept contains a single `EXAMPLE_DATA` value
(§ *Provenance* of the validation report). It found none.

## 4. Vocabulary and rule tables — GENERIC RULE, with declared coverage

None of these branch on a product. All of them are *lists*, and their size is
what limits generalization.

| Location | Contents | Class |
|---|---|---|
| `product_extraction._COUNTABLE` | screws, bolts, cables | GENERIC RULE |
| `product_extraction._COMPONENTS` | PCB, enclosure/housing/casing, lid/cover, label | GENERIC RULE |
| `product_extraction._MATERIALS` | stainless, polycarbonate, PC/ABS, ABS, aluminium, steel, plastic, metal | GENERIC RULE |
| `product_extraction._INSPECTION_STEMS` / `_PACKAGING_STEMS` | inspect/inspection/verify/verified; packaging/packed/packing/carton/box/bag/leaflet | **SUSPICIOUS** (§6) |
| `process_planning._RULES` | 7 fact-key → operation rules | GENERIC RULE |
| `concept_builder._STAGE_VOCABULARY` | 12 process families | GENERIC RULE |
| `engineering_reference_data.PROCESS_PROFILES` | 4 families with bands | GENERIC RULE |
| `local_estimator._SUB_OPERATIONS` | operation-counting stems for those 4 families | GENERIC RULE |
| `requirement_coverage._REQUIREMENT_PREFIXES` | `component. fastener. connection. requirement.` | GENERIC RULE — written as prefixes so a new fact key is checked by default |

`ABS` appearing in `_MATERIALS` is not CEC-120 knowledge: the list also
carries seven other materials, and the two-level family map
(`ABS → Plastic`) is a generic precision rule, exercised in this phase by
Case A's aluminium/steel document.

The estimator's refusal is the strongest generic behaviour found in the
audit: `local_estimator.estimate` returns `MissingInformation` — not an
extrapolated band — for the eight families it has no data for, and names the
four it does have. It is the opposite of a demo shortcut.

## 5. CEC-120 named in docstrings of otherwise generic modules — GENERIC RULE

* `requirement_coverage.py:8` — cites the CEC-120 label requirement as the
  motivating example for a rule that matches every `component.*`,
  `fastener.*`, `connection.*` and `requirement.*` fact. Verified generic:
  Case B's `component.label` and Case A's `component.enclosure` were both
  caught by it, on documents CEC-120 had nothing to do with.

  **What it does not cover, stated here so the classification is not
  over-read:** coverage matches operations against the facts the *extractor
  produced*. It is not, and cannot be, evidence that every
  manufacturing-relevant statement in an arbitrary source document was
  successfully extracted. A step the extraction vocabulary does not recognise
  — Case A's washing/degreasing, its bearing press-fit — produces no fact, so
  there is nothing for coverage to find unaddressed. Its summary sentence
  says *"requirements found in the source"* for exactly this reason.
* `equipment_discovery.py:38` — "The 52 s in the golden demo is therefore
  never written down in this module." Verified: the module derives its cycle
  requirement from the concept it is handed.
* `process_planning.py:14` — "There is no `if demo: return the nice route`."
  Verified by reading the rule table and by Cases A/B/C producing three
  different routes.

## 6. Findings the audit produced, and what happened to them

Each of these was found by reading code and confirmed by running a product
other than CEC-120. Fix decisions are justified in the validation report.

| # | Finding | Class | Status |
|---|---|---|---|
| 1 | `_facts_in_sentence` dropped a countable noun entirely when no quantity sat near it. A document saying "the cover is secured with screws" produced **no fact, no operation, no coverage entry and no gap** — the fastening station simply vanished, in the flattering direction. | SUSPICIOUS → real defect | **FIXED** (generic; CEC-120 output byte-identical) |
| 2 | `concept_builder._NO_NEW_EQUIPMENT_RE` accepted at most one qualifier word, so "do not buy **any new** machines" matched nothing — the exact defect Phase 9B fixed in the sibling regex `requirements_parser._NO_NEW_MACHINE_RE` and did not fix here. Two readers of the same customer sentence disagreed. | SUSPICIOUS → real defect | **FIXED** (generic) |
| 3 | `requirements_parser._OPERATOR_LEVER_RE` / `_SHIFT_LEVER_RE` matched refusals as requests: "we cannot **hire additional operators**" was read as an ask for that lever. A stated constraint was not merely dropped — it was inverted. | SUSPICIOUS → real defect | **FIXED** (generic) |
| 4 | `ReferenceBand.applicability` ("not valid for high-torque joints", "not valid for large or heavy assemblies") was declared in the data and never surfaced. The estimator cannot know whether a station is inside those limits and said nothing either way. | SUSPICIOUS | **FIXED** — the limits are now quoted in the basis |
| 5 | `_INSPECTION_STEMS` / `_PACKAGING_STEMS` are matched by exact token equality although the comment above them claims "whole tokens **with a prefix allowance**". "inspected", "packaged" and "cartons" therefore match nothing. | SUSPICIOUS | **NOT FIXED** — reported; see the validation report for why |
| 6 | Operation names come from a fixed table, so a pressure/leak test is named "Visual inspection" on screen. | SUSPICIOUS | **NOT FIXED** — reported |
| 7 | `local_estimator.count_operations` counts stems in a description Fabrivium itself generated, double-counting a repeated word ("Packaging, implied by packaging required" → 2 packaging steps). | SUSPICIOUS | **NOT FIXED** — reported; the fix would move a number in the frozen competition baseline |
| 8 | `ProductStart.tsx` pre-fills the product name with "Compact electronics controller". | TEST/FIXTURE ONLY | Not a defect; noted so nobody mistakes the default for a binding. |

## 6b. Frontend

| Location | Class | Reasoning |
|---|---|---|
| `utils/assetResolution.ts` `CATEGORY_ALIASES` | GENERIC RULE | Maps `process_type` to one of four station categories, with `GENERIC_PROCESSING_MACHINE` as the fallback and a visible badge when the model is a stand-in rather than the real machine. A new process family renders as a badged generic station, not as a wrong one. |
| `RecommendationHero.tsx`, `FinalSuccessBanner.tsx` | GENERIC RULE | The headline is driven by `metrics.goal_met`; when it is false the UI reads "TARGET NOT YET REACHED" / "Target not reached" with the real remaining gap. Confirmed against Case C. |
| `ProductStart.tsx:44` default product name | TEST/FIXTURE ONLY | A pre-filled string in a text field. |
| `GoalInput.tsx`, `ConversationPanel.tsx`, `ConceptBuilder.tsx` example prompts | TEST/FIXTURE ONLY | Placeholder copy naming the demo's figures. |

One presentational risk, not a defect: when nothing reaches the target,
`arena.recommended_strategy_id` still names the best-effort option, so the
"Recommended" tag sits on a plan the same screen says did not reach the
target. The headline is unambiguous, so this is a wording risk rather than a
false claim — noted in the validation report.

## 7. What was checked and found clean

* No production branch on a product name, document, or case.
* No golden KPI constant read by any decision.
* No fixture-specific machine-id mapping. Stage ids are derived
  (`stage_id_for`, `draft_to_stages`) from the route the document produced.
* `concept_to_factory` refuses to convert while a REQUIRED gap remains, for
  every product — confirmed by Case B receiving HTTP 400 with the three
  missing values named.
* The Siemens integration, the Plant Simulation adapter, core simulation
  semantics, the CEC-120 golden inputs and the competition baseline were not
  modified by this phase.
