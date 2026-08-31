# Fabrivium generalization validation

> **Historical record — read this first.**
>
> This report covers generalization cases A, B and C. It was written when the
> product was called FactoryMind; that name was replaced with *Fabrivium*
> throughout this file, and nothing else was changed.
>
> The report freezes itself at *FULL INTEGRATION REGRESSION PENDING*. That run
> has since happened: the current tree passes 2,776 backend tests and 1,006
> frontend tests. Cases D and E, and the mechanical and packaging domains, are
> covered in [multi-domain validation](FABRIVIUM_MULTI_DOMAIN_VALIDATION.md).


**Question this phase answers:** is Fabrivium's product-to-factory pipeline
a working system, or a CEC-120 demonstration?

**Answer:** it is a working system whose *coverage* is narrow and declared.
Three products it had never seen — none of them electronics, none of them
sharing CEC-120's material, fastener, inspection or packaging — went from a
written specification to a simulated, bottlenecked, alternative-generating
factory concept without a single line of product-specific code and without a
single CEC-120 number reaching any of them. Seven findings came out of the
exercise: **four are fixed**, as rules that leave every CEC-120 figure
unchanged, and **three are reported unfixed**, with the reason for each.

---

## Phase status — FROZEN

```
GENERALIZATION EVIDENCE STRONG
FULL INTEGRATION REGRESSION PENDING
```

The phase is frozen **logically**, not because it is finished being verified.
The generalization question is answered; the whole-tree regression question is
deliberately left open, because other phases are still modifying this working
tree and a full-suite run against a moving target would validate nothing.

The record, stated so nothing has to be inferred from it later:

| | |
|---|---|
| Dedicated generalization tests | **44 passed** (`backend/tests/test_generalization.py`) |
| Affected-module regression results | **878 passed**, across every suite covering a module this phase changed |
| Full backend suite (`pytest -q`) | **Externally interrupted after 68 minutes without reporting. NOT claimed as passed. NOT claimed as failed.** No partial output survived |
| Frontend | **No frontend file was changed by this phase.** The frontend gate was not run, and its current tree state belongs to another session |
| CEC-120-specific production logic | **None introduced.** All four fixes are rules over tables; the audit found 0 PRODUCT-SPECIFIC LEAKAGE before them, and CEC-120's facts, operations, repeat counts, gaps, preference reading and parsed constraints are all unchanged after them |
| Commits | **None.** Everything is left in the working tree |

**What is pending:** one cross-phase integration regression over the settled
tree, run once the concurrent phases have landed. §9 names the suites this
phase did not run. Until that run reports, no whole-system pass may be claimed
on this phase's evidence.

---

## 1. Baseline, and one honest caveat about it

Started from commit `5a9fe53` / tag `competition-strong-finalist-v1`.

The working tree at the start of this phase already carried uncommitted work
from an earlier phase (the estimate contract: `models/uncertainty.py`,
`services/input_resolution.py`, `services/readiness.py`,
`services/equipment_discovery.py`, `main.py`). **A second session was also
editing this repository throughout this phase**, adding an equipment-catalogue
feature (`services/equipment_catalog.py`, three new candidate datasets,
`equipment_compatibility.py`, and frontend files). None of that is this
phase's work and none of it was touched here.

Consequence for this report: the regression evidence in §9 is a large targeted
subset, not a full-suite run. A full run was started and was stopped externally
after 68 minutes without reporting (§9). Every suite that covers a module this
phase changed was run individually, and every one is green; the suites that
were not run are named in §9 rather than glossed over.

**Golden case reproducibility, verified before anything else:**

```
tests/test_credibility_product_path.py   ── the real CEC-120 PDF, LLM off
tests/test_product_understanding.py
tests/test_uncertainty.py                ── golden values unchanged
tests/test_skill_runtime_parity.py       ── golden case through the runtime
tests/test_concept_builder.py            ── golden concept regression
tests/test_input_resolution.py
tests/test_equipment_discovery.py
tests/test_station_assumptions.py
tests/test_local_estimator.py
                                            362 passed
```

CEC-120 golden reference inputs, the Siemens integration, the Plant
Simulation adapter and core simulation semantics were **not modified**.

## 2. The three cases

All three were written and **pre-registered before any of them was run** —
see `examples/generalization/PRE_REGISTRATION.md`, which also records the
predictions this report is scored against. The language model was off for
every run (`FACTORYMIND_LLM_ENABLED=false`); nothing here depends on a model
being reachable.

| | CEC-120 (control) | Case A | Case B | Case C |
|---|---|---|---|---|
| Product | Compact electronics controller | LT-8 cast gearbox housing | FT-9 in-line filter head | GR-7 grinder guard |
| Material | Moulded ABS | Cast aluminium + steel | *not yet selected* | Pressed steel + polycarbonate |
| Fastening | 6 screws | 12 bolts at 24 Nm | screws, **count unstated** | 4 screws |
| Electrical | PCB + 2 cables | none | cables, **count unstated** | none |
| Inspection | visual | pressure/leak + rotation | leak test | visual |
| Packaging | bag + carton + leaflet | oiled paper + steel crate | individual packing | bag + shelf carton |
| Target | 1,900/day | 900/day | 600/day | 6,000/day |

**How each was run.** The real HTTP API, through
`backend/scripts/generalization_run.py`, in this order:

```
POST /product/describe          document text → ProductUnderstanding
POST /product/plan-process      → proposed operations, each citing its fact
POST /product/requirement-coverage
POST /product/process/link-requirement   ← engineer resolution of coverage gaps
     (engineer accepts every proposed operation)
POST /product/build-concept     accepted process + requirements brief → concept
POST /concept/readiness, /concept/resolution-plan     ← state BEFORE any value
POST /concept/estimate   ×N     Phase 18B, per station
POST /concept/accept-assumptions ×N
POST /concept/build             ← attempted BEFORE engineer input, on purpose
POST /concept/resolve-input     ← the engineer's own decisions, listed in the script
POST /concept/build → /simulation/run → /strategies/explore → /planning/run
```

No simulation result was injected. No CEC-120 fixture was reused. The
example-data endpoints (`/concept/example-data`,
`/concept/use-example-data-for-unresolved`) were never called — they are the
one route by which CEC-120's measured numbers can enter another product's
concept, and §5 shows that none did.

**The control.** CEC-120 was put through the *identical* harness as a fourth
case, reading the bundled reference document and the concept builder's own
example brief, so the matrix in §6 compares measurements against measurements
rather than against a remembered demo. It is a read-only run: it changed
nothing about the golden case, and it is not the golden run.

Raw evidence: `examples/generalization/results/case_{cec,a,b,c}.json` and
`audit.json`.

## 3. What happened, case by case

### Case A — LT-8 gearbox housing (different product, different process)

**Extraction.** 7 facts, each citing its sentence: 12 bolts, cover/lid,
housing, overall dimensions, inspection required, packaging required — and
`material.enclosure` as a **CONFLICT**, because the document says "cast in
aluminium" in one section and "are steel" in another. Fabrivium kept both
readings, raised an information gap, and did **not** pick one. That is the
correct answer to a one-slot material model meeting a two-material product.

**Process.** Four operations, in build order, each naming the fact that
produced it: Bolt fastening ×12, Enclosure closure, Visual inspection,
Packaging.

**Coverage.** `component.enclosure` came back UNRESOLVED / CRITICAL and
**blocked approval** — the housing is a stated component that no operation
claimed. The engineer linked it to the fastening operation, and the
operation's `basis` now reads "… Engineer linked this operation to:
component.enclosure." Coverage then reported all 5 requirements addressed.

**Concept.** Target 900/day, 2 × 8 h shifts, 6 operators and a 22 × 14 m floor,
all tagged CUSTOMER. Every simulation parameter came out UNKNOWN.

**Estimation.** Takt derived as 57,600 s ÷ 900 = **64.0 s** (CALCULATED).
Station bands composed from the reference tables:

| Station | Band (s) | Working | Confidence |
|---|---|---|---|
| Bolt fastening ×12 | 54 – 120 | 87.0 | MEDIUM |
| Enclosure closure | 18 – 39 | 28.5 | LOW |
| Visual inspection | 13 – 32 | 22.5 | LOW |
| Packaging | 18 – 40 | 29.0 | LOW |

**Simulation.** 661/900 units, demand not met, gap 239, bottleneck
`m-screwdriving` — which is correct: 87.0 s against a 64.0 s takt.

**Alternatives.** Three verified options, all reaching 900/day: one parallel
machine at the bottleneck; one extra shift per day; three cycle-time changes.
Recommended: the parallel machine. Its cost is **not** claimed — the option
carries a BLOCKING information gap, "Purchase cost of a parallel machine at
m-screwdriving is not recorded in the factory data", and the rationale reads
"EUR 0 known CAPEX plus 1 unpriced item(s)".

### Case B — FT-9 filter head (incomplete engineering information)

This is the case that found the phase's most important defect. See §4.1 for
what the *unfixed* pipeline did. After the fix:

**Extraction.** 6 facts. `fastener.screw.count` and `connection.cable.count`
are recorded as **present with no quantity**; both appear in
`information_gaps` as "count not stated /
BLOCKS_DETAILED_ENGINEERING"; dimensions and material are declared missing
because the document says the envelope study is open and the material is
under review.

**Process.** Five operations. The two whose counts are unknown carry
`repeated_operations: null` and produce two open questions:

> Screws: the source does not state how many. Enter the count before a cycle
> time is estimated from it.

**Concept — the refusal.** The brief states a target and nothing else. Shifts,
hours, operators and floor came back UNKNOWN, and `POST /concept/build`
answered **HTTP 400**:

> This concept is not ready to simulate. Still required: Shifts per day,
> Hours per shift, Operators available

No default shift pattern, no assumed headcount, no zero. This is the required
Case B behaviour and it happened without prompting.

**Engineer resolution.** Three values were then typed in (1 shift, 8 h, 4
operators) and recorded as `ENGINEER` — the endpoint refuses to record a typed
value as CUSTOMER or MEASURED. Final provenance: 1 CUSTOMER, 3 ENGINEER,
15 ENGINEERING_ESTIMATE, 4 CATALOG_DEFAULT, 18 UNKNOWN, **0 EXAMPLE_DATA**.

**Simulation.** 600/600, demand met, bottleneck `m-assembly`. The arena
correctly found nothing to explore: "No verified strategy was found. Baseline
produces 600/day against a target of 600."

### Case C — GR-7 guard (intentionally infeasible)

Pre-registered arithmetic: one 8-hour shift ÷ 6,000 units = **4.8 s takt**,
below the handling time alone of every covered process family. Pre-registered
required behaviour: no feasible plan, with the best result, the gap and the
reason.

**What Fabrivium did.** Baseline 820/6,000, gap 5,180, bottleneck
`m-screwdriving`.

Constraints actually enforced (after the §4.3 fix): `ADD_PARALLEL_MACHINE`,
`CHANGE_SHIFT_CONFIGURATION` and `CHANGE_OPERATOR_CAPACITY` all excluded — the
three levers the request ruled out. Two strategy families reported themselves
empty *with the reason*: "every lever in this family was excluded by the
request".

**Verdict rendered:**

> 3 verified option(s); **0 reach the target**, 0 of those are fully priced.
> Baseline: 820/day against 6,000.

Best evaluated result 1,008/day (hybrid: station capacity + cycle time),
remaining gap 4,992. The planning endpoint said the same in words:

> Goal not reached: target 6000 units/day; final verified output is 1032/6000
> units (demand gap: 4968 units, demand not met).

**No green recommendation was manufactured.** The UI's headline is driven by
`metrics.goal_met` and reads "TARGET NOT YET REACHED" with the real gap.

One presentational risk: `recommended_strategy_id` still names the best-effort
option, so the "Recommended" tag can sit on a plan the same screen says did
not reach the target. Not a false claim, but worth wording differently.

### How the pre-registered predictions scored

The point of writing predictions down first is being able to be wrong in
public. `PRE_REGISTRATION.md` made twelve claims and open questions; here is
every one of them.

| Predicted | Outcome |
|---|---|
| A: bolt count, lid, enclosure, dimensions, inspection, packaging extracted | ✅ all six |
| A: two materials → CONFLICT, both readings kept, neither picked | ✅ |
| A: wash/degrease and bearing press-fit **dropped silently** — no fact, no operation, no gap | ✅ confirmed, and it is the largest gap left open (§10.4) |
| A: no CEC-120 figure anywhere in the output | ✅ 0 EXAMPLE_DATA; one value coincidence checked and disproved (§5) |
| A: takt 64.0 s; nearly-feasible four-station line | ✅ takt 64.0 s, 661/900, one lever closes it |
| B: every missing quantity stays UNKNOWN, nothing substituted | ✅ |
| B: missing dimensions and material declared as gaps | ✅ |
| B: **open question** — does an uncounted fastening operation survive or vanish? | ❌ **it vanished.** The defect this case was written to find (§4.1) |
| B: concept not simulation-ready until an engineer resolves the schedule | ✅ HTTP 400 naming the three values |
| C: takt 4.8 s, below every family's handling time alone | ✅ takt 4.8 s |
| C: `NO VERIFIED FEASIBLE PLAN`, with best result, gap and reason | ✅ "0 reach the target", best 1,008/day, gap 4,992, reason named |
| C: do the prose constraints reach the optimizer, or are they dropped? | ❌ **worse than dropped — inverted** (§4.3). Now fixed |

Every stated prediction held. The two ❌ rows are the two the
pre-registration deliberately left open — "which one happens is the point of
this case" — and both resolved against the system. That is the exercise
working: the places nobody was willing to predict are exactly where the two
most serious defects were.

## 4. Defects found, and what was done about each

### 4.1 A named thing with no stated count vanished — FIXED

**Found by:** Case B.

`product_extraction._facts_in_sentence` required a quantity beside a countable
noun. A document saying

> The cover is secured with screws that engage bosses in the body.

produced **no fact, no operation, no coverage entry and no gap**. FT-9's
fastening station and cable-connection station simply did not exist, and
nothing anywhere said a manufacturing requirement had been dropped — the exact
failure `requirement_coverage` was built to prevent, hidden below the level
coverage can see.

The error ran in the flattering direction: a five-station line became a
three-station line, and the three-station line met its target.

**Fix, and why it is generic:** presence and quantity are now recorded
separately. A countable noun with no number nearby produces an EXTRACTED fact
valued `present` with `quantity: null`; `gaps_for` declares the missing count;
`plan_process` proposes the operation with no repeat count and asks for it.
Merging was extended so a counted sentence supersedes an uncounted one rather
than conflicting with it — two *different* counts still conflict.

There is no product in this rule. It was verified on four wordings, on all
three case documents, and on CEC-120, whose extraction is unchanged: six
screws, two cables, the same six operations, the same single gap, no new open
questions.

### 4.2 Two readers of "no new machines" disagreed — FIXED

**Found by:** Case C.

`concept_builder._NO_NEW_EQUIPMENT_RE` accepted at most one qualifier word, so
"Do not buy **any new** machines" matched nothing and the concept came back
`prefer_no_new_machines=False` — while `requirements_parser`, which had this
defect fixed in Phase 9B, read the same sentence as a constraint. The verb
list also lacked `add`.

**Fix:** the qualifier run repeats and the verb list matches its sibling.
Regression-tested on six phrasings plus two briefs that forbid nothing.

### 4.3 A refusal of a lever was read as a request for it — FIXED

**Found by:** Case C. The most serious of the four.

`_OPERATOR_LEVER_RE` matches *hire | additional | operators*. The sentence

> we cannot hire additional operators

contains all three, so the parser recorded `CHANGE_OPERATOR_CAPACITY` as a
lever the customer **asked for**. "No second shift is available" did the same
for shifts. The result: `allowed_action_types` came back as exactly the two
levers the request forbade, `parse_warnings` was empty, and Fabrivium's
single best-effort plan was "run a second shift" — the first thing the
customer had ruled out.

A dropped constraint is bad. An inverted one is worse, and this was inverted.

**Fix:** one refusal pattern per lever, shaped like the existing
`_NO_NEW_MACHINE_RE`, evaluated **before** the positive patterns and
clause-locally softener-aware, so "avoid a second shift if possible" stays a
preference. The softener logic was extracted into
`_unsoftened_restriction()` so all three levers decide it the same way instead
of each keeping its own copy.

Effect on Case C: the three refused levers are now excluded, two families
report themselves empty with the reason, and the answer is still — correctly —
that nothing reaches the target.

156 constraint/parser/precedence tests pass unchanged, including the Phase 9B
semantics suite and the golden 1,900/day sentences.

### 4.4 Reference bands were applied outside their own stated scope — FIXED

**Found by:** Case A.

The screwdriving band declares `applicability = "Self-tapping or machine
screws into plastic or thin sheet. **Not valid for high-torque joints.**"`
Case A's joint is twelve bolts at 24 Nm. The estimator produced 54–120 s and
said nothing about the limit, because `applicability` never left the data
file. The same applies to the assembly band's "not valid for large or heavy
assemblies" and an 11 kg casting.

**Fix:** the limits are quoted in the estimate's `basis`. The estimator is not
told the joint torque or the part mass and cannot judge this itself, so the
judgement stays with the person approving the number — but they can now see
what they are judging.

### 4.5 Word forms that match nothing — REPORTED, NOT FIXED

`_INSPECTION_STEMS` and `_PACKAGING_STEMS` are compared with **exact token
equality**, although the comment above them says "matched as WHOLE TOKENS with
a prefix allowance". There is no prefix allowance on this path. So
"inspection" matches and "inspected" does not; "packed" matches and "packaged"
does not; "carton" matches and "cartons" does not.

All three case documents happened to use a matching form, so no case failed on
it — which is exactly why it is worth writing down. Measured, not assumed:

```
"Every unit receives a visual inspection before packaging."
    → requirement.inspection, requirement.packaging
"Each unit is inspected and packaged in cartons."
    → []
```

The second sentence is ordinary engineering English and produces neither an
inspection nor a packaging station.

**Why not fixed here:** the fix (real stem matching plus plural handling) is
genuinely generic, but it *broadens* what the extractor fires on across every
document including CEC-120, and its blast radius is the extraction layer the
whole competition demo stands on. It is a change to make deliberately with its
own regression pass, not as a side effect of a validation phase.

### 4.6 Operation names come from a table, not the document — REPORTED, NOT FIXED

Case A's operation is named "Visual inspection" on screen. The document
specifies a pressure test at 0.5 bar and a rotation check. The name comes from
`process_planning._RULES`, which pairs `requirement.inspection` with the
string "Visual inspection". The `basis` and the cited quote are correct; only
the name is a claim the document contradicts.

Low severity, but it is a claim about the process, and the fix (name the
operation from the fact's own evidence) is a design decision rather than a
correction.

### 4.7 The estimator counts words in Fabrivium's own sentence — REPORTED, NOT FIXED

`describe_for_estimator` builds "Packaging, implied by packaging required.
Product: X." and `count_operations` then counts stem hits in it — finding the
word *packaging* twice and concluding there are **two** packaging steps.
Case B's cable station got 2 the same way ("Cable connection, implied by cable
connections"), and its screw station got 1 from a bare mention.

None of those counts came from the product document. They are visible: the
basis states "2 × 6–14 s per packaging step", the confidence is LOW, and the
process draft's open question says the source never gave a count. But a number
with no source is still doing arithmetic.

**Why not fixed here:** the smallest correct fix — stop feeding the provenance
clause into the operation counter — changes the product path's packaging
estimate from 29.0 s to about 20.0 s. That is a number in the frozen
competition baseline, and this phase is explicitly forbidden from moving it.
Recorded for the next phase that is allowed to.

### 4.8 A one-slot material model meets a two-material product — BEHAVED CORRECTLY

Not a defect; recorded because it looks like one. `material.enclosure` is a
single key, so Case A's aluminium castings and steel shaft produced a CONFLICT
rather than a wrong answer, the conflict was declared as an information gap,
and the estimator was given no material at all rather than a guess. The
limitation is real — Fabrivium cannot describe a multi-material product —
but its failure mode is honest.

## 5. Provenance results

`backend/scripts/generalization_audit.py` walks every value in every final
concept and classifies it by `ValueSource`.

| | CEC-120 (control) | Case A | Case B | Case C |
|---|---|---|---|---|
| CUSTOMER | 4 | 6 | 1 | 6 |
| ENGINEER | 2 | 0 | 3 | 0 |
| ENGINEERING_ESTIMATE | 18 | 12 | 15 | 12 |
| CATALOG_DEFAULT (buffer sizes) | 5 | 3 | 4 | 3 |
| UNKNOWN | 19 | 13 | 18 | 13 |
| **EXAMPLE_DATA** | **0** | **0** | **0** | **0** |
| MANUFACTURER / MEASURED / SIMULATED / DOCUMENT / EXTERNAL | 0 | 0 | 0 | 0 |

**Why `DOCUMENT` and `SIMULATION_DERIVED` are zero everywhere.** Not an
omission — a boundary. Product facts read out of a specification decide *which
operations exist*; they never become the value of a simulation parameter, so
nothing in a concept is sourced `DOCUMENT`. Their citations live on the
`ProductFact` and on the operation's `basis`, which is where an engineer asks
"why does this station exist?". `SIMULATED` is zero for a related reason: no
simulation result was written back into any of these concepts. (The one value
Fabrivium does derive from its own runs — the cycle-time threshold from
`sensitivity.derive_cycle_time_requirement` — is deliberately tagged
`CALCULATED` and was not used in any case here.)

**No UNKNOWN quantity became favourable numeric data.** Specifically:

* every station's `purchase_cost` is UNKNOWN with `quote_required: true` — a
  price is never rendered as €0;
* `width` and `length` stay UNKNOWN and are not blocking, because the
  simulator reads no layout;
* the three values an engineer typed in Case B are `ENGINEER`, never
  `CUSTOMER` — `/concept/resolve-input` refuses `CUSTOMER` and `MEASURED` on a
  caller's say-so;
* every accepted estimate is `ENGINEERING_ESTIMATE`, never promoted by
  acceptance;
* the derived values (takt, available production time) are `CALCULATED` and
  carry their formula.

**One value coincidence, checked and disproved.** Case C's screwdriving cycle
time is 35.0 s, and 35.0 s is also the demo dataset's assembly cycle time. The
audit flags it and then classifies it, because equality is not evidence: the
Case C value's source is `ENGINEERING_ESTIMATE`, its basis is "6–12 s handling
+ 4 × 4–9 s per screw", and (6+12)/2 + 4 × (4+9)/2 = 35.0. It is arithmetic
landing on the same midpoint, not a leaked figure. This is the same false
positive `test_credibility_product_path` warns about, and it is why the audit
compares sources rather than digits.

## 6. Generalization matrix

Measured, not asserted. The CEC-120 column is a **fresh run of the bundled
reference document through the identical harness** — not the golden demo, and
it changed nothing about it.

| Capability | CEC-120 (control) | Case A — LT-8 | Case B — FT-9 | Case C — GR-7 |
|---|---|---|---|---|
| **Fact extraction** | 10 facts, all EXTRACTED, each citing a sentence | 7 facts; `material.enclosure` **CONFLICT** (aluminium vs steel), both readings kept | 6 facts; screws and cables **present with no count** | 7 facts; `material.enclosure` **CONFLICT** (steel vs polycarbonate) |
| **Declared information gaps** | 1 (screw type) | 1 (material conflict) | 5 (screw count, cable count, screw type, dimensions, material) | 2 (screw type, material conflict) |
| **Production requirements from brief** | target 1,900, 8 operators, 30×18 m as CUSTOMER; shifts/hours absent → UNKNOWN | target 900, 2 shifts, 8 h, 6 operators, 22×14 m — all CUSTOMER | target 600 only; everything else UNKNOWN | target 6,000, 1 shift, 8 h, 4 operators, 24×12 m + no-new-machines preference |
| **Process proposal** | 6 operations in build order, each citing its fact | 4 operations | 5 operations; 2 carry `repeated_operations: null` and 2 open questions | 4 operations |
| **Coverage approval gate** | **blocked** on enclosure + label; cleared by linking | **blocked** on enclosure; cleared by linking | **blocked** on label; cleared by linking | **blocked** on label; cleared by linking |
| **Unknown handling** | build **refused (400)**: shifts, hours | nothing missing after estimation | build **refused (400)**: shifts, hours, operators. Counts declared unknown, never defaulted | nothing missing after estimation |
| **Concept construction** | 6 stages, every simulation parameter UNKNOWN on arrival | 4 stages, same | 5 stages, same | 4 stages, same |
| **Estimation** | 6 bands, LOW/MEDIUM, arithmetic + applicability stated | 4 bands; takt 64.0 s CALCULATED | 5 bands; two rest on counts the document never gave (§4.7) | 4 bands; takt 4.8 s CALCULATED |
| **Simulation** | 1,196 / 1,900, gap 704 | 661 / 900, gap 239 | 600 / 600, met | 820 / 6,000, gap 5,180 |
| **Bottleneck** | `m-screwdriving` (48.0 s) | `m-screwdriving` (87.0 s vs 64.0 s takt) | `m-assembly` (38.5 s vs 48.0 s takt) | `m-screwdriving` (35.0 s vs 4.8 s takt) |
| **Candidate generation** | 4 families produced options; 2 empty, each with its reason | 3 options; 2 families empty with reason | 0 options; all 6 families empty with reason — the target is already met | 3 options; 2 families **excluded by the request**, 1 empty for lack of evidence |
| **Ranking / recommendation** | hybrid-no-equipment — honours the brief's soft preference over the equipment plan that also works | parallel machine at the bottleneck; cost declared unknown | none, correctly | best-effort only; nothing is recommended as meeting the target |
| **No-feasible-plan behaviour** | n/a (2 of 4 options reach it) | n/a (3 of 3 reach it) | n/a (baseline meets it) | **"0 reach the target"**, best 1,008/day, gap 4,992, reason given, UI headline "TARGET NOT YET REACHED" |
| **Provenance** | 0 EXAMPLE_DATA; prices UNKNOWN + quote-required | 0 EXAMPLE_DATA; same | 0 EXAMPLE_DATA; 3 values ENGINEER, never CUSTOMER | 0 EXAMPLE_DATA; same |

## 7. Tests added

`backend/tests/test_generalization.py` — 44 tests, every rule checked on more
than one product:

| Class | What it pins |
|---|---|
| `TestCountIsSeparateFromPresence` | presence without a count on 4 wordings; a stated count still read on 4 products; a counted sentence beats an uncounted one in the same document; two different counts still CONFLICT; "no cables" is not a presence; a stated number outranks the negation window; the missing count is declared; the operation survives and the count is asked for |
| `TestEquipmentRestrictionIsReadTheSameWayEverywhere` | 6 forbidding phrasings, 2 non-forbidding ones |
| `TestLeverRefusalsAreNotReadAsRequests` | 5 refusals excluded; 2 requests still honoured; a softened refusal stays a preference; refusals compose with the equipment ban |
| `TestApplicabilityTravelsWithTheNumber` | all 4 covered families quote their limits |
| `TestTheProductPathGeneralises` | all 3 case documents yield a route, every operation cites its fact, and no simulation parameter is invented for any of them |

Nothing in that file contains a product name, a case id or a fixture mapping
that a fix could be tuned against — every assertion is a rule, applied to a
list.

## 8. Evidence against CEC-specific hardcoding

1. **Code audit** (`GENERALIZATION_CODE_AUDIT.md`): 0 PRODUCT-SPECIFIC
   LEAKAGE findings; no `if product ==`, `if demo:` or equivalent anywhere in
   the pipeline; the four golden figures appear in production code only in
   comments and in one declared anchor table.
2. **Three unseen products produced three different routes** — 4, 5 and 4
   stations, in different orders, with different repeat counts, from three
   documents with no shared vocabulary beyond ordinary English.
3. **Zero EXAMPLE_DATA values** in any of the three concepts (§5).
4. **The bottleneck was right in every case** and was different arithmetic
   each time (87 s vs 64 s takt; 38.5 s in a 48 s takt; 35 s against a 4.8 s
   takt).
5. **The refusals fired on unseen products**: Case B was refused a build
   (HTTP 400, three values named), Case A was refused approval until a stated
   component was answered for, Case C was refused a feasible plan.
6. **The estimator refuses outside its coverage** rather than extrapolating —
   8 of the 12 process families the concept builder recognises have no bands,
   and it says so and asks for a number.
7. **CEC-120's own values are unchanged by all four fixes** — same ten facts,
   same six operations, same repeat counts, same single information gap, no
   new open questions, same `prefer_no_new_machines` reading, same parsed
   constraints on the golden 1,900/day sentences. The one deliberate textual
   change is additive: every estimate's `basis` now also quotes the band's
   applicability limits (§4.4). No number moved. That is the strongest single
   piece of evidence that the fixes were rules rather than tuning.

## 9. Regression evidence

| Suite | Result |
|---|---|
| `test_credibility_product_path.py`, `test_product_understanding.py` | 83 passed |
| `test_uncertainty.py`, `test_skill_runtime_parity.py`, `test_concept_builder.py`, `test_input_resolution.py`, `test_equipment_discovery.py`, `test_station_assumptions.py`, `test_local_estimator.py` | 279 passed |
| `test_requirements_agent.py`, `test_phase9b_constraint_semantics.py`, `test_requirement_precedence.py`, `test_phase11_requirement_parsing.py`, `test_planning_constraint_propagation.py` | 156 passed |
| `test_generalization.py` (new) | 44 passed |
| `test_chain_of_truth.py`, `test_skill_framework.py`, `test_skill_runtime_parity.py` | 103 passed |
| Combined re-run after all fixes | 213 passed |

**Total: 878 test results across the suites that cover every module this phase
changed.** Every one green.

**The full `python -m pytest -q` run did NOT report.** It was started at 17:38
after the last backend edit, ran for 68 minutes, and was stopped externally at
18:46 before pytest printed a summary; its output was buffered through a pipe,
so no partial result survived. It is not evidence of anything — not of a pass
and not of a failure — and is reported here as absent rather than inferred.

Two things stand in its place, and neither is a substitute for it:

* every suite that exercises a module this phase touched was run individually
  and is green (the table above), including the six that exercise
  `product_extraction`, which is the module with the widest blast radius;
* the concurrent session's in-flight work (`plant_simulation/adapter.py`,
  `localization.py`, `skills/builtin.py`, the equipment-catalogue feature and
  its frontend) would in any case have made a whole-suite failure
  unattributable without first bisecting it by file.

**What is therefore still open:** suites this phase did not run — notably
`test_simulation.py`, `test_planning_*.py`, `test_phase8*`, `test_scenario*`
and the Plant Simulation adapter tests. Nothing changed by this phase reaches
the simulator, the scenario engine or the adapter, and §8.7 shows the parsed
constraints on the golden sentences are unchanged — but that is an argument,
not a run. The full gate should be run once the concurrent session's work has
settled, and this section updated with its real result.

### Frontend gate

Not run, deliberately. This phase changed **no frontend file**. The frontend
working tree currently carries the other session's in-flight equipment-catalogue
work, so `vitest` / `tsc` / `vite build` here would report on their changes,
not on this phase's.

## 10. Limitations — what this does **not** prove

State these before anyone quotes the verdict.

1. **Coverage is narrow and this phase measured its edges, not its extent.**
   Extraction knows 3 countable nouns, 4 component kinds, 8 materials, 2
   requirement kinds and 1 dimension pattern. Process planning has 7 rules.
   Estimation has reference bands for 4 process families out of the 12 the
   concept builder recognises. A product outside those tables produces a
   partial route, honestly, and nothing more.

2. **Three products is three products.** They were chosen to differ from
   CEC-120 along the axes most likely to be overfitted. They are not a
   sample of manufacturing.

3. **All three are still bench-assembled discrete goods.** Nothing here tests
   process manufacturing, batch or continuous flow, multi-product lines,
   assembly trees, rework loops or anything with a fixed dwell time. The
   simulator models a station as N concurrent single-unit servers, and
   `local_estimator` explicitly refuses to express a batch process as a
   capacity — see `_BATCH_MARKERS`.

4. **A source requirement can still be missed silently — the largest
   remaining generalization limitation.** If the extraction layer does not
   recognise a manufacturing concept, that concept produces no fact, no
   operation, no coverage entry and no gap. Nothing on screen distinguishes
   "the document did not ask for this" from "we could not read that it did".

   Measured on Case A: the LT-8 document specifies **washing and degreasing**
   of both castings before assembly, and **pressing two ball bearings into the
   housing bores**. Both are real manufacturing work. Neither has an
   extraction rule. Neither appeared anywhere in the output — not as a
   station, not as a question, not as a gap.

   **Requirement coverage does not catch this, and cannot.** What
   `requirement_coverage` validates is that every *extracted* requirement has
   an operation citing it. That is a real and useful guarantee, and it fired
   correctly on all four products (§3). But it is a claim about the facts the
   extractor produced — **not evidence that every manufacturing-relevant
   statement in an arbitrary source document was successfully extracted**. A
   report reading "All 5 manufacturing requirements found in the source are
   addressed" is true as written and must not be read as "the source is fully
   covered": the phrase *found in the source* is doing load-bearing work.

   Closing this needs a different mechanism from coverage — something that
   notices unrecognised process language in the source and raises it as an
   open question rather than passing over it. **This is the right target for
   the next phase.**

5. **The reference bands are Fabrivium's own stated assumptions**, anchored
   to one bundled dataset of one electronics line. §4.4 makes their limits
   visible; it does not make them valid outside those limits. Every estimate
   in all three cases is LOW or MEDIUM confidence, and none is presented
   otherwise.

6. **No language model was involved.** These results say nothing about
   generalization of the LLM-assisted paths, which the account's exhausted
   watsonx quota makes unreachable.

7. **Case B's engineer inputs were mine.** The shift pattern, hours and
   headcount that made Case B simulatable are working assumptions listed in
   `generalization_run.py`, not customer data — recorded as ENGINEER
   precisely so that stays visible.

8. **Two of Case B's cycle times rest on operation counts nothing sourced**
   (§4.7). They are declared LOW confidence and the process draft says the
   count is unknown, but they are inputs to a simulated KPI, and that KPI —
   600/600, demand met — should be read with that in mind.

9. **No claim of universal manufacturing applicability is made or implied.**

## 11. Verdict

**GENERALIZATION EVIDENCE STRONG.**

The claim being made is narrow and it is the one the evidence supports: *the
pipeline's behaviour is driven by the document it is given and the constraints
it is told, not by CEC-120*. Three unseen products produced three different,
document-derived, evidence-cited routes; the refusals fired on all of them;
no CEC-120 value reached any of them; the infeasible case produced no
feasible plan and said why; and the four defects that were fixed were fixed as
rules, leaving every CEC-120 figure unchanged.

What is **not** claimed: that Fabrivium covers manufacturing. Its
vocabularies are small and its reference data is one line's worth. Section 10
is part of the verdict, not a footnote to it.

Also **not** claimed: a whole-system regression pass. The phase is frozen at

```
GENERALIZATION EVIDENCE STRONG
FULL INTEGRATION REGRESSION PENDING
```

and the second line stays until a cross-phase integration run reports over a
settled tree.
