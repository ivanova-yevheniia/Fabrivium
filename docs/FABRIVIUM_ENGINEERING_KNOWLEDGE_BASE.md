# Fabrivium Engineering Knowledge Base

**Date:** 2026-08-29
**Status:** foundation implemented, additive, zero change to Golden Run behaviour
**Code:** `backend/app/knowledge/`  ·  **Tests:** `backend/tests/test_engineering_knowledge_base.py`

> **On the name.** *Fabrivium* is the product name — it is what the
> application title, the API and the user-facing text say. *FactoryMind* is
> the older internal name still used by the Python package namespace,
> environment variables and the earlier phase documents. They are the same
> system; where this document quotes an identifier, it quotes it as the code
> spells it.

> Fabrivium already has an Engineering Knowledge Base containing structured
> process knowledge, estimation logic, equipment evidence and validation
> rules. The next step is **Engineering Skills**: reusable packages of
> company standards and engineering know-how.

---

## The picture, today and next

**Today — what the product does:**

```
     PRODUCT REQUIREMENTS
              +
     ENGINEERING KNOWLEDGE
              ↓
      ENGINEERING CONCEPT
              ↓
   SIMULATION & VERIFICATION
              ↓
      DECISION / HANDOFF
```

**Next — what the knowledge base is the foundation for:**

```
     PRODUCT REQUIREMENTS
              +
  REUSABLE ENGINEERING SKILLS      ← roadmap: company / domain packages
              ↓
  ENGINEERING KNOWLEDGE BASE       ← implemented today
              ↓
  VERIFIED PRODUCTION CONCEPT
```

The full enterprise flow the roadmap is aimed at:

```
  Product Requirements  +  Engineering Skills
              ↓
     Engineering Knowledge Base
              ↓
       Engineering Concept
              ↓
    Deterministic Simulation
              ↓
        Verified Decision
              ↓
      Engineering Handoff
```

> **A new manufacturing project should not start from an empty form.
> It should start from what the organization already knows.**

---

## 1. Why the knowledge base exists

Fabrivium already held real engineering knowledge — cycle-time reference
bands with their rationale, operation-derivation rules that name the source
sentence, catalogue records citing manufacturer documents, validation rules
that decide what blocks a simulation. All of it was **implemented but
implicit**: distributed across a dozen modules, discoverable only by reading
the code, and impossible to cite, version or hand to somebody else.

Three things follow from that, and all three are product problems:

* **It cannot be pointed at.** "Where does 52 seconds come from?" is
  answerable per value at runtime, but "what does this system know about
  screwdriving?" was not answerable at all.
* **It cannot be versioned.** Knowledge that cannot be cited by version
  cannot be referenced by a decision that used it.
* **It cannot be extended.** An organisation's own standards, preferred
  equipment and process templates have nowhere to go, so every new project
  starts from an empty form.

The knowledge base makes the knowledge explicit, addressable, versioned and
inspectable. It is the foundation the Engineering Skills product layer needs
and does not itself change a single engineering answer.

**The one rule the whole design rests on:**

> The knowledge base changes what Fabrivium can **say** about itself.
> It never changes what Fabrivium **does**.

---

## 2. What knowledge Fabrivium already has

The audit found engineering knowledge in six categories. **71 knowledge
items** are published across them.

| Category | Items | What it holds |
|---|---:|---|
| **PROCESS** | 11 | Product requirement → operation mappings, default build order, precedence from the source document, requirement coverage |
| **ESTIMATION** | 12 | Cycle-time reference bands per process family, automation factors, the composition method, the preference order for resolving an unknown |
| **EQUIPMENT** | 21 | Real manufacturer records with cited documents, the customer's asset register and approved-supplier list, capability declarations, the claim ceiling, one standard reference |
| **VALIDATION** | 12 | Which inputs block simulation and which do not, readiness, route integrity, four-tier handoff verification |
| **LAYOUT** | 7 | Nominal planning footprint, station and buffer defaults, the constraint vocabulary, placement search, geometry conventions |
| **COMMERCIAL** | 8 | Cost category per engineering lever, the information gap each opens, price-status semantics, "unknown is not zero" |

### Inventory: current source → knowledge category → current consumer

The knowledge base does not replace any of these. It describes them.

| Current source (canonical) | Category | Current consumer |
|---|---|---|
| `services/process_planning._RULES` | PROCESS | `plan_process` → `ManufacturingProcessDraft` → concept builder |
| `services/process_planning._order_by_precedence` | PROCESS | `plan_process` route ordering |
| `services/requirement_coverage` | PROCESS | `/product/requirement-coverage`, approval gate |
| `data/engineering_reference_data.PROCESS_PROFILES` | ESTIMATION | `local_estimator.estimate` → `/concept/estimate` |
| `data/engineering_reference_data.AUTOMATION_FACTORS` | ESTIMATION | `local_estimator.estimate` |
| `data/engineering_reference_data.UNKNOWN_AUTOMATION_WIDENING` | ESTIMATION | `local_estimator.estimate` |
| `services/local_estimator.estimate` | ESTIMATION | `/concept/estimate` fallback path |
| `services/estimation` (preference order) | ESTIMATION | `/concept/estimate` |
| `models/uncertainty` (estimate ≠ specification) | ESTIMATION | concept stages, sensitivity, readiness |
| `services/equipment_catalog.default_registry()` | EQUIPMENT | `/equipment/discover` |
| `data/*_candidates.json`, `internal_asset_pool.json`, `approved_supplier_catalog.json` | EQUIPMENT | loaded **only** through the registry |
| `services/equipment_discovery.CAPABILITY_BY_PROCESS_TYPE` | EQUIPMENT | requirement derivation, catalogue search |
| `services/equipment_compatibility` | EQUIPMENT | `/equipment/discover` match report |
| `services/concept_validation.concept_gaps` | VALIDATION | `/concept/validate`, `/concept/readiness`, build gate |
| `services/concept_validation.validate_concept` | VALIDATION | `/concept/build` |
| `services/route_validator.validate_route` | VALIDATION | every `run_simulation` call |
| `integrations/plant_simulation/adapter.VerificationTier` | VALIDATION | `/handoff/plant-simulation` |
| `services/concept_validation.DEFAULT_STATION_*`, `DEFAULT_BUFFER_CAPACITY` | LAYOUT | `concept_to_factory` |
| `services/constraints.validate_layout` | LAYOUT | `/layout/validate`, placement search |
| `services/geometry`, `services/placement_search`, `services/layout` | LAYOUT | layout operations |
| `services/strategy_cost._ACTION_COST_RULES` | COMMERCIAL | `build_cost_profile` → strategy comparison |
| `services/strategy_cost.build_cost_profile` | COMMERCIAL | `/strategies/explore`, `/strategies/compare` |
| `models/equipment_discovery.PriceStatus` | COMMERCIAL | every equipment record |

---

## 3. Architecture

```
  CANONICAL SOURCES                     (unchanged — the single source of truth)
  reference tables · rule tables · bundled catalogues · validation functions
          │
          │  read at build time. never copied, never written back.
          ▼
  ADAPTERS                              app/knowledge/adapters/
  process · estimation · equipment · validation · layout · commercial
          │
          ▼
  EngineeringKnowledgeItem              app/knowledge/contract.py
  id · version · kind · category · domain · provenance · applicability
  exposure · values · tags
          │
          ▼
  EngineeringKnowledgeBase              app/knowledge/base.py
  query by category / kind / domain / source / applicability · inspect
  provenance · report a summary
          │
          ├──────────────▶  GET /knowledge, GET /knowledge/{id}   (read-only)
          │
          └──────────────▶  EngineeringSkillManifest              (contract only)
                            app/knowledge/packaging.py
```

Nothing flows the other way. No service, model, integration or skill imports
`app.knowledge`; a test enforces it (§11).

### The two-relationship rule

Every item declares how it relates to its canonical source, and there are
exactly two options:

| Exposure | Meaning |
|---|---|
| `DERIVED_VALUE` | `values` were **read** from the canonical object at build time. Edit the source and the item changes with it. |
| `POINTER` | The item **names where the knowledge lives** and carries none of it. `values` is empty, and the model refuses to construct a pointer that holds one. |

There is deliberately no third option — no "authored here", no "transcribed
from". An item that wanted one would be a copy, and a copy can disagree with
the original. Of the 71 items, **58 are derived** and **13 are pointers**.

Pointers are used where the knowledge is a *procedure* rather than a table:
precedence ordering, requirement coverage, the estimator's composition, the
route validator, the layout ERROR/WARNING policy. Restating a procedure in
prose is exactly the copy that goes stale silently.

### Two different things are called "skill"

They are not the same, and this document keeps them apart:

| | What it is | Status |
|---|---|---|
| `app.skills` | An engineering **capability** — something Fabrivium can *do*. Declared, versioned, executable, traced. | **Implemented**, in production use |
| `app.knowledge.packaging` | An Engineering **Skill package** — something Fabrivium could *know*. A bundle of knowledge items with an owner, a scope and a version. | **Contract only** — no loader |

A capability without knowledge is a function with no data; knowledge without
a capability is a document. The roadmap needs both, which is why they are
separate types in separate packages rather than one word doing two jobs.

---

## 4. Canonical sources

**One source of truth.** The knowledge base never becomes a second place a
value is kept.

Three consequences visible in the code:

1. **Equipment evidence comes through the loader, never the files.** The
   adapter asks `default_registry()` the same question the discovery service
   asks it. Reading the JSON directly would let a record claim a provenance
   its catalogue was not registered under — precisely what the loader exists
   to prevent.
2. **Validation rules are read back from the real validator.** There is no
   hand-written list of "the required inputs". The adapter builds an empty
   probe concept, runs `concept_gaps` over it, and publishes every gap the
   canonical engine reports with the engine's own severity and its own
   sentence. The probe is discarded immediately; it is never simulated,
   converted or persisted.
3. **Two adapters read module-private tables** (`process_planning._RULES`,
   `strategy_cost._ACTION_COST_RULES`). That is deliberate. The alternative
   is restating the rules, which is the copy this layer exists to avoid.
   Promoting them to public accessors is the tidier follow-up; it was not
   taken in this pass because it would edit production engineering modules
   for a purely additive read-only layer, and *"no production engineering
   module was modified"* is a stronger guarantee to hold before a
   competition freeze.

The anti-drift property is **tested by mutation**, not by comparison: the
suite adds a rule to the planner's table and widens a reference band at
source, then asserts the knowledge base follows. A test that only compared
two constants would pass just as happily against a hand-maintained
duplicate.

---

## 5. Provenance model

**Provenance words are borrowed, never minted.** Fabrivium already has
several precise vocabularies — `ValueSource`, `ReferenceClass`,
`CatalogKind`, `EvidenceLevel`, `PriceStatus`. The knowledge base does not
translate them into a vocabulary of its own; an item carries the domain's own
word *plus the name of the vocabulary it came from*, so a reader can look it
up.

```python
Provenance(
    source_kind = SourceKind.REFERENCE_TABLE,
    source_reference = "app.data.engineering_reference_data.PROCESS_PROFILES['screwdriving']",
    statement = "A documented reference band in Fabrivium's own estimation data. "
                "Not an industry standard. Anchored against the Electronics Assembly "
                "Demo Dataset station value of 52.0 s …",
    classification_vocabulary = "ReferenceClass",
    classification = "STATED_ASSUMPTION",
    verified_on = None,
)
```

A classification and its vocabulary travel together — the model raises if one
appears without the other, because a bare trust word nobody can look up is
the failure this field exists to prevent. A test resolves every published
classification against the real enum it names.

`SourceKind` says what the source physically **is** — not how far it can be
trusted, which is the source's own classification:

`IMPLEMENTED_RULE` · `REFERENCE_TABLE` · `BUNDLED_DATASET` ·
`MANUFACTURER_DOCUMENT` · `CUSTOMER_RECORD` · `EXTERNAL_SERVICE` ·
`EXTERNAL_STANDARD` · `COMPANY_POLICY`

**Applicability is part of provenance, not decoration.** Every reference band
in Fabrivium states what it is *not* valid for, and an adapter that dropped
that on the way through would turn a carefully bounded assumption into an
unbounded claim. Every item carries a scope; most carry an explicit
exclusion.

---

## 6. Versioning model

Three levels, each answering a different question:

| Level | What it versions | Bump it when |
|---|---|---|
| `KNOWLEDGE_BASE_VERSION` | the **set** of published knowledge | an adapter is added, a category retired |
| item `version` (per adapter) | the **exposure** — the shape and selection of what is published | the item's fields or the selection change |
| `Provenance.verified_on` | the **currency of the source** | the source records a new check date |

The critical distinction: an item's `version` is **not** a version of the
engineering value. A band moving from 4–9 s to 5–10 s is not a change to this
layer at all — the value's own currency is a fact about its source and is
already carried. Putting a second version number on a number that already has
one would invite a reader to trust the wrong one.

* `qualified_id` is `id@version` — what a citation records.
* `base.get(id, version)` resolves an **exact** version, so a report saying
  *"per `estimation.profile.screwdriving@1.0.0`"* means that item, not
  whatever succeeded it. Without a version, the highest wins.
* `deprecated_on` exists and is `None` on every item in this build. Nothing is
  deprecated today. The field is present rather than absent because retiring
  knowledge must be possible **without deleting it**: a trace, a report or a
  saved project that cites an item has to keep resolving after the item stops
  being offered.
* There is deliberately **no** `effective_from`. It would be `None` on every
  item here, and the date a source was last checked is a different fact that
  already exists.

Registration refuses two items sharing an id *and* version — one would
silently win, and which one would depend on adapter order. Two *versions* of
one id are legitimate and supported.

---

## 7. Standards-reference safety

Two distinctions, both made **structurally** rather than by wording:

```
  a reference to a standard   ≠   the standard's content
  the standard's content      ≠   compliance with the standard
```

**Fabrivium holds no standard content and asserts no compliance.**

| Guarantee | How it is enforced |
|---|---|
| No copyrighted text can be stored | `StandardReference` has **no field** capable of holding clause or requirement text. A test asserts the field names against a forbidden list, so adding one fails the build rather than a review. |
| No verification status means "compliant" | `StandardVerification` has no `COMPLIANT`, `CERTIFIED`, `APPROVED` or `CONFORMS` member. A test asserts the absence by substring. |
| Compliance is never inferred | `establishes_compliance` is a property returning `False` unconditionally — not a stored flag, which could be set. |
| Content is never claimed | `content_available` likewise. There is no mechanism for holding standard content. |
| Every reference names its citer | An uncited standard reference would be Fabrivium asserting a standard. The model refuses to construct one. |
| Nothing is invented | Identifiers are **extracted** from bundled records by a narrow pattern, never authored. A test asserts every published reference appears in a real catalogue record. |

### What this build actually references

Exactly one, and it is not Fabrivium's own:

> **DIN ISO 8573-1** — referenced by *Weber Legi-Air 4050e* (`weber-legi-air-4050e`),
> whose manufacturer datasheet specifies its compressed-air supply
> "6 bar per DIN ISO 8573-1".
> Verification: `MENTIONED_IN_SOURCE` — the weakest there is.
> `content_available = false` · `establishes_compliance = false`

The disclosure that travels with it wherever it is shown:

> *"DIN ISO 8573-1 is referenced by Weber Legi-Air 4050e (weber-legi-air-4050e).
> Fabrivium holds no content of this standard and makes no assessment of
> compliance with it."*

**Fabrivium does not automatically ensure ISO, IEC or VDI compliance, and
makes no compliance claim of any kind.**

---

## 8. Engineering Skills — the future contract

**Not implemented.** `app/knowledge/packaging.py` defines the manifest shape
and a well-formedness validator. There is deliberately **no loader, no
installer, no merge, no override, no precedence rule and no marketplace**.
Nothing in the product reads a manifest to change an engineering answer, and
a test asserts that no `load`, `install`, `merge`, `apply`, `register` or
`activate` function exists in the module.

```python
EngineeringSkillManifest(
    skill_id, name, version, domain, organization_scope,
    description, owner, applicability, validation_status,
    knowledge_items,   # qualified ids — ids, NOT values
    dependencies,      # declared; explicitly unresolvable today
    sources,
)
```

A manifest holds **ids, not knowledge**. A manifest carrying its own values
would be a second place engineering knowledge lives, which the contract in §4
forbids.

The one manifest that ships, `builtin_manifest(base)`, is **derived** from
the knowledge base rather than authored: its item list is exactly what the
base holds, so it cannot advertise knowledge the product does not have and
cannot go stale. It is a description of the present, not a feature —
`validation_status = BUILT_IN`, and `GET /knowledge` reports
`implemented: false` beside it.

`ManifestValidationStatus` has no `CERTIFIED` member. Who would certify,
against what, is a business question with no code answer.

### Open questions a future implementation must still solve

Named here because a contract that hides its open questions is not a
contract:

* **Precedence.** When a company package and the built-in knowledge both
  cover screwdriving, which wins — and how does the resulting estimate say so
  in its provenance? Nothing answers this today.
* **Trust.** Loading a package means accepting somebody's declared
  engineering knowledge. Registration must be explicit, exactly as
  `app.skills.registry` refuses to scan a directory for code to run.
* **Validation.** `validate_manifest` checks that a manifest is well-formed
  and that every item it declares resolves. That is *all* it checks. It does
  not check that the knowledge is correct, applicable, current or safe, and
  an empty problem list must never be read as approval of the engineering.
* **Standards.** A package may reference standards. It may never carry their
  content.

### Package shapes the roadmap anticipates

Names and scopes only — architectural examples, deliberately **not**
constructed manifest instances, because a constructed manifest is a thing a
loader could pick up:

| Example | Would carry |
|---|---|
| `ElectronicsAssemblySkill` | Process templates and estimation methods for electronics assembly lines |
| `LayoutPlanningSkill` | An organisation's own clearance, aisle and material-flow rules |
| `MedicalDeviceManufacturingSkill` | Domain process knowledge and the standard references that govern it |
| `CompanyStandardsSkill` | Internal procedure references, shift policies, engineering rules |
| `ApprovedSuppliersSkill` | The supplier list and commercial terms procurement has approved |

---

## 9. What is implemented TODAY

**Engineering Knowledge Base foundation.**

* `EngineeringKnowledgeItem` — versioned, provenance-carrying, applicability-bounded, with the derived/pointer invariant enforced at construction.
* `EngineeringKnowledgeBase` — deterministic query by category, kind, domain, source kind, exposure, tag and applicability; exact-version resolution; provenance inspection; an architectural summary.
* Six adapters over the canonical sources, publishing **71 items** across the six categories.
* `StandardReference` with structural safety against content storage and compliance implication.
* `EngineeringSkillManifest` — the future packaging contract, plus a well-formedness validator and the derived built-in manifest.
* `GET /knowledge` and `GET /knowledge/{item_id}` — read-only inspection, including full provenance per item.
* 53 tests.

**No production UI feature was added.** The frontend is untouched. Step 9 of
the brief asked for architecture inspection rather than a new user workflow
before the competition, and that is what shipped.

---

## 10. What remains ROADMAP

**Engineering Skills — reusable, versioned company/domain knowledge packages.**

Not implemented. What would have to be built:

| | |
|---|---|
| Package loader | Explicit registration, never directory scanning |
| Precedence model | Which knowledge wins, and how the answer's provenance says so |
| Package validation | Beyond well-formedness — currency, conflict, scope |
| Authoring path | How an organisation writes a package without writing Python |
| Company policy layer | Hard rules evaluated deterministically — designed, not implemented |
| Standard reference import | With the §7 guarantees intact |

What an organisation would eventually reuse across projects: process
templates · estimation methods · preferred equipment · approved suppliers ·
cost models · shift policies · company engineering rules · internal SOP
references · applicable standard references · domain-specific manufacturing
knowledge.

**Explicitly not planned:** a skills marketplace, a skill-builder UI, or any
path by which an unvalidated package mutates a verified value.

---

## 11. Tests

`backend/tests/test_engineering_knowledge_base.py` — **53 tests, all passing**,
deterministic and network-free.

| Group | Proves |
|---|---|
| **Provenance preserved** | Every item carries an openable source reference, a statement and a scope. A classification never travels without its vocabulary. Every published classification resolves against the real enum it names. |
| **Versions explicit** | Every item is versioned; an empty version is refused; the base is versioned; an exact version can be cited; two items cannot share id + version. |
| **Querying deterministic** | Two builds produce identical ordered output. Order does not depend on registration order. Every filter narrows and stays ordered. An unlimited item answers every process-family question. A missing item raises rather than returning empty. |
| **Adapters, not copies** | A `POINTER` carrying a value is refused; a `DERIVED_VALUE` with no values is refused; published values cannot be mutated through the item. Process rules, estimation bands, automation factors, validation gaps, layout defaults, cost semantics and equipment records each equal their canonical source. **Two mutation tests**: adding a planner rule and widening a reference band at source both flow through without editing the knowledge base. |
| **Standards safe** | No field can hold standard content. No verification status implies compliance. `content_available` and `establishes_compliance` are always false. Every published reference is one a real record cites. A reference must name its citer. Only a `STANDARD_REFERENCE` item carries a standard. |
| **Manifests versioned** | Version and owner are required. The built-in manifest is derived and cannot overclaim. A manifest declaring absent knowledge does not validate. Dependencies are flagged as unsupported. No status word implies certification. No loader function exists. |
| **Behaviour unchanged** | **No module outside `app/knowledge` and `app/main.py` imports the knowledge base.** The knowledge API is GET-only. Building the base leaves every canonical source byte-identical. |
| **Endpoints** | Whole-base reporting, no compliance claim, Engineering Skills presented as not implemented, a filtered view cannot be mistaken for the total, one item inspectable with provenance, unknown item → 404, unknown category → 400. |

---

## 12. Zero Golden Run behaviour change — explicit confirmation

**Nothing on the Golden Run path was modified.**

What changed, exhaustively:

| Change | Kind |
|---|---|
| `backend/app/knowledge/**` (13 new files) | **New** — imported by nothing on any engineering path |
| `backend/tests/test_engineering_knowledge_base.py` | **New** — test only |
| `backend/app/main.py` | **Additive** — two `GET` endpoints appended, plus two lines in the module docstring. No existing endpoint, model or function was touched. |
| `docs/FABRIVIUM_ENGINEERING_KNOWLEDGE_BASE.md` | **Documentation** |

What was **not** changed:

* No simulation mathematics. `app/services/simulation.py` untouched.
* No Golden Run output. No strategy generation behaviour.
* No engineering estimate. No reference band, automation factor or profile.
* No process rule, validation rule, layout rule or cost rule.
* No Siemens handoff behaviour.
* No frontend file. No UI behaviour.
* No project was created, deleted or mutated.
* Nothing was committed, tagged or pushed.

**Structural guarantee.** The knowledge base cannot influence an engineering
answer, because no module that computes one can reach it:
`test_no_engineering_module_imports_the_knowledge_base` scans every file
under `backend/app/`, excludes `app/knowledge/**`, allows only `app/main.py`
(the two read-only endpoints), and fails on any other import. Building the
base is a read; `test_building_the_base_leaves_the_canonical_sources_untouched`
asserts the canonical tables are identical afterwards.

**Regression evidence.** A targeted run rather than the full multi-hour
campaign, per the brief — the change is additive backend code that no
production module imports, and the frontend was not touched at all (so the
frontend gate was not re-run).

| Suites | Result |
|---|---|
| `test_simulation` · `test_domain` · `test_integrity_invariants` · `test_claim_hygiene` · `test_skill_framework` · `test_skill_runtime_parity` · `test_catalog` · `test_equipment_discovery` · `test_local_estimator` · `test_uncertainty` | **570 passed** (5:40) |
| `test_chain_of_truth` · `test_golden_run_defects` · `test_credibility_product_path` · `test_concept_builder` · `test_input_resolution` · `test_planning_api` · `test_handoff_api` · `test_siemens_handoff_integrity` · `test_product_understanding` · `test_equipment_discovery_breadth` · `test_generalization` · `test_project_lifecycle` · `test_engineering_knowledge_base` | **455 passed, 1 skipped** (1:22) |
| Re-verified after the final `main.py` edit: `test_engineering_knowledge_base` · `test_handoff_api` · `test_planning_api` · `test_claim_hygiene` | **124 passed** (1:09) |

The single skip is the opt-in live watsonx suite, excluded by default by
`tests/conftest.py`.

`test_chain_of_truth` is the one that matters most here: it runs the
competition case end to end — PDF → product understanding → process draft →
concept → simulation → strategy arena → selected plan — and asserts the chain
holds by relationship rather than by pinned constants. It passes unchanged.

---

## Related documents

* [`SIMULATION_SCOPE_AND_LIMITATIONS.md`](SIMULATION_SCOPE_AND_LIMITATIONS.md) — what the simulator deliberately leaves out
* [`FABRIVIUM_ROADMAP.md`](FABRIVIUM_ROADMAP.md) — where installable Skills sit on the roadmap

The internal design notes for the Skill packaging layer are not published. That
layer is not implemented, so there is nothing in this repository to check them
against.
