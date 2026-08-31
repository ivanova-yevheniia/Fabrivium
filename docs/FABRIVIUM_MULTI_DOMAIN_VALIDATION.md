# Multi-domain validation — medical device and packaging

**What this answers:** the three existing generalization cases (A, B, C) are
all discrete mechanical/industrial products. The product brief names two
domains that were untested — **medical device** and **packaging**. These are
those two, run through the same production path as everything else, with the
language model off.

**Predictions were written before either case was run**
(`examples/generalization/PRE_REGISTRATION_D_E.md`) and are scored below,
misses included.

**Headline:** the exercise found **three real production defects**, two of
which are fixed here and one of which is reported unfixed with the reason.
Neither new domain produces a usable factory concept, and that is the
correct outcome for the current coverage — what matters is whether the
failures are *legible*. Case D's are. Case E's are not, and that is the most
important finding in this document.

---

## The cases

| | Case D | Case E |
|---|---|---|
| Document | `case_d_dx4_lateral_flow_cassette.txt` | `case_e_bv2_bottled_beverage_line.txt` |
| Product | Single-use diagnostic cassette | 500 ml bottled beverage |
| Domain | Medical device | Continuous-motion packaging |
| Joining | Ultrasonic welding, 4 points | None |
| Fasteners | **None** | **None** |
| Demand | 4,000/day | 18,000/day |
| Schedule | 3 × 7.5 h | 2 × 8 h |
| Workforce | 6 operators | 4, supervisory |
| Automation | MANUAL | **AUTOMATIC** (first non-manual case) |

Both were chosen to break something specific. Case D removes fasteners — the
operation family the reference dataset knows best — and replaces them with a
joining method that has no reference band. Case E is worse by design: its
core operations (filling, capping, sealing) **have no families in the
vocabulary at all**.

---

## Defect 1 — a substring match fabricated facts, with citations · **FIXED**

The fact extractor gated its material, component and screw-drive rules on a
bare substring test. Running the DX-4 document produced:

| Fabricated fact | Cited sentence |
|---|---|
| `material.enclosure = ABS` | "The nitrocellulose membrane strip and the **abs**orbent pad are…" |
| `component.lid = present` | "Synthetic case document written for Fabrivium generalization **valid**ation." |

Both are fabrications, and **both arrived with a citation attached** — the
quote shown to the engineer was the sentence that disproves the claim. That
is worse than fabricating silently, because the provenance badge makes it
look checked.

The first is the more alarming on sight: ABS is the **demo product's**
material and the DX-4 is moulded in polypropylene, so from the outside a
substring bug is indistinguishable from data leaking between products. It
was not leakage. It was "abs" inside "absorbent".

The second did more damage. The false `component.lid` satisfied the lid
rule, which proposed an **"Enclosure closure" operation** — so a line of the
document's own disclaimer became a workstation in the proposed process, and
it was one of only two operations in the entire route.

**Fix:** `product_extraction._marker_position` matches whole tokens with a
plural allowance — never a substring, never a prefix — and the materials,
components and screw-drive tables now use it. The module already knew this
failure mode (the comment above `_INSPECTION_STEMS` records "test" matching
"pre-tested"); those three tables had simply never been brought along.

**Regression:** `backend/tests/test_extraction_substring_facts.py`, 20 tests,
including both fabricating sentences verbatim.

**Cost, stated:** the fix initially dropped the golden route from 7
operations to 6. `"label"` had been substring-matching **"labelled"** in
"The box is closed and labelled." — the only sentence in the CEC-120
document where a label appears with an action verb, which is what promotes
the label into an operation. The inflections are now listed explicitly in
the marker table, on the general grounds that a document saying a thing "is
labelled" states that a label is applied to it. Golden route restored to 7.

## Defect 2 — the production target had to be counted in "units" · **FIXED**

The target pattern required the noun to be `units|pieces|pcs`. That is not a
description of how customers write; it is the three words the demo used.

```
"We need 18,000 bottles per day"    -> no target
"We need 4,000 cassettes per day"   -> no target
"We need 1,900 units per day"       -> 1900
```

The production target is the single number the entire optimisation aims at,
so both new domains reached the concept with their goal recorded as an
**unresolved input the customer had stated plainly in the first sentence**.

**Fix:** any noun is accepted except a unit of time. The exclusion is what
the closed list was really buying — without it "8 hours a day" reads as a
target of eight — so it is now a negative list of time words, which is what
it always meant. 12 cases pinned, including every time-word trap.

## Defect 3 — sentences are split at line breaks · **REPORTED, NOT FIXED**

Specifications are hard-wrapped at seventy-something columns. The sentence
splitter treats a newline as a sentence end, so on the DX-4:

```
"A unique identification label carrying the lot number and expiry date is"   <- cited
"applied to the exterior of the upper shell."                                <- separate
```

The half kept as evidence is the half **without the verb**, so the label is
recorded as a component and not as work anybody does — and no labelling
operation is proposed for a document that plainly requires one.

**A de-wrapping pass was implemented and reverted.** In text extracted from
a PDF — the real customer input path — line breaks are *layout*, not prose
wrapping: headings stand alone and a bill-of-materials table is one line per
row. De-wrapping merged the "Packaging" heading into the following paragraph
and collapsed the whole BOM table into a single run-on citation, breaking
two verified tests on the document this product is actually demonstrated
with.

Trading a working real input path for a synthetic one is a bad trade. Fixing
this properly needs the ingestion layer to tell prose from layout — a
per-source-format concern that belongs in the adapter which already knows
whether it read a PDF or a text file. The reasoning is recorded at
`_SENTENCE_RE` so the next person does not re-derive it.

---

## Case D — result

```
facts        4   component.enclosure, component.label, dimensions.overall,
                 requirement.packaging
operations   1   Packaging
coverage     "1 of 3 manufacturing requirements are addressed; 2 unresolved,
              2 of them stated explicitly by the source."
build        REFUSED (400) — "The source states requirements that no
             operation answers: Enclosure, Label."
```

### Scored against the pre-registration

| # | Prediction | Result |
|---|---|---|
| 1 | A welding operation is proposed | **MISS** — no rule reaches welding at all, so no operation was proposed. A bigger gap than predicted. |
| 2 | That operation gets no reference estimate | **UNTESTABLE** — there is no operation to estimate |
| 3 | No screwdriving operation appears | **HIT** |
| 4 | Functional test and visual inspection distinguishable | **MISS** — neither was extracted |
| 5 | Build is refused | **HIT**, though for a different reason than predicted |
| 6 | No CEC-120 figure appears | **HIT** after defect 1 was fixed; **would have been a MISS before it** |
| 7 | 3 × 7.5 h schedule read correctly | **HIT** |

**Verdict: legible failure.** Fabrivium proposes one operation out of the
seven the document describes, says so, names the two requirements nothing
answers, and refuses to build. Every number it does carry is either from the
document or marked unknown. It is not a usable concept and it does not
pretend to be one.

**What is missing and why:** the rule table has no rule for a joining or
welding operation, none for a functional test, and none for component
placement. Those are vocabulary gaps in a rule table, not defects — but they
mean **medical-device assembly is not currently supported**, and the honest
statement is that Fabrivium covers the fastener-and-inspection shape of
assembly, not the joining-and-test shape.

---

## Case E — result, and the finding that matters most

```
facts        4   component.label, fastener.screw.count, requirement.inspection,
                 requirement.packaging
operations   4   Screw fastening ×1, Product labelling, Visual inspection, Packaging
coverage     "All 4 extracted manufacturing requirements are addressed."
build        SUCCEEDED (200), target 18,000/day [CUSTOMER]
```

### Scored against the pre-registration

| # | Prediction | Result |
|---|---|---|
| 1 | Will not propose a complete route | **HIT** — 4 operations against 7 described |
| 2 | Labelling and packaging are proposed | **HIT** |
| 3 | Palletizing may be proposed | **MISS** — it is not |
| 4 | Should fail to meet demand | **UNTESTABLE** — no cycle time is known, so it never simulates |
| 5 | Operators mis-modelled | **UNTESTABLE** for the same reason |
| 6 | No CEC-120 figure appears | **HIT** |

### Two findings the predictions did not anticipate

**A fabricated operation.** `fastener.screw.count = 1` was extracted from
*"a PET bottle with a **screw** closure"*. "Screw" there is an adjective
describing a closure type, not a fastener count — and it produced a
**"Screw fastening ×1" screwdriving station on a beverage line**. This
survives the defect-1 fix, because "screw" genuinely is a whole token here.
Distinguishing the noun from the adjective needs grammatical context, not a
token boundary. **Reported, not fixed.**

**Coverage reported complete for a route missing its core process.** This is
the one that matters:

> "All 4 extracted manufacturing requirements are addressed."

Filling, capping, fill-level inspection, collating and shrink-wrapping are
all absent from the route. Coverage does not notice, because **coverage is
computed over extracted facts, not over the document**. A process step that
was never extracted as a fact can never appear as an unresolved requirement.

So the honesty mechanism has a floor: it can report what the extractor found
and failed to route, and it is structurally blind to what the extractor
never found at all. The word "extracted" is in the sentence, which is
technically honest and is not what a reader takes from it.

**This is the worst outcome the pre-registration named**, and it happened:
*"A confident, complete-looking concept for case E would be the worst
possible outcome and would be reported as a failure of this pass even though
every number in it was computed correctly."*

The mitigation that does exist: the concept still cannot simulate, because
every cycle time is UNKNOWN and Fabrivium refuses to convert a concept with
a required gap. So a wrong *throughput* is never produced. But a wrong
*process* is, and it is presented as complete.

**Verdict: illegible failure.** Case E is the strongest argument in this
document for the roadmap items it points at.

---

## What both cases say about the product

1. **Coverage is bounded by extraction.** A "complete" coverage report means
   every extracted requirement is routed, not that the document has been
   understood. The wording should say so — a coverage surface that cannot
   see an entire process should not be able to render a green summary.
2. **The rule table is shaped like bench assembly of fastened goods.** It
   has no joining, no functional test, no filling, no sealing, no
   collating. That is a declared limit and it is narrow.
3. **Operation ≡ station makes packaging unrepresentable anyway.** Even with
   every rule present, a continuous-motion monobloc performing fill, cap and
   label as one resource has no representation — see
   `FABRIVIUM_LIMITATIONS_AND_ROADMAP.md` §1.1.
4. **Provenance held up.** Every fabricated fact was visible *because* its
   citation contradicted it. The defect was in extraction; the mechanism
   that made it findable worked exactly as designed.

## Reproducing

```bash
cd backend
python scripts/generalization_run.py D E      # LLM off, production HTTP path
```

Results: `examples/generalization/results/case_{d,e}.json` — every request
and response, step by step. Predictions:
`examples/generalization/PRE_REGISTRATION_D_E.md`. The cases were not
rewritten to make predictions come true, and no rule was added to make
either route cleanly — a rule added for that reason is the product-specific
code this whole exercise exists to rule out.

---

## Addendum — scenarios M and P, driven to a verified simulation

Cases D and E above stopped at the concept. The final sprint added two more,
written to a specification given by the product owner, and drove them all
the way through the production HTTP API to a deterministic simulation.

| | **M — AC-6 compact actuator** | **P — LF-3 liquid filling line** |
|---|---|---|
| Domain | Mechanical assembly | Packaging / filling |
| Facts extracted | 7 | 3 |
| Operations proposed | 5 | 3 |
| Coverage | 5 of 5 after one engineer link | 3 of 3 |
| Engineering inputs | Estimated per station | Estimated; **operator counts by ENGINEER** |
| **Simulation** | **420 / 420 per day, met** | **2,952 / 4,000 per day** |
| Constraint | — (met at baseline) | `m-packaging` |
| Improvement options | — | **3 verified, 2 reach the target** |
| Leakage audit | clean | clean |

**Why P needed an engineer.** Its line is automatic, and
`local_estimator.propose_operators` deliberately returns nothing for an
automated station: "an unattended assumption here would silently free an
operator the line may actually need." So three operator counts were supplied
as ENGINEER decisions with stated reasons. That is the human-in-the-loop
stage working, not a workaround — and it is why P's numbers carry an
engineer's name rather than an estimator's.

**What is still missing from both routes:** pressing a bearing and greasing
a seat (M); filling and sealing (P). No process family covers them, so no
rule can propose them. Both concepts are partial models of their documents,
and §"What both cases say about the product" above still stands.

### Browser verification

Both projects were then created **through the real UI** — new project,
paste the specification, read facts, accept the process, resolve coverage,
build the concept — and checked at three resolutions:

| | 1920×1080 | 1440×900 | 1366×768 | Console errors | Electronics vocabulary |
|---|---|---|---|---|---|
| Mechanical | PASS | PASS | PASS | 0 | none |
| Packaging | PASS | PASS | PASS | 0 | none |

Screenshots: `docs/images/fabrivium-mechanical-1366.png`,
`docs/images/fabrivium-packaging-1920.png`.

### One defect the browser found that no test had

The **"Use demo value"** action was being offered on both projects. It fills
a station from the Electronics Assembly Demo Dataset, matched by process
family — so on an aluminium actuator it offered the electronics demo's
measured cycle time. The value it writes is honestly badged `EXAMPLE_DATA`,
so nothing was falsified; but the offer itself suggests the number applies,
and a reader scanning figures rather than provenance badges would not
notice.

It is now gated on the project actually being the bundled example. Verified
in the browser: 0 demo-value buttons on both real projects, all 30 and 24
"Enter value" options intact. Pinned by three tests in
`ResolveInputs.test.tsx`.

---

## Addendum 2 — the coverage semantics this exercise exposed, and the fix

The finding above ("coverage reported complete for a route missing its core
process") was the most important one in this document. It is now addressed
in the product, not only in prose.

**What was wrong:** nothing about the metric. Coverage measures whether
every requirement *extracted from the source* has an operation, and that is
a real and useful thing to measure. What was wrong is that its scope lived
in a docstring, where the person reading the screen could not see it — so
"All 3 extracted manufacturing requirements are addressed" over a filling
line with no filling operation read as *done*.

**What changed:**

| | Before | After |
|---|---|---|
| Panel title | "Source requirement coverage" | **"Extracted-requirement coverage"** |
| Incomplete sentence | "4 of 5 manufacturing requirements…" | "4 of 5 **extracted** manufacturing requirements…" |
| Scope | docstring only | **"What does this mean?"** note on screen, collapsed |
| Process review | not stated | **PROCESS SCOPE** line, from the review state operations already carry |
| Verification badge | "Verified by deterministic simulation" | "Verified by deterministic simulation **of the current engineering model**" |

The qualifier "extracted" now appears in *both* sentences. It previously
appeared only in the complete one, and a qualifier that shows up only when
the news is good reads as a hedge attached to success rather than as a
property of the metric.

**PROCESS SCOPE reuses existing state.** `ProposedOperation.status` already
records whether an engineer accepted each operation; no new field, no
migration, no new workflow. It reads either:

> Not yet reviewed — these operations are Fabrivium's proposal from the
> extracted facts.

or, once accepted:

> Engineer reviewed every proposed operation. Completeness against the
> source document is not independently established.

Neither claims completeness. Reviewed means a person looked.

### Verified in the browser, all three domains

| | Title | Summary | Scope note | Process scope | Says "fully covered" |
|---|---|---|---|---|---|
| **CEC-120** | Extracted-requirement coverage | "7 of 8 extracted…; 1 unresolved" | present | stated | **no** |
| **Mechanical** | Extracted-requirement coverage | "4 of 5 extracted…; 1 unresolved" | present | stated | **no** |
| **Packaging** | Extracted-requirement coverage | "All 3 extracted… addressed." | present | stated | **no** |

The packaging row is the one that matters: three operations, no filling and
no sealing, and the screen no longer implies the document was understood.
0 console errors on all three. Screenshot:
`docs/images/fabrivium-coverage-scope-cec.png`.

**The CEC workflow is undamaged** — 7 operations, the same blocked banner on
the unresolved enclosure requirement that the film shows an engineer
resolving.

### What is still true

The underlying limit has not moved: a manufacturing step the extractor never
read still cannot appear as missing, because nothing in the pipeline
establishes what the document contains. Roadmap item 6 is the work that
would change that. What changed here is that the product now says so.
