# Fabrivium — limitations and roadmap

A system that reports its own limits is the only kind whose reports are
worth reading. This document is the list Fabrivium would rather a reviewer
find here than discover on their own.

Each limitation states **what does not work**, **what happens instead**
(because a limit that degrades silently is a different and worse thing from
one that announces itself), and **what it would take to lift**.

---

## 1. Structural

### 1.1 Operation ≠ station — **RESOLVED**, with a stated remainder

`concept_validation.concept_to_factory` maps each concept stage to exactly
one machine and one route step. A concept cannot express:

* several parallel resources performing one operation, **as a chosen
  architecture**;
* one resource performing several operations — a complete-assembly cell, a
  U-cell;
* a shared resource serving two points in the route;
* a hybrid manual/automatic grouping.

**What is not broken.** Parallelism is modelled properly *downstream*:
`Machine.parallel_of_machine_id` and `services/machine_pool.py` implement a
real service pool, the simulator honours it, and interventions add parallel
resources through it. So one operation can end up served by N machines — but
only as the result of an intervention on an already-serial baseline.

**What has no representation anywhere:** the converse. One resource, several
operations. There is no cell and no operation grouping.

**What happens instead:** every concept starts as a serial line. For a
five-operation product that would really be built as one bench cell, or as
three identical cells, Fabrivium models a five-station line and then
discovers parallelism one intervention at a time. The throughput arithmetic
is not wrong; the architecture is not the one an engineer would draw.

**RESOLVED.** `ConceptOperationGroup` lets an engineer declare that one
resource performs a contiguous run of operations. `concept_to_factory`
compiles the group into ONE machine and ONE route step whose cycle time is
the **sum** of the members', capacity the minimum, operators the maximum;
buffers inside the cell are dropped and buffers at its boundary are
remapped. A grouped concept simulates. Twenty-seven tests
(`test_operation_grouping.py`) pin all of it, including that an ungrouped
concept compiles byte-for-byte as before — the property CEC-120 depends on.

Grouping is reachable at `POST /concept/group-operations`, requires the
engineer's stated reason, refuses a non-contiguous or overlapping grouping,
is reversible at `/concept/ungroup-operations`, and moves the
SIMULATION_INPUTS channel so any verified result goes stale.

**What remains, and is deliberately not built:** Fabrivium never proposes a
grouping and never ranks one — production-architecture *synthesis* is
roadmap item 1. And the only execution mode is `SEQUENTIAL`. Concurrency
inside a cell has to arrive as an explicit second mode, because a factor
quietly applied to this one would make cells faster than their parts on
nobody's authority.

### 1.2 No production-architecture *candidate* representation

Grouping (§1.1) expresses one architecture — the one the engineer built.
There is still no `SERIAL_LINE / PARALLEL_RESOURCES / CELLULAR / HYBRID`
topology object, and nowhere to hold a *candidate* architecture's
parallelism, shared resources, workforce allocation, rationale or
provenance so that two architectures could be compared the way two
intervention scenarios are.

**To lift:** the model, and a comparison surface. Proposing candidates is a
language-model task; structuring and simulating them is not — the boundary
in §3 already holds.

### 1.3 The project lifecycle is a route pointer

`ProjectState.stage` is a single string. There is no stage model with status,
requirements, blocking conditions, optionality or completion evidence, so
the five-stage spine (UNDERSTAND → ENGINEER → VERIFY → IMPROVE → HANDOFF)
lives in the frontend's arrangement of screens rather than in data.

**What happens instead:** every project walks the same screen order.
Domain-specific steps — software flashing and ESD for electronics, filling
and sealing for packaging, torque and dimensional inspection for mechanical
— have nowhere to be declared.

**What is already right, and must not be rebuilt while doing this:** the
revision and invalidation model in the same file. Channels, per-artifact
revision stamps and transitive staleness are correct and well-tested.

---

## 2. Representation

### 2.1 Units are implicit

There is no unit type and no conversion boundary.

* `cycle_time: PositiveFloat` — seconds, by comment only.
* `demand_per_day` — **the period is welded into the field name**, so a
  target stated per hour, per shift or per week has nowhere to live.
* `"EUR"` is a hardcoded literal in every cost surface. There is no currency
  field, and therefore nowhere a currency mismatch could be detected.

**What happens instead:** nothing visible, because everything is seconds,
units/day, metres and EUR by assumption. The limit bites the first time two
of those assumptions are false at once — and it would bite silently, which
is the reason to fix it before it is needed rather than after.

**To lift:** typed quantities normalised at the boundary and rendered at the
edge. Currency must never convert without a stated exchange rate; the
correct behaviour for a mismatch is a refusal, not a conversion.

### 2.2 No domain / project context

No `ManufacturingDomain`, no `ProjectContext`, no `GENERIC_MANUFACTURING`
fallback. Domain knowledge is spread across vocabularies and rule tables
with nothing naming which domain any of them serves, so nothing can be
scoped, swapped, or declared absent.

**Deliberately, this must never influence an equation.** Domain belongs to
terminology, extraction prompts, knowledge retrieval, suggested operations
and resource categories. A domain that changed a capacity calculation would
be a second source of engineering truth.

---

## 3. Coverage

Coverage limits are declared, reported through the API, and shown in the UI
at the moment of choosing. They are narrow, not hidden.

| | Covered | Total |
|---|---|---|
| Process families | **12** | — |
| …with a reference cycle-time band | **5** | 12 |
| …with a researched equipment catalogue | **3** | 12 |

**Estimation:** assembly, screwdriving, inspection, packaging, labelling
have measured bands. Welding, soldering, painting, machining, cleaning,
curing and palletizing do not.

**What happens instead:** the family is selectable and the option reads
"Welding — no reference estimate". The engineer supplies the cycle time.
Nothing is guessed and no estimate button silently does nothing.

**Equipment:** screwdriving, visual inspection and label application have
researched catalogues. Any other category returns an **empty shortlist plus
a note**, never a fabricated candidate. `test_every_mapped_capability_has_a_catalogue`
fails if a capability is mapped without one, so a station can never report
having been searched when nothing was collected for it.

**Reference bands are anchored to one measured dataset** (the Electronics
Assembly Demo Dataset), and its name travels with every estimate that uses
it. Bands for families outside that dataset's scope are derived, and say so.

---

## 4. Integration

### 4.1 The IBM Bob runtime path has never been executed

The provider is implemented, wired and covered by 47 unit tests against a
stubbed transport. **No live call has ever been made from this repository**,
because no Bob credential exists in the environment it was built in.

**What happens instead:** `FACTORYMIND_LLM_PROVIDER=bob` would work or would
not, and nobody here knows which. `python -m scripts.bob_smoke` is the one
command that answers it. Nothing in the product claims otherwise.

Full account in `FABRIVIUM_IBM_BOB_RUNTIME.md`, including which API details
are corroborated by two sources and which is single-sourced.

### 4.2 IBM watsonx is externally blocked

Live Granite calls return `403 token_quota_reached`: the account's
watsonx.ai instance is on the **Lite plan** and its monthly inference
allowance is exhausted. Nothing in the code or configuration can unblock it;
it needs a plan upgrade or the monthly reset.

**What happens instead, and this is the designed behaviour:** the 403 maps
to a non-retryable `LLMAuthenticationError`, so exactly one call is made with
no retry storm, the deterministic backend takes over, and provenance says
the fallback ran. Pinned by `test_phase9b_quota_fallback.py`.

### 4.3 Siemens Plant Simulation requires a local installation

The handoff drives Tecnomatix Plant Simulation 2404 over COM, on Windows,
with `pywin32`. There is no cloud path and no emulation.

**What happens instead:** the handoff is unavailable and says so. Everything
upstream of it works.

Where the two simulators disagree, the disagreement is documented rather
than tuned away — see `CROSS_SIMULATOR_SEMANTICS.md`.

---

## 5. Scope of the simulation itself

Stated because a simulation's assumptions are part of its result.

* **Deterministic.** No stochastic cycle times, no distributions, no
  confidence intervals on throughput. Uncertainty is expressed as
  *sensitivity* — the result recomputed across an input's band — not as
  variance.
* **Failures and repairs are modelled but not exercised** by the default
  reference data (`failure_rate` defaults to 0).
* **Layout is not a simulation input.** Station footprints and positions
  affect the floor plan and never the throughput, which is why moving a
  station does not invalidate a verified run.
* **Single product per run.** No mix, no changeover sequencing.

Full statement in `SIMULATION_SCOPE_AND_LIMITATIONS.md`.

---

## 6. Verification status of this generalization pass

What was and was not done, so the claims are attributable.

**Done and verified:**

* Repository-wide coupling audit, mechanical and reproducible
  (`scripts/fabrivium_coupling_audit.py`, exits non-zero on a finding).
  Production hard-coding: **0**. Hidden golden-run coupling: **0**.
* The process-family vocabulary unified behind `GET /process/families`, and
  the two divergent hard-coded UI lists removed — including the two entries
  (`labeling`, `testing`) that silently matched no reference band.
* Demo Mode scaffolding removed from production state entirely.
* Deterministic-core isolation proven by a transitive import-graph test over
  32 core modules.
* IBM Bob provider implemented, wired, unit-tested, documented.
* README and `.env.example` written for a reader with no competition
  history.

**Designed but not built** — and therefore not documented as if it existed:
production architecture (§1.1, §1.2), typed units (§2.1), domain context
(§2.2), the lifecycle stage model (§1.3).

**One defect the full regression surfaced, and what it was:** a single test
asserted the string `"FactoryMind engineering heuristic"` while the
production code had been renamed to `"Fabrivium engineering heuristic"`. It
predates this pass — both the renamed source and the stale assertion are
present in the pre-generalization checkpoint — and it was the only failure in
2,679 tests.

It was fixed at the level that prevents recurrence rather than by editing
the string: the label is now the named constant
`estimation.LOCAL_HEURISTIC_METHOD_LABEL`, and the test asserts against the
symbol. A test that spells out a brand name it is supposed to be checking
cannot detect a rename — it just fails later, somewhere that says nothing
about the cause.

**The rebrand is otherwise complete where it matters.** The 27 remaining
`FactoryMind` occurrences in production code are **identifiers, not copy**:
the `FactoryMindExchange` class that names the Plant Simulation exchange
package, and the `X-FactoryMind-Skills` HTTP header shared by backend and
frontend. Renaming either is a breaking change — the header would break any
external client, and the class name appears in generated exchange artifacts
— with no user-visible benefit. They are deliberately left.

**Done, and it found things:** the medical-device and packaging cases
(D and E) were written, pre-registered and run — see
`FABRIVIUM_MULTI_DOMAIN_VALIDATION.md`. They surfaced **three production
defects**:

1. A substring match fabricated facts *with citations attached* — "abs"
   inside "absorbent" reported the enclosure material as ABS for a
   polypropylene device, and "lid" inside "validation" turned a document's
   disclaimer line into a workstation. **Fixed**, with 20 regression tests.
2. The production target had to be counted in "units" — "18,000 bottles per
   day" parsed to no target at all, losing the single number the whole
   optimisation aims at. **Fixed**, with the time-word trap it existed to
   prevent kept.
3. Sentences split at line breaks, so a hard-wrapped specification loses the
   half of a sentence carrying the verb. **Reported, not fixed** — the
   de-wrapping fix broke the real PDF input path, where line breaks are
   layout rather than prose wrapping.

**Neither new domain produces a usable concept**, which is correct for the
current coverage. Case D fails legibly: one operation of seven, refused
build, named unresolved requirements. **Case E fails illegibly** and is the
most important open finding in this repository — it reports "All 4 extracted
manufacturing requirements are addressed" for a route with no filling, no
capping and no collating, because coverage is computed over extracted facts
rather than over the document. It also proposes a screwdriving station for a
beverage line, from the word "screw" in "screw closure".

---

## Roadmap

In dependency order. Item 1 is larger than everything below it combined and
decides whether Fabrivium is a line planner or a production-system planner.

| # | Item | Unlocks |
|---|---|---|
| 1 | **Production architecture** — topology, operation groups, cells, shared resources; break operation ≡ station | §1.1, §1.2; realistic non-serial products |
| 2 | **Typed units** — explicit period and currency, no silent conversion | §2.1; demand stated in any period |
| 3 | **Domain context** — `ManufacturingDomain` + `GENERIC_MANUFACTURING` | §2.2; scoped vocabularies, per-domain terminology |
| 4 | **Lifecycle model** — stages with status, requirements, evidence | §1.3; domain-dependent steps |
| 5 | **Engineering Skills as packages** — manifests bundling knowledge queries, prompt instructions, validation rules, vocabulary | Company standards, approved suppliers, cost models |
| 6 | **Medical-device and packaging scenarios**, end to end from scratch | Evidence for 2, 3 and the coverage limits in §3 |
| 7 | **Finish the Bob runtime path** — one API key | §4.1 |
| 8 | **Estimation coverage beyond five families** | §3; every family currently marked "no reference estimate" |

Items 2 and 3 are independent of 1 and can proceed in parallel. Item 6
should follow 3, because running those scenarios before domain context
exists would measure the wrong thing.
